from fastapi import FastAPI, File, Header, Response, UploadFile, status
from worker import app as celery_app, analysis as analysis_task
from celery.result import AsyncResult
from redis_client import redis_client

app = FastAPI()


#Idempotency: client sends a unique Idempotency-Key header per submission attempt.
#We reserve it in redis (SET NX) before doing any work, so two
#requests with the same key can't both create tasks.

#keys are scoped globally, not per-user - there's no auth system yet.
#Once one exists, prefix the redis key with the user id to scope it per-user.


#When we receive the HTTP request with the image bytes, filename, content type
#We get all the information and pass it to the worker function
#Then we return 202 accepted and the taskid for the polling GET requests

IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24  # 24h

@app.post("/analysis", status_code=status.HTTP_202_ACCEPTED)
async def analysis(
    #Reponse here allows to access metadata, specifically here change status code.
    response: Response,
    photo: UploadFile = File(),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    redis_key = f"idempotency:{idempotency_key}"

    reserved = await redis_client.set(
        redis_key, "processing", nx=True, ex=IDEMPOTENCY_TTL_SECONDS
    )

    if not reserved:
        existing = await redis_client.get(redis_key)
        if existing == "processing":
            #Another request with this key is still being processed
            response.status_code = status.HTTP_409_CONFLICT
            return {"detail": "Request with this Idempotency-Key is already being processed"}
        #Key already holds a completed task_id - replay the original response
        return {"task_id": existing}

    try:
        contents: bytes = await photo.read()
        filename = photo.filename
        content_type = photo.content_type

        task = analysis_task.delay(filename, content_type)
    except Exception:
        #Don't leave a failed attempt stuck as "processing" for the full TTL
        await redis_client.delete(redis_key)
        raise

    await redis_client.set(redis_key, task.id, ex=IDEMPOTENCY_TTL_SECONDS)

    return {"task_id" : task.id}

@app.get("/analysis/{task_id}")
async def getAnalysis(task_id: str):

    task_result = AsyncResult(task_id, app=celery_app)
    status = task_result.state

    if status == "FAILURE":
        return {"task_id": task_id, "status": status, "error": str(task_result.result)}

    if status == "PENDING" or status == "STARTED" or status == "RETRY":
        return {"task_id": task_id, "status": status}

    return {"task_id": task_id, "status": status, "result": task_result.result}





