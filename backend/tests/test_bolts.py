"""Tests for bolts.detect_bolt_holes (feature wall_size_hold_distance, slice 3).

Designed from the spec's "Slice 3 bolt detection" decision block and the
public contract only:

    detect_bolt_holes(image: PIL.Image, detections: list[dict]) -> [{x, y, diameter}]

x, y are normalized to the image's width/height; diameter is in pixels of the
image passed in. Holes inside any detection polygon are ignored; only dark
(relative contrast >= 0.3) round holes that sit on an evenly spaced grid are
kept; nearest-neighbour spacing is assumed >= 5x the hole diameter.

The synthetic walls below draw the reference lattice: a square grid of side
`s` with an extra bolt in each square's centre, so nearest neighbours are the
diagonals at s / sqrt(2). Ground truth is known exactly, so recall and false
positives are measured, not eyeballed.

The reference-photo tests at the bottom are marked slow and need models/best.pt
plus the photos in mobile/ML-Rock-Climbing-App/assets/known_measurements/reference.
"""

import json
import math
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageOps

import bolts
from bolts import detect_bolt_holes

# --- synthetic wall helpers ---------------------------------------------------

BG = 205.0  # light plywood / painted wall grey level
HOLE_CONTRAST = 0.75  # (bg - hole) / bg, well above MIN_CONTRAST


def _lattice_points(width, height, s, margin, angle_deg=0.0, squash_y=1.0):
    """Centred-square lattice points (px) that fall inside the image minus margin.

    The lattice is built around the image centre, optionally rotated and
    squashed vertically (a cheap stand-in for an angled panel's foreshortening).
    """
    cx, cy = width / 2, height / 2
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    n = int(max(width, height) / s) + 3
    pts = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            for du, dv in ((0.0, 0.0), (0.5, 0.5)):
                u, v = (i + du) * s, (j + dv) * s
                x = cx + u * ca - v * sa
                y = cy + (u * sa + v * ca) * squash_y
                if margin <= x <= width - margin and margin <= y <= height - margin:
                    pts.append((x, y))
    return pts


def _background(width, height, rng, noise=4.0, gradient=0.0):
    """Light wall with a gentle left-to-right illumination falloff and grain."""
    ramp = np.linspace(1.0, 1.0 - gradient, width, dtype=np.float32)[None, :]
    bg = BG * np.repeat(ramp, height, axis=0)
    if noise:
        bg = bg + rng.normal(0.0, noise, size=(height, width)).astype(np.float32)
    return bg


def _draw_discs(canvas, centres, diameters, contrast):
    """Darken discs multiplicatively so relative contrast is exactly `contrast`
    against the local background, whatever the illumination ramp does."""
    h, w = canvas.shape
    ss = 4  # supersample the mask for clean, anti-aliased edges
    mask = np.zeros((h * ss, w * ss), dtype=np.uint8)
    if np.isscalar(diameters):
        diameters = [diameters] * len(centres)
    for (x, y), d in zip(centres, diameters):
        cv2.circle(
            mask,
            (int(round(x * ss)), int(round(y * ss))),
            max(1, int(round(d / 2 * ss))),
            255,
            thickness=-1,
            lineType=cv2.LINE_AA,
        )
    mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    return canvas * (1.0 - contrast * mask)


def _to_image(canvas):
    grey = np.clip(canvas, 0, 255).astype(np.uint8)
    rgb = np.stack([grey, grey, grey], axis=-1)
    return Image.fromarray(rgb, mode="RGB")


def _wall(width, height, s, d, *, seed=0, contrast=HOLE_CONTRAST, angle_deg=0.0, squash_y=1.0,
          speckle=0, speckle_d=(2.0, 4.0), dots=(), dots_d=None, gradient=0.0):
    """Synthetic wall. Returns (PIL image, lattice points px, extra dot points px)."""
    rng = np.random.default_rng(seed)
    canvas = _background(width, height, rng, gradient=gradient)
    pts = [] if s is None else _lattice_points(width, height, s, margin=max(d, 0.25 * s), angle_deg=angle_deg, squash_y=squash_y)
    if pts:
        canvas = _draw_discs(canvas, pts, d, contrast)
    if speckle:
        sx = rng.uniform(0, width, speckle)
        sy = rng.uniform(0, height, speckle)
        sd = rng.uniform(*speckle_d, speckle)
        canvas = _draw_discs(canvas, list(zip(sx, sy)), list(sd), 0.7)
    if dots:
        canvas = _draw_discs(canvas, list(dots), dots_d or d, contrast)
    return _to_image(canvas), pts, list(dots)


def _random_points(width, height, n, rng, margin, avoid=(), min_gap=0.0):
    out = []
    avoid = np.array(avoid, dtype=float).reshape(-1, 2)
    while len(out) < n:
        p = rng.uniform([margin, margin], [width - margin, height - margin])
        if len(avoid) and np.min(np.hypot(*(avoid - p).T)) < min_gap:
            continue
        if out and np.min(np.hypot(*(np.array(out) - p).T)) < min_gap:
            continue
        out.append(tuple(p))
    return out


def _to_px(found, size):
    w, h = size
    return np.array([(b["x"] * w, b["y"] * h) for b in found], dtype=float).reshape(-1, 2)


def _match(found_px, truth_px, tol):
    """Greedy one-to-one match within `tol` px. Returns (matched truth idx set,
    matched found idx set)."""
    truth = np.asarray(truth_px, dtype=float).reshape(-1, 2)
    found = np.asarray(found_px, dtype=float).reshape(-1, 2)
    if not len(truth) or not len(found):
        return set(), set()
    dist = np.hypot(found[:, None, 0] - truth[None, :, 0], found[:, None, 1] - truth[None, :, 1])
    pairs = sorted(zip(*np.nonzero(dist <= tol)), key=lambda ij: dist[ij])
    used_f, used_t = set(), set()
    for f, t in pairs:
        if f not in used_f and t not in used_t:
            used_f.add(int(f))
            used_t.add(int(t))
    return used_t, used_f


def _square_polygon(cx, cy, half, size):
    w, h = size
    return [
        {"x": (cx - half) / w, "y": (cy - half) / h},
        {"x": (cx + half) / w, "y": (cy - half) / h},
        {"x": (cx + half) / w, "y": (cy + half) / h},
        {"x": (cx - half) / w, "y": (cy + half) / h},
    ]


def _detection(id_, polygon, class_name="HOLD"):
    xs = [p["x"] for p in polygon]
    ys = [p["y"] for p in polygon]
    return {
        "id": id_,
        "class_name": class_name,
        "centroid": {"x": sum(xs) / len(xs), "y": sum(ys) / len(ys)},
        "polygon": polygon,
        "confidence": 0.9,
        "size": 0.01,
    }


# Recall / false-positive targets for clean synthetic lattices. Real walls lose
# bolts at panel edges and behind holds; a clean drawn grid should not.
MIN_RECALL = 0.9
MAX_FP_FRACTION = 0.05


def _assert_lattice_found(found, truth, size, d, *, min_recall=MIN_RECALL, max_fp=MAX_FP_FRACTION):
    tol = max(2.0, 0.5 * d)
    matched_t, matched_f = _match(_to_px(found, size), truth, tol)
    recall = len(matched_t) / len(truth)
    fp = len(found) - len(matched_f)
    assert recall >= min_recall, f"recall {recall:.2f} ({len(matched_t)}/{len(truth)}) < {min_recall}"
    assert fp <= max_fp * len(truth), f"{fp} false positives for {len(truth)} lattice points"
    return matched_t, matched_f


def _assert_recall(found, truth, size, d, min_recall=MIN_RECALL):
    """Recall only, for when `truth` is a subset of the drawn lattice."""
    matched_t, _ = _match(_to_px(found, size), truth, max(2.0, 0.5 * d))
    recall = len(matched_t) / len(truth)
    assert recall >= min_recall, f"recall {recall:.2f} ({len(matched_t)}/{len(truth)}) < {min_recall}"


# --- public tunables ------------------------------------------------------------


def test_public_tunables_match_spec():
    assert bolts.MIN_CONTRAST == pytest.approx(0.3)
    assert bolts.MIN_SPACING_TO_DIAMETER == pytest.approx(5.0)
    assert bolts.MAX_SIDE == 4096


# --- output contract -------------------------------------------------------------


def test_output_shape_and_types():
    image, truth, _ = _wall(1200, 900, s=120, d=12)

    found = detect_bolt_holes(image, [])

    assert isinstance(found, list) and found
    for b in found:
        assert set(b) == {"x", "y", "diameter"}
        for k in ("x", "y", "diameter"):
            assert isinstance(b[k], float), (k, type(b[k]))
            assert math.isfinite(b[k])
        assert 0.0 <= b["x"] <= 1.0
        assert 0.0 <= b["y"] <= 1.0
        assert b["diameter"] > 0
    assert json.loads(json.dumps(found)) == found


def test_does_not_mutate_inputs():
    image, _, _ = _wall(800, 600, s=100, d=10)
    before = np.asarray(image).copy()
    dets = [_detection(0, _square_polygon(50, 50, 20, image.size))]
    dets_before = json.loads(json.dumps(dets))

    detect_bolt_holes(image, dets)

    assert np.array_equal(np.asarray(image), before)
    assert image.size == (800, 600)
    assert dets == dets_before


@pytest.mark.parametrize("size", [(1, 1), (64, 48), (1000, 800), (3024, 4032)])
@pytest.mark.parametrize("colour", [(120, 80, 40), (230, 225, 215), (0, 0, 0)])
def test_plain_image_has_no_bolts(size, colour):
    assert detect_bolt_holes(Image.new("RGB", size, colour), []) == []


def test_plain_image_with_detections_has_no_bolts():
    size = (640, 480)
    dets = [_detection(i, _square_polygon(100 + 100 * i, 200, 40, size)) for i in range(4)]

    assert detect_bolt_holes(Image.new("RGB", size, (200, 200, 200)), dets) == []


def test_grain_only_wall_has_no_bolts():
    rng = np.random.default_rng(7)
    canvas = _background(1600, 1200, rng, noise=8.0)

    assert detect_bolt_holes(_to_image(canvas), []) == []


# --- lattice recall / precision ---------------------------------------------------


# Diameters span the stated working range (~6 px to ~50 px at full res); s is
# chosen so nearest-neighbour spacing s/sqrt(2) is ~7x the diameter, inside
# the >= 5x assumption.
@pytest.mark.parametrize(
    "size, s, d",
    [
        ((900, 700), 60, 6),
        ((1600, 1200), 120, 12),
        ((2400, 1800), 250, 25),
        ((3000, 3000), 500, 50),
    ],
    ids=["d6", "d12", "d25", "d50"],
)
def test_clean_lattice_is_found(size, s, d):
    image, truth, _ = _wall(*size, s=s, d=d)
    assert len(truth) >= 30  # enough points for the test to mean something

    found = detect_bolt_holes(image, [])

    _assert_lattice_found(found, truth, size, d)


@pytest.mark.parametrize(
    "size, s, d",
    [((1600, 1200), 120, 12), ((2400, 1800), 200, 20)],
    ids=["d12", "d20"],
)
def test_reported_diameter_is_close_to_drawn_hole(size, s, d):
    image, truth, _ = _wall(*size, s=s, d=d)

    found = detect_bolt_holes(image, [])

    diam = np.median([b["diameter"] for b in found])
    assert diam == pytest.approx(d, rel=0.35)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_lattice_with_dense_small_speckle(seed):
    # Paint speckle (IMG_7500) is smaller and far more numerous than bolts.
    size, s, d = (1600, 1200), 120, 12
    image, truth, _ = _wall(*size, s=s, d=d, seed=seed, speckle=3000, speckle_d=(2.0, 5.0))
    assert 3000 > 10 * len(truth)  # speckle outnumbers bolts by >10x, like the spec says

    found = detect_bolt_holes(image, [])

    _assert_lattice_found(found, truth, size, d)


@pytest.mark.parametrize("gradient", [0.15, 0.3])
def test_lattice_under_illumination_gradient(gradient):
    # Real photos are never evenly lit: the wall darkens by 15-30% from one side
    # to the other. Holes are darkened multiplicatively, so the relative
    # contrast (ring - core) / ring stays at HOLE_CONTRAST everywhere and every
    # hole still clears MIN_CONTRAST by a wide margin.
    size, s, d = (1600, 1200), 120, 12
    image, truth, _ = _wall(*size, s=s, d=d, gradient=gradient)

    found = detect_bolt_holes(image, [])

    _assert_lattice_found(found, truth, size, d)


def test_rotated_lattice_is_found():
    size, s, d = (1600, 1200), 130, 12
    image, truth, _ = _wall(*size, s=s, d=d, angle_deg=17.0)

    found = detect_bolt_holes(image, [])

    _assert_lattice_found(found, truth, size, d)


def test_foreshortened_lattice_is_found():
    # Angled panel seen from below: vertical spacing compressed to 75%.
    # Nearest neighbour is still ~6x the hole diameter.
    size, s, d = (1600, 1200), 130, 12
    image, truth, _ = _wall(*size, s=s, d=d, squash_y=0.75)

    found = detect_bolt_holes(image, [])

    _assert_lattice_found(found, truth, size, d)


# --- rejection of things that are not bolts --------------------------------------


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_random_isolated_dots_are_rejected(seed):
    size, d = (1600, 1200), 12
    rng = np.random.default_rng(seed)
    dots = _random_points(*size, 60, rng, margin=30, min_gap=6 * d)
    image, _, _ = _wall(*size, s=None, d=d, seed=seed, dots=dots)  # no lattice at all

    found = detect_bolt_holes(image, [])

    assert len(found) <= 2, f"{len(found)} of 60 random dots accepted as bolts"


def test_random_dots_alongside_lattice_are_rejected():
    size, s, d = (1600, 1200), 140, 12
    rng = np.random.default_rng(5)
    lattice = _lattice_points(*size, s, margin=0.25 * s)
    # Same size and darkness as bolts, but off-lattice (>= 0.3 s from any point).
    dots = _random_points(*size, 25, rng, margin=30, avoid=lattice, min_gap=0.3 * s)
    image, truth, dots = _wall(*size, s=s, d=d, seed=5, dots=dots)

    found = detect_bolt_holes(image, [])

    _assert_lattice_found(found, truth, size, d, max_fp=0.1)
    hit_dots, _ = _match(_to_px(found, size), dots, max(2.0, 0.5 * d))
    assert len(hit_dots) <= 0.2 * len(dots), f"{len(hit_dots)}/{len(dots)} off-lattice dots kept"


@pytest.mark.parametrize("contrast", [0.08, 0.15])
def test_low_contrast_lattice_is_rejected(contrast):
    # Same lattice geometry that test_clean_lattice_is_found accepts, but the
    # holes are only faintly darker than the wall (well under MIN_CONTRAST).
    size, s, d = (1600, 1200), 120, 12
    image, truth, _ = _wall(*size, s=s, d=d, contrast=contrast)

    found = detect_bolt_holes(image, [])

    assert len(found) <= 0.05 * len(truth), f"{len(found)} low-contrast holes accepted"


def test_clearly_dark_lattice_is_accepted_at_moderate_contrast():
    size, s, d = (1600, 1200), 120, 12
    image, truth, _ = _wall(*size, s=s, d=d, contrast=0.55)

    found = detect_bolt_holes(image, [])

    _assert_lattice_found(found, truth, size, d)


def test_lattice_too_dense_for_hole_size_is_rejected():
    # Nearest neighbour s/sqrt(2) = 42 px is only 2.1x the 20 px diameter,
    # breaking the >= 5x physical prior: these are not bolt holes.
    size, s, d = (1600, 1200), 60, 20
    image, truth, _ = _wall(*size, s=s, d=d)

    found = detect_bolt_holes(image, [])

    assert len(found) <= 0.05 * len(truth)


# --- detection polygons mask holes ------------------------------------------------


def test_bolt_under_detection_polygon_is_excluded():
    size, s, d = (1600, 1200), 120, 12
    image, truth, _ = _wall(*size, s=s, d=d)
    cx, cy = size[0] / 2, size[1] / 2  # the lattice is built around the centre, so (cx, cy) is a bolt
    target = int(np.argmin([math.hypot(x - cx, y - cy) for x, y in truth]))
    tx, ty = truth[target]
    assert math.hypot(tx - cx, ty - cy) < 1.0
    # Polygon covers that one disc only (half-width 2d, well under the 85 px pitch).
    dets = [_detection(0, _square_polygon(tx, ty, 2 * d, size))]

    found = detect_bolt_holes(image, dets)

    near = [p for p in _to_px(found, size) if math.hypot(p[0] - tx, p[1] - ty) <= 2 * d]
    assert near == [], "bolt inside a detection polygon was returned"
    others = [p for i, p in enumerate(truth) if i != target]
    _assert_lattice_found(found, others, size, d)


@pytest.mark.parametrize("class_name", ["HOLD", "VOLUME"])
def test_large_polygon_masks_every_bolt_inside_it(class_name):
    size, s, d = (1600, 1200), 120, 12
    image, truth, _ = _wall(*size, s=s, d=d)
    # A big volume over the left third of the wall (normalized polygon).
    x0, x1, y0, y1 = 0.0, 0.33, 0.0, 1.0
    poly = [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]
    dets = [_detection(0, poly, class_name)]

    found = detect_bolt_holes(image, dets)

    w, h = size
    assert all(b["x"] > x1 for b in found), "bolt returned from inside a polygon"
    outside = [(x, y) for x, y in truth if x / w > x1 + 0.02]
    _assert_recall(found, outside, size, d)


def test_non_rectangular_polygon_masks_by_shape_not_bbox():
    # Triangle over the top-left; a bolt inside its bounding box but outside
    # the triangle must survive, so the mask is the polygon, not its bbox.
    size, s, d = (1600, 1200), 120, 12
    image, truth, _ = _wall(*size, s=s, d=d)
    w, h = size
    tri = [{"x": 0.0, "y": 0.0}, {"x": 0.6, "y": 0.0}, {"x": 0.0, "y": 0.6}]

    found = detect_bolt_holes(image, [_detection(0, tri)])

    def inside(x, y):  # normalized; triangle x + y < 0.6
        return x + y < 0.6

    assert not [b for b in found if inside(b["x"], b["y"])]
    in_bbox_outside_tri = [(x, y) for x, y in truth if x / w < 0.6 and y / h < 0.6 and x / w + y / h > 0.66]
    assert len(in_bbox_outside_tri) >= 5
    _assert_recall(found, in_bbox_outside_tri, size, d, min_recall=0.8)


# --- resolution independence -----------------------------------------------------


def _symmetric_match_fraction(a_norm, b_norm, size, tol_px):
    a = _to_px(a_norm, size)
    b = _to_px(b_norm, size)
    ma, _ = _match(b, a, tol_px)
    mb, _ = _match(a, b, tol_px)
    return len(ma) / max(1, len(a)), len(mb) / max(1, len(b))


def test_same_lattice_at_two_resolutions_gives_same_normalized_bolts():
    big_size, s, d = (2400, 1800), 180, 18
    big, truth, _ = _wall(*big_size, s=s, d=d, seed=3)
    small = big.resize((1200, 900), Image.Resampling.LANCZOS)

    found_big = detect_bolt_holes(big, [])
    found_small = detect_bolt_holes(small, [])

    _assert_lattice_found(found_big, truth, big_size, d)
    assert len(found_small) == pytest.approx(len(found_big), rel=0.1)
    fa, fb = _symmetric_match_fraction(found_big, found_small, big_size, tol_px=0.5 * d)
    assert fa >= 0.9 and fb >= 0.9
    # Diameter is in pixels of the image passed in, so it halves.
    ratio = np.median([b["diameter"] for b in found_big]) / np.median([b["diameter"] for b in found_small])
    assert ratio == pytest.approx(2.0, rel=0.25)


def test_image_larger_than_max_side_keeps_normalized_coords_and_full_res_diameter():
    # 5000 px long side > MAX_SIDE (4096): detector shrinks internally, but the
    # output stays normalized and diameter stays in the caller's pixels.
    size, s, d = (5000, 3750), 400, 40
    assert max(size) > bolts.MAX_SIDE
    image, truth, _ = _wall(*size, s=s, d=d, seed=4)

    found = detect_bolt_holes(image, [])

    _assert_lattice_found(found, truth, size, d)
    assert np.median([b["diameter"] for b in found]) == pytest.approx(d, rel=0.35)


# --- reference photos (slow) ------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWN = REPO_ROOT / "mobile" / "ML-Rock-Climbing-App" / "assets" / "known_measurements" / "reference"
MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "best.pt"

# Thresholds for IMG_7500 and IMG_7502-7504, all 3024x4032 phone shots of whole
# panels on a 20 cm centred-square grid (measurements.md):
#
# * MIN_REFERENCE_BOLTS = 60. The grid has 2 bolts per (20 cm)^2 = 50 per m^2.
#   Each photo shows several m^2 of wall across 2-4 panels, so hundreds of
#   holes; even with half hidden behind holds and the blurry far edges, 60 is a
#   floor that slice 4 needs (>= ~15 bolts per panel to fit a local Jacobian),
#   not a stretch target.
# * Spacing regularity. On a centred-square lattice every bolt's nearest
#   neighbour is s/sqrt(2). Perspective changes that smoothly across the photo,
#   so each bolt's NN distance is compared with the median NN distance of its
#   K spatial neighbours. REGULAR_TOL = 0.15 is about the spacing change across
#   one local neighbourhood on the steepest panel (34 deg, IMG_7502) plus blob
#   centroid jitter. A bolt counts as regular if that ratio is within
#   +/-REGULAR_TOL of ANY real lattice distance in LATTICE_MULTIPLES: 1x (the
#   diagonal pitch s/sqrt(2)), sqrt(2)x (the square side s) or 2x (twice the
#   diagonal). A real bolt whose diagonal neighbours are hidden by holds lands
#   on sqrt(2)x or 2x (human decision, handover slice 3 Q1). REGULAR_FRACTION =
#   0.75 is kept: the remaining quarter covers seams, panel edges and centroid
#   jitter. Speckle or wood-grain false positives, which outnumber bolts
#   10-20x, sit much closer than one pitch to their neighbours (ratio < 0.85)
#   or at off-lattice distances, so they still break this.
# * NN / diameter in [5, 25]. 5 is the detector's physical prior. A T-nut hole
#   is roughly 1-2.5 cm wide in a photo (hole plus dark rim) against a 14.1 cm
#   diagonal pitch, i.e. ~6-14x; 25 leaves room for diameter under-estimation.
MIN_REFERENCE_BOLTS = 60
K_LOCAL = 8
REGULAR_TOL = 0.15
REGULAR_FRACTION = 0.75
LATTICE_MULTIPLES = (1.0, float(np.sqrt(2.0)), 2.0)
NN_TO_DIAMETER_RANGE = (5.0, 25.0)

REFERENCE_PHOTOS = ["IMG_7500.jpeg", "IMG_7502.jpeg", "IMG_7503.jpeg", "IMG_7504.jpeg"]
HARD_PHOTO = "IMG_7501.jpeg"


@lru_cache(maxsize=None)
def _run_reference(name):
    import detection

    with Image.open(KNOWN / name) as raw:
        image = ImageOps.exif_transpose(raw)
        image.load()
    dets = detection.run_detection(image)
    found = detect_bolt_holes(image, dets)
    return image.size, dets, found


def _nn_stats(found, size):
    pts = _to_px(found, size)
    dist = np.hypot(pts[:, None, 0] - pts[None, :, 0], pts[:, None, 1] - pts[None, :, 1])
    np.fill_diagonal(dist, np.inf)
    nn = dist.min(axis=1)
    order = np.argsort(dist, axis=1)[:, :K_LOCAL]
    local = np.array([np.median(nn[np.r_[i, order[i]]]) for i in range(len(pts))])
    return nn, nn / local


def _point_in_polygon(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]["x"], poly[i]["y"]
        x2, y2 = poly[(i + 1) % n]["x"], poly[(i + 1) % n]["y"]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _reference_skip(name):
    return [
        pytest.mark.slow,
        pytest.mark.skipif(not MODEL_PATH.exists(), reason="models/best.pt not present (gitignored)"),
        pytest.mark.skipif(not (KNOWN / name).exists(), reason=f"{name} not present"),
    ]


def _check_reference(name):
    size, dets, found = _run_reference(name)
    n = len(found)
    assert n >= MIN_REFERENCE_BOLTS, f"{name}: only {n} bolts"

    nn, rel = _nn_stats(found, size)
    on_lattice = np.zeros(len(rel), dtype=bool)
    for k in LATTICE_MULTIPLES:
        on_lattice |= np.abs(rel / k - 1.0) <= REGULAR_TOL
    regular = float(np.mean(on_lattice))
    assert regular >= REGULAR_FRACTION, f"{name}: only {regular:.0%} of {n} bolts have regular NN spacing"

    ratio = float(np.median(nn) / np.median([b["diameter"] for b in found]))
    lo, hi = NN_TO_DIAMETER_RANGE
    assert lo <= ratio <= hi, f"{name}: median NN / diameter = {ratio:.1f}"

    masks = [d["polygon"] for d in dets if len(d["polygon"]) >= 3]
    inside = [b for b in found if any(_point_in_polygon(b["x"], b["y"], p) for p in masks)]
    assert not inside, f"{name}: {len(inside)} bolts inside YOLO polygons"
    return n, regular, ratio


@pytest.mark.parametrize(
    "name",
    [pytest.param(p, marks=_reference_skip(p)) for p in REFERENCE_PHOTOS],
)
def test_reference_photo_bolt_count_and_spacing_regularity(name):
    n, regular, ratio = _check_reference(name)
    print(f"{name}: bolts={n} regular={regular:.2f} nn/diam={ratio:.1f}")


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(
            HARD_PHOTO,
            marks=_reference_skip(HARD_PHOTO)
            + [
                pytest.mark.xfail(
                    reason="IMG_7501 is a close-up with metal-filled holes and misaligned panels; "
                    "spec defers it to slices 6–8 (panel segmentation)",
                    strict=False,
                )
            ],
        )
    ],
)
def test_hard_reference_photo_img_7501(name):
    # Documented expectation, not a blocker: the same checks as the other
    # photos, with a lower count floor because the close-up only shows ~20-30
    # holes in total.
    size, dets, found = _run_reference(name)
    assert len(found) >= 10
    _, rel = _nn_stats(found, size)
    assert float(np.mean(np.abs(rel - 1.0) <= REGULAR_TOL)) >= REGULAR_FRACTION
