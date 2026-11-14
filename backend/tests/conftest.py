import io
import json

import fakeredis
import pytest
from PIL import Image
from unittest.mock import patch

# Shared across every test module in backend/. Patching "main.analysis_task.delay"
# and "main.redis_client" forces main.py (and transitively worker.py,
# detection.py, redis_client.py) to import, which is harmless - none of that
# module-level code opens a real network connection or loads the YOLO model.


@pytest.fixture(autouse=True)
def mock_celery_task():
    with patch("main.analysis_task.delay") as mock_task:
        mock_task.return_value.id = "test-task-id-1234"
        yield mock_task


@pytest.fixture(autouse=True)
def mock_redis_client():
    # decode_responses=True to match the real client in redis_client.py -
    # without it GET returns bytes and main.py's "processing" sentinel
    # comparison never matches.
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    with patch("main.redis_client", fake_redis):
        yield fake_redis


@pytest.fixture
def anyio_backend():
    # Restrict anyio-marked async tests to asyncio - trio isn't a project
    # dependency and we don't need two backends' worth of test runs.
    return "asyncio"


# Same shape detection.run_detection() returns - ids are list indices.

@pytest.fixture
def sample_detections():
    def _det(id_, class_name, x, y, confidence=0.9, size=0.05):
        return {
            "id": id_,
            "class_name": class_name,
            "centroid": {"x": x, "y": y},
            "polygon": [
                {"x": x - 0.01, "y": y - 0.01},
                {"x": x + 0.01, "y": y - 0.01},
                {"x": x + 0.01, "y": y + 0.01},
                {"x": x - 0.01, "y": y + 0.01},
            ],
            "confidence": confidence,
            "size": size,
        }

    return [
        _det(0, "HOLD", 0.2, 0.9),
        _det(1, "HOLD", 0.4, 0.6),
        _det(2, "VOLUME", 0.5, 0.4, size=0.2),
        _det(3, "HOLD", 0.6, 0.1),
    ]


@pytest.fixture
def sample_scale():
    # Hand-built (not computed by scale.compute_scale) so /analysis tests can
    # check the sub-matrix selection against distinct, known values. Indexed
    # in sample_detections order; symmetric with a zero diagonal.
    return {
        "status": "ok",
        "bolt_count": 0,
        "wall_length_units": 20.0,
        "distances_units": [
            [0.0, 1.0, 2.0, 3.0],
            [1.0, 0.0, 4.0, 5.0],
            [2.0, 4.0, 0.0, 6.0],
            [3.0, 5.0, 6.0, 0.0],
        ],
        # Slice 5c: N rows of N chars, "A"/"C" per pair. Symmetric, "A" on the
        # diagonal. C pairs: (0,2), (1,2), (1,3); the rest are A.
        "tiers": ["AACA", "AACC", "CCAA", "ACAA"],
    }


@pytest.fixture
async def cached_detection_id(mock_redis_client, sample_detections, sample_scale):
    # Seeds the fake redis the way a prior /detect call would (both the
    # detections and the scale key), so /analysis tests don't need to go
    # through /detect first.
    detection_id = "cafebabe" * 4
    await mock_redis_client.set(f"detections:{detection_id}", json.dumps(sample_detections))
    await mock_redis_client.set(f"scale:{detection_id}", json.dumps(sample_scale))
    return detection_id


@pytest.fixture
def jpeg_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color=(120, 80, 40)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def mock_run_detection(sample_detections):
    with patch("main.detection.run_detection", return_value=sample_detections) as mock_run:
        yield mock_run
