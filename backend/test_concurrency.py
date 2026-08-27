import asyncio
import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from main import app

# mock_celery_task and mock_redis_client are autouse fixtures from conftest.py.
# Both patch attributes on `main`, so every concurrent coroutine below shares
# the same fake Celery mock and the same in-memory fake Redis - exactly what
# we need to prove the SET NX idempotency guard holds under real concurrency,
# not just sequential calls.

CONCURRENT_REQUESTS = 300


def _analysis_payload():
    return {
        "files": {"photo": ("test_image.jpg", io.BytesIO(b"fake binary image contents"), "image/jpeg")},
    }


@pytest.mark.anyio
@pytest.mark.concurrency
async def test_concurrent_requests_same_key_create_exactly_one_task(mock_celery_task):
    key = str(uuid.uuid4())
    transport = ASGITransport(app=app)

    async def fire_one():
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            files = {"photo": ("test_image.jpg", b"fake binary image contents", "image/jpeg")}
            headers = {"Idempotency-Key": key}
            return await ac.post("/analysis", files=files, headers=headers)

    responses = await asyncio.gather(*(fire_one() for _ in range(CONCURRENT_REQUESTS)))

    # The one property that actually matters at scale: no matter how many
    # requests race for the same key, only one Celery task gets created.
    assert mock_celery_task.call_count == 1

    statuses = {r.status_code for r in responses}
    # Every response is either the 202 winner (first reservation, or a
    # replay of an already-finished task id) or a 409 while a request is
    # still in flight. Nothing should ever 500.
    assert statuses <= {202, 409}
    assert 202 in statuses

    task_ids = {r.json()["task_id"] for r in responses if r.status_code == 202}
    assert task_ids == {"test-task-id-1234"}


@pytest.mark.anyio
@pytest.mark.concurrency
async def test_concurrent_requests_distinct_keys_all_create_tasks(mock_celery_task):
    keys = [str(uuid.uuid4()) for _ in range(CONCURRENT_REQUESTS)]
    transport = ASGITransport(app=app)

    async def fire_one(key):
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            files = {"photo": ("test_image.jpg", b"fake binary image contents", "image/jpeg")}
            headers = {"Idempotency-Key": key}
            return await ac.post("/analysis", files=files, headers=headers)

    responses = await asyncio.gather(*(fire_one(k) for k in keys))

    # Distinct keys must never be serialized against each other or dropped -
    # every one of them should independently succeed.
    assert all(r.status_code == 202 for r in responses)
    assert mock_celery_task.call_count == CONCURRENT_REQUESTS
