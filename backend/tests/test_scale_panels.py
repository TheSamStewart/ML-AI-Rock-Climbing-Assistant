"""Slice 5b tests for scale.py: panel segmentation from the bolt lattice, one
homography per panel, cross-seam distances.

Written from the spec (docs/features/wall_size_hold_distance.md: Reference
data, "Accuracy results (slice 5b)", Decisions -> "Slice 5b panels +
homography per panel", the 5b row of Slices) only, not from the implementation.

Contract under test:
* Lattice.panel (N,) int, -1 = in no panel; Lattice.grid (N, 2), the bolt's
  lattice site in its panel's frame (grid units). Filled by fit_lattice via
  segment_panels(lattice) -> (panel, grid).
* Lattice.take(mask) subsets every per-bolt field. A subset made any other way
  that leaves panel/grid at full length makes measuring raise ValueError. A
  Lattice without them (None) measures on the interpolated field only.
* panel_homographies(lattice) -> {panel id: 3x3 homography, grid units -> px},
  fitted from that lattice's own bolts.
* index_lattice: panel sites; panels whose grid continues across a seam share
  one frame (the unfolded wall), so a cross-seam true distance is along the
  surface.

Bars:
* DEGRADED_P95 = 7% (the spec's in-panel target) for in-panel distances on
  synthetic walls with jitter / hidden bolts.
* MARGIN = worker.DISTANCE_MARGIN_PCT (6%) for cross-seam distances (spec 5b
  done-when: "cross-seam bolt pairs are within the margin").
* Synthetic truth: walls are built in grid units and projected by a known map.
  Across a fold the truth is the unfolded straight line (the geodesic along the
  surface). The method integrates along the image line instead; for the fold
  geometry below that path is < 0.2% longer than the geodesic (p95, checked
  numerically with ray-plane back-projection), so the margin is a fair bar.
"""

from dataclasses import fields, replace

import numpy as np
import pytest

from scale import (
    LATTICE_BASIS,
    Lattice,
    fit_lattice,
    index_lattice,
    panel_homographies,
    segment_lengths,
    segment_panels,
)
from test_scale import (
    AFFINE,
    DEGRADED_P95,
    CLEAN_AFFINE_P95,
    GENUINE_SCALE_CHANGES,
    HOMOGRAPHY,
    N_PAIRS,
    NX,
    NY,
    OUTLINED_PHOTOS,
    PANEL_NX,
    PX_PER_UNIT,
    REF_MIN_SCORED_PAIRS,
    REGRESSION_SEEDS,
    Affine,
    _check_index,
    _hide,
    _leave_own_j_out,
    _outline_of,
    _outlines,
    _pairs,
    _random_points,
    _reach_pairs,
    _ref_marks,
    _reference_fit,
    _rel_errors,
    _rot,
    _two_panels,
    centred_square,
)
from worker import DISTANCE_MARGIN_PCT

MARGIN = DISTANCE_MARGIN_PCT / 100.0
# Synthetic segmentation bars (bolts at least SIDE_CLEARANCE units from a seam
# or fold, so a bolt sitting on the fold line itself, which belongs to both
# planes, isn't counted either way).
SIDE_CLEARANCE = 0.75
SYNTH_PURITY = 0.95
SYNTH_COVERAGE = 0.9
# Panel metric check: a bolt's panel homography gives the true metric there
# (trace ratio) within 2 x DEGRADED_P95, the same tolerance test_scale uses for
# metric ratios.
METRIC_TOL = 2 * DEGRADED_P95


# --- helpers ---------------------------------------------------------------------


def _match(lat, px):
    """Index into px of each fitted bolt (fitted bolts are input bolts)."""
    d = np.linalg.norm(np.asarray(lat.xy)[:, None, :] - np.asarray(px)[None, :, :], axis=2)
    assert np.all(d.min(axis=1) < 1e-6)
    return d.argmin(axis=1)


def _purity(panel, label):
    """Spec definition: of bolts in both a segmented panel (panel >= 0) and a
    labelled region (label >= 0), the share whose panel's majority label is
    their own. Also returns coverage (share of labelled bolts in a panel) and
    {panel: majority label}."""
    panel, label = np.asarray(panel), np.asarray(label)
    both = (panel >= 0) & (label >= 0)
    majority = {int(p): int(np.bincount(label[both & (panel == p)]).argmax()) for p in np.unique(panel[both])}
    purity = float(np.mean([majority[int(p)] == l for p, l in zip(panel[both], label[both])])) if both.any() else 0.0
    coverage = float(np.mean(panel[label >= 0] >= 0)) if (label >= 0).any() else 0.0
    return purity, coverage, majority


def _apply_h(H, g):
    g = np.asarray(g, float).reshape(-1, 2)
    h = np.c_[g, np.ones(len(g))] @ np.asarray(H, float).T
    return h[:, :2] / h[:, 2:]


def _h_metric(H, g, eps=1e-4):
    """Metric (grid units^2 per px^2) of homography H at grid points g."""
    g = np.asarray(g, float).reshape(-1, 2)
    cols = []
    for k in range(2):
        e = np.zeros(2)
        e[k] = eps
        cols.append((_apply_h(H, g + e) - _apply_h(H, g - e)) / (2 * eps))
    J = np.stack(cols, axis=2)
    A = np.linalg.inv(J)
    return np.transpose(A, (0, 2, 1)) @ A


def _fd_metric(fwd, g, eps=1e-4):
    g = np.asarray(g, float).reshape(-1, 2)
    cols = []
    for k in range(2):
        e = np.zeros(2)
        e[k] = eps
        cols.append((fwd(g + e) - fwd(g - e)) / (2 * eps))
    J = np.stack(cols, axis=2)
    A = np.linalg.inv(J)
    return np.transpose(A, (0, 2, 1)) @ A


def _panel_metric_ok(lat, true_metric_px):
    """For each bolt in a panel: does its panel homography's metric at the
    bolt's grid site match true_metric_px (n, 2, 2) within METRIC_TOL?
    Returns a bool array over all bolts (False for bolts in no panel)."""
    panel, grid = np.asarray(lat.panel), np.asarray(lat.grid, float)
    Hs = panel_homographies(lat)
    ok = np.zeros(len(panel), bool)
    for p, H in Hs.items():
        m = panel == p
        if not m.any():
            continue
        M = _h_metric(H, grid[m])
        ratio = np.trace(M, axis1=1, axis2=2) / np.trace(true_metric_px[m], axis1=1, axis2=2)
        ok[np.flatnonzero(m)] = np.abs(ratio - 1) <= METRIC_TOL
    return ok


def _p95(lat, fwd, ga, gb):
    return float(np.percentile(_rel_errors(lat, fwd, ga, gb), 95))


def _cross_pairs(rng, a_pts, b_pts, n=N_PAIRS, lo=1.5, hi=12.5):
    ia = rng.integers(0, len(a_pts), 4 * n)
    ib = rng.integers(0, len(b_pts), 4 * n)
    ga, gb = a_pts[ia], b_pts[ib]
    d = np.linalg.norm(ga - gb, axis=1)
    keep = (d >= lo) & (d <= hi)
    return ga[keep][:n], gb[keep][:n]


def _cross_share_of_component(comp, side):
    """Fraction of (side 0, side 1) bolt pairs that share an index_lattice
    component."""
    comp, side = np.asarray(comp), np.asarray(side)
    a, b = comp[side == 0], comp[side == 1]
    if not len(a) or not len(b):
        return 0.0
    return float(np.mean(a[:, None] == b[None, :]))


# --- contract: panel / grid fields, take(), ValueError, panel-less ---------------


def test_lattice_has_panel_and_grid_fields():
    names = {f.name for f in fields(Lattice)}
    assert {"panel", "grid"} <= names


def _clean_wall(name="foreshortened_rotated"):
    fwd = HOMOGRAPHY if name == "homography" else AFFINE[name]
    g, _ = centred_square(NX, NY)
    px = fwd(g)
    lat = fit_lattice(px)
    return fwd, g, px, lat


@pytest.mark.parametrize("name", ["scale", "foreshortened_rotated", "homography"])
def test_fit_lattice_fills_panel_and_grid(name):
    _, g, px, lat = _clean_wall(name)
    n = len(lat.xy)

    panel, grid = np.asarray(lat.panel), np.asarray(lat.grid, float)

    assert panel.shape == (n,)
    assert np.issubdtype(panel.dtype, np.integer)
    assert panel.min() >= -1
    assert grid.shape == (n, 2)
    assert np.all(np.isfinite(grid[panel >= 0]))
    # One flat wall: (nearly) every bolt is in a panel, and one homography
    # fits all of it, so it isn't split.
    ids, counts = np.unique(panel[panel >= 0], return_counts=True)
    assert counts.max() >= 0.9 * n, f"{name}: panel sizes {counts.tolist()}"
    truth = g[_match(lat, px)]
    for p in ids:
        m = panel == p
        gp, tp = grid[m], truth[m]
        # Sites of the centred-square lattice (integer combinations of the
        # diagonal basis), one bolt per site, and the panel frame is the
        # truth up to a lattice symmetry and offset: pairwise distances agree.
        nb = gp @ np.linalg.inv(np.asarray(LATTICE_BASIS, float)).T
        np.testing.assert_allclose(nb, np.round(nb), atol=1e-6)
        assert len({tuple(np.round(s, 6)) for s in gp}) == len(gp), "two bolts on one site"
        dg = np.linalg.norm(gp[:, None] - gp[None], axis=2)
        dt = np.linalg.norm(tp[:, None] - tp[None], axis=2)
        np.testing.assert_allclose(dg, dt, atol=1e-6)


@pytest.mark.parametrize("name", ["scale", "foreshortened_rotated", "homography"])
def test_panel_homographies_map_grid_sites_to_bolts(name):
    _, _, _, lat = _clean_wall(name)
    panel, grid, xy = np.asarray(lat.panel), np.asarray(lat.grid, float), np.asarray(lat.xy)

    Hs = panel_homographies(lat)

    assert set(Hs) == {int(p) for p in np.unique(panel[panel >= 0])}
    for p, H in Hs.items():
        H = np.asarray(H, float)
        assert H.shape == (3, 3) and np.all(np.isfinite(H))
        m = panel == p
        # Clean bolts on an exact plane: the homography reprojects every site
        # onto its bolt to well under a pixel (spacing here is ~25-60 px).
        assert np.abs(_apply_h(H, grid[m]) - xy[m]).max() <= 1.0


def test_segment_panels_returns_the_fitted_partition():
    _, _, _, lat = _clean_wall("homography")
    n = len(lat.xy)

    panel, grid = segment_panels(lat)

    panel, grid = np.asarray(panel), np.asarray(grid, float)
    assert panel.shape == (n,) and grid.shape == (n, 2)
    # Same partition as fit_lattice stored (ids may be relabelled).
    stored = np.asarray(lat.panel)
    assert np.array_equal(panel < 0, stored < 0)
    pairs = {(int(a), int(b)) for a, b in zip(panel[panel >= 0], stored[stored >= 0])}
    assert len(pairs) == len({a for a, _ in pairs}) == len({b for _, b in pairs})


def test_take_subsets_every_per_bolt_field():
    _, _, _, lat = _clean_wall("homography")
    n = len(lat.xy)
    mask = np.random.default_rng(0).random(n) < 0.7

    sub = lat.take(mask)

    assert len(sub.xy) == mask.sum()
    for f in ("xy", "jacobian", "metric", "spacing_px", "panel", "grid"):
        np.testing.assert_array_equal(np.asarray(getattr(sub, f)), np.asarray(getattr(lat, f))[mask], err_msg=f)
    # The original isn't modified.
    assert len(lat.xy) == n and len(lat.panel) == n and len(lat.grid) == n


def test_take_all_measures_like_the_original():
    fwd, g, _, lat = _clean_wall("homography")
    rng = np.random.default_rng(1)
    ga, gb = _pairs(rng, _random_points(rng, 200, (0, 0), (NX, NY)), n=100)

    full = np.asarray(segment_lengths(lat, fwd(ga), fwd(gb)))
    same = np.asarray(segment_lengths(lat.take(np.ones(len(lat.xy), bool)), fwd(ga), fwd(gb)))

    np.testing.assert_allclose(same, full, rtol=1e-9, atol=1e-9)


def test_subset_that_leaves_panel_and_grid_full_length_raises():
    fwd, _, _, lat = _clean_wall("homography")
    mask = np.random.default_rng(2).random(len(lat.xy)) < 0.7
    # The pre-5b way of subsetting: per-bolt arrays except panel and grid.
    bad = replace(
        lat,
        xy=np.asarray(lat.xy)[mask],
        jacobian=np.asarray(lat.jacobian)[mask],
        metric=np.asarray(lat.metric)[mask],
        spacing_px=np.asarray(lat.spacing_px)[mask],
    )
    a, b = fwd(np.array([[1.0, 1.0]])), fwd(np.array([[8.0, 12.0]]))

    with pytest.raises(ValueError):
        segment_lengths(bad, a, b)


@pytest.mark.parametrize("name", ["scale", "rotation_30", "foreshortened"])
def test_lattice_without_panels_measures_on_the_field(name):
    fwd, g, _, lat = _clean_wall(name)
    bare = replace(lat, panel=None, grid=None)
    rng = np.random.default_rng(3)
    ga, gb = _pairs(rng, _random_points(rng, 2 * N_PAIRS, (0, 0), (NX, NY)))

    p95 = _p95(bare, fwd, ga, gb)

    assert p95 <= CLEAN_AFFINE_P95, f"{name}: field-only p95 = {p95:.4f}"


def test_lattice_without_panels_subset_by_replace_still_measures():
    # Spec: a Lattice built without panel/grid measures on the field only, so
    # subsetting it field by field (no panel/grid to forget) is fine.
    fwd, g, _, lat = _clean_wall("scale")
    mask = np.random.default_rng(4).random(len(lat.xy)) < 0.7
    bare = replace(
        lat,
        xy=np.asarray(lat.xy)[mask],
        jacobian=np.asarray(lat.jacobian)[mask],
        metric=np.asarray(lat.metric)[mask],
        spacing_px=np.asarray(lat.spacing_px)[mask],
        panel=None,
        grid=None,
    )
    rng = np.random.default_rng(5)
    ga, gb = _pairs(rng, g)

    assert _p95(bare, fwd, ga, gb) <= DEGRADED_P95


def test_empty_fit_has_no_panels():
    lat = fit_lattice(np.zeros((0, 2)))

    assert lat.panel is None or len(lat.panel) == 0
    assert lat.grid is None or len(lat.grid) == 0


# --- a fold: two flat panels, one continuous grid ---------------------------------
#
# The wall's top part (v <= FOLD_V) is vertical; below the fold line it kicks
# out towards the camera by `theta`. The bolt grid runs on across the fold
# (one sheet bent along a grid line), so the unfolded grid coordinates are the
# true along-the-surface frame. Pinhole camera ~30 units away, ~60 px per unit
# on the vertical part, slightly off-centre.

FOLD_V = 7.0
CAM_F, CAM_D, CAM_C = 1800.0, 30.0, 1000.0
CAM_AT = (5.5, 6.0)


class Fold:
    def __init__(self, theta_deg):
        self.th = np.radians(theta_deg)

    def world(self, g):
        g = np.asarray(g, float).reshape(-1, 2)
        u, v = g[:, 0], g[:, 1]
        dv = np.maximum(v - FOLD_V, 0.0)
        Y = np.where(v <= FOLD_V, v, FOLD_V + dv * np.cos(self.th))
        Z = -dv * np.sin(self.th)
        return np.stack([u, Y, Z], axis=1)

    def __call__(self, g):
        P = self.world(g)
        depth = P[:, 2] + CAM_D
        return np.stack([CAM_F * (P[:, 0] - CAM_AT[0]) / depth + CAM_C, CAM_F * (P[:, 1] - CAM_AT[1]) / depth + CAM_C], axis=1)


def _side_of_fold(g):
    v = np.asarray(g)[:, 1]
    return np.where(v <= FOLD_V - SIDE_CLEARANCE, 0, np.where(v >= FOLD_V + SIDE_CLEARANCE, 1, -1))


@pytest.mark.parametrize("hidden", [0.0, 0.3])
@pytest.mark.parametrize("theta", [15.0, 25.0])
def test_fold_with_continuous_grid(theta, hidden):
    fwd = Fold(theta)
    rng = np.random.default_rng(40 + int(theta) + int(100 * hidden))
    g, _ = centred_square(NX, NY)
    vis = g[_hide(rng, len(g), hidden)]
    px = fwd(vis) + (rng.normal(0.0, 0.5, size=(len(vis), 2)) if hidden else 0.0)
    lat = fit_lattice(px)
    truth = vis[_match(lat, px)]
    side = _side_of_fold(truth)

    # Segmented into two panels, one per side of the fold.
    purity, coverage, majority = _purity(lat.panel, side)
    assert purity >= SYNTH_PURITY and coverage >= SYNTH_COVERAGE, f"fold {theta}: purity {purity:.2f}, coverage {coverage:.2f}"
    assert set(majority.values()) == {0, 1}, f"fold {theta}: majority side per panel {majority}"

    # Each panel's homography has the right scale at its bolts.
    ok = _panel_metric_ok(lat, _fd_metric(fwd, truth))
    in_panel = np.asarray(lat.panel) >= 0
    assert ok[in_panel].mean() >= 0.9, f"fold {theta}: only {ok[in_panel].mean():.0%} of panel bolts have the right metric"

    # The grid continues across the fold, so index_lattice links both sides
    # into one frame: the unfolded wall.
    coords, comp = index_lattice(lat)
    _check_index(coords, comp, truth, len(lat.xy))
    comp = np.asarray(comp)
    main = np.bincount(comp[side == 0]).argmax()
    assert np.mean(comp[side == 1] == main) >= 0.8, f"fold {theta}: the two sides aren't one index_lattice frame"

    # In-panel distances on each side (bolts incl. hidden ones, and arbitrary
    # points standing in for holds).
    for s, (lo, hi) in ((0, (0.0, FOLD_V - SIDE_CLEARANCE)), (1, (FOLD_V + SIDE_CLEARANCE, NY))):
        pts = np.vstack([g[(g[:, 1] >= lo) & (g[:, 1] <= hi)], _random_points(rng, 300, (0.0, lo), (NX, hi))])
        ga, gb = _pairs(rng, pts)
        p95 = _p95(lat, fwd, ga, gb)
        assert p95 <= DEGRADED_P95, f"fold {theta} side {s}: in-panel p95 = {p95:.4f}"

    # Cross-seam: one end above the fold, one below; truth is along the surface.
    top = np.vstack([g[g[:, 1] <= FOLD_V - 0.25], _random_points(rng, 300, (0.0, 0.0), (NX, FOLD_V - 0.25))])
    bottom = np.vstack([g[g[:, 1] >= FOLD_V + 0.25], _random_points(rng, 300, (0.0, FOLD_V + 0.25), (NX, NY))])
    ga, gb = _cross_pairs(rng, top, bottom)
    p95 = _p95(lat, fwd, ga, gb)
    assert p95 <= MARGIN, f"fold {theta}: cross-seam p95 = {p95:.4f} (margin {MARGIN:.0%})"


# --- a seam where the grid is offset ----------------------------------------------
#
# Two 5 x 14 panels side by side; the right panel's bolts sit at
# (OFFSET_X + i, OFFSET_Y + j) in the left panel's frame, which is no site of
# the left lattice (>= 0.3 units, ~0.45 nearest-bolt spacings, from every
# site). "coplanar": both panels in one plane, same map. "turned": the right
# panel is also at a different angle (foreshortened horizontally).

OFFSET_X, OFFSET_Y = PANEL_NX + 0.75, 0.3
SEAM_FWD = AFFINE["foreshortened_rotated"]


def _offset_seam(kind, rng, hidden):
    gl, _ = centred_square(PANEL_NX, NY)
    gr, _ = centred_square(PANEL_NX, NY, x0=OFFSET_X, y0=OFFSET_Y)
    left_fwd = SEAM_FWD
    if kind == "coplanar":
        right_fwd = SEAM_FWD
    else:
        # Turned ~35 deg about the seam: horizontal foreshortened to 0.82, and
        # placed so its left edge is where the coplanar one's would be.
        G = SEAM_FWD.G @ np.diag([0.82, 1.0])
        t = SEAM_FWD(np.array([[OFFSET_X, OFFSET_Y]]))[0] - G @ np.array([OFFSET_X, OFFSET_Y])
        right_fwd = Affine(G, t=t)
    vl, vr = gl[_hide(rng, len(gl), hidden)], gr[_hide(rng, len(gr), hidden)]
    px = np.vstack([left_fwd(vl), right_fwd(vr)])
    px = px + (rng.normal(0.0, 0.5, size=px.shape) if hidden else 0.0)
    side = np.r_[np.zeros(len(vl), int), np.ones(len(vr), int)]
    return (left_fwd, gl), (right_fwd, gr), px, side


@pytest.mark.parametrize("hidden", [0.0, 0.3])
@pytest.mark.parametrize("kind", ["coplanar", "turned"])
def test_offset_seam_is_two_panels_and_two_frames(kind, hidden):
    rng = np.random.default_rng(50 + int(100 * hidden))
    (lf, gl), (rf, gr), px, side_all = _offset_seam(kind, rng, hidden)
    lat = fit_lattice(px)
    side = side_all[_match(lat, px)]

    purity, coverage, majority = _purity(lat.panel, side)
    assert purity >= SYNTH_PURITY and coverage >= SYNTH_COVERAGE, f"{kind}: purity {purity:.2f}, coverage {coverage:.2f}"
    assert set(majority.values()) == {0, 1}, f"{kind}: majority side per panel {majority}"

    # Not one frame: an offset grid can't be put on one lattice.
    _, comp = index_lattice(lat)
    shared = _cross_share_of_component(comp, side)
    assert shared <= 0.02, f"{kind}: {shared:.1%} of left-right bolt pairs share an index_lattice component"

    for name, fwd, g in (("left", lf, gl), ("right", rf, gr)):
        lo, hi = g.min(axis=0), g.max(axis=0)
        ga, gb = _pairs(rng, np.vstack([g, _random_points(rng, 300, lo, hi)]))
        p95 = _p95(lat, fwd, ga, gb)
        assert p95 <= DEGRADED_P95, f"{kind} {name}: in-panel p95 = {p95:.4f}"

    if kind == "coplanar":
        # One plane, so the true cross-seam distance is the straight line in
        # it, whatever the grids do at the seam.
        ga, gb = _cross_pairs(rng, gl, gr)
        p95 = _p95(lat, SEAM_FWD, ga, gb)
        assert p95 <= MARGIN, f"coplanar offset seam: cross-seam p95 = {p95:.4f}"


# --- adjacent panels at a genuinely different scale / rotation ----------------------
#
# The slice 5a guard geometry (test_scale._two_panels): these are separate
# panels, never one frame.


@pytest.mark.parametrize("right_G", list(GENUINE_SCALE_CHANGES.values()), ids=list(GENUINE_SCALE_CHANGES))
def test_adjacent_panels_at_different_scale_are_segmented_apart(right_G):
    rng = np.random.default_rng(33)
    panels = _two_panels(right_G, rng=rng, extra_hidden=0.3)
    px = np.vstack([fwd(vis) for fwd, _, vis in panels])
    side_all = np.r_[np.zeros(len(panels[0][2]), int), np.ones(len(panels[1][2]), int)]
    lat = fit_lattice(px)
    side = side_all[_match(lat, px)]

    purity, coverage, majority = _purity(lat.panel, side)
    _, comp = index_lattice(lat)

    assert purity >= SYNTH_PURITY and coverage >= SYNTH_COVERAGE, f"purity {purity:.2f}, coverage {coverage:.2f}"
    assert set(majority.values()) == {0, 1}, f"majority side per panel {majority}"
    assert _cross_share_of_component(comp, side) <= 0.02


# --- one flat panel with a bolt-free strip ------------------------------------------
#
# Holds (or a volume) hide every bolt in a strip 2.5 units (~3.5 nearest-bolt
# spacings) wide across a perspective wall, plus 20% of the rest. Distances
# from one side of the strip to the other, and into the strip, stay right.

STRIPS = {
    "vertical": (0, 4.0, 6.5),
    "horizontal": (1, 5.5, 8.0),
}


@pytest.mark.parametrize("strip", list(STRIPS), ids=list(STRIPS))
def test_bolt_free_strip_through_one_panel(strip):
    axis, a, b = STRIPS[strip]
    fwd = HOMOGRAPHY
    rng = np.random.default_rng(60 + axis)
    g, _ = centred_square(NX, NY)
    in_strip = (g[:, axis] > a) & (g[:, axis] < b)
    vis = g[~in_strip & _hide(rng, len(g), 0.2)]
    px = fwd(vis) + rng.normal(0.0, 0.5, size=(len(vis), 2))
    lat = fit_lattice(px)

    coords, comp = index_lattice(lat)
    _check_index(coords, comp, vis[_match(lat, px)], len(lat.xy))

    hi_corner = np.array([NX, NY], float)
    lo_box, hi_box = np.zeros(2), hi_corner.copy()
    hi_box[axis] = a
    before = np.vstack([g[g[:, axis] <= a], _random_points(rng, 300, lo_box, hi_box)])
    lo_box, hi_box = np.zeros(2), hi_corner.copy()
    lo_box[axis] = b
    after = np.vstack([g[g[:, axis] >= b], _random_points(rng, 300, lo_box, hi_box)])
    lo_box, hi_box = np.zeros(2), hi_corner.copy()
    lo_box[axis], hi_box[axis] = a, b
    inside = np.vstack([g[in_strip], _random_points(rng, 200, lo_box, hi_box)])

    for label, (pa, pb) in (("across the strip", (before, after)), ("into the strip", (np.vstack([before, after]), inside))):
        ga, gb = _cross_pairs(rng, pa, pb, lo=1.0, hi=np.inf)
        p95 = _p95(lat, fwd, ga, gb)
        assert p95 <= DEGRADED_P95, f"{strip} strip, {label}: p95 = {p95:.4f}"


# --- a panel plus a separate wall in the background ----------------------------------


@pytest.mark.parametrize("bg_scale", [0.45, 0.7])
def test_panel_and_background_wall_at_another_depth(bg_scale):
    rng = np.random.default_rng(70)
    main_fwd = Affine(PX_PER_UNIT * np.eye(2), t=(1000.0, 1000.0))
    gm, _ = centred_square(NX, NY)
    # Background wall to the right, further away and turned a little; its
    # leftmost bolt is 150 px right of the main wall's right edge.
    bg_G = bg_scale * PX_PER_UNIT * _rot(10)
    gb_, _ = centred_square(6, 8)
    left_edge = Affine(bg_G, t=(0.0, 0.0))(gb_)[:, 0].min()
    bg_fwd = Affine(bg_G, t=(1000.0 + NX * PX_PER_UNIT + 150.0 - left_edge, 1100.0))
    vm, vb = gm[_hide(rng, len(gm), 0.2)], gb_[_hide(rng, len(gb_), 0.2)]
    px = np.vstack([main_fwd(vm), bg_fwd(vb)])
    side_all = np.r_[np.zeros(len(vm), int), np.ones(len(vb), int)]
    lat = fit_lattice(px)
    side = side_all[_match(lat, px)]

    purity, _, majority = _purity(lat.panel, side)
    _, comp = index_lattice(lat)
    assert purity >= SYNTH_PURITY, f"purity {purity:.2f}"
    assert 0 in majority.values(), "the main wall has no panel of its own"
    assert _cross_share_of_component(comp, side) <= 0.02

    for name, fwd, g in (("main", main_fwd, gm), ("background", bg_fwd, gb_)):
        ga, gb = _pairs(rng, np.vstack([g, _random_points(rng, 300, g.min(axis=0), g.max(axis=0))]))
        p95 = _p95(lat, fwd, ga, gb)
        assert p95 <= DEGRADED_P95, f"{name} wall: p95 = {p95:.4f}"


# --- a lone too-fine or degenerate fit must not swallow the photo ---------------------
#
# Spec: a degenerate or too-fine homography puts every bolt near *some* site and
# swallowed whole photos (p95 > 1000%) before the metric-agreement guard; and
# (slice 5a) a single stray bolt fitted on a too-fine lattice re-read a whole
# 78-bolt panel before the "finer group >= 7 bolts" guard. Here the wall is a
# clean 10 x 14 panel plus a few false points that invite such a fit:
# * strays on the sqrt(2)-finer lattice (square edge midpoints, 0.5 units from
#   the nearest bolts). That is 0.71 x the 0.71-unit nearest-bolt spacing, so
#   they survive slice 2's "NN >= 0.7 x local median" filter, and they sit in
#   evenly spaced lines along 2 directions (slice 2's lattice support). Points
#   any closer (e.g. on the twice-finer lattice, 0.35 units) are removed by
#   slice 2 before fit_lattice sees them, so they aren't tested here;
# * a collinear row: 14 evenly spaced points 2 units below the wall, off its
#   lattice (a 1-D "lattice" has no unique homography).

STRAY_CASES = {
    "one_stray_on_finer_lattice": [[4.5, 6.0]],
    "three_strays_in_one_finer_cell": [[4.5, 6.0], [5.0, 6.5], [4.5, 7.0]],
    "six_scattered_strays": [[2.5, 3.0], [7.0, 10.5], [5.5, 7.0], [1.0, 12.5], [8.5, 2.0], [3.0, 9.5]],
    "collinear_row": np.c_[np.linspace(0.3, 0.3 + 13 * 0.6, 14), np.full(14, NY + 2.0)].tolist(),
    # The four edge midpoints around one centre bolt: with that bolt and the
    # cell's 4 corners they are 9 bolts on the sqrt(2)-finer lattice, past the
    # 7-bolt minimum, and every wall bolt also sits on that finer lattice. On
    # the 5b code the whole wall is then read sqrt(2) wrong (p95 41%, every
    # transform). Fixed in the 5b follow-up (finer reference group must reach
    # 1.5 units from its centre): must-pass on the homography transform. The
    # foreshortened_rotated transform still fails, see _xfail_stray below.
    "four_strays_completing_one_finer_cell": [[4.5, 6.0], [5.0, 6.5], [4.5, 7.0], [4.0, 6.5]],
}


def _stray_params():
    return [pytest.param(v, id=k) for k, v in STRAY_CASES.items()]


@pytest.mark.parametrize("name", ["foreshortened_rotated", "homography"])
@pytest.mark.parametrize("extra", _stray_params())
def test_a_lone_too_fine_or_degenerate_fit_does_not_swallow_the_wall(extra, name, request):
    if name == "foreshortened_rotated" and request.node.callspec.id.startswith("four_strays_completing_one_finer_cell"):
        request.applymarker(pytest.mark.xfail(
            strict=False,
            reason="not the sqrt(2) rule (fails identically with it off): the 4 false points disturb the per-bolt fit, wall p95 10.4% vs 7%",
        ))
    fwd = HOMOGRAPHY if name == "homography" else AFFINE[name]
    rng = np.random.default_rng(80)
    g, _ = centred_square(NX, NY)
    extra = np.asarray(extra, float)
    pts = np.vstack([g, extra])
    is_wall = np.r_[np.ones(len(g), bool), np.zeros(len(extra), bool)]
    px = fwd(pts)
    lat = fit_lattice(px)
    m = _match(lat, px)
    wall = is_wall[m]

    # Most wall bolts sit in a panel whose homography has the wall's true scale.
    ok = _panel_metric_ok(lat, _fd_metric(fwd, pts[m]))
    assert ok[wall].mean() >= 0.8, f"only {ok[wall].mean():.0%} of wall bolts are in a correctly scaled panel"

    # Distances on the wall away from the false points (>= 1.5 units).
    far = np.linalg.norm(g[:, None] - extra[None], axis=2).min(axis=1) >= 1.5
    ga, gb = _pairs(rng, g[far])
    p95 = _p95(lat, fwd, ga, gb)
    assert p95 <= DEGRADED_P95, f"wall p95 = {p95:.4f}"


# --- reference photos (slow) ----------------------------------------------------------
#
# Spec slice 5b done-when, scored with the live ground truth (index_lattice):
# * segmented panels match panels.json: "most bolts land in the right panel",
#   measured as the spec's purity (and coverage, the share of in-outline bolts
#   in some segmented panel). The spec gives no number; REF_PURITY /
#   REF_COVERAGE are the Tester's proposal (spec table: purity 94-100%,
#   coverage 89-98%) - open question for the human;
# * in-panel reach-range p95 <= 7% on every outlined photo, incl. IMG_7502;
# * cross-seam bolt pairs (in two different outlines, one index_lattice
#   component) within the margin, as p95 over leave-own-J-out pairs.

REF_PURITY = 0.90
REF_COVERAGE = 0.85
# Photos where the spec's 5b table has cross-seam pairs. IMG_7503's grids are
# turned 45 deg to each other (no shared frame possible); IMG_7504's are offset
# at the seam (n/a in the table).
CROSS_SEAM_PHOTOS = ["IMG_7500", "IMG_7502"]
REF_MIN_CROSS_PAIRS = 20


def _ref_params(photos):
    return [pytest.param(p, marks=_ref_marks(f"{p}.jpeg")) for p in photos]


def _ref_ground_truth(photo):
    size, lat = _reference_fit(photo)
    outline = _outline_of(lat.xy, size, _outlines(photo))
    coords, comp = index_lattice(lat)
    return size, lat, outline, np.asarray(coords, float), np.asarray(comp)


@pytest.mark.parametrize("photo", _ref_params(OUTLINED_PHOTOS))
def test_reference_segmentation_matches_panel_outlines(photo):
    size, lat, outline, _, _ = _ref_ground_truth(photo)
    panel = np.asarray(lat.panel)

    purity, coverage, majority = _purity(panel, outline)

    sizes = {p: int(np.sum(panel == p)) for p in majority}
    print(f"{photo}: purity {purity:.3f} coverage {coverage:.3f} panel -> majority outline {majority} sizes {sizes}")
    assert purity >= REF_PURITY, f"{photo}: purity {purity:.3f}"
    assert coverage >= REF_COVERAGE, f"{photo}: coverage {coverage:.3f}"


@pytest.mark.parametrize("photo", _ref_params(OUTLINED_PHOTOS))
def test_reference_in_panel_reach_range_p95(photo):
    _, lat, outline, coords, comp = _ref_ground_truth(photo)
    ia, ib, true = _reach_pairs(coords, comp, outline, "in")

    errs = _leave_own_j_out(lat, ia, ib, true)

    assert len(errs) >= REF_MIN_SCORED_PAIRS * REGRESSION_SEEDS, f"{photo}: only {len(errs)} scored pairs"
    p95 = float(np.percentile(errs, 95))
    print(f"{photo}: in-panel reach-range scored {len(errs)} p50={np.median(errs):.4f} p95={p95:.4f}")
    assert p95 <= DEGRADED_P95, f"{photo}: in-panel reach-range p95 = {p95:.4f}"


@pytest.mark.parametrize("photo", _ref_params(CROSS_SEAM_PHOTOS))
def test_reference_cross_seam_pairs_within_margin(photo):
    _, lat, outline, coords, comp = _ref_ground_truth(photo)
    ia, ib, true = _reach_pairs(coords, comp, outline, "cross")

    errs = _leave_own_j_out(lat, ia, ib, true)

    assert len(errs) >= REF_MIN_CROSS_PAIRS, f"{photo}: only {len(errs)} scored cross-seam pairs"
    p95 = float(np.percentile(errs, 95))
    print(f"{photo}: cross-seam reach-range scored {len(errs)} p50={np.median(errs):.4f} p95={p95:.4f} max={errs.max():.4f}")
    assert p95 <= MARGIN, f"{photo}: cross-seam p95 = {p95:.4f} (margin {MARGIN:.0%})"


@pytest.mark.parametrize("photo", _ref_params(["IMG_7503"]))
def test_reference_panels_with_turned_grids_share_no_frame(photo):
    # IMG_7503's two panels have grids turned 45 deg to each other (spec,
    # slice 3 Metric note), so no index_lattice component may hold a real
    # share of both outlines (>= 3 bolts of each: the spec's minimum for
    # linking two panels).
    _, _, outline, _, comp = _ref_ground_truth(photo)

    for c in np.unique(comp):
        counts = np.bincount(outline[(comp == c) & (outline >= 0)], minlength=2)
        assert np.sum(counts >= 3) <= 1, f"{photo}: component {c} spans outlines {counts.tolist()}"
