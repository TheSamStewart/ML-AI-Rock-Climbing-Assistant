"""Slice 9: /detect gravity field, scale angle fields, and /analysis angle plumbing."""
import json
import math
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

import detection
import scale
import worker
from main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=300) as ac:
        yield ac


def _lattice_bolts(image_size, s):
    # Centred-square bolt lattice (corners + centres) with side s px, as normalized dicts.
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


FAKE_BOLTS = _lattice_bolts((64, 48), 8.0)


@pytest.fixture
def mock_bolts():
    with patch("main.bolts.detect_bolt_holes", return_value=FAKE_BOLTS) as mock_detect:
        yield mock_detect


async def _post_analysis(client, key, detection_id, selected):
    return await client.post(
        "/analysis",
        headers={"Idempotency-Key": key},
        data={"detection_id": detection_id, "selected_hold_ids": selected},
    )


ANGLE_KEYS = ("angles_deg", "angle_source", "angle_margin_deg")

# Phone upright, camera looking 14 deg above horizontal. Android reports the
# reaction to gravity (y ~ +g), iOS native reports gravity (y ~ -g).
G = 9.81
P14 = math.radians(14)
ANDROID_14 = [0.0, G * math.cos(P14), -G * math.sin(P14)]
IOS_14 = [-c for c in ANDROID_14]
FLAT_PHONE = [0.0, 0.5, -9.8]


def _csv(v):
    return ",".join(str(c) for c in v)


async def _detect(client, jpeg, gravity):
    data = {} if gravity is None else {"gravity": gravity}
    return await client.post("/detect", files={"photo": ("wall.jpg", jpeg, "image/jpeg")}, data=data)


def _assert_source(s, n, source, margin):
    assert s["status"] == "ok"
    assert s["angle_source"] == source
    assert s["angle_margin_deg"] == margin
    assert len(s["angles_deg"]) == n


# --- /detect: gravity field ---


@pytest.mark.parametrize(
    "gravity",
    [json.dumps(ANDROID_14), json.dumps(IOS_14), _csv(ANDROID_14), _csv(IOS_14), " " + ", ".join(str(c) for c in ANDROID_14) + " "],
)
async def test_valid_upright_gravity_uses_sensor(client, jpeg_bytes, mock_run_detection, mock_bolts, sample_detections, gravity):
    response = await _detect(client, jpeg_bytes, gravity)

    assert response.status_code == 200
    _assert_source(response.json()["scale"], len(sample_detections), "sensor", 8)


async def test_android_ios_and_csv_readings_give_the_same_angles(client, jpeg_bytes, mock_run_detection, mock_bolts):
    a = (await _detect(client, jpeg_bytes, json.dumps(ANDROID_14))).json()["scale"]
    i = (await _detect(client, jpeg_bytes, json.dumps(IOS_14))).json()["scale"]
    csv = (await _detect(client, jpeg_bytes, _csv(ANDROID_14))).json()["scale"]

    assert a["angles_deg"] == i["angles_deg"] == csv["angles_deg"]


async def test_angles_are_floats_or_null_with_one_decimal(client, jpeg_bytes, mock_run_detection, mock_bolts):
    s = (await _detect(client, jpeg_bytes, json.dumps(ANDROID_14))).json()["scale"]

    for a in s["angles_deg"]:
        assert a is None or (isinstance(a, float) and a == round(a, 1) and -90 < a < 90)


async def test_sensor_reading_moves_the_angles_versus_assumed(client, jpeg_bytes, mock_run_detection, mock_bolts):
    # A reading of 35 deg pitch against the 12 deg fallback: same photo, different tilt.
    p = math.radians(35)
    steep = json.dumps([0.0, G * math.cos(p), -G * math.sin(p)])
    sensor = (await _detect(client, jpeg_bytes, steep)).json()["scale"]
    assumed = (await _detect(client, jpeg_bytes, None)).json()["scale"]

    pairs = [(a, b) for a, b in zip(sensor["angles_deg"], assumed["angles_deg"]) if a is not None and b is not None]
    assert pairs, "expected at least one numeric angle on the fake lattice"
    assert any(abs(a - b) > 1.0 for a, b in pairs)


@pytest.mark.parametrize("gravity", [None, "", "   "])
async def test_missing_or_empty_gravity_is_assumed(client, jpeg_bytes, mock_run_detection, mock_bolts, sample_detections, gravity):
    response = await _detect(client, jpeg_bytes, gravity)

    assert response.status_code == 200
    _assert_source(response.json()["scale"], len(sample_detections), "assumed", 15)


@pytest.mark.parametrize(
    "gravity",
    ["abc", "1,2", "[1, 2]", "[]", "{}", '{"x": 1}', '["a", 1, 2]', "nan,nan,nan", "[NaN, NaN, NaN]", "0,0,0", "inf,0,0", "1,,3", "null"],
)
async def test_malformed_gravity_is_ignored_not_an_error(client, jpeg_bytes, mock_run_detection, mock_bolts, sample_detections, gravity):
    response = await _detect(client, jpeg_bytes, gravity)

    assert response.status_code == 200
    _assert_source(response.json()["scale"], len(sample_detections), "assumed", 15)


@pytest.mark.parametrize(
    "reading",
    [FLAT_PHONE, [0.0, -0.5, 9.8], [9.8, 0.3, 0.0], [0.0, 0.4 * G, -math.sqrt(1 - 0.16) * G]],
)
async def test_flat_or_sideways_phone_reading_is_assumed(client, jpeg_bytes, mock_run_detection, mock_bolts, sample_detections, reading):
    for form in (json.dumps(reading), _csv(reading)):
        response = await _detect(client, jpeg_bytes, form)

        assert response.status_code == 200
        _assert_source(response.json()["scale"], len(sample_detections), "assumed", 15)


async def test_gravity_y_axis_just_inside_60_degrees_is_used(client, jpeg_bytes, mock_run_detection, mock_bolts, sample_detections):
    response = await _detect(client, jpeg_bytes, json.dumps([0.0, 0.6 * G, -0.8 * G]))

    _assert_source(response.json()["scale"], len(sample_detections), "sensor", 8)


@pytest.mark.parametrize("gravity", [None, json.dumps(ANDROID_14), "abc", json.dumps(FLAT_PHONE)])
async def test_insufficient_bolts_has_null_angle_fields_whatever_the_gravity(client, jpeg_bytes, mock_run_detection, gravity):
    # Real bolt detector on a flat-colour image finds nothing.
    response = await _detect(client, jpeg_bytes, gravity)

    s = response.json()["scale"]
    assert response.status_code == 200
    assert s["status"] == "insufficient_bolts"
    assert s["angles_deg"] is None
    assert s["angle_source"] is None
    assert s["angle_margin_deg"] is None


async def test_gravity_does_not_change_distances(client, jpeg_bytes, mock_run_detection, mock_bolts):
    with_sensor = (await _detect(client, jpeg_bytes, json.dumps(ANDROID_14))).json()["scale"]
    without = (await _detect(client, jpeg_bytes, None)).json()["scale"]

    for key in ("status", "bolt_count", "wall_length_units", "distances_units", "tiers"):
        assert with_sensor[key] == without[key]


async def test_scale_with_angles_is_cached_unchanged(client, jpeg_bytes, mock_run_detection, mock_bolts, mock_redis_client):
    body = (await _detect(client, jpeg_bytes, json.dumps(ANDROID_14))).json()

    cached = await mock_redis_client.get(f"scale:{body['detection_id']}")
    assert json.loads(cached) == body["scale"]
    assert body["scale"]["angle_source"] == "sensor"


async def test_angle_failure_never_fails_detect(client, jpeg_bytes, mock_run_detection, mock_bolts):
    baseline = (await _detect(client, jpeg_bytes, json.dumps(ANDROID_14))).json()["scale"]

    with patch("angle.plane_normals", side_effect=RuntimeError("angle exploded")):
        response = await _detect(client, jpeg_bytes, json.dumps(ANDROID_14))

    assert response.status_code == 200
    s = response.json()["scale"]
    assert s["angles_deg"] is None
    assert s["angle_source"] is None
    assert s["angle_margin_deg"] is None
    for key in ("status", "bolt_count", "wall_length_units", "distances_units", "tiers"):
        assert s[key] == baseline[key]


# --- scale.select_angles ---

ANGLES = [10.0, None, 25.5, 14.0]  # sample_detections order


def _scale_with_angles(sample_scale, angles=ANGLES, source="sensor", margin=8):
    sample_scale["angles_deg"] = angles
    sample_scale["angle_source"] = source
    sample_scale["angle_margin_deg"] = margin
    return sample_scale


def test_select_angles_follows_pick_order(sample_detections, sample_scale):
    s = _scale_with_angles(sample_scale)

    assert scale.select_angles(s, sample_detections, [3, 0, 2]) == [14.0, 10.0, 25.5]
    assert scale.select_angles(s, sample_detections, [2, 3, 0]) == [25.5, 14.0, 10.0]


def test_select_angles_keeps_nulls_and_duplicates(sample_detections, sample_scale):
    s = _scale_with_angles(sample_scale)

    assert scale.select_angles(s, sample_detections, [1, 0, 1]) == [None, 10.0, None]


def test_select_angles_none_when_scale_has_none(sample_detections, sample_scale):
    assert scale.select_angles(sample_scale, sample_detections, [0, 1, 2]) is None  # pre-5d scale (no key)
    sample_scale["angles_deg"] = None
    assert scale.select_angles(sample_scale, sample_detections, [0, 1, 2]) is None


def test_select_angles_does_not_mutate_scale(sample_detections, sample_scale):
    s = _scale_with_angles(sample_scale)
    before = json.dumps(s)

    scale.select_angles(s, sample_detections, [3, 0, 2])

    assert json.dumps(s) == before


# --- /analysis ---


async def _seed(mock_redis_client, detection_id, sample_scale, **kw):
    await mock_redis_client.set(f"scale:{detection_id}", json.dumps(_scale_with_angles(sample_scale, **kw)))


async def test_analysis_passes_picked_angles_in_pick_order(client, cached_detection_id, sample_scale, mock_celery_task, mock_redis_client):
    await _seed(mock_redis_client, cached_detection_id, sample_scale)

    response = await _post_analysis(client, "key-angles", cached_detection_id, json.dumps([3, 0, 2]))

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert route["angles_deg"] == [14.0, 10.0, 25.5]
    assert route["angle_source"] == "sensor"
    assert route["angle_margin_deg"] == 8
    json.dumps(route)


async def test_analysis_passes_null_for_hold_without_angle_and_assumed_margin(client, cached_detection_id, sample_scale, mock_celery_task, mock_redis_client):
    await _seed(mock_redis_client, cached_detection_id, sample_scale, source="assumed", margin=15)

    await _post_analysis(client, "key-angles-null", cached_detection_id, json.dumps([1, 0, 3]))

    [route] = mock_celery_task.call_args.args
    assert route["angles_deg"] == [None, 10.0, 14.0]
    assert route["angle_source"] == "assumed"
    assert route["angle_margin_deg"] == 15


async def test_analysis_route_angles_match_select_angles(client, cached_detection_id, sample_detections, sample_scale, mock_celery_task, mock_redis_client):
    await _seed(mock_redis_client, cached_detection_id, sample_scale)

    await _post_analysis(client, "key-angles-sel", cached_detection_id, json.dumps([2, 3, 1, 0]))

    [route] = mock_celery_task.call_args.args
    assert route["angles_deg"] == scale.select_angles(sample_scale, sample_detections, [2, 3, 1, 0])


async def test_analysis_old_scale_without_angles_gives_pre_5d_payload(client, cached_detection_id, mock_celery_task):
    response = await _post_analysis(client, "key-no-angles", cached_detection_id, json.dumps([3, 0, 2]))

    assert response.status_code == 202
    [route] = mock_celery_task.call_args.args
    assert route.get("angles_deg") is None
    data = worker.build_route_data(route)
    assert set(data) == {"holds", "distances_cm", "wall_length_cm", "accuracy"}
    assert all("wall_angle_deg" not in h for h in data["holds"])


async def test_detect_then_analysis_angles_reach_the_worker_payload(client, jpeg_bytes, mock_run_detection, mock_bolts, mock_celery_task):
    detect = (await _detect(client, jpeg_bytes, json.dumps(ANDROID_14))).json()

    await _post_analysis(client, "key-e2e-angles", detect["detection_id"], "[0, 1, 3]")

    [route] = mock_celery_task.call_args.args
    assert route["angle_source"] == "sensor"
    assert route["angle_margin_deg"] == 8
    assert route["angles_deg"] == [detect["scale"]["angles_deg"][i] for i in (0, 1, 3)]
    data = worker.build_route_data(route)
    if any(a is not None for a in route["angles_deg"]):
        assert data["wall_angle"]["margin_deg"] == 8
        assert data["wall_angle"]["source"] == "sensor"


# --- reference photo (slow) ---

EPIC = Path(__file__).resolve().parents[2] / "mobile" / "ML-Rock-Climbing-App" / "assets" / "known_measurements" / "reference" / "epic_wall.jpg"


@pytest.mark.slow
@pytest.mark.skipif(not detection.MODEL_PATH.exists(), reason="models/best.pt not present (gitignored)")
@pytest.mark.skipif(not EPIC.exists(), reason="epic_wall.jpg not present")
async def test_epic_wall_angles_with_simulated_pitch_14(client, mock_celery_task):
    # epic_wall panels: 14 deg at the top, 25-31 deg below. Phone reading simulates pitch 14.
    response = await client.post(
        "/detect",
        files={"photo": ("epic_wall.jpg", EPIC.read_bytes(), "image/jpeg")},
        data={"gravity": json.dumps(ANDROID_14)},
    )

    assert response.status_code == 200
    body = response.json()
    s = body["scale"]
    assert s["status"] == "ok"
    assert s["angle_source"] == "sensor"
    assert s["angle_margin_deg"] == 8
    dets, angles = body["detections"], s["angles_deg"]
    assert len(angles) == len(dets)

    def median(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2

    top = [a for d, a in zip(dets, angles) if a is not None and d["centroid"]["y"] < 1 / 3]
    low = [a for d, a in zip(dets, angles) if a is not None and d["centroid"]["y"] >= 1 / 3]
    assert len(top) >= 5 and len(low) >= 10
    assert abs(median(top) - 14) <= 5, median(top)
    assert abs(median(low) - 27) <= 6, median(low)
