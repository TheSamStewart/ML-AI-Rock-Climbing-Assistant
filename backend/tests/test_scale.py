"""Slice 4 tests for scale.py: lattice fit, metric field, segment distances,
wall length, index_lattice and compute_scale.

Written from the spec (docs/features/wall_size_hold_distance.md, Decisions ->
"Slice 4 lattice + distances") only, not from the implementation.

Ground truth: synthetic centred-square lattices built in grid units (corners
(i, j) plus centres (i + 0.5, j + 0.5); 1 unit = one bolt_spacing_cm), mapped
to px by a known transform. The wall is a plane, so the true distance between
two image points is the Euclidean distance between their grid-unit preimages.

Bars (spec target: held-out in-panel bolt pairs p95 <= 7%):
* CLEAN_AFFINE_P95 = 2%. Under an affine map every bolt's neighbour vectors
  are exact lattice offsets, so the per-bolt J is exact and the interpolated
  metric is constant. Any error is numerical; 2% is generous.
* CLEAN_HOMOGRAPHY_P95 = 3%. With perspective the metric varies across the
  wall; J is a finite-difference estimate over ~half a square and is
  interpolated between bolts, which costs a little.
* DEGRADED_P95 = 7% (the spec's acceptance bar) for jitter (~1 px at ~60 px
  per square, i.e. ~2.4% of the 42 px diagonal pitch), 30-40% of bolts hidden,
  a region with every centre bolt hidden (the sqrt(2) ambiguity), and a few
  spurious points.
Pairs are measured between bolt positions (including hidden ones, standing in
for holds) and between arbitrary non-bolt points, all at least 1 unit apart.
"""

import json
import math
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

import scale
from scale import (
    DISTANCE_DECIMALS,
    LATTICE_BASIS,
    SEGMENT_SAMPLES,
    WALL_END_ALLOWANCE_UNITS,
    Lattice,
    compute_scale,
    fit_lattice,
    index_lattice,
    metric_at,
    segment_lengths,
    select_distances,
    select_tiers,
    wall_length_units,
)

CLEAN_AFFINE_P95 = 0.02
CLEAN_HOMOGRAPHY_P95 = 0.03
DEGRADED_P95 = 0.07
MIN_PAIR_UNITS = 1.0
N_PAIRS = 400

PX_PER_UNIT = 60.0
NX, NY = 10, 14  # squares; 11*15 + 10*14 = 305 bolts


# --- synthetic lattices ---------------------------------------------------------


def centred_square(nx, ny, x0=0.0, y0=0.0):
    """Grid-unit bolt positions and a bool mask of which are centre bolts."""
    i, j = np.meshgrid(np.arange(nx + 1), np.arange(ny + 1), indexing="ij")
    corners = np.stack([i.ravel(), j.ravel()], axis=1).astype(float)
    ci, cj = np.meshgrid(np.arange(nx) + 0.5, np.arange(ny) + 0.5, indexing="ij")
    centres = np.stack([ci.ravel(), cj.ravel()], axis=1)
    g = np.vstack([corners, centres]) + [x0, y0]
    is_centre = np.r_[np.zeros(len(corners), bool), np.ones(len(centres), bool)]
    return g, is_centre


def _rot(deg):
    t = math.radians(deg)
    return np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])


class Affine:
    def __init__(self, G, t=(1000.0, 1000.0)):
        self.G = np.asarray(G, float)
        self.t = np.asarray(t, float)

    def __call__(self, g):
        return np.asarray(g, float) @ self.G.T + self.t

    def true_metric(self):
        A = np.linalg.inv(self.G)
        return A.T @ A


class Homography:
    def __init__(self, H):
        self.H = np.asarray(H, float)

    def __call__(self, g):
        g = np.asarray(g, float)
        h = np.c_[g, np.ones(len(g))] @ self.H.T
        return h[:, :2] / h[:, 2:]


AFFINE = {
    "scale": Affine(PX_PER_UNIT * np.eye(2)),
    "rotation_30": Affine(PX_PER_UNIT * _rot(30)),
    "rotation_45": Affine(PX_PER_UNIT * _rot(45)),
    # Wall tilted ~53 deg away from the camera: vertical squashed to 0.6.
    "foreshortened": Affine(np.diag([PX_PER_UNIT, 0.6 * PX_PER_UNIT])),
    "foreshortened_rotated": Affine(_rot(15) @ np.diag([PX_PER_UNIT, 0.65 * PX_PER_UNIT])),
}

# Perspective: px-per-unit falls by ~20% from the top-left to the bottom-right
# corner of the 10x14 lattice (w goes 1 -> 1.21).
HOMOGRAPHY = Homography([[60.0, 4.0, 200.0], [3.0, 58.0, 150.0], [0.004, 0.012, 1.0]])


def _rel_errors(lattice, fwd, ga, gb):
    pred = np.asarray(segment_lengths(lattice, fwd(ga), fwd(gb)), float)
    true = np.linalg.norm(ga - gb, axis=1)
    assert pred.shape == true.shape
    assert np.all(np.isfinite(pred))
    return np.abs(pred - true) / true


def _pairs(rng, points, n=N_PAIRS, min_units=MIN_PAIR_UNITS):
    a = rng.integers(0, len(points), size=4 * n)
    b = rng.integers(0, len(points), size=4 * n)
    ga, gb = points[a], points[b]
    keep = np.linalg.norm(ga - gb, axis=1) >= min_units
    return ga[keep][:n], gb[keep][:n]


def _random_points(rng, n, lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    return lo + rng.random((n, 2)) * (hi - lo)


def _eval_pairs(rng, lattice, fwd, all_bolts_g, lo, hi):
    """p95 rel error over bolt-bolt pairs and arbitrary-point pairs."""
    ga, gb = _pairs(rng, all_bolts_g)
    errs = [_rel_errors(lattice, fwd, ga, gb)]
    pts = _random_points(rng, 2 * N_PAIRS, lo, hi)
    pa, pb = _pairs(rng, pts)
    errs.append(_rel_errors(lattice, fwd, pa, pb))
    # Lattice midpoints between neighbouring bolts (not bolts themselves).
    mids = np.vstack([all_bolts_g + [0.25, 0.25], all_bolts_g + [0.5, 0.0], all_bolts_g + [0.0, 0.5]])
    ma, mb = _pairs(rng, mids)
    errs.append(_rel_errors(lattice, fwd, ma, mb))
    return [float(np.percentile(e, 95)) for e in errs]


def _hide(rng, n, frac):
    return rng.random(n) >= frac  # True = visible


# --- constants & dataclass ------------------------------------------------------


def test_constants():
    assert DISTANCE_DECIMALS == 3
    assert SEGMENT_SAMPLES == 16
    assert WALL_END_ALLOWANCE_UNITS == 0.5
    B = np.asarray(LATTICE_BASIS, float)
    assert B.shape == (2, 2)
    # Columns are the two diagonals (0.5, 0.5) and (0.5, -0.5).
    np.testing.assert_allclose(B[:, 0], [0.5, 0.5])
    np.testing.assert_allclose(B[:, 1], [0.5, -0.5])


def test_lattice_dataclass_fields():
    assert {f.name for f in fields(Lattice)} >= {"xy", "jacobian", "metric", "spacing_px"}


def test_stub_constant_is_gone():
    assert not hasattr(scale, "STUB_PHOTO_HEIGHT_UNITS")


# --- fit_lattice: shapes, degenerate input --------------------------------------


@pytest.mark.parametrize("n", [0, 1, 2])
def test_fit_lattice_fewer_than_three_points_is_empty(n):
    pts = np.array([[100.0, 100.0], [160.0, 100.0]])[:n].reshape(n, 2)

    lat = fit_lattice(pts)

    assert len(lat.xy) == 0
    assert wall_length_units(lat) is None


def test_fit_lattice_shapes_and_subset_of_input():
    g, _ = centred_square(NX, NY)
    px = AFFINE["scale"](g)

    lat = fit_lattice(px)

    n = len(lat.xy)
    assert np.asarray(lat.xy).shape == (n, 2)
    assert np.asarray(lat.jacobian).shape == (n, 2, 2)
    assert np.asarray(lat.metric).shape == (n, 2, 2)
    assert np.asarray(lat.spacing_px).shape == (n,)
    assert np.all(np.isfinite(lat.spacing_px)) and np.all(np.asarray(lat.spacing_px) > 0)
    # Every fitted bolt is one of the input bolts.
    d = np.linalg.norm(np.asarray(lat.xy)[:, None, :] - px[None, :, :], axis=2)
    assert np.all(d.min(axis=1) < 1e-6)
    assert len(np.unique(d.argmin(axis=1))) == n
    # A clean lattice: nearly every bolt (all but perhaps a few corners) fits.
    assert n >= 0.9 * len(px)


def test_fit_lattice_does_not_mutate_input():
    g, _ = centred_square(4, 4)
    px = AFFINE["rotation_30"](g)
    before = px.copy()

    fit_lattice(px)

    np.testing.assert_array_equal(px, before)


# --- metric and jacobian against the true affine map ----------------------------


def _is_signed_permutation(S, tol):
    S = np.asarray(S)
    rounded = np.round(S)
    if np.max(np.abs(S - rounded)) > tol:
        return False
    return sorted(np.abs(rounded).ravel().tolist()) == [0.0, 0.0, 1.0, 1.0] and abs(abs(np.linalg.det(rounded)) - 1) < 1e-9


@pytest.mark.parametrize("name", list(AFFINE))
def test_metric_and_jacobian_match_true_affine_map(name):
    fwd = AFFINE[name]
    g, _ = centred_square(NX, NY)
    lat = fit_lattice(fwd(g))
    M_true = fwd.true_metric()

    M = np.asarray(lat.metric)
    rel = np.linalg.norm(M - M_true, axis=(1, 2)) / np.linalg.norm(M_true)
    assert np.percentile(rel, 95) <= 0.02, f"{name}: metric p95 rel err {np.percentile(rel, 95):.3f}"

    # J (px per grid unit) equals the true G up to one of the lattice's 8
    # symmetries: inv(G) @ J is a signed permutation matrix.
    S = np.linalg.inv(fwd.G) @ np.asarray(lat.jacobian)
    ok = np.mean([_is_signed_permutation(s, 0.05) for s in S])
    assert ok >= 0.95, f"{name}: only {ok:.0%} of J are a lattice symmetry of the true map"


@pytest.mark.parametrize("name", ["scale", "rotation_45", "foreshortened"])
def test_metric_at_matches_true_metric_off_bolts(name):
    fwd = AFFINE[name]
    g, _ = centred_square(NX, NY)
    lat = fit_lattice(fwd(g))
    rng = np.random.default_rng(1)
    pts = fwd(_random_points(rng, 50, (0, 0), (NX, NY)))

    M = np.asarray(metric_at(lat, pts))

    assert M.shape == (50, 2, 2)
    M_true = fwd.true_metric()
    rel = np.linalg.norm(M - M_true, axis=(1, 2)) / np.linalg.norm(M_true)
    assert rel.max() <= 0.02


# --- segment_lengths: clean lattices -------------------------------------------


@pytest.mark.parametrize("name", list(AFFINE))
def test_clean_affine_lattice_distances(name):
    fwd = AFFINE[name]
    g, _ = centred_square(NX, NY)
    lat = fit_lattice(fwd(g))

    p95 = _eval_pairs(np.random.default_rng(2), lat, fwd, g, (0, 0), (NX, NY))

    assert max(p95) <= CLEAN_AFFINE_P95, f"{name}: p95 (bolt, random, midpoint) = {p95}"


def test_clean_homography_lattice_distances():
    g, _ = centred_square(NX, NY)
    lat = fit_lattice(HOMOGRAPHY(g))

    p95 = _eval_pairs(np.random.default_rng(3), lat, HOMOGRAPHY, g, (0, 0), (NX, NY))

    assert max(p95) <= CLEAN_HOMOGRAPHY_P95, f"homography: p95 = {p95}"


def test_segment_lengths_basic_properties():
    fwd = AFFINE["foreshortened_rotated"]
    g, _ = centred_square(NX, NY)
    lat = fit_lattice(fwd(g))
    a = fwd(np.array([[1.0, 1.0], [2.0, 3.0], [5.0, 5.0]]))
    b = fwd(np.array([[1.0, 1.0], [7.0, 9.0], [5.0, 12.0]]))

    ab = np.asarray(segment_lengths(lat, a, b))
    ba = np.asarray(segment_lengths(lat, b, a))

    assert ab.shape == (3,)
    assert ab[0] == pytest.approx(0.0, abs=1e-9)
    np.testing.assert_allclose(ab, ba, rtol=1e-9, atol=1e-9)
    assert np.all(ab[1:] > 0)


def test_segment_lengths_are_additive_along_a_line():
    a_g, m_g, c_g = np.array([[1.0, 2.0]]), np.array([[4.0, 7.0]]), np.array([[7.0, 12.0]])
    g, _ = centred_square(NX, NY)
    lat = fit_lattice(HOMOGRAPHY(g))

    whole = segment_lengths(lat, HOMOGRAPHY(a_g), HOMOGRAPHY(c_g))[0]
    halves = segment_lengths(lat, HOMOGRAPHY(a_g), HOMOGRAPHY(m_g))[0] + segment_lengths(lat, HOMOGRAPHY(m_g), HOMOGRAPHY(c_g))[0]

    assert halves == pytest.approx(whole, rel=0.01)


def test_segment_lengths_empty_input():
    g, _ = centred_square(4, 4)
    lat = fit_lattice(AFFINE["scale"](g))

    out = np.asarray(segment_lengths(lat, np.zeros((0, 2)), np.zeros((0, 2))))

    assert out.shape == (0,)


# --- segment_lengths: degraded lattices -----------------------------------------


@pytest.mark.parametrize("name", ["scale", "rotation_45", "foreshortened_rotated", "homography"])
@pytest.mark.parametrize("seed", [0, 1])
def test_jittered_lattice_distances(name, seed):
    fwd = HOMOGRAPHY if name == "homography" else AFFINE[name]
    rng = np.random.default_rng(10 + seed)
    g, _ = centred_square(NX, NY)
    px = fwd(g) + rng.normal(0.0, 1.0, size=(len(g), 2))
    lat = fit_lattice(px)

    p95 = _eval_pairs(rng, lat, fwd, g, (0, 0), (NX, NY))

    assert max(p95) <= DEGRADED_P95, f"{name} jitter: p95 = {p95}"


@pytest.mark.parametrize("name", ["scale", "rotation_30", "foreshortened", "homography"])
@pytest.mark.parametrize("frac", [0.30, 0.40])
def test_lattice_with_hidden_bolts(name, frac):
    # Holds hide a random 30-40% of bolts. Distances are still measured between
    # every lattice position, including the hidden ones (as holds would be).
    fwd = HOMOGRAPHY if name == "homography" else AFFINE[name]
    rng = np.random.default_rng(int(frac * 100))
    g, _ = centred_square(NX, NY)
    visible = _hide(rng, len(g), frac)
    px = fwd(g[visible]) + rng.normal(0.0, 0.5, size=(int(visible.sum()), 2))
    lat = fit_lattice(px)

    assert len(lat.xy) > 0
    p95 = _eval_pairs(rng, lat, fwd, g, (0, 0), (NX, NY))

    assert max(p95) <= DEGRADED_P95, f"{name} {frac:.0%} hidden: p95 = {p95}"


TRANSFORMS = {**AFFINE, "homography": HOMOGRAPHY}


def _true_metric_at(fwd, g, h=1e-4):
    """True metric (grid units^2 per px^2) at grid points g, from the forward
    map's Jacobian by central differences. Exact for affine maps."""
    g = np.asarray(g, float)
    cols = []
    for k in range(2):
        e = np.zeros(2)
        e[k] = h
        cols.append((fwd(g + e) - fwd(g - e)) / (2 * h))
    J = np.stack(cols, axis=2)  # (n, 2 px, 2 grid)
    A = np.linalg.inv(J)
    return np.transpose(A, (0, 2, 1)) @ A


def _metric_ratio(lat, fwd, g):
    M = np.asarray(metric_at(lat, fwd(g)))
    return np.trace(M, axis1=1, axis2=2) / np.trace(_true_metric_at(fwd, g), axis1=1, axis2=2)


def _check_region_without_centres(name, box, extra_hidden, seed=7):
    # Inside `box` every centre bolt is hidden: locally that region is a plain
    # square grid whose nearest neighbours are the square SIDES (1 unit), and a
    # "these are the diagonals" reading fits it equally well but is sqrt(2)
    # off (metric 0.5x). Spec (Decisions, "sqrt(2) fix, boundary rule"): the
    # coarser of two touching groups whose metrics differ by a uniform 2x is
    # re-read on the finer variant, whatever the region's size, so the region
    # must come out at the same scale as the rest.
    x0, x1, y0, y1 = box
    fwd = TRANSFORMS[name]
    rng = np.random.default_rng(seed)
    g, is_centre = centred_square(NX, NY)
    in_region = (g[:, 0] >= x0) & (g[:, 0] <= x1) & (g[:, 1] >= y0) & (g[:, 1] <= y1)
    keep = ~(is_centre & in_region) & _hide(rng, len(g), extra_hidden)
    lat = fit_lattice(fwd(g[keep]))

    # Metric inside the region is the true one, not 0.5x.
    ratio = _metric_ratio(lat, fwd, _random_points(rng, 40, (x0 + 0.2, y0 + 0.2), (x1 - 0.2, y1 - 0.2)))
    assert np.percentile(np.abs(ratio - 1), 95) <= 2 * DEGRADED_P95, f"{name}: region metric / true = {np.round(ratio, 2)}"

    ga, gb = _pairs(rng, g[in_region])
    p95_region = float(np.percentile(_rel_errors(lat, fwd, ga, gb), 95))
    p95_all = _eval_pairs(rng, lat, fwd, g, (0, 0), (NX, NY))

    assert p95_region <= DEGRADED_P95, f"{name}: in-region p95 = {p95_region:.3f}"
    assert max(p95_all) <= DEGRADED_P95, f"{name}: wall p95 = {p95_all}"


@pytest.mark.parametrize("name", ["scale", "rotation_30", "foreshortened"])
@pytest.mark.parametrize("extra_hidden", [0.0, 0.3])
@pytest.mark.parametrize("box", [(4, 6, 6, 8), (3, 7, 4, 10)], ids=["2x2_squares", "4x6_squares"])
def test_interior_region_with_all_centre_bolts_hidden_sqrt2_ambiguity(name, extra_hidden, box):
    # A cluster of holds hides every centre bolt in an interior patch; the
    # patch is surrounded by normal lattice on all sides.
    _check_region_without_centres(name, box, extra_hidden)


# Slice 6 done-when: centre-less regions of ANY size measure at p95 <= 7%
# (DEGRADED_P95). Made must-pass by the human on 2026-10-19 ("being 40% off
# is unacceptable"); was xfail before 5a. Boxes are (x0, x1, y0, y1) in
# squares on the 10x14 wall; image y grows downwards, so y = NY is the bottom
# edge. The rest of the wall keeps its centre bolts, so there is always a
# correct group to compare with (a photo with no centre bolts anywhere is
# documented as ambiguous and isn't tested).
LARGE_CENTRELESS_BOXES = {
    "interior_6x8_squares": (2, 8, 3, 11),
    "left_edge_strip_3_squares_full_height": (0, 3, 0, NY),
    "bottom_edge_strip_3_squares_full_width": (0, NX, NY - 3, NY),
    "top_left_corner_4x5_squares": (0, 4, 0, 5),
    "bottom_right_corner_4x5_squares": (NX - 4, NX, NY - 5, NY),
    # Size-independence: the centre-less part is the larger group (70% of the
    # wall). The boundary rule picks the coarser group, not the smaller one.
    "majority_7_of_10_columns": (0, 7, 0, NY),
}


@pytest.mark.parametrize("name", ["scale", "rotation_30", "foreshortened", "homography"])
@pytest.mark.parametrize("extra_hidden", [0.0, 0.3])
@pytest.mark.parametrize("box", list(LARGE_CENTRELESS_BOXES.values()), ids=list(LARGE_CENTRELESS_BOXES))
def test_large_or_edge_region_with_all_centre_bolts_hidden(name, extra_hidden, box):
    _check_region_without_centres(name, box, extra_hidden)


# --- guards: genuine scale changes must not be re-read as sqrt(2) ---------------
#
# Two touching panels of the same centred-square lattice whose px-per-unit
# differ (one is further away or at a different angle). Their metrics differ,
# but not by the uniform 2x of the sqrt(2) misread, so neither may be re-read:
# each panel's own distances must stay right. Panels are 5x14 squares side by
# side with a 40 px seam (about one diagonal pitch at 60 px per unit).

SEAM_GAP_PX = 40.0
PANEL_NX = 5


def _two_panels(right_G, right_centre_box=None, rng=None, extra_hidden=0.0):
    """Left panel at PX_PER_UNIT, right panel at `right_G` (px per unit).
    Returns [(fwd, all grid points, visible grid points)] per panel.
    `right_centre_box` hides every centre bolt in that box of the right panel."""
    left_fwd = Affine(PX_PER_UNIT * np.eye(2), t=(1000.0, 1000.0))
    # The right panel's leftmost corner sits SEAM_GAP_PX right of the left
    # panel's right edge. For an unrotated right panel that corner is its grid
    # origin; a panel turned in-plane swings its lower-left corner left, so it
    # is shifted right until it clears the seam too (two real panels can't
    # interleave their bolts in the same image area).
    corners = np.array([[0.0, 0.0], [PANEL_NX, 0.0], [0.0, NY], [PANEL_NX, NY]])
    left_edge = Affine(right_G, t=(0.0, 0.0))(corners)[:, 0].min()
    right_x = 1000.0 + PANEL_NX * PX_PER_UNIT + SEAM_GAP_PX - left_edge
    right_fwd = Affine(right_G, t=(right_x, 1000.0))
    out = []
    for fwd, box in ((left_fwd, None), (right_fwd, right_centre_box)):
        g, is_centre = centred_square(PANEL_NX, NY)
        keep = np.ones(len(g), bool)
        if box is not None:
            x0, x1, y0, y1 = box
            in_box = (g[:, 0] >= x0) & (g[:, 0] <= x1) & (g[:, 1] >= y0) & (g[:, 1] <= y1)
            keep &= ~(is_centre & in_box)
        if rng is not None and extra_hidden:
            keep &= _hide(rng, len(g), extra_hidden)
        out.append((fwd, g, g[keep]))
    return out


def _check_panels(panels, rng, label):
    lat = fit_lattice(np.vstack([fwd(vis) for fwd, _, vis in panels]))
    assert len(lat.xy) > 0
    for side, (fwd, g, _) in zip(("left", "right"), panels):
        # Each panel's interior (>= 1 unit from the seam) has its own true metric.
        lo, hi = ((0.2, 0.2), (PANEL_NX - 1.0, NY - 0.2)) if side == "left" else ((1.0, 0.2), (PANEL_NX - 0.2, NY - 0.2))
        ratio = _metric_ratio(lat, fwd, _random_points(rng, 40, lo, hi))
        assert np.percentile(np.abs(ratio - 1), 95) <= 2 * DEGRADED_P95, f"{label} {side}: metric / true = {np.round(ratio, 2)}"
        ga, gb = _pairs(rng, g)
        p95_bolts = float(np.percentile(_rel_errors(lat, fwd, ga, gb), 95))
        pa, pb = _pairs(rng, _random_points(rng, 2 * N_PAIRS, (0.0, 0.0), (PANEL_NX, NY)))
        p95_points = float(np.percentile(_rel_errors(lat, fwd, pa, pb), 95))
        assert max(p95_bolts, p95_points) <= DEGRADED_P95, f"{label} {side}: p95 (bolt, random) = {p95_bolts:.3f}, {p95_points:.3f}"


GENUINE_SCALE_CHANGES = {
    # Right panel at 1.2x / 0.8x the px per unit: metric 0.69x / 1.56x, not 0.5x / 2x.
    "closer_1.2": 1.2 * PX_PER_UNIT * np.eye(2),
    "further_0.8": 0.8 * PX_PER_UNIT * np.eye(2),
    # A panel at a different angle: one axis foreshortened, so the metric
    # changes shape as well as size.
    "steeper_0.7_vertical": np.diag([PX_PER_UNIT, 0.7 * PX_PER_UNIT]),
    # Panels whose grids are also turned in-plane relative to each other (as in
    # IMG_7503). A rotation leaves the metric unchanged, so the metric ratio is
    # still 0.69x / 1.56x.
    "further_0.8_rotated_20": 0.8 * PX_PER_UNIT * _rot(20),
    "closer_1.2_rotated_20": 1.2 * PX_PER_UNIT * _rot(20),
}


def _inside_convex_hull(points, hull_points):
    import cv2

    hull = cv2.convexHull(np.asarray(hull_points, np.float32))
    return np.array([cv2.pointPolygonTest(hull, (float(x), float(y)), True) for x, y in points])


@pytest.mark.parametrize("right_G", list(GENUINE_SCALE_CHANGES.values()), ids=list(GENUINE_SCALE_CHANGES))
def test_two_panel_geometry_keeps_the_seam_clear(right_G):
    # Self-check of the test geometry: the panels are side by side, with no
    # bolt of one panel inside (or within SEAM_GAP_PX of) the other's outline.
    (lf, lg, _), (rf, rg, _) = _two_panels(right_G)
    left, right = lf(lg), rf(rg)

    assert _inside_convex_hull(left, right).max() <= -SEAM_GAP_PX + 1e-6
    assert _inside_convex_hull(right, left).max() <= -SEAM_GAP_PX + 1e-6


@pytest.mark.parametrize("extra_hidden", [0.0, 0.3])
@pytest.mark.parametrize("right_G", list(GENUINE_SCALE_CHANGES.values()), ids=list(GENUINE_SCALE_CHANGES))
def test_adjacent_panels_at_different_scale_are_not_reread_as_sqrt2(right_G, extra_hidden):
    rng = np.random.default_rng(31)
    panels = _two_panels(right_G, rng=rng, extra_hidden=extra_hidden)

    _check_panels(panels, rng, f"{extra_hidden:.0%} hidden")


@pytest.mark.parametrize(
    "right_G",
    [GENUINE_SCALE_CHANGES["closer_1.2"], GENUINE_SCALE_CHANGES["further_0.8"]],
    ids=["closer_1.2", "further_0.8"],
)
def test_centreless_region_inside_a_panel_at_a_different_scale(right_G):
    # The sqrt(2) fix and a genuine scale change together: the right panel is
    # at a different depth AND has a 3x8-square centre-less block inside it.
    # The block must be re-read against its own panel (a uniform 2x), and the
    # left panel (0.69x or 1.56x off the right panel, not 2x) left alone.
    rng = np.random.default_rng(32)
    panels = _two_panels(right_G, right_centre_box=(1, 4, 3, 11))

    _check_panels(panels, rng, "centre-less block in right panel")


SPURIOUS_FRACTION = 0.01
SPURIOUS_MIN_UNITS = 0.45


@pytest.mark.parametrize("hidden", [0.0, 0.3])
def test_a_few_spurious_points_do_not_break_distances(hidden):
    # 1% off-lattice false positives (3 points on a 305-bolt wall). They sit
    # >= 0.45 units (~0.64 diagonal pitches) from every visible bolt, so they
    # would survive slice 3's "NN >= 0.7x local median" filter. The spec's
    # outlier drop (metric > 35% off the local median) exists for exactly
    # this; one bad point must not spoil the whole wall's p95.
    fwd = AFFINE["foreshortened_rotated"]
    rng = np.random.default_rng(21)
    g, _ = centred_square(NX, NY)
    visible = g[_hide(rng, len(g), hidden)]
    cand = _random_points(rng, 5000, (0, 0), (NX, NY))
    far = np.linalg.norm(cand[:, None] - visible[None], axis=2).min(axis=1) >= SPURIOUS_MIN_UNITS
    spurious = cand[far][: max(1, int(SPURIOUS_FRACTION * len(g)))]
    lat = fit_lattice(np.vstack([fwd(visible), fwd(spurious)]))

    p95 = _eval_pairs(rng, lat, fwd, g, (0, 0), (NX, NY))

    assert max(p95) <= DEGRADED_P95, f"{len(spurious)} spurious points, {hidden:.0%} hidden: p95 = {p95}"


# --- invariance ----------------------------------------------------------------


@pytest.mark.parametrize("deg", [17.0, 45.0, 90.0])
def test_global_rotation_does_not_change_distances(deg):
    g, _ = centred_square(NX, NY)
    base = AFFINE["foreshortened"]
    rotated = Affine(_rot(deg) @ base.G)
    rng = np.random.default_rng(4)
    ga, gb = _pairs(rng, _random_points(rng, 2 * N_PAIRS, (0, 0), (NX, NY)))

    d0 = np.asarray(segment_lengths(fit_lattice(base(g)), base(ga), base(gb)))
    d1 = np.asarray(segment_lengths(fit_lattice(rotated(g)), rotated(ga), rotated(gb)))

    assert np.percentile(np.abs(d1 - d0) / d0, 95) <= CLEAN_AFFINE_P95


def test_region_rotated_45_deg_relative_to_rest():
    # Two panels side by side whose bolt grids are rotated 45 deg to each other
    # (as in IMG_7503). M is invariant to lattice orientation, so both panels
    # and pairs across the gap measure correctly.
    left, _ = centred_square(6, 12)
    big, _ = centred_square(40, 40, x0=-20.0, y0=-20.0)
    turned = big @ _rot(45).T + [11.0, 6.0]
    right = turned[(turned[:, 0] >= 8.0) & (turned[:, 0] <= 14.0) & (turned[:, 1] >= 0.0) & (turned[:, 1] <= 12.0)]
    g = np.vstack([left, right])
    fwd = AFFINE["scale"]
    lat = fit_lattice(fwd(g))
    rng = np.random.default_rng(5)

    for name, pts in (("left", left), ("right", right), ("both", g)):
        ga, gb = _pairs(rng, pts)
        p95 = float(np.percentile(_rel_errors(lat, fwd, ga, gb), 95))
        assert p95 <= CLEAN_HOMOGRAPHY_P95, f"{name}: p95 = {p95:.3f}"


@pytest.mark.parametrize("k", [0.25, 3.0])
def test_scaling_pixels_leaves_grid_distances_unchanged(k):
    fwd = AFFINE["rotation_30"]
    rng = np.random.default_rng(6)
    g, _ = centred_square(NX, NY)
    px = fwd(g[_hide(rng, len(g), 0.3)])
    ga, gb = _pairs(rng, g)

    d1 = np.asarray(segment_lengths(fit_lattice(px), fwd(ga), fwd(gb)))
    dk = np.asarray(segment_lengths(fit_lattice(k * px), k * fwd(ga), k * fwd(gb)))

    np.testing.assert_allclose(dk, d1, rtol=1e-4)
    wl1, wlk = wall_length_units(fit_lattice(px)), wall_length_units(fit_lattice(k * px))
    assert (wl1 is None) == (wlk is None)
    if wl1 is not None:
        assert wlk == pytest.approx(wl1, rel=1e-4)


# --- wall_length_units ---------------------------------------------------------

# Spec: top bolt to bottom bolt within a +/-4 nearest-neighbour band around the
# median bolt x, integrated, plus 0.5 units each end. For an upright lattice
# ny squares tall that is ny + 1.0. Which top and bottom bolt inside the band
# is picked isn't pinned: the band is +/-4 * 0.707 units wide, so a slanted
# pick on a 20-square-tall wall is at most sqrt(20^2 + 5.7^2) = 20.8, i.e. +4%.
WALL_NX, WALL_NY = 10, 20
WALL_REL_TOL = 0.05


@pytest.mark.parametrize("name", ["scale", "foreshortened"])
@pytest.mark.parametrize("hidden", [0.0, 0.3])
def test_wall_length_of_upright_lattice(name, hidden):
    fwd = AFFINE[name]
    rng = np.random.default_rng(8)
    g, _ = centred_square(WALL_NX, WALL_NY)
    keep = _hide(rng, len(g), hidden)
    # Keep the central column's top and bottom bolts so the extent is known.
    centre_col = np.isclose(g[:, 0], WALL_NX / 2)
    keep |= centre_col & (np.isclose(g[:, 1], 0) | np.isclose(g[:, 1], WALL_NY))

    wl = wall_length_units(fit_lattice(fwd(g[keep])))

    assert wl is not None
    assert wl == pytest.approx(WALL_NY + 2 * WALL_END_ALLOWANCE_UNITS, rel=WALL_REL_TOL)


def test_wall_length_under_perspective():
    g, _ = centred_square(WALL_NX, WALL_NY)
    H = Homography([[60.0, 0.0, 200.0], [0.0, 60.0, 150.0], [0.0, 0.01, 1.0]])  # keystone

    wl = wall_length_units(fit_lattice(H(g)))

    assert wl == pytest.approx(WALL_NY + 1.0, rel=WALL_REL_TOL)


def test_wall_length_ignores_a_distant_side_patch():
    # A short patch far to the side must not be the "top" or "bottom".
    main, _ = centred_square(WALL_NX, WALL_NY)
    side, _ = centred_square(2, 4, x0=40.0, y0=-6.0)
    wl = wall_length_units(fit_lattice(AFFINE["scale"](np.vstack([main, side]))))

    assert wl == pytest.approx(WALL_NY + 1.0, rel=WALL_REL_TOL)


# --- index_lattice -------------------------------------------------------------


def _match_to_truth(lat_xy, px, g):
    d = np.linalg.norm(np.asarray(lat_xy)[:, None, :] - px[None, :, :], axis=2)
    return g[d.argmin(axis=1)]


def _check_index(coords, comp, truth_g, n):
    coords = np.asarray(coords, float)
    comp = np.asarray(comp)
    assert coords.shape == (n, 2)
    assert comp.shape == (n,)
    # Integer combinations of the diagonal basis.
    nb = coords @ np.linalg.inv(np.asarray(LATTICE_BASIS, float)).T
    np.testing.assert_allclose(nb, np.round(nb), atol=1e-6)
    for c in np.unique(comp):
        idx = np.flatnonzero(comp == c)
        cc, tg = coords[idx], truth_g[idx]
        assert len({tuple(np.round(p, 6)) for p in cc}) == len(idx), "two bolts share a coordinate"
        dc = np.linalg.norm(cc[:, None] - cc[None], axis=2)
        dt = np.linalg.norm(tg[:, None] - tg[None], axis=2)
        np.testing.assert_allclose(dc, dt, atol=1e-6)


@pytest.mark.parametrize("name", ["scale", "rotation_45", "foreshortened_rotated"])
def test_index_lattice_clean(name):
    fwd = AFFINE[name]
    g, _ = centred_square(NX, NY)
    px = fwd(g)
    lat = fit_lattice(px)

    coords, comp = index_lattice(lat)

    _check_index(coords, comp, _match_to_truth(lat.xy, px, g), len(lat.xy))
    assert len(np.unique(comp)) == 1


def test_index_lattice_jittered_homography_with_hidden_bolts():
    rng = np.random.default_rng(9)
    g, _ = centred_square(NX, NY)
    g = g[_hide(rng, len(g), 0.3)]
    px = HOMOGRAPHY(g) + rng.normal(0, 1.0, size=(len(g), 2))
    lat = fit_lattice(px)

    coords, comp = index_lattice(lat)

    _check_index(coords, comp, _match_to_truth(lat.xy, px, g), len(lat.xy))
    # Most bolts are in one patch.
    _, counts = np.unique(comp, return_counts=True)
    assert counts.max() >= 0.8 * len(lat.xy)


def test_index_lattice_separates_distant_patches():
    a, _ = centred_square(5, 5)
    b, _ = centred_square(5, 5, x0=30.0, y0=0.3)  # off-grid relative to a
    g = np.vstack([a, b])
    px = AFFINE["scale"](g)
    lat = fit_lattice(px)

    coords, comp = index_lattice(lat)

    _check_index(coords, comp, _match_to_truth(lat.xy, px, g), len(lat.xy))
    truth = _match_to_truth(lat.xy, px, g)
    side = truth[:, 0] > 15
    assert set(np.asarray(comp)[side]).isdisjoint(set(np.asarray(comp)[~side]))


def test_index_lattice_empty():
    coords, comp = index_lattice(fit_lattice(np.zeros((0, 2))))

    assert len(coords) == 0 and len(comp) == 0


# --- compute_scale -------------------------------------------------------------

IMAGE_SIZE = (1200, 900)


def _det(id_, x, y, class_name="HOLD"):
    return {
        "id": id_,
        "class_name": class_name,
        "centroid": {"x": x, "y": y},
        "polygon": [{"x": x, "y": y}],
        "confidence": 0.9,
        "size": 0.05,
    }


def _bolts_from_px(px, image_size, diameter=8.0):
    w, h = image_size
    return [{"x": float(x / w), "y": float(y / h), "diameter": diameter} for x, y in px]


def _wall(image_size=IMAGE_SIZE, G=None):
    """An upright foreshortened lattice filling most of the image."""
    G = np.diag([60.0, 45.0]) if G is None else np.asarray(G, float)
    fwd = Affine(G, t=(60.0, 45.0))
    g, _ = centred_square(18, 18)
    px = fwd(g)
    w, h = image_size
    inside = (px[:, 0] > 0) & (px[:, 0] < w) & (px[:, 1] > 0) & (px[:, 1] < h)
    return fwd, g[inside], px[inside]


def _dets_at_grid(fwd, grid_pts, image_size=IMAGE_SIZE):
    w, h = image_size
    px = fwd(np.asarray(grid_pts, float))
    return [_det(i, float(x / w), float(y / h)) for i, (x, y) in enumerate(px)]


HOLDS_G = [(1.3, 2.2), (4.0, 7.5), (8.2, 3.1), (12.6, 11.4), (2.5, 13.0)]

_KEYS = {"status", "bolt_count", "wall_length_units", "distances_units", "tiers", "angles_deg", "angle_source", "angle_margin_deg"}


def _insufficient(n):
    return {
        "status": "insufficient_bolts",
        "bolt_count": n,
        "wall_length_units": None,
        "distances_units": None,
        "tiers": None,
        "angles_deg": None,
        "angle_source": None,
        "angle_margin_deg": None,
    }


@pytest.mark.parametrize("n", [0, 1, 2])
@pytest.mark.parametrize("with_dets", [False, True])
def test_compute_scale_too_few_bolts_is_insufficient(sample_detections, n, with_dets):
    bolts = [{"x": 0.2 + 0.05 * i, "y": 0.3, "diameter": 8.0} for i in range(n)]
    dets = sample_detections if with_dets else []

    result = compute_scale(dets, IMAGE_SIZE, bolts)

    assert result == _insufficient(n)
    assert json.loads(json.dumps(result)) == result


def test_compute_scale_ok_shape_and_rounding():
    fwd, _, px = _wall()
    bolts = _bolts_from_px(px, IMAGE_SIZE)
    dets = _dets_at_grid(fwd, HOLDS_G)

    result = compute_scale(dets, IMAGE_SIZE, bolts)

    assert set(result) == _KEYS
    assert result["status"] == "ok"
    assert result["bolt_count"] == len(bolts)
    d = result["distances_units"]
    n = len(dets)
    # Slice 8: tiers is N rows of N characters, "A" or "C" ("B" is not produced).
    assert len(result["tiers"]) == n
    assert all(isinstance(r, str) and len(r) == n and set(r) <= {"A", "C"} for r in result["tiers"])
    assert len(d) == n and all(len(row) == n for row in d)
    for i in range(n):
        assert d[i][i] == 0
        for j in range(n):
            assert d[i][j] == d[j][i]
            assert round(d[i][j], DISTANCE_DECIMALS) == d[i][j]
            if i != j:
                assert d[i][j] > 0
    wl = result["wall_length_units"]
    assert wl is None or (isinstance(wl, float) and round(wl, DISTANCE_DECIMALS) == wl)
    assert json.loads(json.dumps(result)) == result


def test_compute_scale_distances_are_true_grid_distances():
    fwd, _, px = _wall()
    dets = _dets_at_grid(fwd, HOLDS_G)

    d = np.asarray(compute_scale(dets, IMAGE_SIZE, _bolts_from_px(px, IMAGE_SIZE))["distances_units"])

    g = np.asarray(HOLDS_G)
    true = np.linalg.norm(g[:, None] - g[None], axis=2)
    off = ~np.eye(len(g), dtype=bool)
    assert np.max(np.abs(d[off] - true[off]) / true[off]) <= CLEAN_AFFINE_P95


def test_compute_scale_matches_segment_lengths_and_wall_length():
    fwd, _, px = _wall()
    bolts = _bolts_from_px(px, IMAGE_SIZE)
    dets = _dets_at_grid(fwd, HOLDS_G)
    w, h = IMAGE_SIZE

    result = compute_scale(dets, IMAGE_SIZE, bolts)

    bpx = np.array([[b["x"] * w, b["y"] * h] for b in bolts])
    lat = fit_lattice(bpx)
    cpx = np.array([[dd["centroid"]["x"] * w, dd["centroid"]["y"] * h] for dd in dets])
    ii, jj = np.triu_indices(len(dets), k=1)
    expected = segment_lengths(lat, cpx[ii], cpx[jj])
    for i, j, e in zip(ii, jj, expected):
        assert result["distances_units"][i][j] == pytest.approx(e, abs=1.0001 * 10 ** -DISTANCE_DECIMALS)
    wl = wall_length_units(lat)
    if wl is None:
        assert result["wall_length_units"] is None
    else:
        assert result["wall_length_units"] == pytest.approx(wl, abs=1.0001 * 10 ** -DISTANCE_DECIMALS)


def test_compute_scale_uses_image_size_for_px():
    # Same physical wall photographed at two resolutions: normalized bolts and
    # holds are identical, so grid-unit distances are too.
    fwd, _, px = _wall()
    bolts = _bolts_from_px(px, IMAGE_SIZE)
    dets = _dets_at_grid(fwd, HOLDS_G)

    a = compute_scale(dets, IMAGE_SIZE, bolts)
    b = compute_scale(dets, (2 * IMAGE_SIZE[0], 2 * IMAGE_SIZE[1]), bolts)

    np.testing.assert_allclose(b["distances_units"], a["distances_units"], atol=2e-3)


def test_compute_scale_anisotropic_normalization():
    # Bolts on a square grid in px for a non-square image: the normalized
    # coordinates are anisotropic and must be multiplied back by (W, H).
    size = (1600, 600)
    fwd = Affine(50.0 * np.eye(2), t=(25.0, 25.0))
    g, _ = centred_square(30, 10)
    px = fwd(g)
    dets = _dets_at_grid(fwd, [(2.0, 2.0), (22.0, 2.0), (2.0, 9.0), (22.0, 9.0)], size)

    d = np.asarray(compute_scale(dets, size, _bolts_from_px(px, size))["distances_units"])

    assert d[0][1] == pytest.approx(20.0, rel=CLEAN_AFFINE_P95)
    assert d[0][2] == pytest.approx(7.0, rel=CLEAN_AFFINE_P95)
    assert d[0][3] == pytest.approx(math.hypot(20, 7), rel=CLEAN_AFFINE_P95)


def test_compute_scale_matrix_follows_detections_order():
    fwd, _, px = _wall()
    bolts = _bolts_from_px(px, IMAGE_SIZE)
    dets = _dets_at_grid(fwd, HOLDS_G)
    perm = [3, 0, 4, 2, 1]

    a = np.asarray(compute_scale(dets, IMAGE_SIZE, bolts)["distances_units"])
    b = np.asarray(compute_scale([dets[p] for p in perm], IMAGE_SIZE, bolts)["distances_units"])

    np.testing.assert_allclose(b, a[np.ix_(perm, perm)], atol=1e-9)


def test_compute_scale_no_detections_gives_empty_matrix():
    _, _, px = _wall()

    result = compute_scale([], IMAGE_SIZE, _bolts_from_px(px, IMAGE_SIZE))

    assert result["status"] == "ok"
    assert result["distances_units"] == []


def test_compute_scale_wall_length_of_upright_wall():
    size = (900, 1500)
    fwd = Affine(np.diag([60.0, 60.0]), t=(60.0, 60.0))
    g, _ = centred_square(WALL_NX, WALL_NY)

    result = compute_scale([], size, _bolts_from_px(fwd(g), size))

    assert result["wall_length_units"] == pytest.approx(WALL_NY + 1.0, rel=WALL_REL_TOL)


def test_compute_scale_does_not_mutate_inputs(sample_detections):
    _, _, px = _wall()
    bolts = _bolts_from_px(px, IMAGE_SIZE)
    before = json.dumps([sample_detections, bolts])

    compute_scale(sample_detections, IMAGE_SIZE, bolts)

    assert json.dumps([sample_detections, bolts]) == before


# --- select_distances (unchanged) ----------------------------------------------


def test_select_distances_returns_sub_matrix_in_hold_id_order(sample_detections, sample_scale):
    result = select_distances(sample_scale, sample_detections, [3, 0, 2])

    assert result == [
        [0.0, 3.0, 6.0],
        [3.0, 0.0, 2.0],
        [6.0, 2.0, 0.0],
    ]


def test_select_distances_keeps_duplicates(sample_detections, sample_scale):
    assert select_distances(sample_scale, sample_detections, [1, 2, 1]) == [
        [0.0, 4.0, 0.0],
        [4.0, 0.0, 4.0],
        [0.0, 4.0, 0.0],
    ]


def test_select_distances_none_when_scale_has_no_distances(sample_detections, sample_scale):
    sample_scale["distances_units"] = None

    assert select_distances(sample_scale, sample_detections, [0, 1, 2]) is None


def test_select_distances_from_compute_scale_round_trip():
    fwd, _, px = _wall()
    dets = _dets_at_grid(fwd, HOLDS_G)
    s = compute_scale(dets, IMAGE_SIZE, _bolts_from_px(px, IMAGE_SIZE))

    sub = select_distances(s, dets, [2, 0])

    assert sub[0][1] == s["distances_units"][2][0]
    assert sub[1][0] == sub[0][1]
    assert sub[0][0] == sub[1][1] == 0


# --- tiers (slice 8) ----------------------------------------------------------
#
# Spec "Slice 8: confidence tiers": a distance is "A" when every one of its 16
# sample points is within 1.5 nearest-bolt spacings (about 1 grid unit) of a
# fitted bolt, "C" otherwise (part of its scale is borrowed from further away).
# `tiers` is N rows of N chars. On a full lattice no point is more than 0.5
# units from a bolt, so every distance is A; a large bolt-free block (holds or
# volumes hiding the bolts) makes any segment through it C.


def _norm_tiers(rows):
    return None if rows is None else ["".join(r) for r in rows]


def _block_removed_wall(lo=5.0, hi=13.0):
    fwd, g, px = _wall()
    keep = ~((g[:, 0] >= lo) & (g[:, 0] <= hi) & (g[:, 1] >= lo) & (g[:, 1] <= hi))
    return fwd, g[keep], px[keep]


def test_tiers_short_line_on_full_lattice_is_a():
    fwd, _, px = _wall()
    holds = [(4.0, 7.5), (5.0, 7.5), (4.5, 8.5)]
    dets = _dets_at_grid(fwd, holds)

    result = compute_scale(dets, IMAGE_SIZE, _bolts_from_px(px, IMAGE_SIZE))

    assert result["tiers"] == ["AAA", "AAA", "AAA"]


def test_tiers_every_pair_on_a_full_lattice_is_a():
    fwd, _, px = _wall()
    dets = _dets_at_grid(fwd, HOLDS_G)

    result = compute_scale(dets, IMAGE_SIZE, _bolts_from_px(px, IMAGE_SIZE))

    n = len(HOLDS_G)
    assert result["tiers"] == ["A" * n] * n


def test_tiers_segment_crossing_a_large_bolt_free_block_is_c():
    fwd, g, px = _block_removed_wall()
    assert len(g) > 100  # plenty of bolts left around the block
    holds = [
        (3.0, 9.0),    # 0: left of the block
        (15.0, 9.0),   # 1: right of the block; 0-1 crosses 8 units of bare wall
        (14.5, 2.0),   # 2: top right, far from the block
        (16.0, 3.0),   # 3: 2-3 is a short line on intact lattice
    ]
    dets = _dets_at_grid(fwd, holds)

    result = compute_scale(dets, IMAGE_SIZE, _bolts_from_px(px, IMAGE_SIZE))

    assert result["status"] == "ok"
    t = result["tiers"]
    assert t[0][1] == "C" and t[1][0] == "C"
    assert t[2][3] == "A" and t[3][2] == "A"
    assert set("".join(t)) <= {"A", "C"}


def test_tiers_are_symmetric_and_follow_detections_order():
    fwd, g, px = _block_removed_wall()
    holds = [(3.0, 9.0), (15.0, 9.0), (14.5, 2.0), (16.0, 3.0), (2.0, 15.0)]
    bolts = _bolts_from_px(px, IMAGE_SIZE)
    dets = _dets_at_grid(fwd, holds)
    perm = [3, 0, 4, 2, 1]

    a = compute_scale(dets, IMAGE_SIZE, bolts)["tiers"]
    b = compute_scale([dets[p] for p in perm], IMAGE_SIZE, bolts)["tiers"]

    n = len(holds)
    for i in range(n):
        for j in range(n):
            assert a[i][j] == a[j][i]
            assert b[i][j] == a[perm[i]][perm[j]]


def test_tiers_do_not_change_distances():
    # Tiers only label; the distances are the slice 7 ones (re-derived here
    # from segment_lengths like test_compute_scale_matches_segment_lengths).
    fwd, _, px = _wall()
    bolts = _bolts_from_px(px, IMAGE_SIZE)
    dets = _dets_at_grid(fwd, HOLDS_G)

    result = compute_scale(dets, IMAGE_SIZE, bolts)

    assert result["tiers"] is not None and result["distances_units"] is not None
    g = np.asarray(HOLDS_G)
    true = np.linalg.norm(g[:, None] - g[None], axis=2)
    off = ~np.eye(len(g), dtype=bool)
    d = np.asarray(result["distances_units"])
    assert np.max(np.abs(d[off] - true[off]) / true[off]) <= CLEAN_AFFINE_P95


def test_tiers_empty_detections_give_empty_tiers_or_none():
    _, _, px = _wall()

    result = compute_scale([], IMAGE_SIZE, _bolts_from_px(px, IMAGE_SIZE))

    assert result["status"] == "ok"
    assert result["tiers"] in ([], None)


# --- select_tiers (slice 8) ---------------------------------------------------
# conftest's sample_scale tiers: ["AACA", "AACC", "CCAA", "ACAA"]; the C pairs
# are (0,2), (1,2), (1,3).


def test_select_tiers_returns_sub_matrix_in_hold_id_order(sample_detections, sample_scale):
    result = select_tiers(sample_scale, sample_detections, [3, 0, 2])

    assert _norm_tiers(result) == ["AAA", "AAC", "ACA"]


def test_select_tiers_ordering_follows_pick_order(sample_detections, sample_scale):
    forward = _norm_tiers(select_tiers(sample_scale, sample_detections, [0, 2]))
    backward = _norm_tiers(select_tiers(sample_scale, sample_detections, [2, 0]))

    assert forward == ["AC", "CA"]
    assert backward == ["AC", "CA"]  # symmetric pair, diagonal A
    # An asymmetric pick order where position matters:
    assert _norm_tiers(select_tiers(sample_scale, sample_detections, [1, 3, 2])) == ["ACC", "CAA", "CAA"]
    assert _norm_tiers(select_tiers(sample_scale, sample_detections, [2, 3, 1])) == ["AAC", "AAC", "CCA"]


def test_select_tiers_keeps_duplicates(sample_detections, sample_scale):
    assert _norm_tiers(select_tiers(sample_scale, sample_detections, [1, 2, 1])) == ["ACA", "CAC", "ACA"]


def test_select_tiers_agrees_with_select_distances_shape(sample_detections, sample_scale):
    ids = [3, 0, 2, 1]

    tiers = select_tiers(sample_scale, sample_detections, ids)
    dist = select_distances(sample_scale, sample_detections, ids)

    assert len(tiers) == len(dist) == len(ids)
    assert all(len(r) == len(ids) for r in tiers)


def test_select_tiers_none_when_scale_has_no_tiers(sample_detections, sample_scale):
    sample_scale["tiers"] = None

    assert select_tiers(sample_scale, sample_detections, [0, 1, 2]) is None


def test_select_tiers_does_not_mutate_scale(sample_detections, sample_scale):
    before = json.dumps(sample_scale)

    select_tiers(sample_scale, sample_detections, [3, 0, 2])

    assert json.dumps(sample_scale) == before


def test_select_tiers_from_compute_scale_round_trip():
    fwd, g, px = _block_removed_wall()
    dets = _dets_at_grid(fwd, [(3.0, 9.0), (15.0, 9.0), (14.5, 2.0), (16.0, 3.0)])
    s = compute_scale(dets, IMAGE_SIZE, _bolts_from_px(px, IMAGE_SIZE))

    sub = _norm_tiers(select_tiers(s, dets, [1, 0]))

    assert sub[0][1] == s["tiers"][1][0] == "C"
    assert sub[1][0] == s["tiers"][0][1]


# --- reference photos (slow) ---------------------------------------------------
#
# Spec slice 4 done-when: held-out in-panel bolt pairs p95 <= 7%. Ground truth
# is index_lattice's integer coordinates within one connected patch (patches
# stand in for panels until slices 6–8). "Leave-own-J-out" (the spec's headline):
# fit on all bolts, then drop the held-out bolts' own J, which mirrors
# measuring between holds. Only pairs >= 2 units apart are scored, so centroid
# jitter on the ~1 unit pitch doesn't dominate.

REF_HELD_OUT_FRACTION = 0.2
REF_MIN_PAIR_UNITS = 2.0
# 10 random 20% hold-outs; IMG_7502 fits only ~94 bolts split into patches of
# 31/19/18/11, so a 50-pair floor is what a fair sample there can reach.
REF_REPEATS = 10
REF_MIN_SCORED_PAIRS = 50


def _ref_marks(name):
    import test_bolts

    return test_bolts._reference_skip(name)


def _subset(lat, mask):
    # Spec (slice 7 contract): Lattice.take(mask) subsets every per-bolt field,
    # including panel and grid, and the subset's panel homographies are fitted
    # from the bolts it keeps, so leave-own-J-out stays honest.
    return lat.take(np.asarray(mask, bool))


@pytest.mark.parametrize(
    "name",
    [pytest.param(p, marks=_ref_marks(p)) for p in ["IMG_7500.jpeg", "IMG_7502.jpeg", "IMG_7503.jpeg", "IMG_7504.jpeg"]],
)
def test_reference_photo_held_out_bolt_pairs_p95(name):
    import test_bolts

    _, _, found = test_bolts._run_reference(name)
    _, lat = _reference_fit(name.removesuffix(".jpeg"))
    coords, comp = index_lattice(lat)
    coords, comp = np.asarray(coords, float), np.asarray(comp)
    rng = np.random.default_rng(0)

    errs = []
    for _ in range(REF_REPEATS):
        held = rng.random(len(lat.xy)) < REF_HELD_OUT_FRACTION
        sub = _subset(lat, ~held)
        idx = np.flatnonzero(held)
        ii, jj = np.meshgrid(idx, idx, indexing="ij")
        ii, jj = ii.ravel(), jj.ravel()
        true = np.linalg.norm(coords[ii] - coords[jj], axis=1)
        ok = (ii < jj) & (comp[ii] == comp[jj]) & (true >= REF_MIN_PAIR_UNITS)
        ii, jj, true = ii[ok], jj[ok], true[ok]
        pred = np.asarray(segment_lengths(sub, np.asarray(lat.xy)[ii], np.asarray(lat.xy)[jj]))
        errs.append(np.abs(pred - true) / true)
    errs = np.concatenate(errs)

    assert len(errs) >= REF_MIN_SCORED_PAIRS, f"{name}: only {len(errs)} scored pairs"
    p95 = float(np.percentile(errs, 95))
    print(f"{name}: fitted={len(lat.xy)}/{len(found)} pairs={len(errs)} p50={np.median(errs):.3f} p95={p95:.3f}")
    assert p95 <= DEGRADED_P95, f"{name}: held-out bolt-pair p95 = {p95:.3f}"


@pytest.mark.parametrize("name", [pytest.param("IMG_7500.jpeg", marks=_ref_marks("IMG_7500.jpeg"))])
def test_reference_photo_compute_scale_is_ok(name):
    import test_bolts

    size, dets, found = test_bolts._run_reference(name)

    result = compute_scale(dets, size, found)

    assert result["status"] == "ok"
    assert result["bolt_count"] == len(found)
    assert result["wall_length_units"] is not None and result["wall_length_units"] > 5
    assert len(result["distances_units"]) == len(dets)


# --- reference photos: shared helpers for the in-panel / cross-seam tests -------
#
# In-panel = both bolts inside the same outline in panels.json; cross-seam =
# both bolts in outlines, but two different ones. Reach range = true distance
# 1.5-12.5 grid units (30-250 cm at 20 cm). Leave-own-J-out with a 5-fold
# partition (each bolt held out once), as in the spec's accuracy tables; the
# fold draw is pooled over REGRESSION_SEEDS partitions, because one draw moves
# p95 by ~0.3 points (IMG_7502: 1.6-3.1% per draw since slice 7).

REGRESSION_SEEDS = 8
REGRESSION_FOLDS = 5
REACH_RANGE_UNITS = (1.5, 12.5)
OUTLINED_PHOTOS = ["IMG_7500", "IMG_7502", "IMG_7503", "IMG_7504"]


def _in_polygon(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _outlines(photo):
    import test_bolts

    panels_path = test_bolts.KNOWN / "panels.json"
    if not panels_path.exists():
        pytest.skip("panels.json reference data missing")
    return json.loads(panels_path.read_text(encoding="utf-8"))[photo]


def _outline_of(xy, size, outlines):
    """Index of the panels.json outline each px point lies in, -1 for none."""
    w, h = size
    polys = [e["polygon"] for e in outlines]
    pts = np.asarray(xy, float).reshape(-1, 2)
    return np.array([next((k for k, poly in enumerate(polys) if _in_polygon(x / w, y / h, poly)), -1) for x, y in pts], int)


_REFERENCE_FITS = {}


def _reference_fit(photo):
    """(image size, Lattice) for a reference photo, fitted once per session."""
    import test_bolts

    if photo not in _REFERENCE_FITS:
        (w, h), _, found = test_bolts._run_reference(f"{photo}.jpeg")
        px = np.array([[b["x"] * w, b["y"] * h] for b in found]).reshape(-1, 2)
        _REFERENCE_FITS[photo] = ((w, h), fit_lattice(px))
    return _REFERENCE_FITS[photo]


def _reach_pairs(coords, comp, outline, kind):
    """Bolt pairs (i < j) in one index_lattice component, both in an outline,
    with a reach-range true distance. kind: "in" (same outline) or "cross"."""
    coords, comp, outline = np.asarray(coords, float), np.asarray(comp), np.asarray(outline)
    ii, jj = np.triu_indices(len(coords), k=1)
    true = np.linalg.norm(coords[ii] - coords[jj], axis=1)
    lo, hi = REACH_RANGE_UNITS
    ok = (comp[ii] == comp[jj]) & (outline[ii] >= 0) & (outline[jj] >= 0) & (true >= lo) & (true <= hi)
    ok &= (outline[ii] == outline[jj]) if kind == "in" else (outline[ii] != outline[jj])
    return ii[ok], jj[ok], true[ok]


def _leave_own_j_out(lat, ia, ib, true, fold_key=None):
    """Relative errors of held-out pairs (ia, ib index lat's bolts), pooled over
    REGRESSION_SEEDS 5-fold partitions. A pair is scored in a fold when both its
    bolts are held out, and measured on lat.take(~held). Folds are drawn over
    fold_key (default: the bolt's own index); fold_key -1 = never held out."""
    xy = np.asarray(lat.xy)
    ia, ib, true = np.asarray(ia, int), np.asarray(ib, int), np.asarray(true, float)
    key = np.arange(len(xy)) if fold_key is None else np.asarray(fold_key, int)
    n_keys = int(key.max()) + 1 if len(key) else 0
    errs = []
    for seed in range(REGRESSION_SEEDS):
        perm = np.random.default_rng(seed).permutation(n_keys) % REGRESSION_FOLDS
        fold = np.where(key >= 0, perm[np.maximum(key, 0)], -1)
        for f in range(REGRESSION_FOLDS):
            held = fold == f
            sel = held[ia] & held[ib]
            if not sel.any():
                continue
            pred = np.asarray(segment_lengths(_subset(lat, ~held), xy[ia[sel]], xy[ib[sel]]))
            errs.append(np.abs(pred - true[sel]) / true[sel])
    return np.concatenate(errs) if errs else np.zeros(0)


# --- reference photos must not regress (slow) -----------------------------------
#
# Guards each outlined photo's in-panel reach-range p95 against a baseline
# (slice 6 done-when: within 0.5 points). Since slice 7 the pairs and their
# true distances come from a FROZEN bolt index (tests/data/
# reference_bolt_index.json: every fitted bolt's px position, index_lattice
# component and coordinates when it was frozen), not from the live fit's own
# index_lattice (human-approved, slice 6 Q3). So:
# * the scored pairs are fixed: a fit that links more of the wall doesn't add
#   new, harder pairs (the slice 6 IMG_7503 artefact), and one that links less
#   doesn't quietly drop the hard ones;
# * live bolts are matched to frozen ones by position (mutual nearest within
#   FROZEN_MATCH_SPACINGS of the frozen median nearest-bolt distance), so a few
#   bolts more or fewer from detection only lose the pairs they're in;
# * folds are drawn over the frozen index, so each pair is held out with the
#   same partners every run.
# Too few frozen bolts matched (FROZEN_MIN_MATCHED) means detection or the fit
# changed what it finds, and the guard fails rather than score a different set.
# The live ground truth is checked separately (absolute 7% bar, slice 7 tests
# in test_scale_panels.py).
#
# Re-freeze only when the ground truth itself is meant to change, with the
# human's approval: `cd backend && uv run python tests/freeze_reference_index.py`
# rewrites the JSON and prints the new REGRESSION_BASELINE_P95. Frozen
# 2026-10-20 on the slice 7 fit (ground truth = panel sites). The baselines
# are this guard's own numbers at that point; the spec's slice 7 table (one
# eval_scale draw, live pairs) gives 1.1 / 1.9 / 2.6 / 3.1%.
# IMG_7502 is guarded again: with the slice 7 ground truth its per-draw p95
# spread is 1.6-3.1% (was 9.8-17.7%), and the pooled number is steadier still.

FROZEN_INDEX_PATH = Path(__file__).resolve().parent / "data" / "reference_bolt_index.json"
FROZEN_MATCH_SPACINGS = 0.15
# Detection has given e.g. 202 vs 211 bolts on IMG_7504 across code versions
# (~5%); with 3-5% of bolts dropped at random, 89-98% of frozen bolts match.
FROZEN_MIN_MATCHED = 0.85
REGRESSION_BASELINE_P95 = {"IMG_7500": 0.0103, "IMG_7502": 0.0228, "IMG_7503": 0.024, "IMG_7504": 0.0295}
# 0.5 points; IMG_7504 gets 1.0 point (human decision, 2026-11-04): it moved
# +0.77 in 1 of 8 simulated detection changes, which is noise, not a regression.
REGRESSION_TOL = {"IMG_7500": 0.005, "IMG_7502": 0.005, "IMG_7503": 0.005, "IMG_7504": 0.01}


def _frozen_index(photo):
    if not FROZEN_INDEX_PATH.exists():
        pytest.skip("tests/data/reference_bolt_index.json missing")
    entry = json.loads(FROZEN_INDEX_PATH.read_text(encoding="utf-8"))["photos"][photo]
    b = np.asarray(entry["bolts"], float).reshape(-1, 5)  # x_px, y_px, component, coord_x, coord_y
    return tuple(entry["size"]), b[:, :2], b[:, 2].astype(int), b[:, 3:5]


def _match_bolts(live_xy, frozen_xy):
    """For each frozen bolt, the index of its live bolt (mutual nearest within
    FROZEN_MATCH_SPACINGS x the frozen median nearest-bolt distance), or -1."""
    live_xy, frozen_xy = np.asarray(live_xy, float).reshape(-1, 2), np.asarray(frozen_xy, float).reshape(-1, 2)
    out = np.full(len(frozen_xy), -1)
    if len(live_xy) == 0 or len(frozen_xy) < 2:
        return out
    dff = np.linalg.norm(frozen_xy[:, None] - frozen_xy[None], axis=2)
    np.fill_diagonal(dff, np.inf)
    tol = FROZEN_MATCH_SPACINGS * float(np.median(dff.min(axis=1)))
    d = np.linalg.norm(frozen_xy[:, None] - live_xy[None], axis=2)
    near_live, near_frozen = d.argmin(axis=1), d.argmin(axis=0)
    mutual = (near_frozen[near_live] == np.arange(len(frozen_xy))) & (d.min(axis=1) <= tol)
    out[mutual] = near_live[mutual]
    return out


def _frozen_in_panel_errors(photo, lat, size):
    """Leave-own-J-out errors of the frozen in-panel reach-range pairs on the
    live fit `lat`. Returns (errors, matched fraction of frozen bolts, number of
    frozen pairs, number of them with both bolts matched)."""
    fsize, fxy, fcomp, fcoords = _frozen_index(photo)
    assert tuple(fsize) == tuple(size), f"{photo}: frozen index is for a {fsize} image, got {size}"
    fa, fb, true = _reach_pairs(fcoords, fcomp, _outline_of(fxy, size, _outlines(photo)), "in")
    live_of = _match_bolts(lat.xy, fxy)
    fold_key = np.full(len(lat.xy), -1)
    fold_key[live_of[live_of >= 0]] = np.flatnonzero(live_of >= 0)
    both = (live_of[fa] >= 0) & (live_of[fb] >= 0)
    errs = _leave_own_j_out(lat, live_of[fa[both]], live_of[fb[both]], true[both], fold_key)
    return errs, float(np.mean(live_of >= 0)), len(fa), int(both.sum())


@pytest.mark.parametrize("photo", [pytest.param(p, marks=_ref_marks(f"{p}.jpeg")) for p in OUTLINED_PHOTOS])
def test_reference_photo_in_panel_reach_range_p95_does_not_regress(photo):
    size, lat = _reference_fit(photo)

    errs, matched, n_frozen_pairs, n_pairs = _frozen_in_panel_errors(photo, lat, size)

    p95 = float(np.percentile(errs, 95)) if len(errs) else float("nan")
    base = REGRESSION_BASELINE_P95[photo]
    print(f"{photo}: frozen bolts matched {matched:.1%}, frozen pairs {n_pairs}/{n_frozen_pairs}, scored {len(errs)}, p95={p95:.4f} (baseline {base})")
    assert matched >= FROZEN_MIN_MATCHED, f"{photo}: only {matched:.0%} of frozen bolts found again; detection or the fit changed, re-freeze with the human's approval"
    assert len(errs) >= REF_MIN_SCORED_PAIRS * REGRESSION_SEEDS, f"{photo}: only {len(errs)} scored pairs"
    tol = REGRESSION_TOL[photo]
    assert p95 <= base + tol, f"{photo}: p95 {p95:.4f} regressed past baseline {base:.4f} + {tol * 100:.1f} points"
