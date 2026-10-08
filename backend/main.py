import io
import json
import logging
from uuid import uuid4

import detection
from fastapi import FastAPI, File, Form, Header, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from redis.exceptions import RedisError
from worker import app as celery_app, analysis as analysis_task
from celery.result import AsyncResult
from redis_client import redis_client

logger = logging.getLogger(__name__)

app = FastAPI()


#Idempotency: client sends a unique Idempotency-Key header per submission attempt.
#We reserve it in redis (SET NX) before doing any work, so two
#requests with the same key can't both create tasks.

#keys are scoped globally, not per-user - there's no auth system yet.
#Once one exists, prefix the redis key with the user id to scope it per-user.


#/detect runs YOLO on the photo and caches the detections under a fresh
#detection_id, keyed for lookup by /analysis once the client has resolved
#which detections the user selected. /analysis then dispatches the LLM
#coaching call and returns 202 + a task_id for the polling GET below.

IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24  # 24h

#How long a detection result stays selectable before the user has to retake
#the photo - long enough to finish tapping, short enough not to accumulate
#stale cache entries.

DETECTIONS_TTL_SECONDS = 60 * 60  # 1h

#Fewer than this many holds isn't enough to build a real climbing sequence -
#keep in sync with the mobile app's own minimum in PhotoPreview.tsx.

MIN_SELECTED_HOLDS = 3


@app.post("/detect")
async def detect(response: Response, photo: UploadFile = File()):
    contents = await photo.read()

    try:
        image = Image.open(io.BytesIO(contents))
        #Image.open() only reads the header - force the full pixel decode now
        #so a truncated/corrupt body fails here with a clear 422, not deep
        #inside YOLO's own image handling later.
        image.load()
    except (UnidentifiedImageError, OSError):
        #UnidentifiedImageError = not an image at all; plain OSError = valid
        #header but truncated body (e.g. a dropped mobile upload).
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": "Uploaded file isn't a readable image."}

    #YOLO inference is CPU/GPU-bound, blocking work - run it off the event
    #loop so concurrent requests (e.g. another client's idempotency check)
    #aren't stalled behind it.

    try:
        detections = await run_in_threadpool(detection.run_detection, image)
    except Exception:
        logger.exception("detect: YOLO inference failed")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"detail": "Hold detection failed - try again."}

    detection_id = uuid4().hex
    try:
        await redis_client.set(
            f"detections:{detection_id}", json.dumps(detections), ex=DETECTIONS_TTL_SECONDS
        )
    except RedisError:
        logger.exception("detect: failed to cache detections")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"detail": "Couldn't save detection results - try again."}

    return {"detection_id": detection_id, "detections": detections}


@app.post("/analysis", status_code=status.HTTP_202_ACCEPTED)
async def analysis(
    #Reponse here allows to access metadata, specifically here change status code.

    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),

    #The detection_id from a prior /detect call, and the JSON-encoded list of
    #hold ids (from that same call's detections) the user selected.

    detection_id: str = Form(...),
    selected_hold_ids: str = Form(...),
):
    #Lenient on purpose: this mirrors the rest of the endpoint's stub-level

    try:
        parsed_ids = json.loads(selected_hold_ids)
        if not isinstance(parsed_ids, list) or not all(isinstance(i, int) for i in parsed_ids):
            parsed_ids = None
    except (TypeError, ValueError):
        parsed_ids = None

    #Reject too-few selections before touching redis/Celery - the client is
    #expected to enforce this too, but that's bypassable, so this is the
    #check that actually guarantees it.

    if parsed_ids is None or len(parsed_ids) < MIN_SELECTED_HOLDS:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": f"At least {MIN_SELECTED_HOLDS} holds must be selected before submitting for analysis."}

    cached = await redis_client.get(f"detections:{detection_id}")
    if cached is None:
        response.status_code = status.HTTP_410_GONE
        return {"detail": "Detection results expired or not found - retake the photo and try again."}

    detections = json.loads(cached)

    try:
        master_hold_dict = detection.select_holds(detections, parsed_ids)
    except detection.UnknownHoldIdError:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": "One or more selected hold ids were not found in the detection results."}

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
        task = analysis_task.delay(master_hold_dict)
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
