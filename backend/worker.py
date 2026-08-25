import os
import time
from celery import Celery

#Defaults to localhost for running outside Docker; docker-compose sets REDIS_URL to the redis service
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery("Tasks", broker=redis_url, backend=redis_url)

@app.task
def analysis(filename : str, content_type : str, taps=None):
    #taps: list of {x, y} normalized (0-1) hold-tap points from the mobile app.
    #Not used yet - this task is still a stub - accepted here so the field
    #isn't silently dropped once real (e.g. LLM/segmentation) processing lands.

    res = filename + content_type

    return res