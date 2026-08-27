import fakeredis
import pytest
from unittest.mock import patch

# Shared across every test module in backend/. Patching "main.analysis_task.delay"
# and "main.redis_client" forces main.py (and transitively worker.py,
# redis_client.py) to import, which is harmless - none of that module-level
# code opens a real network connection.


@pytest.fixture(autouse=True)
def mock_celery_task():
    with patch("main.analysis_task.delay") as mock_task:
        mock_task.return_value.id = "test-task-id-1234"
        yield mock_task


@pytest.fixture(autouse=True)
def mock_redis_client():
    fake_redis = fakeredis.aioredis.FakeRedis()

    with patch("main.redis_client", fake_redis):
        yield fake_redis


@pytest.fixture
def anyio_backend():
    # Restrict anyio-marked async tests to asyncio - trio isn't a project
    # dependency and we don't need two backends' worth of test runs.
    return "asyncio"
