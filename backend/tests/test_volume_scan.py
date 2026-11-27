"""Volume scan (test feature): tests written from docs/milestones/v0.2/38-volume-scan-trial/spec.md.

Fast tests cover the POST /dev/volume-scan contract (scan_volume and YOLO
patched, scans saved under tmp_path) and scan_volume's input rules. Slow
tests cover acceptance criterion 1 on synthetic sweeps from
experiments/two_photo/synth.py (each rendered image takes ~15 s).

Slice 4 contracts (frame_diagnostics, ScanError.diagnostics, determinism, and
the endpoint saving diagnostics on a failed line-up) are tested fast on a
drawn front-on wall: a bolt lattice plus speckle texture, with burst frames
that are the photo shifted sideways (a camera step parallel to a front-on
wall moves the whole picture by the same amount, so each frame's true camera
move is known), or noise images that share nothing with the photo.

Slice 5 (chained line-up): every diagnostics entry has `source_frame`; a used
(lined-up) entry has photo_inliers, wall_ncc, wall_ncc_peak, linked_from and
turn_deg, and passes the pose check (volume_scan.MIN_* thresholds);
wall_inliers may exceed wall_matches; the result has `wall_features`. These
are checked on every diagnostics list the tests see (_assert_diagnostics).
Slow tests cover AC 6's synthetic part: step, arc (45 deg, phone turned to
keep the volume centred) and height (40 cm drop) sweeps from synth.py with
known camera moves, where every burst photo must line up within 2 cm and 1 deg.
"""
import functools
import inspect
import io
import json
import math
import random
import re
import statistics
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
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


POSE_CHECK_CONSTANTS = ["MIN_WALL_INLIERS", "MIN_PHOTO_INLIERS", "MIN_WALL_NCC", "MIN_NCC_PEAK",
                        "MIN_BASELINE_CM", "MAX_BASELINE_CM"]


def test_pose_check_constants():
    # Slice 5: the pose check's thresholds are module constants; the baseline cap is now 500 cm.
    for name in POSE_CHECK_CONSTANTS:
        assert hasattr(volume_scan, name), f"volume_scan.{name} missing"
        value = getattr(volume_scan, name)
        assert isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), \
            f"{name} = {value!r}"
    assert volume_scan.MAX_BASELINE_CM == 500
    assert volume_scan.MIN_BASELINE_CM < volume_scan.MAX_BASELINE_CM
    assert -1.0 <= volume_scan.MIN_WALL_NCC <= 1.0, volume_scan.MIN_WALL_NCC


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
# slice 4: frame_diagnostics, ScanError.diagnostics, determinism (fast)
# ---------------------------------------------------------------------------
#
# The photo is a drawn front-on wall: light grey with grain, 4000 small dark
# speckles (texture for matching), and a centred-square bolt lattice of side
# LAT_S px (the same lattice test_bolts.py draws). With bolt_spacing_cm =
# SPACING_CM, LAT_S px on the wall is SPACING_CM cm. A frame shifted by dx px
# is the view after the camera moved |dx| / LAT_S * SPACING_CM cm sideways.

LAT_W, LAT_H, LAT_S, LAT_D = 1600, 1200, 120, 12
SPACING_CM = 25.0
UPRIGHT_GRAVITY = [0.0, -9.8, 0.0]
DIAG_REQUIRED = {"frame", "source_frame", "wall_matches", "sharpness", "used"}
# Slice 5: fields of a lined-up (used) frame.
LINEUP_FIELDS = {"wall_inliers", "baseline_cm", "photo_inliers", "wall_ncc", "wall_ncc_peak", "linked_from",
                 "turn_deg"}
# Diagnostics may be rounded for scan.json, while the pose check runs on the
# unrounded numbers; allow half a unit of a 2-decimal NCC / 1-decimal cm value
# when checking that a used frame passed the thresholds.
NCC_ROUNDING, CM_ROUNDING = 0.005, 0.05


def _discs(canvas, centres, diameters, contrast):
    h, w = canvas.shape
    ss = 4
    mask = np.zeros((h * ss, w * ss), dtype=np.uint8)
    for (x, y), d in zip(centres, diameters):
        cv2.circle(mask, (int(round(x * ss)), int(round(y * ss))), max(1, int(round(d / 2 * ss))), 255,
                   thickness=-1, lineType=cv2.LINE_AA)
    mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return canvas * (1.0 - contrast * mask)


@functools.lru_cache(maxsize=None)
def _wall_array(lattice=True):
    """RGB uint8 array of the drawn wall (with or without the bolt lattice)."""
    rng = np.random.default_rng(0)
    canvas = 205.0 + rng.normal(0.0, 4.0, size=(LAT_H, LAT_W)).astype(np.float32)
    if lattice:
        cx, cy, margin = LAT_W / 2, LAT_H / 2, 0.25 * LAT_S
        n = int(max(LAT_W, LAT_H) / LAT_S) + 3
        pts = [(cx + (i + du) * LAT_S, cy + (j + du) * LAT_S)
               for i in range(-n, n + 1) for j in range(-n, n + 1) for du in (0.0, 0.5)]
        pts = [(x, y) for x, y in pts if margin <= x <= LAT_W - margin and margin <= y <= LAT_H - margin]
        canvas = _discs(canvas, pts, [LAT_D] * len(pts), 0.75)
    n_speckle = 4000
    sx, sy = rng.uniform(0, LAT_W, n_speckle), rng.uniform(0, LAT_H, n_speckle)
    sd = rng.uniform(2.0, 5.0, n_speckle)
    canvas = _discs(canvas, list(zip(sx, sy)), list(sd), 0.7)
    grey = np.clip(canvas, 0, 255).astype(np.uint8)
    arr = np.stack([grey, grey, grey], axis=-1)
    arr.setflags(write=False)
    return arr


def _wall_photo(lattice=True):
    return Image.fromarray(_wall_array(lattice).copy())


def _shifted(dx, lattice=True):
    """The photo moved dx px sideways (dx < 0: the camera stepped right)."""
    m = np.float32([[1, 0, dx], [0, 1, 0]])
    arr = cv2.warpAffine(_wall_array(lattice), m, (LAT_W, LAT_H), borderMode=cv2.BORDER_REFLECT)
    return Image.fromarray(arr)


def _true_move_cm(dx):
    return abs(dx) / LAT_S * SPACING_CM


def _noise_frame(seed):
    rng = np.random.default_rng(1000 + seed)
    return Image.fromarray(rng.integers(0, 256, (LAT_H, LAT_W, 3), dtype=np.uint8))


def _grainy(img, sigma, seed):
    rng = np.random.default_rng(2000 + seed)
    a = np.asarray(img).astype(np.float32) + rng.normal(0.0, sigma, (LAT_H, LAT_W, 1)).astype(np.float32)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _blurred(img, sigma):
    return Image.fromarray(cv2.GaussianBlur(np.asarray(img), (0, 0), sigma))


def _scan(frames, photo=None, polygon=POLYGON):
    return volume_scan.scan_volume(
        _wall_photo() if photo is None else photo, frames, polygon, DETS,
        gravity_reading=UPRIGHT_GRAVITY, bolt_spacing_cm=SPACING_CM)


def _scan_error(frames, photo=None, polygon=POLYGON):
    with pytest.raises(volume_scan.ScanError) as e:
        _scan(frames, photo=photo, polygon=polygon)
    assert str(e.value).strip(), "ScanError without a message"
    return e.value


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _assert_lineup_fields(entry):
    """Slice 5: the numbers of a lined-up frame, and the pose check it passed."""
    assert LINEUP_FIELDS <= set(entry), f"used frame missing {LINEUP_FIELDS - set(entry)}: {entry}"
    wi, pi = entry["wall_inliers"], entry["photo_inliers"]
    assert _is_int(wi) and wi > 0, entry
    assert _is_int(pi) and pi >= 0, entry
    # wall_inliers also counts guided and neighbour matches, so it includes the
    # photo's own inliers (and may exceed wall_matches, which it is not checked against).
    assert pi <= wi, f"photo_inliers {pi} > wall_inliers {wi}: {entry}"
    assert _is_num(entry["wall_ncc"]) and -1.0 - 1e-9 <= entry["wall_ncc"] <= 1.0 + 1e-9, entry
    assert _is_num(entry["wall_ncc_peak"]), entry
    assert _is_num(entry["turn_deg"]) and entry["turn_deg"] >= 0.0, entry
    assert _is_num(entry["baseline_cm"]), entry
    lf = entry["linked_from"]
    assert lf is None or _is_int(lf), f"linked_from is {lf!r}: {entry}"
    # The pose check (spec, "Changed in slice 5"): used implies every threshold holds.
    vs = volume_scan
    assert wi >= vs.MIN_WALL_INLIERS, f"used with wall_inliers {wi} < {vs.MIN_WALL_INLIERS}: {entry}"
    assert pi >= vs.MIN_PHOTO_INLIERS, f"used with photo_inliers {pi} < {vs.MIN_PHOTO_INLIERS}: {entry}"
    assert entry["wall_ncc"] >= vs.MIN_WALL_NCC - NCC_ROUNDING, \
        f"used with wall_ncc {entry['wall_ncc']} < {vs.MIN_WALL_NCC}: {entry}"
    assert entry["wall_ncc_peak"] >= vs.MIN_NCC_PEAK - NCC_ROUNDING, \
        f"used with wall_ncc_peak {entry['wall_ncc_peak']} < {vs.MIN_NCC_PEAK}: {entry}"
    b = entry["baseline_cm"]
    assert vs.MIN_BASELINE_CM - CM_ROUNDING <= b <= vs.MAX_BASELINE_CM + CM_ROUNDING, \
        f"used with baseline {b} cm outside {vs.MIN_BASELINE_CM}..{vs.MAX_BASELINE_CM}: {entry}"


def _assert_diag_entry(entry):
    assert isinstance(entry, dict), entry
    assert DIAG_REQUIRED <= set(entry), f"missing {DIAG_REQUIRED - set(entry)} in {entry}"
    assert _is_int(entry["frame"]), entry
    assert _is_int(entry["source_frame"]) and entry["source_frame"] >= 0, entry
    assert _is_int(entry["wall_matches"]), entry
    assert entry["wall_matches"] >= 0, entry
    assert isinstance(entry["sharpness"], float) and math.isfinite(entry["sharpness"]), entry
    assert isinstance(entry["used"], bool), entry
    if not entry["used"]:
        assert isinstance(entry.get("reason"), str) and entry["reason"].strip(), f"unused frame, no reason: {entry}"
    if entry["used"]:
        # A used frame was posed from a wall homography and passed the pose check.
        _assert_lineup_fields(entry)
    elif entry.get("linked_from") is not None:
        assert _is_int(entry["linked_from"]), entry


def _assert_links(diags, thinned):
    """linked_from names another frame of the scan, and chains end at a frame
    lined up straight with the photo (no loops). Which numbering linked_from
    uses (`frame` or `source_frame`) is only visible when frames were thinned,
    so then either is accepted and the loop check is skipped."""
    by_frame = {e["frame"]: e for e in diags}
    by_source = {e["source_frame"]: e for e in diags}
    for e in diags:
        lf = e.get("linked_from")
        if lf is None:
            continue
        targets = [t for t in (by_frame.get(lf), by_source.get(lf) if thinned else None)
                   if t is not None and t is not e]
        assert targets, f"frame {e['frame']}: linked_from {lf} names no other frame of the scan: {diags}"
    if thinned:
        return
    for e in diags:
        seen, cur = {e["frame"]}, e
        while cur.get("linked_from") is not None:
            cur = by_frame[cur["linked_from"]]
            assert cur["frame"] not in seen, f"linked_from loop through frame {cur['frame']}: {diags}"
            seen.add(cur["frame"])


def _assert_source_frames(diags, n_sent):
    """source_frame is the index in the burst as sent: equal to `frame` when
    nothing was thinned, else increasing with `frame` and spread evenly."""
    ordered = sorted(diags, key=lambda e: e["frame"])
    src = [e["source_frame"] for e in ordered]
    assert all(0 <= s < n_sent for s in src), f"source_frame outside 0..{n_sent - 1}: {src}"
    if n_sent == len(diags):
        assert src == [e["frame"] for e in ordered], f"nothing thinned, yet source_frame != frame: {src}"
        return
    assert all(a < b for a, b in zip(src, src[1:])), f"source_frame not increasing with frame: {src}"
    gaps = [b - a for a, b in zip(src, src[1:])]
    assert max(gaps) - min(gaps) <= 1, f"{n_sent} frames not thinned evenly: kept {src}"


def _assert_diagnostics(diags, n_frames, n_sent=None):
    n_sent = n_frames if n_sent is None else n_sent
    assert isinstance(diags, list), f"frame_diagnostics is {type(diags).__name__}: {diags!r}"
    assert len(diags) == n_frames, f"{len(diags)} entries for {n_frames} frames: {diags}"
    for entry in diags:
        _assert_diag_entry(entry)
    assert sorted(e["frame"] for e in diags) == list(range(n_frames)), diags
    _assert_source_frames(diags, n_sent)
    _assert_links(diags, thinned=n_sent != n_frames)
    json.dumps(diags)  # saved to scan.json, so it must be plain JSON


def _assert_wall_features(result):
    assert "wall_features" in result, f"result keys: {sorted(result)}"
    assert _is_int(result["wall_features"]) and result["wall_features"] >= 0, result["wall_features"]


def _by_frame(diags):
    return {e["frame"]: e for e in diags}


def _without_seconds(result):
    return {k: v for k, v in result.items() if k != "seconds"}


def _shuffle_global_rngs(seed):
    """Moves every global random state a scan could lean on, so a result that
    depends on run-to-run randomness shows up as a difference."""
    random.seed(seed)
    np.random.seed(seed)
    cv2.setRNGSeed(seed)


def test_scan_error_has_diagnostics_attribute_default_none():
    err = volume_scan.ScanError("No bolt grid at the volume.")
    assert hasattr(err, "diagnostics")
    assert err.diagnostics is None


@pytest.mark.parametrize("n", [0, 1])
def test_too_few_frames_error_has_no_diagnostics(n):
    # Raised before any frame is lined up, so diagnostics is None.
    err = _scan_error([_shifted(-40 * (i + 1)) for i in range(n)])
    assert err.diagnostics is None


def test_bad_polygon_error_has_no_diagnostics():
    # Frames that would line up; only the polygon (two points) is bad.
    polygon = [{"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.6}]
    err = _scan_error([_shifted(-40), _shifted(-80), _shifted(-120)], polygon=polygon)
    assert err.diagnostics is None


@pytest.mark.parametrize("polygon", [
    [{"x": 0.4, "y": 0.4}, {"x": 0.5, "y": 0.5}, {"x": 0.6, "y": 0.6}],  # collinear, zero area
    [{"x": 0.5, "y": 0.5}] * 4,                                          # one point repeated
], ids=["collinear", "one-point"])
def test_zero_area_polygon_raises_on_a_wall_with_bolt_grid(polygon):
    # test_degenerate_polygon_raises uses blank images, which also have no bolt
    # grid; here the grid and the frames are good, so only the polygon is wrong.
    err = _scan_error([_shifted(-40), _shifted(-80), _shifted(-120)], polygon=polygon)
    assert err.diagnostics is None


def test_no_bolt_grid_error_has_no_diagnostics():
    # Textured wall with no bolt lattice; the frames are its own shifted copies,
    # so they would match. The scan fails on the missing grid, not on line-up.
    photo = _wall_photo(lattice=False)
    frames = [_shifted(-40, lattice=False), _shifted(-80, lattice=False), _shifted(-120, lattice=False)]
    err = _scan_error(frames, photo=photo)
    assert err.diagnostics is None, f"{err}: {err.diagnostics}"


@pytest.mark.parametrize("make_frame", [_noise_frame, lambda i: Image.new("RGB", (LAT_W, LAT_H), (128, 128, 128))],
                         ids=["noise", "blank"])
def test_lineup_failure_carries_per_frame_diagnostics(make_frame):
    frames = [make_frame(i) for i in range(3)]
    err = _scan_error(frames)
    _assert_diagnostics(err.diagnostics, 3)
    assert not any(e["used"] for e in err.diagnostics), err.diagnostics


def test_lineup_failure_diagnostics_cover_thinned_frames():
    # More than MAX_FRAMES are thinned evenly; `frame` indexes the frames as
    # scanned, `source_frame` (slice 5) the burst as sent.
    n_sent = volume_scan.MAX_FRAMES + 3
    frames = [_noise_frame(i) for i in range(n_sent)]
    err = _scan_error(frames)
    _assert_diagnostics(err.diagnostics, volume_scan.MAX_FRAMES, n_sent=n_sent)


@functools.lru_cache(maxsize=None)
def _shift_scan(shifts):
    """One scan of the photo's shifted copies, shared by tests that only read it."""
    return _scan([_shifted(dx) for dx in shifts])


def _shift_scan_copy(shifts):
    return json.loads(json.dumps(_shift_scan(tuple(shifts))))


def test_success_diagnostics_one_per_frame_with_homography_fields():
    # Slice 5: wall_inliers is the refined homography's support (guided and
    # neighbour matches too), so it may be larger than wall_matches; it is
    # positive and at least MIN_WALL_INLIERS on a used frame. The new fields
    # and the pose check are checked by _assert_diagnostics.
    shifts = [-40, -80, -120, -160]
    result = _shift_scan_copy(shifts)
    diags = result["frame_diagnostics"]
    _assert_diagnostics(diags, len(shifts))
    assert all(e["used"] for e in diags), diags
    for e in diags:
        assert _is_int(e["wall_inliers"]) and e["wall_inliers"] > 0, e
        assert e["wall_inliers"] >= volume_scan.MIN_WALL_INLIERS, e
        assert _is_num(e["baseline_cm"]), e


def test_success_result_has_wall_features():
    # Slice 5: how many of the photo's features are on the plain wall around
    # the volume. The drawn wall is speckled everywhere, so there are some.
    result = _shift_scan_copy([-40, -80, -120, -160])
    _assert_wall_features(result)
    assert result["wall_features"] > 0, result["wall_features"]


def test_baseline_cm_is_the_camera_move():
    # Within AC 6's pose tolerance (2 cm) of the known sideways move.
    shifts = [-40, -80, -120]
    result = _shift_scan_copy(shifts)
    got = _by_frame(result["frame_diagnostics"])
    for i, dx in enumerate(shifts):
        assert got[i]["used"], got[i]
        assert abs(got[i]["baseline_cm"] - _true_move_cm(dx)) <= 2.0, \
            f"frame {i}: baseline {got[i]['baseline_cm']} cm, camera moved {_true_move_cm(dx):.2f} cm"


def test_turn_deg_is_zero_for_a_sideways_step():
    # A whole-picture shift of a front-on wall is a camera step with no turn,
    # so turn_deg is 0 within AC 6's 1 deg.
    shifts = [-40, -80, -120]
    result = _shift_scan_copy(shifts)
    got = _by_frame(result["frame_diagnostics"])
    for i in range(len(shifts)):
        assert got[i]["used"], got[i]
        assert got[i]["turn_deg"] <= 1.0, f"frame {i}: turn {got[i]['turn_deg']} deg for a pure sideways step"


def test_frame_identical_to_photo_is_not_used():
    # No camera move means a baseline of ~0 cm, below the pose check's MIN_BASELINE_CM.
    if volume_scan.MIN_BASELINE_CM <= 0:
        pytest.skip(f"MIN_BASELINE_CM is {volume_scan.MIN_BASELINE_CM}: a zero baseline passes the pose check")
    result = _scan([_wall_photo(), _shifted(-60), _shifted(-120)])
    diags = result["frame_diagnostics"]
    _assert_diagnostics(diags, 3)
    got = _by_frame(diags)
    assert got[0]["used"] is False, got[0]
    assert got[1]["used"] and got[2]["used"], diags
    assert result["frames_used"] == 2, (result["frames_used"], diags)


def test_thinned_success_source_frame_maps_back():
    # 15 frames, each a different camera step (3.3 cm apart, more than AC 6's
    # 2 cm), thinned to MAX_FRAMES. Each entry's baseline must be the move of
    # the burst photo its source_frame names.
    n_sent = volume_scan.MAX_FRAMES + 3
    shifts = [-(30 + 16 * i) for i in range(n_sent)]
    result = _scan([_shifted(dx) for dx in shifts])
    diags = result["frame_diagnostics"]
    _assert_diagnostics(diags, volume_scan.MAX_FRAMES, n_sent=n_sent)
    assert all(e["used"] for e in diags), diags
    for e in diags:
        truth = _true_move_cm(shifts[e["source_frame"]])
        assert abs(e["baseline_cm"] - truth) <= 2.0, \
            f"frame {e['frame']} (source {e['source_frame']}): baseline {e['baseline_cm']} cm, " \
            f"that burst photo moved {truth:.2f} cm"


def test_mixed_frames_unused_one_has_reason_and_frames_used_matches():
    frames = [_shifted(-60), _noise_frame(0), _shifted(-120)]
    result = _scan(frames)
    diags = result["frame_diagnostics"]
    _assert_diagnostics(diags, 3)
    got = _by_frame(diags)
    assert got[0]["used"] and got[2]["used"], diags
    assert got[1]["used"] is False and got[1]["reason"].strip(), diags
    assert result["frames_used"] == sum(e["used"] for e in diags), (result["frames_used"], diags)
    assert result["frames_sent"] == 3
    _assert_wall_features(result)


def test_sharpness_higher_is_sharper():
    frames = [_shifted(-40), _blurred(_shifted(-80), 3.0), _shifted(-120)]
    result = _scan(frames)
    got = _by_frame(result["frame_diagnostics"])
    assert got[1]["sharpness"] < min(got[0]["sharpness"], got[2]["sharpness"]), \
        [got[i]["sharpness"] for i in range(3)]


def test_same_inputs_same_result_every_call():
    # A frame with grain (so matching has outliers) and a frame that won't line up.
    frames = [_shifted(-40), _noise_frame(1), _grainy(_shifted(-90), 12.0, 0), _shifted(-130)]
    photo = _wall_photo()
    runs = []
    for seed in (1, 2, 3):
        _shuffle_global_rngs(seed)
        runs.append(_without_seconds(volume_scan.scan_volume(
            photo, frames, POLYGON, DETS, gravity_reading=UPRIGHT_GRAVITY, bolt_spacing_cm=SPACING_CM)))
    assert runs[0] == runs[1] == runs[2], [r["frame_diagnostics"] for r in runs]


def test_same_failing_inputs_same_error_every_call():
    frames = [_noise_frame(i) for i in range(3)]
    errors = []
    for seed in (1, 2):
        _shuffle_global_rngs(seed)
        errors.append(_scan_error(frames))
    assert str(errors[0]) == str(errors[1])
    assert errors[0].diagnostics == errors[1].diagnostics


# ---------------------------------------------------------------------------
# slice 4: endpoint saves diagnostics of a failed line-up
# ---------------------------------------------------------------------------

FAKE_DIAGS = [
    {"frame": 0, "source_frame": 0, "wall_matches": 3, "sharpness": 812.5, "used": False,
     "reason": "too few wall matches"},
    {"frame": 1, "source_frame": 1, "wall_matches": 140, "sharpness": 905.0, "wall_inliers": 190,
     "baseline_cm": 2.1, "photo_inliers": 60, "wall_ncc": 0.12, "wall_ncc_peak": 0.01, "linked_from": 0,
     "turn_deg": 3.4, "used": False, "reason": "pose check: wall_ncc 0.12"},
    {"frame": 2, "source_frame": 2, "wall_matches": 1, "sharpness": 15.25, "used": False, "reason": "bad pose"},
]


def _jpeg_of(img, quality=95):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


@pytest.mark.anyio
async def test_scan_error_diagnostics_saved_in_scan_json(scans_dir, fake_scan, mock_run_detection):
    err = volume_scan.ScanError("Couldn't line up enough burst photos with the wall.")
    err.diagnostics = [dict(d) for d in FAKE_DIAGS]
    fake_scan.side_effect = err
    r = await _post()
    body = _assert_422_saved(r, scans_dir)
    assert set(body) == {"detail", "scan_id"}, body  # response unchanged
    assert "Couldn't line up enough burst photos" in body["detail"]
    saved = _scan_json(scans_dir, body["scan_id"])
    assert saved.get("frame_diagnostics") == FAKE_DIAGS, saved


@pytest.mark.anyio
async def test_real_lineup_failure_diagnostics_saved(scans_dir, mock_run_detection):
    # No mock of scan_volume: a bolt-grid photo with noise frames fails while lining up.
    frames = [_jpeg_of(_noise_frame(i)) for i in range(3)]
    r = await _post(photo=_jpeg_of(_wall_photo()), frames=frames, gravity=UPRIGHT_GRAVITY, spacing=SPACING_CM)
    body = _assert_422_saved(r, scans_dir)
    assert set(body) == {"detail", "scan_id"}, body
    saved = _scan_json(scans_dir, body["scan_id"])
    assert "frame_diagnostics" in saved, f"scan.json keys: {sorted(saved)}"
    _assert_diagnostics(saved["frame_diagnostics"], 3)
    assert not any(e["used"] for e in saved["frame_diagnostics"])


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
    _assert_wall_features(result)
    for f in result["faces"]:
        assert FACE_KEYS <= set(f)
        assert f["facing"] in FACINGS


@pytest.mark.slow
def test_synthetic_frame_diagnostics(synth_run):
    name, case, result = synth_run
    diags = result["frame_diagnostics"]
    _assert_diagnostics(diags, N_FRAMES)
    assert result["frames_used"] == sum(e["used"] for e in diags), (name, result["frames_used"], diags)


@pytest.mark.slow
def test_synthetic_same_result_twice(synth_run):
    # Re-scan the same rendered case (faces come from RANSAC planes, so this is
    # where run-to-run randomness would show).
    name, case, first = synth_run
    synth = _synth()
    sc = next(s for s in synth.scenes() if s.name == name)
    _shuffle_global_rngs(12345)
    again = volume_scan.scan_volume(
        case["photo"], case["frames"], case["volume_polygon"], case["detections"],
        gravity_reading=case["gravity"], focal_35mm=sc.focal_35mm, bolt_spacing_cm=synth.BOLT_SPACING_CM)
    a, b = _without_seconds(first), _without_seconds(again)
    assert a.keys() == b.keys()
    for key in a:
        assert a[key] == b[key], f"{name}: {key} differs between two scans of the same inputs"


# ---------------------------------------------------------------------------
# slow: acceptance criterion 6, synthetic part (slice 5)
# ---------------------------------------------------------------------------
#
# The movements trial 1 recorded, rendered by synth.sweep_case with known
# camera poses: a straight step, an arc round the volume ending 45 deg to the
# right with the phone turned to keep the volume centred, and a step while
# lowering the phone 40 cm. The step is 40 cm, the top of trial 1's 10-40 cm.
# Every burst photo must line up (used, so it passed the pose check) with
# baseline_cm within 2 cm of frame_baseline_cm and turn_deg within 1 deg of
# frame_turn_deg.

AC6_SCENE = "s_pyr4_wall0"
AC6_N_FRAMES, AC6_SPAN_CM = 6, 40.0
AC6_PATHS = {"step": {}, "arc": {"arc_deg": 45}, "height": {"drop_cm": 40}}
AC6_BASELINE_TOL_CM, AC6_TURN_TOL_DEG = 2.0, 1.0


@pytest.fixture(scope="module", params=list(AC6_PATHS))
def sweep_run(request):
    synth = _synth()
    path = request.param
    sc = next(s for s in synth.scenes() if s.name == AC6_SCENE)
    case = synth.sweep_case(sc, AC6_N_FRAMES, AC6_SPAN_CM, path=path, **AC6_PATHS[path])
    try:
        result, error = volume_scan.scan_volume(
            case["photo"], case["frames"], case["volume_polygon"], case["detections"],
            gravity_reading=case["gravity"], focal_35mm=sc.focal_35mm,
            bolt_spacing_cm=synth.BOLT_SPACING_CM), None
    except volume_scan.ScanError as e:  # reported by the tests, with its diagnostics
        result, error = None, e
    return path, case, result, error


def _truth_moves(case):
    base, turn = case["frame_baseline_cm"], case["frame_turn_deg"]
    assert len(base) == len(turn) == len(case["frames"]) == AC6_N_FRAMES, (len(base), len(turn))
    return [float(b) for b in base], [float(t) for t in turn]


def _sweep_diags(path, result, error):
    if error is not None:
        pytest.fail(f"{path}: ScanError {error!s}; diagnostics {error.diagnostics}")
    diags = result["frame_diagnostics"]
    _assert_diagnostics(diags, AC6_N_FRAMES)
    return diags


def _sweep_table(path, case, diags):
    base, turn = _truth_moves(case)
    rows = []
    for e in sorted(diags, key=lambda e: e["source_frame"]):
        s = e["source_frame"]
        rows.append(f"#{s} used={e['used']} reason={e.get('reason')!r} "
                    f"baseline {e.get('baseline_cm')} vs {base[s]:.2f} cm, turn {e.get('turn_deg')} vs "
                    f"{turn[s]:.2f} deg, linked_from={e.get('linked_from')}, matches={e.get('wall_matches')}, "
                    f"inliers={e.get('wall_inliers')}, photo_inliers={e.get('photo_inliers')}, "
                    f"ncc={e.get('wall_ncc')}, peak={e.get('wall_ncc_peak')}")
    return f"{path}:\n  " + "\n  ".join(rows)


@pytest.mark.slow
def test_sweep_every_burst_photo_lines_up(sweep_run):
    path, case, result, error = sweep_run
    diags = _sweep_diags(path, result, error)
    table = _sweep_table(path, case, diags)
    unused = [e["source_frame"] for e in diags if not e["used"]]
    assert not unused, f"burst photos {unused} not lined up; {table}"
    assert result["frames_used"] == AC6_N_FRAMES, f"frames_used {result['frames_used']}; {table}"
    _assert_wall_features(result)


@pytest.mark.slow
def test_sweep_baseline_within_2cm_of_true_move(sweep_run):
    path, case, result, error = sweep_run
    diags = _sweep_diags(path, result, error)
    base, _ = _truth_moves(case)
    table = _sweep_table(path, case, diags)
    for e in diags:
        assert "baseline_cm" in e and _is_num(e["baseline_cm"]), f"#{e['source_frame']} has no pose; {table}"
        err = abs(e["baseline_cm"] - base[e["source_frame"]])
        assert err <= AC6_BASELINE_TOL_CM, f"#{e['source_frame']}: baseline off by {err:.2f} cm; {table}"


@pytest.mark.slow
def test_sweep_turn_within_1deg_of_true_turn(sweep_run):
    path, case, result, error = sweep_run
    diags = _sweep_diags(path, result, error)
    _, turn = _truth_moves(case)
    table = _sweep_table(path, case, diags)
    for e in diags:
        assert "turn_deg" in e and _is_num(e["turn_deg"]), f"#{e['source_frame']} has no turn_deg; {table}"
        err = abs(e["turn_deg"] - turn[e["source_frame"]])
        assert err <= AC6_TURN_TOL_DEG, f"#{e['source_frame']}: turn off by {err:.2f} deg; {table}"
