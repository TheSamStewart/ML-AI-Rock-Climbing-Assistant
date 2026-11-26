"""Volume scan (test feature): tests written from docs/milestones/v0.2/38-volume-scan-trial/spec.md.

Fast tests cover the POST /dev/volume-scan contract (scan_volume and YOLO
patched, scans saved under tmp_path) and scan_volume's input rules. Slow
tests cover acceptance criterion 1 on synthetic sweeps from
experiments/two_photo/synth.py (each rendered image takes ~15 s).
"""
import inspect
import io
import json
import math
import re
import statistics
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from api import main
from wall_analysis import volume_scan
from api.main import app

BACKEND = Path(__file__).resolve().parents[1]
SYNTH_DIR = BACKEND / "experiments" / "two_photo"

RESPONSE_KEYS = {"scan_id", "faces", "depth_cm", "wall_angle_deg", "frames_used", "frames_sent", "seconds"}
FACE_KEYS = {"steepness_deg", "facing", "facing_deg", "outline", "n_points"}
FACINGS = {"out", "left", "right", "undefined"}
FRAME_FILE = re.compile(r"^frame_\d\d\.jpg$")

POLYGON = [{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.4}, {"x": 0.6, "y": 0.6}, {"x": 0.4, "y": 0.6}]
GRAVITY = [0.0, -9.5, 2.4]


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------

def _jpeg(size=(64, 48), color=(120, 80, 40)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="JPEG")
    return buf.getvalue()


def _fake_result(frames_sent=3):
    """What scan_volume returns per the contract: the response fields except
    scan_id, plus points, photo_axis_ratio and frame_diagnostics."""
    return {
        "faces": [
            {"steepness_deg": 23.0, "facing": "out", "facing_deg": 1.5,
             "outline": [{"x": 0.45, "y": 0.45}, {"x": 0.55, "y": 0.45}, {"x": 0.5, "y": 0.55}],
             "n_points": 120},
            {"steepness_deg": -10.0, "facing": "left", "facing_deg": -40.0,
             "outline": [{"x": 0.40, "y": 0.45}, {"x": 0.45, "y": 0.45}, {"x": 0.42, "y": 0.55}],
             "n_points": 80},
        ],
        "depth_cm": 30.0,
        "wall_angle_deg": 20.0,
        "frames_used": min(frames_sent, 12),
        "frames_sent": frames_sent,
        "seconds": 1.25,
        "points": [[0.0, 0.0, 1.0]],
        "photo_axis_ratio": 1.01,
        "frame_diagnostics": [],
    }


@pytest.fixture
def scans_dir(tmp_path, monkeypatch):
    d = tmp_path / "scans"
    d.mkdir()
    monkeypatch.setattr(main, "SCANS_DIR", d)
    return d


@pytest.fixture
def fake_scan():
    """Patches volume_scan.scan_volume (and main's own name for it, if main
    imported the function directly) with one shared mock."""
    mock = MagicMock(side_effect=lambda *a, **k: _fake_result(len(_bound(a, k)["frames"])))
    patches = [patch.object(volume_scan, "scan_volume", mock)]
    if hasattr(main, "scan_volume"):
        patches.append(patch.object(main, "scan_volume", mock))
    for p in patches:
        p.start()
    yield mock
    for p in reversed(patches):
        p.stop()


REAL_SCAN_VOLUME = volume_scan.scan_volume


def _bound(args, kwargs):
    """Call arguments by name, using the real scan_volume signature."""
    b = inspect.signature(REAL_SCAN_VOLUME).bind(*args, **kwargs)
    b.apply_defaults()
    return b.arguments


async def _post(photo=None, frames=None, polygon=POLYGON, gravity=None, spacing=None):
    photo = _jpeg((640, 480)) if photo is None else photo
    frames = [_jpeg((640, 480)) for _ in range(3)] if frames is None else frames
    files = [("photo", ("photo.jpg", photo, "image/jpeg"))]
    files += [("frames", (f"f{i}.jpg", fr, "image/jpeg")) for i, fr in enumerate(frames)]
    data = {}
    if polygon is not None:
        data["volume_polygon"] = polygon if isinstance(polygon, str) else json.dumps(polygon)
    if gravity is not None:
        data["gravity"] = gravity if isinstance(gravity, str) else json.dumps(gravity)
    if spacing is not None:
        data["bolt_spacing_cm"] = str(spacing)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post("/dev/volume-scan", files=files, data=data)


def _scan_json(scans_dir, scan_id):
    folder = scans_dir / scan_id
    assert folder.is_dir(), f"no scan folder {folder}"
    path = folder / "scan.json"
    assert path.is_file(), "scan.json not saved"
    return json.loads(path.read_text())


def _assert_422_saved(response, scans_dir):
    assert response.status_code == 422, response.text
    body = response.json()
    assert isinstance(body.get("detail"), str) and body["detail"].strip(), body
    assert isinstance(body.get("scan_id"), str) and body["scan_id"], body
    saved = _scan_json(scans_dir, body["scan_id"])
    assert saved.get("error"), f"scan.json has no error: {saved}"
    assert "result" not in saved or not saved["result"]
    return body


# ---------------------------------------------------------------------------
# endpoint: success
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_success_returns_documented_shape(scans_dir, fake_scan, mock_run_detection):
    r = await _post(gravity=GRAVITY, spacing=25)
    assert r.status_code == 200, r.text
    body = r.json()
    assert RESPONSE_KEYS <= set(body), set(body)
    assert isinstance(body["scan_id"], str) and body["scan_id"]
    assert isinstance(body["faces"], list) and len(body["faces"]) == 2
    for face in body["faces"]:
        assert FACE_KEYS <= set(face)
        assert face["facing"] in FACINGS
        assert isinstance(face["n_points"], int)
        assert all(set(p) >= {"x", "y"} for p in face["outline"])
    assert body["faces"][0]["steepness_deg"] == 23.0
    assert body["depth_cm"] == 30.0
    assert body["wall_angle_deg"] == 20.0
    assert body["frames_sent"] == 3
    assert isinstance(body["frames_used"], int)
    assert isinstance(body["seconds"], (int, float))


@pytest.mark.anyio
async def test_success_saves_inputs_result_and_template(scans_dir, fake_scan, mock_run_detection):
    r = await _post(frames=[_jpeg((640, 480)) for _ in range(4)])
    assert r.status_code == 200, r.text
    scan_id = r.json()["scan_id"]
    folder = scans_dir / scan_id
    assert (folder / "photo.jpg").is_file()
    Image.open(folder / "photo.jpg").verify()
    frame_files = sorted(p.name for p in folder.iterdir() if FRAME_FILE.match(p.name))
    assert len(frame_files) == 4, sorted(p.name for p in folder.iterdir())
    saved = _scan_json(scans_dir, scan_id)
    assert saved.get("result"), saved
    assert not saved.get("error")
    json.loads((folder / "volume.json").read_text())  # a valid JSON template


@pytest.mark.anyio
async def test_each_request_gets_a_new_folder(scans_dir, fake_scan, mock_run_detection):
    a = (await _post()).json()["scan_id"]
    b = (await _post()).json()["scan_id"]
    assert a != b
    assert (scans_dir / a).is_dir() and (scans_dir / b).is_dir()


@pytest.mark.anyio
async def test_scan_volume_gets_inputs(scans_dir, fake_scan, mock_run_detection, sample_detections):
    r = await _post(gravity=GRAVITY, spacing=30)
    assert r.status_code == 200, r.text
    fake_scan.assert_called_once()
    args = _bound(fake_scan.call_args.args, fake_scan.call_args.kwargs)
    assert isinstance(args["photo"], Image.Image)
    assert len(args["frames"]) == 3 and all(isinstance(f, Image.Image) for f in args["frames"])
    poly = [(p["x"], p["y"]) for p in args["volume_polygon"]] if isinstance(args["volume_polygon"][0], dict) \
        else [tuple(p) for p in args["volume_polygon"]]
    assert poly == [(p["x"], p["y"]) for p in POLYGON]
    assert args["detections"] == sample_detections
    assert args["gravity_reading"] is not None
    assert float(args["bolt_spacing_cm"]) == 30.0
    mock_run_detection.assert_called_once()


@pytest.mark.anyio
async def test_default_spacing_is_20(scans_dir, fake_scan, mock_run_detection):
    r = await _post()
    assert r.status_code == 200, r.text
    args = _bound(fake_scan.call_args.args, fake_scan.call_args.kwargs)
    assert float(args["bolt_spacing_cm"]) == 20.0


@pytest.mark.anyio
@pytest.mark.parametrize("spacing", [10, 50])
async def test_spacing_range_ends_accepted(scans_dir, fake_scan, mock_run_detection, spacing):
    r = await _post(spacing=spacing)
    assert r.status_code == 200, r.text


@pytest.mark.anyio
async def test_yolo_failure_does_not_stop_scan(scans_dir, fake_scan):
    with patch("api.main.detection.run_detection", side_effect=RuntimeError("model blew up")):
        r = await _post()
    assert r.status_code == 200, r.text
    fake_scan.assert_called_once()
    assert (scans_dir / r.json()["scan_id"] / "scan.json").is_file()


@pytest.mark.anyio
async def test_twenty_frames_accepted(scans_dir, fake_scan, mock_run_detection):
    r = await _post(frames=[_jpeg() for _ in range(20)])
    assert r.status_code == 200, r.text
    args = _bound(fake_scan.call_args.args, fake_scan.call_args.kwargs)
    assert len(args["frames"]) == 20  # thinning to 12 is scan_volume's job


# ---------------------------------------------------------------------------
# endpoint: 422s, each saved with an error
# ---------------------------------------------------------------------------

@pytest.mark.anyio
@pytest.mark.parametrize("polygon", [
    "not json",
    "{}",
    '{"x": 0.5, "y": 0.5}',
    "[]",
    json.dumps([{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.6}]),          # too short
    json.dumps([{"x": 0.4}, {"y": 0.4}, {"x": 0.6, "y": 0.6}]),          # missing keys
    json.dumps([{"x": "a", "y": 0.4}, {"x": 0.6, "y": 0.4}, {"x": 0.5, "y": 0.6}]),
    json.dumps([1, 2, 3]),
])
async def test_bad_polygon_422(scans_dir, fake_scan, mock_run_detection, polygon):
    r = await _post(polygon=polygon)
    _assert_422_saved(r, scans_dir)
    fake_scan.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("spacing", ["abc", "", "nan", "inf", 5, 9.9, 50.1, 60, -20, 0])
async def test_bad_spacing_422(scans_dir, fake_scan, mock_run_detection, spacing):
    r = await _post(spacing=spacing)
    if spacing == "" and r.status_code == 200:
        pytest.skip("empty spacing treated as absent (spec doesn't say)")
    _assert_422_saved(r, scans_dir)
    fake_scan.assert_not_called()


@pytest.mark.anyio
async def test_more_than_20_frames_422(scans_dir, fake_scan, mock_run_detection):
    r = await _post(frames=[_jpeg() for _ in range(21)])
    _assert_422_saved(r, scans_dir)
    fake_scan.assert_not_called()


@pytest.mark.anyio
async def test_unreadable_photo_422(scans_dir, fake_scan, mock_run_detection):
    r = await _post(photo=b"definitely not an image")
    _assert_422_saved(r, scans_dir)
    fake_scan.assert_not_called()


@pytest.mark.anyio
async def test_unreadable_frame_422(scans_dir, fake_scan, mock_run_detection):
    r = await _post(frames=[_jpeg(), b"garbage bytes", _jpeg()])
    _assert_422_saved(r, scans_dir)
    fake_scan.assert_not_called()


@pytest.mark.anyio
async def test_scan_error_422_with_its_message(scans_dir, fake_scan, mock_run_detection):
    fake_scan.side_effect = volume_scan.ScanError("No bolt grid at the volume.")
    r = await _post()
    body = _assert_422_saved(r, scans_dir)
    assert "No bolt grid at the volume." in body["detail"]


@pytest.mark.anyio
async def test_unexpected_exception_422_not_500(scans_dir, fake_scan, mock_run_detection):
    fake_scan.side_effect = ZeroDivisionError("boom")
    r = await _post()
    _assert_422_saved(r, scans_dir)


@pytest.mark.anyio
async def test_missing_required_fields_never_500(scans_dir, fake_scan, mock_run_detection):
    # Missing polygon / frames / photo: framework validation is fine, but never a 500.
    r = await _post(polygon=None)
    assert r.status_code == 422
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/dev/volume-scan", files=[("photo", ("p.jpg", _jpeg(), "image/jpeg"))],
                          data={"volume_polygon": json.dumps(POLYGON)})
        assert r.status_code == 422
        r = await ac.post("/dev/volume-scan", files=[("frames", ("f.jpg", _jpeg(), "image/jpeg"))],
                          data={"volume_polygon": json.dumps(POLYGON)})
        assert r.status_code == 422
    fake_scan.assert_not_called()


# ---------------------------------------------------------------------------
# scan_volume input rules (fast)
# ---------------------------------------------------------------------------

def _img():
    return Image.new("RGB", (640, 480), color=(120, 165, 205))


DETS = [{"id": 0, "class_name": "VOLUME", "confidence": 1.0, "polygon": POLYGON}]


def test_constants_and_error_type():
    assert volume_scan.MIN_FRAMES == 2
    assert volume_scan.MAX_FRAMES == 12
    assert issubclass(volume_scan.ScanError, ValueError)


@pytest.mark.parametrize("n", [0, 1])
def test_too_few_frames_raises(n):
    with pytest.raises(volume_scan.ScanError) as e:
        volume_scan.scan_volume(_img(), [_img() for _ in range(n)], POLYGON, DETS)
    assert str(e.value).strip()


@pytest.mark.parametrize("polygon", [
    [],
    [{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.6}],
    [{"x": 0.4, "y": 0.4}, {"x": 0.5, "y": 0.5}, {"x": 0.6, "y": 0.6}],  # collinear, zero area
    [{"x": 0.5, "y": 0.5}] * 4,                                          # one point repeated
])
def test_degenerate_polygon_raises(polygon):
    # Blank images have no bolt grid either, so any ScanError passes here; the
    # contract only promises a ScanError (not which check fires first).
    with pytest.raises(volume_scan.ScanError):
        volume_scan.scan_volume(_img(), [_img() for _ in range(3)], polygon, DETS)


# ---------------------------------------------------------------------------
# slow: acceptance criterion 1 on synthetic sweeps
# ---------------------------------------------------------------------------

SLOW_SCENES = ["s_wedge_over35", "s_box_over20", "s_pyr4_wall0"]
N_FRAMES, SPAN_CM = 6, 60.0


def _synth():
    if not (SYNTH_DIR / "synth.py").is_file():
        pytest.skip("experiments/two_photo/synth.py missing")
    if str(SYNTH_DIR) not in sys.path:
        sys.path.insert(0, str(SYNTH_DIR))
    try:
        import synth
    except ImportError as e:
        pytest.skip(f"synth.py not importable: {e}")
    return synth


@pytest.fixture(scope="module", params=SLOW_SCENES)
def synth_run(request):
    synth = _synth()
    sc = next(s for s in synth.scenes() if s.name == request.param)
    case = synth.sweep_case(sc, n_frames=N_FRAMES, span_cm=SPAN_CM)
    result = volume_scan.scan_volume(
        case["photo"], case["frames"], case["volume_polygon"], case["detections"],
        gravity_reading=case["gravity"], focal_35mm=sc.focal_35mm, bolt_spacing_cm=synth.BOLT_SPACING_CM)
    return sc.name, case, result


def _match(truth_faces, found_faces):
    """Pair each truth face with one found face.

    A found face can only stand for a truth face that faces the same way
    (the `facing` label is part of the output, so a face labelled "left" is
    not a measurement of the face that points "out"). Within a facing, pairs
    are taken greedily by smallest steepness difference, each found face used
    at most once. A truth face with no same-facing found face left is
    unmatched ("not found"). Extra found faces aren't penalised: AC 1 is about
    the truth faces being found and measured."""
    pairs = sorted(
        ((abs(f["steepness_deg"] - t["angle_deg"]), ti, fi)
         for ti, t in enumerate(truth_faces) for fi, f in enumerate(found_faces)
         if f["facing"] == t["facing"]),
        key=lambda p: p[0])
    used_t, used_f, matched = set(), set(), {}
    for err, ti, fi in pairs:
        if ti in used_t or fi in used_f:
            continue
        used_t.add(ti)
        used_f.add(fi)
        matched[ti] = (fi, err)
    return matched


def _summary(name, case, result, matched=None):
    truth = [(t["facing"], round(t["angle_deg"], 1)) for t in case["truth_faces"]]
    found = [(f["facing"], round(f["steepness_deg"], 1), f.get("n_points")) for f in result["faces"]]
    return (f"{name}: truth {truth}; found {found}; matched {matched}; "
            f"depth {result.get('depth_cm')} vs {case['depth_cm']}; wall {result.get('wall_angle_deg')} vs "
            f"{case.get('wall_deg')}; frames {result.get('frames_used')}/{result.get('frames_sent')}")


@pytest.mark.slow
def test_synthetic_faces_found_and_measured(synth_run):
    name, case, result = synth_run
    truth, found = case["truth_faces"], result["faces"]
    assert truth, f"{name}: synth gave no visible faces"
    matched = _match(truth, found)
    msg = _summary(name, case, result, matched)
    missing = [truth[i] for i in range(len(truth)) if i not in matched]
    assert not missing, f"faces not found: {missing}; {msg}"
    errors = [err for _, err in matched.values()]
    assert statistics.median(errors) <= 3.0, f"median {statistics.median(errors):.2f} deg; {msg}"
    assert max(errors) <= 6.0, f"max {max(errors):.2f} deg; {msg}"


@pytest.mark.slow
def test_synthetic_depth(synth_run):
    name, case, result = synth_run
    msg = _summary(name, case, result)
    assert "depth_cm" in result
    if result["depth_cm"] is None:
        pytest.skip(f"depth_cm null (photo bolt-grid fit uneven); {msg}")
    assert math.isfinite(result["depth_cm"])
    assert abs(result["depth_cm"] - case["depth_cm"]) <= 5.0, msg


@pytest.mark.slow
def test_synthetic_response_shape(synth_run):
    name, case, result = synth_run
    for key in RESPONSE_KEYS - {"scan_id"} | {"points", "photo_axis_ratio", "frame_diagnostics"}:
        assert key in result, f"{name}: missing {key}"
    assert result["frames_sent"] == N_FRAMES
    assert 2 <= result["frames_used"] <= N_FRAMES
    for f in result["faces"]:
        assert FACE_KEYS <= set(f)
        assert f["facing"] in FACINGS
