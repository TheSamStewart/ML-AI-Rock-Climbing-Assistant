import os

from celery import Celery

#Defaults to localhost for running outside Docker; docker-compose sets REDIS_URL to the redis service
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery("Tasks", broker=redis_url, backend=redis_url)

@app.task
def analysis(filename, content_type):

    res = filename + content_type

    return res