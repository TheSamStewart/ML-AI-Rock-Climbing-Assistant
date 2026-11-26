import io
import json
import math

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from redis.exceptions import RedisError
from unittest.mock import patch

from wall_analysis import detection
from wall_analysis import scale
from coaching import worker
from api.main import (
    app,
    DEFAULT_BOLT_SPACING_CM,
    DETECTIONS_TTL_SECONDS,
    IDEMPOTENCY_TTL_SECONDS,
    MAX_BOLT_SPACING_CM,
    MIN_BOLT_SPACING_CM,
    MIN_SELECTED_HOLDS,
)

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


async def _post_analysis(client, idempotency_key="key-1", detection_id=None, selected_hold_ids="[0, 1, 2]", bolt_spacing_cm=None):
    headers = {} if idempotency_key is None else {"Idempotency-Key": idempotency_key}
    data = {}
    if detection_id is not None:
        data["detection_id"] = detection_id
    if selected_hold_ids is not None:
        data["selected_hold_ids"] = selected_hold_ids
    if bolt_spacing_cm is not None:
        data["bolt_spacing_cm"] = str(bolt_spacing_cm)
    return await client.post("/analysis", headers=headers, data=data)


def _jpeg(size):
    buf = io.BytesIO()
    Image.new("RGB", size, color=(120, 80, 40)).save(buf, format="JPEG")
    return buf.getvalue()


def _jpeg_with_orientation(size, orientation):
    # Stored pixels: left third red, rest blue, so a rotation is visible.
    image = Image.new("RGB", size, color=(0, 0, 255))
    image.paste((255, 0, 0), (0, 0, size[0] // 3, size[1]))
    exif = Image.Exif()
    exif[0x0112] = orientation  # Orientation
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif.tobytes(), quality=95)
    return buf.getvalue()


def _lattice_bolts(image_size, s):
    # Centred-square bolt lattice (corners + centres) with side s px, filling
    # the image, as normalized {x, y, diameter} dicts.
    w, h = image_size
    pts = []
    ys = [s / 2 + j * s for j in range(int((h - s / 2) // s) + 1)]
    xs = [s / 2 + i * s for i in range(int((w - s / 2) // s) + 1)]
    for y in ys:
        for x in xs:
            pts.append((x, y))
            if x + s < w and y + s < h:
                pts.append((x + s / 2, y + s / 2))
    return [{"x": x / w, "y": y / h, "diameter": s / 8} for x, y in pts]


def _units_from_px(a, b, image_size, s):
    # Ground truth for a fronto-parallel lattice of side s px: px distance / s.
    w, h = image_size
    return math.hypot((a["centroid"]["x"] - b["centroid"]["x"]) * w, (a["centroid"]["y"] - b["centroid"]["y"]) * h) / s


ANGLE_KEYS = ("angles_deg", "angle_source", "angle_margin_deg")


def _pipeline_class(redis):
    return type(redis.pipeline(transaction=True))


# The plain JPEG fixtures contain no bolts, so tests that need distances patch
# the detector to "find" a clean lattice. jpeg_bytes is 64x48; side 8 px.
FAKE_BOLT_SIDE_PX = 8.0
FAKE_BOLTS = _lattice_bolts((64, 48), FAKE_BOLT_SIDE_PX)


@pytest.fixture
def mock_bolts():
    with patch("api.main.bolts.detect_bolt_holes", return_value=FAKE_BOLTS) as mock_detect:
        yield mock_detect


def _first_arg(mock_call):
    args, kwargs = mock_call
    return args[0] if args else next(iter(kwargs.values()))


# --- POST /detect ---


async def test_detect_returns_and_caches_detections_and_scale(client, jpeg_bytes, mock_run_detection, mock_redis_client, sample_detections):
    response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 200
    body = response.json()
    assert body["detections"] == sample_detections
    detection_id = body["detection_id"]
    int(detection_id, 16)  # uuid4().hex

    cached = await mock_redis_client.get(f"detections:{detection_id}")
    assert json.loads(cached) == sample_detections
    cached_scale = await mock_redis_client.get(f"scale:{detection_id}")
    assert json.loads(cached_scale) == body["scale"]
    for key in (f"detections:{detection_id}", f"scale:{detection_id}"):
        ttl = await mock_redis_client.ttl(key)
        assert 0 < ttl <= DETECTIONS_TTL_SECONDS


async def test_detect_scale_shape(client, jpeg_bytes, mock_run_detection, mock_bolts, sample_detections):
    response = await _post_detect(client, jpeg_bytes)

    s = response.json()["scale"]
    assert set(s) == {"status", "bolt_count", "wall_length_units", "distances_units", "tiers", *ANGLE_KEYS, "wall_axes"}  # wall_axes: slice 15
    assert s["status"] == "ok"
    assert s["bolt_count"] == len(FAKE_BOLTS)
    assert isinstance(s["wall_length_units"], float) and s["wall_length_units"] > 0
    n = len(sample_detections)
    # Slice 8: tiers is N rows of N characters, "A" or "C" ("B" is not produced).
    assert len(s["tiers"]) == n
    assert all(isinstance(row, str) and len(row) == n and set(row) <= {"A", "C"} for row in s["tiers"])
    assert len(s["distances_units"]) == n and all(len(row) == n for row in s["distances_units"])
    # Slice 9: the angle fields are added on top of compute_scale's output.
    expected = scale.compute_scale(sample_detections, (64, 48), FAKE_BOLTS)
    assert {k: v for k, v in s.items() if k not in ANGLE_KEYS} == {k: v for k, v in expected.items() if k not in ANGLE_KEYS}
    assert len(s["angles_deg"]) == n
    assert all(a is None or isinstance(a, float) for a in s["angles_deg"])
    assert s["angle_source"] == "assumed"
    assert s["angle_margin_deg"] == 15


async def test_detect_plain_image_without_bolts_is_insufficient_bolts(client, jpeg_bytes, mock_run_detection, mock_redis_client):
    # Real bolt detector on a flat-colour 64x48 JPEG: nothing to find.
    response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 200
    body = response.json()
    assert body["scale"] == {
        "status": "insufficient_bolts",
        "bolt_count": 0,
        "wall_length_units": None,
        "distances_units": None,
        "tiers": None,
        "angles_deg": None,
        "angle_source": None,
        "angle_margin_deg": None,
    }
    cached = await mock_redis_client.get(f"scale:{body['detection_id']}")
    assert json.loads(cached) == body["scale"]


async def test_detect_runs_bolt_detection_on_full_res_image_without_exif(client, mock_run_detection, mock_bolts, sample_detections):
    # No EXIF orientation: the image goes through unchanged.
    response = await _post_detect(client, _jpeg((300, 100)))

    assert response.status_code == 200
    mock_bolts.assert_called_once()
    args, kwargs = mock_bolts.call_args
    image = args[0] if args else kwargs["image"]
    dets = args[1] if len(args) > 1 else kwargs["detections"]
    assert isinstance(image, Image.Image)
    assert image.size == (300, 100)
    assert dets == sample_detections
    # Same orientation as the image handed to YOLO.
    yolo_image = _first_arg(mock_run_detection.call_args)
    assert yolo_image.size == image.size


async def test_detect_passes_found_bolts_to_compute_scale(client, jpeg_bytes, mock_run_detection, mock_bolts, sample_detections):
    with patch("wall_analysis.scale.compute_scale", wraps=scale.compute_scale) as spy:
        response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 200
    spy.assert_called_once()
    args, kwargs = spy.call_args
    passed = list(args) + list(kwargs.values())
    assert passed[0] == sample_detections
    assert tuple(passed[1]) == (64, 48)
    assert passed[2] == FAKE_BOLTS


async def test_detect_bolt_detection_failure_is_500_and_caches_nothing(client, jpeg_bytes, mock_run_detection, mock_redis_client):
    with patch("api.main.bolts.detect_bolt_holes", side_effect=RuntimeError("cv2 exploded")):
        response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 500
    assert await mock_redis_client.keys("detections:*") == []
    assert await mock_redis_client.keys("scale:*") == []


async def test_analysis_after_insufficient_bolts_still_enqueues_with_null_distances(
    client, jpeg_bytes, mock_run_detection, mock_celery_task, sample_detections
):
    detection_id = (await _post_detect(client, jpeg_bytes)).json()["detection_id"]

    response = await _post_analysis(client, "key-nobolts", detection_id, "[0, 1, 2]")

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert route["holds"] == detection.select_holds(sample_detections, [0, 1, 2])
    assert route["distances_units"] is None
    assert route["wall_length_units"] is None
    data = worker.build_route_data(route)
    assert data["distances_cm"] is None
    assert data["wall_length_cm"] is None


@pytest.mark.parametrize("image_size", [(300, 100), (100, 300), (64, 48)])
async def test_detect_distances_come_from_bolt_lattice_in_px(client, mock_run_detection, sample_detections, image_size):
    # Normalized bolts and holds are mapped back to px with the uploaded image
    # size; on a fronto-parallel lattice of side s px a hold pair is px / s units.
    s = min(image_size) / 6
    with patch("api.main.bolts.detect_bolt_holes", return_value=_lattice_bolts(image_size, s)):
        response = await _post_detect(client, _jpeg(image_size))

    body = response.json()["scale"]
    assert body["status"] == "ok"
    d = body["distances_units"]
    for i, a in enumerate(sample_detections):
        assert d[i][i] == 0
        for j, b in enumerate(sample_detections):
            assert d[i][j] == d[j][i]
            if i != j:
                assert d[i][j] == pytest.approx(_units_from_px(a, b, image_size, s), rel=0.03)


# --- POST /detect: EXIF orientation (slice 4) ---


async def test_detect_applies_exif_orientation_before_yolo_and_bolts(client, mock_run_detection, mock_bolts, sample_detections):
    # Stored 300x100 with Orientation=6 (rotate 90 deg CW to display): the app
    # shows it as 100x300, so YOLO and bolt detection must see 100x300.
    with patch("wall_analysis.scale.compute_scale", wraps=scale.compute_scale) as spy:
        response = await _post_detect(client, _jpeg_with_orientation((300, 100), 6))

    assert response.status_code == 200
    yolo_image = _first_arg(mock_run_detection.call_args)
    assert yolo_image.size == (100, 300)
    mock_bolts.assert_called_once()
    args, kwargs = mock_bolts.call_args
    bolt_image = args[0] if args else kwargs["image"]
    assert isinstance(bolt_image, Image.Image)
    assert bolt_image.size == (100, 300)
    spy.assert_called_once()
    args, kwargs = spy.call_args
    passed = list(args) + list(kwargs.values())
    assert tuple(passed[1]) == (100, 300)
    assert passed[2] == FAKE_BOLTS


async def test_detect_exif_rotation_moves_pixels_not_just_size(client, mock_run_detection, mock_bolts):
    # Orientation 6: the stored left (red) third ends up as the displayed top third.
    await _post_detect(client, _jpeg_with_orientation((300, 100), 6))

    image = _first_arg(mock_run_detection.call_args).convert("RGB")
    top = image.getpixel((50, 30))
    bottom = image.getpixel((50, 270))
    assert top[0] > 200 and top[2] < 60, top
    assert bottom[2] > 200 and bottom[0] < 60, bottom


async def test_detect_exif_orientation_1_is_unchanged(client, mock_run_detection, mock_bolts):
    with patch("wall_analysis.scale.compute_scale", wraps=scale.compute_scale) as spy:
        response = await _post_detect(client, _jpeg_with_orientation((300, 100), 1))

    assert response.status_code == 200
    assert _first_arg(mock_run_detection.call_args).size == (300, 100)
    assert _first_arg(mock_bolts.call_args).size == (300, 100)
    args, kwargs = spy.call_args
    assert tuple((list(args) + list(kwargs.values()))[1]) == (300, 100)


async def test_detect_writes_both_keys_through_one_pipeline(client, jpeg_bytes, mock_run_detection, mock_redis_client):
    with patch.object(mock_redis_client, "pipeline", wraps=mock_redis_client.pipeline) as spy_pipeline:
        response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 200
    spy_pipeline.assert_called_once()
    args, kwargs = spy_pipeline.call_args
    assert kwargs.get("transaction", args[0] if args else True) is True


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
    with patch("api.main.detection.run_detection", side_effect=RuntimeError("CUDA on fire")):
        response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 500
    assert response.json() == {"detail": "Hold detection failed - try again."}
    assert await mock_redis_client.keys("detections:*") == []


async def test_detect_cache_write_failure_is_503(client, jpeg_bytes, mock_run_detection, mock_redis_client):
    with patch.object(_pipeline_class(mock_redis_client), "execute", side_effect=RedisError("down")):
        response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 503
    assert response.json() == {"detail": "Couldn't save detection results - try again."}
    assert await mock_redis_client.keys("detections:*") == []
    assert await mock_redis_client.keys("scale:*") == []


async def test_detect_scale_failure_is_500_and_caches_nothing(client, jpeg_bytes, mock_run_detection, mock_redis_client):
    with patch("wall_analysis.scale.compute_scale", side_effect=RuntimeError("scale exploded")):
        response = await _post_detect(client, jpeg_bytes)

    assert response.status_code == 500
    assert await mock_redis_client.keys("detections:*") == []
    assert await mock_redis_client.keys("scale:*") == []


async def test_detect_missing_photo_is_422(client, mock_run_detection):
    response = await client.post("/detect")

    assert response.status_code == 422
    mock_run_detection.assert_not_called()


# --- POST /analysis ---


async def test_analysis_happy_path_enqueues_route(client, cached_detection_id, sample_detections, sample_scale, mock_celery_task, mock_redis_client):
    selected = [3, 0, 2]

    response = await _post_analysis(client, "key-happy", cached_detection_id, json.dumps(selected))

    assert response.status_code == 202
    assert response.json() == {"task_id": "test-task-id-1234"}

    mock_celery_task.assert_called_once()
    [route] = mock_celery_task.call_args.args
    assert set(route) - set(ANGLE_KEYS) == {"holds", "distances_units", "tiers", "wall_length_units", "bolt_spacing_cm"}
    # conftest's sample_scale predates slice 9: no angles to pass on.
    assert route.get("angles_deg") is None
    assert route["holds"] == detection.select_holds(sample_detections, selected)
    assert route["distances_units"] == [[0.0, 3.0, 6.0], [3.0, 0.0, 2.0], [6.0, 2.0, 0.0]]
    # Picked sub-matrix of conftest's sample_scale tiers, in pick order [3, 0, 2].
    assert ["".join(r) for r in route["tiers"]] == ["AAA", "AAC", "ACA"]
    assert route["wall_length_units"] == 20.0
    assert route["bolt_spacing_cm"] == DEFAULT_BOLT_SPACING_CM

    assert await mock_redis_client.get("idempotency:key-happy") == "test-task-id-1234"
    ttl = await mock_redis_client.ttl("idempotency:key-happy")
    assert 0 < ttl <= IDEMPOTENCY_TTL_SECONDS


async def test_analysis_route_matches_select_distances(client, cached_detection_id, sample_detections, sample_scale, mock_celery_task):
    selected = [1, 3, 0, 2]

    await _post_analysis(client, "key-sub", cached_detection_id, json.dumps(selected), bolt_spacing_cm=30)

    [route] = mock_celery_task.call_args.args
    assert route["distances_units"] == scale.select_distances(sample_scale, sample_detections, selected)
    assert route["tiers"] == scale.select_tiers(sample_scale, sample_detections, selected)
    assert route["wall_length_units"] == sample_scale["wall_length_units"]
    assert route["bolt_spacing_cm"] == 30.0
    assert isinstance(route["bolt_spacing_cm"], float)
    json.dumps(route)  # Celery's JSON serializer must accept it


async def test_analysis_old_cached_scale_without_tiers_still_enqueues(client, cached_detection_id, sample_detections, sample_scale, mock_celery_task, mock_redis_client):
    # A scale cached before slice 8 has tiers None: /analysis must still enqueue.
    sample_scale["tiers"] = None
    await mock_redis_client.set(f"scale:{cached_detection_id}", json.dumps(sample_scale))

    response = await _post_analysis(client, "key-no-tiers", cached_detection_id, json.dumps([3, 0, 2]))

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert route.get("tiers") is None
    json.dumps(route)


async def test_analysis_reads_both_keys_with_mget(client, cached_detection_id, mock_redis_client):
    with patch.object(mock_redis_client, "mget", wraps=mock_redis_client.mget) as spy_mget:
        response = await _post_analysis(client, "key-mget", cached_detection_id)

    assert response.status_code == 202
    spy_mget.assert_called_once()
    args, kwargs = spy_mget.call_args
    flat = [k for a in args for k in (a if isinstance(a, (list, tuple)) else [a])]
    assert set(flat) == {f"detections:{cached_detection_id}", f"scale:{cached_detection_id}"}


# --- POST /analysis: bolt_spacing_cm ---


def test_bolt_spacing_constants():
    assert DEFAULT_BOLT_SPACING_CM == 20.0
    assert MIN_BOLT_SPACING_CM == 10.0
    assert MAX_BOLT_SPACING_CM == 50.0


@pytest.mark.parametrize("bolt_spacing_cm, expected", [(None, 20.0), ("10", 10.0), ("50", 50.0), ("10.0", 10.0), ("20.5", 20.5)])
async def test_analysis_bolt_spacing_accepted_values(client, cached_detection_id, mock_celery_task, bolt_spacing_cm, expected):
    response = await _post_analysis(client, "key-bolt-ok", cached_detection_id, bolt_spacing_cm=bolt_spacing_cm)

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert route["bolt_spacing_cm"] == expected


NO_BOLT_SPACING_DETAIL = {"detail": "No bolt spacing provided."}
BOLT_SPACING_RANGE_DETAIL = {"detail": "Bolt spacing must be between 10 and 50 cm."}

EMPTY_BOLT_SPACING = ["", "  ", " ", "	", " 	 "]
INVALID_BOLT_SPACING = ["9.9", "5", "4.9", "50.1", "0", "-20", "nan", "NaN", "inf", "-inf", "abc"]


@pytest.mark.parametrize(
    "bolt_spacing_cm, expected_body",
    [(v, NO_BOLT_SPACING_DETAIL) for v in EMPTY_BOLT_SPACING]
    + [(v, BOLT_SPACING_RANGE_DETAIL) for v in INVALID_BOLT_SPACING],
)
async def test_analysis_bolt_spacing_rejected_before_touching_redis_or_celery(
    client, cached_detection_id, mock_celery_task, mock_redis_client, bolt_spacing_cm, expected_body
):
    with patch.object(mock_redis_client, "mget", wraps=mock_redis_client.mget) as spy_mget, \
            patch.object(mock_redis_client, "get", wraps=mock_redis_client.get) as spy_get:
        response = await client.post(
            "/analysis",
            headers={"Idempotency-Key": "key-bolt-bad"},
            data={"detection_id": cached_detection_id, "selected_hold_ids": "[0, 1, 2]", "bolt_spacing_cm": bolt_spacing_cm},
        )

    assert response.status_code == 422
    assert response.json() == expected_body
    spy_mget.assert_not_called()
    spy_get.assert_not_called()
    mock_celery_task.assert_not_called()
    assert await mock_redis_client.get("idempotency:key-bolt-bad") is None


async def test_analysis_bolt_spacing_absent_defaults_to_20(client, cached_detection_id, mock_celery_task):
    # Field omitted entirely (not sent as "") -> default, unlike the empty case.
    response = await client.post(
        "/analysis",
        headers={"Idempotency-Key": "key-bolt-absent"},
        data={"detection_id": cached_detection_id, "selected_hold_ids": "[0, 1, 2]"},
    )

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert route["bolt_spacing_cm"] == DEFAULT_BOLT_SPACING_CM == 20.0


@pytest.mark.parametrize("bolt_spacing_cm", ["nan", "abc", "9.9", "", "  "])
async def test_analysis_hold_selection_is_checked_before_bolt_spacing(client, cached_detection_id, mock_celery_task, bolt_spacing_cm):
    response = await _post_analysis(client, "key-both-bad", cached_detection_id, "[]", bolt_spacing_cm=bolt_spacing_cm)

    assert response.status_code == 422
    assert str(MIN_SELECTED_HOLDS) in response.json()["detail"]
    assert response.json() not in (NO_BOLT_SPACING_DETAIL, BOLT_SPACING_RANGE_DETAIL)
    mock_celery_task.assert_not_called()


@pytest.mark.parametrize("bolt_spacing_cm", ["", "  ", "abc", "9.9", "50.1"])
async def test_analysis_rejected_bolt_spacing_does_not_reserve_idempotency_key(
    client, cached_detection_id, mock_celery_task, bolt_spacing_cm
):
    # A 422 for bolt spacing must not burn the Idempotency-Key: a corrected retry
    # with the same key is accepted.
    bad = await _post_analysis(client, "key-bolt-retry", cached_detection_id, bolt_spacing_cm=bolt_spacing_cm)
    good = await _post_analysis(client, "key-bolt-retry", cached_detection_id, bolt_spacing_cm="25")

    assert bad.status_code == 422
    assert good.status_code == 202
    mock_celery_task.assert_called_once()
    [route] = mock_celery_task.call_args.args
    assert route["bolt_spacing_cm"] == 25.0


async def test_changing_bolt_spacing_rescales_llm_distances_without_rerunning_detection(
    client, jpeg_bytes, mock_run_detection, mock_bolts, mock_celery_task
):
    # Spec target: changing bolt_spacing_cm rescales distances without
    # re-running detection. One /detect, two /analysis calls on the same id.
    detection_id = (await _post_detect(client, jpeg_bytes)).json()["detection_id"]

    r10 = await _post_analysis(client, "key-bolt-10", detection_id, "[0, 1, 2, 3]", bolt_spacing_cm=10)
    r40 = await _post_analysis(client, "key-bolt-40", detection_id, "[0, 1, 2, 3]", bolt_spacing_cm=40)

    assert r10.status_code == r40.status_code == 202
    assert mock_run_detection.call_count == 1
    route10, route40 = (c.args[0] for c in mock_celery_task.call_args_list)
    assert route10["distances_units"] == route40["distances_units"]

    data10 = worker.build_route_data(route10)
    data40 = worker.build_route_data(route40)
    assert len(data10["distances_cm"]) == len(data40["distances_cm"]) == 6
    for a, b in zip(data10["distances_cm"], data40["distances_cm"]):
        assert (a["from"], a["to"]) == (b["from"], b["to"])
        assert a["cm"] > 0
        assert b["cm"] == pytest.approx(4 * a["cm"], abs=0.25)
    assert route10["wall_length_units"] == route40["wall_length_units"] is not None
    assert data10["wall_length_cm"] == round(route10["wall_length_units"] * 10, 1)
    assert data40["wall_length_cm"] == round(route40["wall_length_units"] * 40, 1)
    assert data40["wall_length_cm"] == pytest.approx(4 * data10["wall_length_cm"], abs=0.25)


# --- POST /analysis: cache misses ---


@pytest.mark.parametrize("missing_prefix", ["detections", "scale"])
async def test_analysis_missing_either_cached_key_is_410(client, cached_detection_id, mock_celery_task, mock_redis_client, missing_prefix):
    await mock_redis_client.delete(f"{missing_prefix}:{cached_detection_id}")

    response = await _post_analysis(client, "key-half", cached_detection_id)

    assert response.status_code == 410
    assert "expired or not found" in response.json()["detail"]
    mock_celery_task.assert_not_called()
    assert await mock_redis_client.get("idempotency:key-half") is None


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
    with patch.object(mock_redis_client, "get", wraps=mock_redis_client.get) as spy_get, \
            patch.object(mock_redis_client, "mget", wraps=mock_redis_client.mget) as spy_mget:
        response = await _post_analysis(client, "key-bad", cached_detection_id, selected_hold_ids)

    assert response.status_code == 422
    assert str(MIN_SELECTED_HOLDS) in response.json()["detail"]
    spy_get.assert_not_called()
    spy_mget.assert_not_called()
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
    with patch("api.main.AsyncResult") as mock_async_result:
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
    with patch("api.main.AsyncResult") as mock_async_result:
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
    with patch("api.main.AsyncResult") as mock_async_result:
        mock_instance = mock_async_result.return_value
        mock_instance.state = "SUCCESS"
        mock_instance.result = steps

        response = await client.get("/analysis/test-task-id-1234")

    assert response.status_code == 200
    assert response.json() == {"task_id": "test-task-id-1234", "status": "SUCCESS", "result": steps}


# --- /analysis climber stats (slice 15, Developer-written) --------------------

async def _post_with_climber(client, detection_id, **fields):
    data = {"detection_id": detection_id, "selected_hold_ids": "[3, 0, 2]", **{k: str(v) for k, v in fields.items()}}
    return await client.post("/analysis", headers={"Idempotency-Key": f"key-climber-{len(fields)}-{sorted(fields.items())}"}, data=data)


async def test_analysis_passes_climber_stats_to_the_worker(client, cached_detection_id, mock_celery_task):
    response = await _post_with_climber(client, cached_detection_id, climber_height_cm=175, climber_arm_span_cm="181.5")

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert route["climber"] == {"height_cm": 175.0, "arm_span_cm": 181.5}


async def test_analysis_without_climber_stats_has_no_climber_key(client, cached_detection_id, mock_celery_task):
    response = await _post_with_climber(client, cached_detection_id, climber_height_cm="")

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert "climber" not in route


@pytest.mark.parametrize("field,value", [("climber_height_cm", 40), ("climber_height_cm", "tall"), ("climber_arm_span_cm", 400), ("climber_arm_span_cm", "nan")])
async def test_analysis_rejects_nonsense_climber_stats(client, cached_detection_id, mock_celery_task, field, value):
    response = await _post_with_climber(client, cached_detection_id, **{field: value})

    assert response.status_code == 422
    mock_celery_task.assert_not_called()


@pytest.mark.parametrize("sent,expect", [("true", True), ("false", False), ("maybe", None)])
async def test_analysis_passes_whole_wall_answer(client, cached_detection_id, mock_celery_task, sent, expect):
    data = {"detection_id": cached_detection_id, "selected_hold_ids": "[3, 0, 2]", "whole_wall_in_photo": sent}
    response = await client.post("/analysis", headers={"Idempotency-Key": f"key-wall-{sent}"}, data=data)

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert route.get("whole_wall_in_photo") == expect
