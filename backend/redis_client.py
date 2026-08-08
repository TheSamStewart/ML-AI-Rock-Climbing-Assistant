import os
from redis.asyncio import Redis

#Dedicated async client for our own key/value use (idempotency reservations).
#Separate from Celery's own connection in worker.py - Celery manages that one
#internally as a sync broker/backend, and main.py's handlers are async def,
#so we need redis.asyncio here instead.

#Same env var + default as worker.py, so one REDIS_URL configures both.
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

#decode_responses=True so GET/SET return str - we compare stored values
#against the "processing" string sentinel, which would silently fail
#against raw bytes otherwise.
redis_client = Redis.from_url(redis_url, decode_responses=True)
