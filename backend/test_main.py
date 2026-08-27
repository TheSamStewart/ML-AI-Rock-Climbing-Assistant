import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from mock import AsyncMock
from main import app, IDEMPOTENCY_TTL_SECONDS

# create a test client instance wrapping the app (FastAPI)
client = TestClient(app)

# mock_celery_task and mock_redis_client are autouse fixtures from conftest.py


def _post_analysis(idempotency_key=None, taps=None, filename="test_image.jpg", content_type="image/jpeg"):
    fake_image_data = io.BytesIO(b"fake binary image contents")
    files = {"photo": (filename, fake_image_data, content_type)}
    headers = {}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    data = {}
    if taps is not None:
        data["taps"] = taps
    return client.post("/analysis", files=files, headers=headers, data=data)


def test_post_already_processing():

    with patch("main.redis_client.set", new_callable=AsyncMock) as mock_redis_set, \
    patch("main.redis_client.get", new_callable=AsyncMock) as mock_idem_key_check:

        mock_redis_set.return_value = False
        mock_idem_key_check.return_value = "processing"

        response = _post_analysis(idempotency_key=str(uuid.uuid4()))

        assert response.status_code == 409

        data = response.json()

        assert data["detail"] == "Request with this Idempotency-Key is already being processed"


def test_post_image():

    response = _post_analysis(idempotency_key=str(uuid.uuid4()))

    # Check status 202 is returned for good data

    assert response.status_code == 202

    data = response.json()

    # Ensure we recieve a task_id

    assert "task_id" in data
    assert isinstance(data["task_id"], str)
    assert len(data["task_id"]) > 0


def test_get_analysis_failure():

    with patch("main.AsyncResult") as mock_async_result:

        mock_instance = mock_async_result.return_value
        mock_instance.state = "FAILURE"
        mock_instance.result = Exception("Something went wrong")

        response = client.get("/analysis/test-task-id-1234")

        assert response.status_code == 200

        data = response.json()

        assert data["task_id"] == "test-task-id-1234"
        assert data["status"] == "FAILURE"
        assert data["error"] == "Something went wrong"


def test_get_analysis_pending():

    with patch("main.AsyncResult") as mock_async_result:

        mock_instance = mock_async_result.return_value
        mock_instance.state = "PENDING"

        response = client.get("/analysis/test-task-id-1234")

        assert response.status_code == 200

        data = response.json()

        assert data["task_id"] == "test-task-id-1234"
        assert data["status"] == "PENDING"


# --- New coverage below ---


def test_post_missing_idempotency_key_header_is_422():
    # Idempotency-Key is a required header; omitting it should fail FastAPI's
    # own validation before any handler code runs.
    fake_image_data = io.BytesIO(b"fake binary image contents")
    files = {"photo": ("test_image.jpg", fake_image_data, "image/jpeg")}

    response = client.post("/analysis", files=files)

    assert response.status_code == 422


def test_post_replays_task_id_for_completed_key(mock_celery_task):
    # If the idempotency key already maps to a finished task id (not the
    # "processing" sentinel), the endpoint must hand back that task id
    # without creating a new Celery task.
    with patch("main.redis_client.set", new_callable=AsyncMock) as mock_redis_set, \
    patch("main.redis_client.get", new_callable=AsyncMock) as mock_idem_key_check:

        mock_redis_set.return_value = False
        mock_idem_key_check.return_value = "already-finished-task-id"

        response = _post_analysis(idempotency_key=str(uuid.uuid4()))

        assert response.status_code == 202
        assert response.json() == {"task_id": "already-finished-task-id"}
        mock_celery_task.assert_not_called()


def test_post_invalid_taps_json_defaults_to_empty_list(mock_celery_task):
    response = _post_analysis(idempotency_key=str(uuid.uuid4()), taps="not valid json")

    assert response.status_code == 202
    mock_celery_task.assert_called_once()
    _, _, taps_arg = mock_celery_task.call_args.args
    assert taps_arg == []


def test_post_valid_taps_json_is_parsed_and_forwarded(mock_celery_task):
    taps_payload = [{"x": 0.25, "y": 0.5}, {"x": 0.9, "y": 0.1}]

    response = _post_analysis(idempotency_key=str(uuid.uuid4()), taps=json.dumps(taps_payload))

    assert response.status_code == 202
    mock_celery_task.assert_called_once()
    _, _, taps_arg = mock_celery_task.call_args.args
    assert taps_arg == taps_payload


def test_post_no_taps_field_defaults_to_empty_list(mock_celery_task):
    response = _post_analysis(idempotency_key=str(uuid.uuid4()))

    assert response.status_code == 202
    mock_celery_task.assert_called_once()
    _, _, taps_arg = mock_celery_task.call_args.args
    assert taps_arg == []


def test_post_forwards_filename_and_content_type(mock_celery_task):
    response = _post_analysis(
        idempotency_key=str(uuid.uuid4()),
        filename="climb.png",
        content_type="image/png",
    )

    assert response.status_code == 202
    mock_celery_task.assert_called_once()
    filename_arg, content_type_arg, _ = mock_celery_task.call_args.args
    assert filename_arg == "climb.png"
    assert content_type_arg == "image/png"


@pytest.mark.anyio
async def test_post_sets_idempotency_reservation_with_ttl(mock_redis_client):
    # TTL isn't observable through the HTTP response, so check the fake
    # redis instance directly.
    key = str(uuid.uuid4())

    response = _post_analysis(idempotency_key=key)
    assert response.status_code == 202

    ttl = await mock_redis_client.ttl(f"idempotency:{key}")
    assert 0 < ttl <= IDEMPOTENCY_TTL_SECONDS


@pytest.mark.anyio
async def test_post_task_creation_failure_cleans_up_idempotency_key(mock_celery_task, mock_redis_client):
    # If delay() raises after the key was reserved, the reservation must be
    # deleted rather than left "processing" for the full 24h TTL.
    mock_celery_task.side_effect = RuntimeError("celery broker unreachable")
    key = str(uuid.uuid4())

    with pytest.raises(RuntimeError):
        _post_analysis(idempotency_key=key)

    remaining = await mock_redis_client.get(f"idempotency:{key}")
    assert remaining is None


def test_get_analysis_success_returns_result():
    with patch("main.AsyncResult") as mock_async_result:
        mock_instance = mock_async_result.return_value
        mock_instance.state = "SUCCESS"
        mock_instance.result = {"grade": "V4", "holds": 12}

        response = client.get("/analysis/test-task-id-1234")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SUCCESS"
        assert data["result"] == {"grade": "V4", "holds": 12}


@pytest.mark.parametrize("celery_state", ["STARTED", "RETRY"])
def test_get_analysis_in_progress_states(celery_state):
    with patch("main.AsyncResult") as mock_async_result:
        mock_instance = mock_async_result.return_value
        mock_instance.state = celery_state

        response = client.get("/analysis/test-task-id-1234")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "test-task-id-1234"
        assert data["status"] == celery_state
        assert "result" not in data
        assert "error" not in data
