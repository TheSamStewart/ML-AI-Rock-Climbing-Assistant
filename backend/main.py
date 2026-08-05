from fastapi import FastAPI, File, UploadFile, status
from worker import analysis as analysis_task

app = FastAPI()

#When we receive the HTTP request with the image bytes, filename, content type
#We get all the information and pass it to the worker function
#Then we return 202 accepted and the taskid for the polling GET requests

#Next we need to deal with the 202 reply in the frontend
#Then we need to implement app.get here for the polling request once the work is done 

@app.post("/analysis", status_code=status.HTTP_202_ACCEPTED)
async def analysis(photo : UploadFile = File()):

    contents: bytes = await photo.read()
    filename = photo.filename
    content_type = photo.content_type

    task = analysis_task.delay(filename, content_type)

    return {"task_id" : task.id}

@app.get("/analysis/{task_id}")
async def getAnalysis(task_id: str):
    return {"task_id": task_id}

    



