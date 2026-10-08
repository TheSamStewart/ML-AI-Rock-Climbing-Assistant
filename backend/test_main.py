import json

import pytest
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from unittest.mock import patch

import detection
from main import app, DETECTIONS_TTL_SECONDS, IDEMPOTENCY_TTL_SECONDS, MIN_SELECTED_HOLDS

# mock_celery_task and mock_redis_client are autouse fixtures from conftest.py.
# Every test is async (httpx + ASGITransport) so the fake redis is awaited on
# the same event loop the app uses.

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _post_detect(client, contents, filename="wall.jpg", content_type="image/jpeg"):
    return await client.post("/detect", files={"photo": (filename, contents, content_type)})


async def _post_analysis(client, idempotency_key="key-1", detection_id=None, selected_hold_ids="[0, 1, 2]"):
    headers = {} if idempotency_key is None else {"Idempotency-Key": idempotency_key}
    data = {}
    if detection_id is not None:
        data["detection_id"] = detection_id
    if selected_hold_ids is not None:
        data["selected_hold_ids"] = selected_hold_ids
    return await client.post("/analysis", headers=headers, data=data)


# --- POST /detect ---


async def test_detect_returns_and_caches_detections(client, jpeg_bytes, mock_run_detection, mock_redis_client, sample_detections):
    response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 200
    body = response.json()
    assert body["detections"] == sample_detections
    detection_id = body["detection_id"]
    int(detection_id, 16)  # uuid4().hex

    cached = await mock_redis_client.get(f"detections:{detection_id}")
    assert json.loads(cached) == sample_detections
    ttl = await mock_redis_client.ttl(f"detections:{detection_id}")
    assert 0 < ttl <= DETECTIONS_TTL_SECONDS


async def test_detect_each_call_gets_a_fresh_detection_id(client, jpeg_bytes, mock_run_detection):
    first = await _post_detect(client, jpeg_bytes)
    second = await _post_detect(client, jpeg_bytes)

    assert first.json()["detection_id"] != second.json()["detection_id"]


async def test_detect_non_image_is_422(client, mock_run_detection):
    response = await _post_detect(client, b"definitely not an image")

    assert response.status_code == 422
    assert response.json() == {"detail": "Uploaded file isn't a readable image."}
    mock_run_detection.assert_not_called()


async def test_detect_truncated_image_is_422(client, jpeg_bytes, mock_run_detection):
    # Valid JPEG header, cut-off body: Image.open() succeeds, image.load()
    # raises a plain OSError rather than UnidentifiedImageError.
    response = await _post_detect(client, jpeg_bytes[:200])

    assert response.status_code == 422
    assert response.json() == {"detail": "Uploaded file isn't a readable image."}
    mock_run_detection.assert_not_called()


async def test_detect_inference_failure_is_500(client, jpeg_bytes, mock_redis_client):
    with patch("main.detection.run_detection", side_effect=RuntimeError("CUDA on fire")):
        response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 500
    assert response.json() == {"detail": "Hold detection failed - try again."}
    assert await mock_redis_client.keys("detections:*") == []


async def test_detect_cache_write_failure_is_503(client, jpeg_bytes, mock_run_detection, mock_redis_client):
    with patch.object(mock_redis_client, "set", side_effect=RedisError("down")):
        response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 503
    assert response.json() == {"detail": "Couldn't save detection results - try again."}


async def test_detect_missing_photo_is_422(client, mock_run_detection):
    response = await client.post("/detect")

    assert response.status_code == 422
    mock_run_detection.assert_not_called()


# --- POST /analysis ---


async def test_analysis_happy_path_enqueues_selected_holds(client, cached_detection_id, sample_detections, mock_celery_task, mock_redis_client):
    selected = [0, 2, 3]

    response = await _post_analysis(client, "key-happy", cached_detection_id, json.dumps(selected))

    assert response.status_code == 202
    assert response.json() == {"task_id": "test-task-id-1234"}

    mock_celery_task.assert_called_once_with(detection.select_holds(sample_detections, selected))

    assert await mock_redis_client.get("idempotency:key-happy") == "test-task-id-1234"
    ttl = await mock_redis_client.ttl("idempotency:key-happy")
    assert 0 < ttl <= IDEMPOTENCY_TTL_SECONDS


async def test_analysis_exactly_min_holds_is_accepted(client, cached_detection_id):
    ids = json.dumps(list(range(MIN_SELECTED_HOLDS)))

    response = await _post_analysis(client, "key-min", cached_detection_id, ids)

    assert response.status_code == 202


@pytest.mark.parametrize(
    "selected_hold_ids",
    [
        json.dumps(list(range(MIN_SELECTED_HOLDS - 1))),  # too few
        "[]",
        "not json",
        '{"a": 1}',  # valid JSON, not a list
        '[1, "2", 3]',  # list, but not all ints
    ],
)
async def test_analysis_bad_selection_is_422_before_touching_redis_or_celery(
    client, cached_detection_id, mock_celery_task, mock_redis_client, selected_hold_ids
):
    with patch.object(mock_redis_client, "get", wraps=mock_redis_client.get) as spy_get:
        response = await _post_analysis(client, "key-bad", cached_detection_id, selected_hold_ids)

    assert response.status_code == 422
    assert str(MIN_SELECTED_HOLDS) in response.json()["detail"]
    spy_get.assert_not_called()
    mock_celery_task.assert_not_called()
    assert await mock_redis_client.get("idempotency:key-bad") is None


async def test_analysis_unknown_detection_id_is_410(client, mock_celery_task, mock_redis_client):
    response = await _post_analysis(client, "key-410", "no-such-detection")

    assert response.status_code == 410
    assert "expired or not found" in response.json()["detail"]
    mock_celery_task.assert_not_called()
    assert await mock_redis_client.get("idempotency:key-410") is None


async def test_analysis_unknown_hold_id_is_422_and_reserves_nothing(client, cached_detection_id, mock_celery_task, mock_redis_client):
    response = await _post_analysis(client, "key-unknown", cached_detection_id, "[0, 1, 99]")

    assert response.status_code == 422
    assert response.json() == {"detail": "One or more selected hold ids were not found in the detection results."}
    mock_celery_task.assert_not_called()
    assert await mock_redis_client.get("idempotency:key-unknown") is None


@pytest.mark.parametrize("missing", ["idempotency_key", "detection_id", "selected_hold_ids"])
async def test_analysis_missing_required_field_is_422(client, cached_detection_id, mock_celery_task, missing):
    kwargs = {"idempotency_key": "key-missing", "detection_id": cached_detection_id, "selected_hold_ids": "[0, 1, 2]"}
    kwargs[missing] = None

    response = await _post_analysis(client, **kwargs)

    assert response.status_code == 422
    mock_celery_task.assert_not_called()


async def test_analysis_key_still_processing_is_409(client, cached_detection_id, mock_celery_task, mock_redis_client):
    await mock_redis_client.set("idempotency:key-busy", "processing")

    response = await _post_analysis(client, "key-busy", cached_detection_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Request with this Idempotency-Key is already being processed"}
    mock_celery_task.assert_not_called()


async def test_analysis_completed_key_replays_task_id(client, cached_detection_id, mock_celery_task, mock_redis_client):
    await mock_redis_client.set("idempotency:key-done", "already-finished-task-id")

    response = await _post_analysis(client, "key-done", cached_detection_id)

    assert response.status_code == 202
    assert response.json() == {"task_id": "already-finished-task-id"}
    mock_celery_task.assert_not_called()


async def test_analysis_same_key_twice_sequentially_replays(client, cached_detection_id, mock_celery_task):
    first = await _post_analysis(client, "key-twice", cached_detection_id)
    second = await _post_analysis(client, "key-twice", cached_detection_id)

    assert first.json() == second.json() == {"task_id": "test-task-id-1234"}
    mock_celery_task.assert_called_once()


async def test_analysis_task_creation_failure_cleans_up_idempotency_key(client, cached_detection_id, mock_celery_task, mock_redis_client):
    # If delay() raises after the key was reserved, the reservation must be
    # deleted rather than left "processing" for the full 24h TTL.
    mock_celery_task.side_effect = RuntimeError("celery broker unreachable")

    with pytest.raises(RuntimeError):
        await _post_analysis(client, "key-fail", cached_detection_id)

    assert await mock_redis_client.get("idempotency:key-fail") is None


# --- GET /analysis/{task_id} ---


async def test_get_analysis_failure(client):
    with patch("main.AsyncResult") as mock_async_result:
        mock_instance = mock_async_result.return_value
        mock_instance.state = "FAILURE"
        mock_instance.result = RuntimeError("Coaching LLM output was truncated (hit max_tokens)")

        response = await client.get("/analysis/test-task-id-1234")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "test-task-id-1234",
        "status": "FAILURE",
        "error": "Coaching LLM output was truncated (hit max_tokens)",
    }


@pytest.mark.parametrize("celery_state", ["PENDING", "STARTED", "RETRY"])
async def test_get_analysis_in_progress_states(client, celery_state):
    with patch("main.AsyncResult") as mock_async_result:
        mock_async_result.return_value.state = celery_state

        response = await client.get("/analysis/test-task-id-1234")

    assert response.status_code == 200
    assert response.json() == {"task_id": "test-task-id-1234", "status": celery_state}


async def test_get_analysis_success_returns_steps(client):
    steps = {
        "steps": [
            {"step_number": 1, "instruction": "Both hands on the start hold.", "reason": "Matched start."},
            {"step_number": 2, "instruction": "Right hand to the volume.", "reason": "Use the big feature."},
        ]
    }
    with patch("main.AsyncResult") as mock_async_result:
        mock_instance = mock_async_result.return_value
        mock_instance.state = "SUCCESS"
        mock_instance.result = steps

        response = await client.get("/analysis/test-task-id-1234")

    assert response.status_code == 200
    assert response.json() == {"task_id": "test-task-id-1234", "status": "SUCCESS", "result": steps}
