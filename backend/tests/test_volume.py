"""Tests for volume.py (feature wall_size_hold_distance, slice 6b step 2).

Designed from the module's stated contract only, not from its internals:

    wall_plane(lattice, point, K, spacing_cm) -> {n, d, axis_ratio, trusted, ...}
    backproject(pixels, n, d, K)   px on a known plane -> cm points
    fit_box / fit_ridge / fit_pyramid(..., height_cm=None) -> {faces, heights, h_source, ...}
    describe_face(normal, wall_normal, gravity) -> {steepness_deg, facing_deg, facing}
    hold_face(hold_px, fit, K, n, d) -> {face_index, standoff_cm, ...}

Conventions under test (same as angle.py): camera frame x right, y down,
z forward; the wall is `n . X = d` with `n` facing the camera, so `d` is
negative and a point `h` cm proud of the wall has `n . X = d + h`.

Every scene here is built forwards from exact geometry - a wall at a known
angle, a solid of known shape and height, projected through a known pinhole -
so the truth is exact and the error is measured, not eyeballed. These are the
noise-free guarantees; mask noise, focal-length error and real volumes are the
job of `eval_volume.py` and the measured captures, not of pytest.

The central limitation is asserted rather than worked around: the outline
cannot see how far a volume stands off the wall, so `fit_pyramid` depends on
an assumed anchor and `test_pyramid_offcentre_apex_is_amplified` pins down
what that costs.
"""

import numpy as np
import pytest

import volume

# --- exact synthetic geometry ------------------------------------------------

WIDTH, HEIGHT = 1776, 3840  # the field phone's frame (field_captures/*/capture.json)
FOCAL_35MM = 26.0
FOCAL_PX = FOCAL_35MM / 43.27 * np.hypot(WIDTH, HEIGHT)
K = volume.camera_matrix((WIDTH, HEIGHT), FOCAL_PX)


def scene(wall_deg: float, pitch_deg: float, distance_cm: float = 300.0):
    """A wall at `wall_deg` from vertical (+ overhanging) seen by a camera
    pitched `pitch_deg` above horizontal.

    Returns (n, d, gravity, wall_point) where wall_point(u, v, h) is the cm
    point `u` across and `v` up the wall, standing `h` cm proud of it.
    """
    pitch = np.radians(pitch_deg)
    gravity = np.array([0.0, np.cos(pitch), -np.sin(pitch)])
    up = -gravity
    forward = np.array([0.0, 0.0, 1.0])
    horizontal = volume.unit(forward - (forward @ up) * up)
    lean = np.radians(wall_deg)
    n = volume.unit(np.cos(lean) * -horizontal + np.sin(lean) * gravity)
    centre = forward * distance_cm
    across = np.array([1.0, 0.0, 0.0])
    upwards = volume.unit(np.cross(n, across))
    if upwards @ up < 0:
        upwards = -upwards

    def wall_point(u, v, h=0.0):
        return centre + u * across + v * upwards + h * n

    return n, float(n @ centre), gravity, wall_point


def truth_normals(base, raised):
    """The camera-facing normals of the visible faces of a solid, worked out
    from the exact 3D corners rather than from the module under test."""
    raised = np.atleast_2d(raised)
    everything = np.vstack([base, raised])
    middle = everything.mean(axis=0)
    if len(raised) == 1:
        groups = [[base[i], base[(i + 1) % len(base)], raised[0]] for i in range(len(base))]
    elif len(raised) == 2:
        #A wedge: raised[0] stands over the middle of base[1]-base[2] and
        #raised[1] over the middle of base[3]-base[0].
        groups = [[base[0], base[1], raised[0], raised[1]],
                  [base[2], base[3], raised[1], raised[0]],
                  [base[1], base[2], raised[0]],
                  [base[3], base[0], raised[1]]]
    else:
        groups = [[base[i], base[(i + 1) % len(base)], raised[(i + 1) % len(raised)], raised[i]]
                  for i in range(len(base))] + [list(raised)]
    out = []
    for group in groups:
        group = np.asarray(group)
        normal = volume.unit(np.cross(group[1] - group[0], group[-1] - group[0]))
        centre = group.mean(axis=0)
        outward = normal if normal @ (centre - middle) > 0 else -normal
        if outward @ centre < 0:
            out.append(outward)
    return out


def worst_face_error_deg(fit, expected):
    """The largest angle, in degrees, between each expected face normal and
    the closest one the fit produced."""
    produced = [f for f in fit["faces"] if f["visible"]]
    assert produced, "the fit produced no visible faces"
    worst = 0.0
    for wanted in expected:
        closest = min(np.degrees(np.arccos(np.clip(f["normal"] @ volume.unit(wanted), -1.0, 1.0)))
                      for f in produced)
        worst = max(worst, float(closest))
    return worst


# --- the plane the whole method rests on -------------------------------------

@pytest.mark.parametrize("wall_deg, pitch_deg", [(0, 5), (16, 8), (30, 15), (-10, 2)])
@pytest.mark.parametrize("u, v", [(0, 0), (-60, 40), (80, -30)])
def test_backproject_inverts_project_on_the_wall(wall_deg, pitch_deg, u, v):
    """A known wall point projects to a pixel and that pixel back-projects to
    the same cm point. Everything else depends on this being exact."""
    n, d, _, wall_point = scene(wall_deg, pitch_deg)
    expected = wall_point(u, v)
    pixel = volume.project(expected.reshape(1, 3), K)
    assert np.isfinite(pixel).all()
    assert volume.backproject(pixel, n, d, K)[0] == pytest.approx(expected, abs=1e-6)


def test_backproject_rejects_a_plane_behind_the_camera():
    """A plane the rays point away from gives NaN, not a bogus point.

    Note flipping BOTH `n` and `d` describes the same plane, so the sign of
    `d` alone is what puts it behind the camera.
    """
    n, d, _, _ = scene(0, 0)
    behind = volume.backproject(np.array([[WIDTH / 2, HEIGHT / 2]]), n, -d, K)
    assert np.isnan(behind).all()


def test_fitters_return_none_for_a_non_finite_pixel():
    """A degenerate mask can hand over a NaN pixel; that has to come back as
    "no fit" rather than raising out of numpy."""
    n, d, _, wall_point = scene(16, 8)
    triangle = [(-35, -25), (35, -25), (0, 40)]
    base_px = volume.project(np.array([wall_point(*c) for c in triangle]), K)
    assert volume.fit_pyramid(base_px, np.array([np.nan, np.nan]), n, d, K) is None

    quad = np.array([wall_point(*c) for c in [(-40, -30), (40, -30), (40, 30), (-40, 30)]])
    quad_px = volume.project(quad, K)
    nan_pair = np.array([[np.nan, np.nan], [np.nan, np.nan]])
    assert volume.fit_ridge(quad_px, nan_pair, n, d, K) is None
    assert volume.fit_box(quad_px, np.full((4, 2), np.nan), n, d, K) is None


def test_height_of_and_point_at_height_agree():
    """`h` is measured towards the camera and the two helpers are inverses."""
    n, d, _, wall_point = scene(16, 8)
    on_wall = wall_point(20, -10)
    assert volume.height_of(on_wall, n, d) == pytest.approx(0.0, abs=1e-6)
    proud = wall_point(20, -10, 30.0)
    assert volume.height_of(proud, n, d) == pytest.approx(30.0, abs=1e-6)
    ray = volume.rays(volume.project(proud.reshape(1, 3), K), K)[0]
    assert volume.point_at_height(ray, n, d, 30.0) == pytest.approx(proud, abs=1e-6)


# --- the three shape families, on exact geometry -----------------------------

@pytest.mark.parametrize("wall_deg, pitch_deg, height_cm", [(0, 5, 30), (16, 8, 25), (30, 15, 40), (-10, 2, 18)])
def test_pyramid_with_a_centred_apex_is_exact(wall_deg, pitch_deg, height_cm):
    """With the apex really over the base centroid - the assumption the fitter
    makes - every face normal and the height come back exactly."""
    n, d, gravity, wall_point = scene(wall_deg, pitch_deg)
    triangle = [(-35, -25), (35, -25), (0, 40)]
    base = np.array([wall_point(*corner) for corner in triangle])
    apex = wall_point(*np.mean(triangle, axis=0), height_cm)

    fit = volume.fit_pyramid(volume.project(base, K),
                             volume.project(apex.reshape(1, 3), K)[0], n, d, K)
    assert fit is not None
    assert fit["h_source"] == "centroid-assumed"
    assert fit["heights"][0] == pytest.approx(height_cm, abs=0.1)
    assert worst_face_error_deg(fit, truth_normals(base, apex)) < 0.5


@pytest.mark.parametrize("wall_deg, pitch_deg, height_cm", [(0, 5, 30), (16, 8, 22), (-8, 3, 35)])
def test_wedge_is_exact_without_any_shape_prior(wall_deg, pitch_deg, height_cm):
    """A wedge's ridge ends stand over the midpoints of two base edges, and
    those midpoints are observed - so no assumption is involved."""
    n, d, gravity, wall_point = scene(wall_deg, pitch_deg)
    quad = [(-40, -30), (40, -30), (40, 30), (-40, 30)]
    base = np.array([wall_point(*corner) for corner in quad])
    ridge = np.array([(base[1] + base[2]) / 2 + height_cm * n,
                      (base[3] + base[0]) / 2 + height_cm * n])

    fit = volume.fit_ridge(volume.project(base, K), volume.project(ridge, K), n, d, K)
    assert fit is not None
    assert fit["h_source"] == "ridge-anchored"
    assert fit["heights"][0] == pytest.approx(height_cm, abs=0.1)
    assert fit["reprojection_px"] < 1.0
    assert worst_face_error_deg(fit, truth_normals(base, ridge)) < 0.5


@pytest.mark.parametrize("wall_deg, pitch_deg, height_cm", [(0, 5, 20), (16, 8, 30), (25, 12, 15)])
def test_box_is_exact_without_any_shape_prior(wall_deg, pitch_deg, height_cm):
    """A box's top is its base translated off the wall, so every anchor is
    observed and the single height is over-determined."""
    n, d, gravity, wall_point = scene(wall_deg, pitch_deg)
    quad = [(-35, -30), (35, -30), (35, 30), (-35, 30)]
    base = np.array([wall_point(*corner) for corner in quad])
    top = base + height_cm * n

    fit = volume.fit_box(volume.project(base, K), volume.project(top, K), n, d, K)
    assert fit is not None
    assert fit["h_source"] == "box-translate"
    assert fit["heights"][0] == pytest.approx(height_cm, abs=0.1)
    assert fit["reprojection_px"] < 1.0
    assert worst_face_error_deg(fit, truth_normals(base, top)) < 0.5


@pytest.mark.parametrize("off_axis_cm", [0, 300, 600])
def test_box_is_exact_wherever_it_sits_in_the_frame(off_axis_cm):
    """The box fit has no assumed anchor, so unlike the pyramid its accuracy
    does not depend on where in the frame the volume appears."""
    n, d, _, wall_point = scene(16, 8)
    quad = [(off_axis_cm - 35, -30), (off_axis_cm + 35, -30),
            (off_axis_cm + 35, 30), (off_axis_cm - 35, 30)]
    base = np.array([wall_point(*corner) for corner in quad])
    top = base + 20.0 * n

    fit = volume.fit_box(volume.project(base, K), volume.project(top, K), n, d, K)
    assert fit is not None
    assert fit["heights"][0] == pytest.approx(20.0, abs=0.1)


# --- the limitation, asserted rather than worked around ----------------------

def test_outline_cannot_see_how_far_a_volume_stands_off_the_wall():
    """The reason `fit_pyramid` needs an assumed anchor at all: two pyramids
    of very different heights, sharing a base and an apex PIXEL, project to
    the same outline, so no outline score can tell them apart."""
    n, d, _, wall_point = scene(16, 8)
    triangle = [(-35, -25), (35, -25), (0, 40)]
    base = np.array([wall_point(*corner) for corner in triangle])
    apex_px = volume.project(wall_point(*np.mean(triangle, axis=0), 30.0).reshape(1, 3), K)
    ray = volume.rays(apex_px, K)[0]

    low = np.vstack([base, volume.point_at_height(ray, n, d, 15.0)])
    high = np.vstack([base, volume.point_at_height(ray, n, d, 60.0)])
    assert volume.project(low, K) == pytest.approx(volume.project(high, K), abs=1e-6)


def test_pyramid_offcentre_apex_is_amplified_and_the_residual_hides_it():
    """An apex that is not really centred costs height error amplified by
    roughly 1/tan(angle between the apex ray and the wall normal), which is
    large near the middle of the frame - and the leftover reprojection
    residual does NOT reflect how wrong the height is.

    This is why `offcentre_gain` is reported and why the residual must not be
    used as the quality gate.
    """
    n, d, _, wall_point = scene(16, 8)
    triangle = [(-50, -40), (40, -40), (-50, 50)]
    base = np.array([wall_point(*corner) for corner in triangle])
    true_height = 40.0
    apex = wall_point(-25, -15, true_height)  # offset from the centroid at (-20, -10)

    fit = volume.fit_pyramid(volume.project(base, K),
                             volume.project(apex.reshape(1, 3), K)[0], n, d, K)
    assert fit is not None
    assert fit["offcentre_gain"] > 2.0, "near the optical axis the gain must be large"
    height_error = abs(fit["heights"][0] - true_height)
    assert height_error > 10.0, "an off-centre apex must show up as a large height error"
    #The point of the test: the residual is small while the height is far out.
    assert fit["reprojection_px"] < height_error


def test_height_cm_overrides_the_assumption():
    """Supplying the height from outside - a catalogue size, a shading cue or
    the user - skips the anchor assumption and is then exact."""
    n, d, _, wall_point = scene(16, 8)
    triangle = [(-50, -40), (40, -40), (-50, 50)]
    base = np.array([wall_point(*corner) for corner in triangle])
    apex = wall_point(-25, -15, 40.0)

    fit = volume.fit_pyramid(volume.project(base, K),
                             volume.project(apex.reshape(1, 3), K)[0], n, d, K, height_cm=40.0)
    assert fit is not None
    assert fit["h_source"] == "given"
    assert fit["heights"][0] == pytest.approx(40.0, abs=1e-6)
    assert worst_face_error_deg(fit, truth_normals(base, apex)) < 0.5


def test_implausible_fits_are_rejected():
    """A solid that would be a metre and a half deep, or a base the size of a
    bus, is not returned at all."""
    n, d, _, wall_point = scene(16, 8)
    triangle = [(-35, -25), (35, -25), (0, 40)]
    base = np.array([wall_point(*corner) for corner in triangle])
    far_too_deep = volume.point_at_height(
        volume.rays(volume.project(wall_point(0, 0, 1.0).reshape(1, 3), K), K)[0],
        n, d, volume.MAX_DEPTH_CM + 200.0)
    assert volume.fit_pyramid(volume.project(base, K),
                              volume.project(far_too_deep.reshape(1, 3), K)[0],
                              n, d, K, height_cm=volume.MAX_DEPTH_CM + 200.0) is None


# --- how a face is described to the climber ----------------------------------

def test_the_wall_itself_reads_as_vertical_and_facing_out():
    n, d, gravity, _ = scene(0, 0)
    described = volume.describe_face(n, n, gravity)
    assert described["steepness_deg"] == pytest.approx(0.0, abs=0.1)
    assert described["facing"] == "out"


@pytest.mark.parametrize("wall_deg", [-10, 0, 16, 30])
def test_steepness_matches_the_wall_angle_convention(wall_deg):
    """A face parallel to the wall must report the wall's own angle, with the
    same sign convention angle.py uses (+ overhanging)."""
    n, d, gravity, _ = scene(wall_deg, 8)
    assert volume.describe_face(n, n, gravity)["steepness_deg"] == pytest.approx(wall_deg, abs=0.5)


def test_a_sideways_face_reads_as_a_sidepull_not_as_vertical():
    """The reason facing is reported alongside steepness: a face turned 90
    degrees has no steepness at all but climbs like a sidepull."""
    n, d, gravity, _ = scene(0, 0)
    to_the_right = volume.unit(np.cross(n, gravity))
    right = volume.describe_face(to_the_right, n, gravity)
    left = volume.describe_face(-to_the_right, n, gravity)

    assert right["facing"] == "right"
    assert left["facing"] == "left"
    assert right["steepness_deg"] == pytest.approx(0.0, abs=0.1)
    assert right["off_wall_deg"] == pytest.approx(90.0, abs=0.5)
    assert left["facing_deg"] == pytest.approx(-right["facing_deg"], abs=0.1)


# --- what this is all for: a hold on a volume --------------------------------

def test_hold_face_reports_the_real_standoff_from_the_wall():
    """A hold on a volume face is measured on that FACE, not on the wall -
    the fix for a hold 20-30 cm proud being measured as if it were flat."""
    n, d, gravity, wall_point = scene(16, 8)
    triangle = [(-35, -25), (35, -25), (0, 40)]
    base = np.array([wall_point(*corner) for corner in triangle])
    apex = wall_point(*np.mean(triangle, axis=0), 30.0)
    fit = volume.fit_pyramid(volume.project(base, K),
                             volume.project(apex.reshape(1, 3), K)[0], n, d, K)
    assert fit is not None

    #Halfway up the first face, so a known standoff partway up the volume.
    on_face = 0.25 * base[0] + 0.25 * base[1] + 0.5 * apex
    found = volume.hold_face(volume.project(on_face.reshape(1, 3), K)[0], fit, K, n, d)
    assert found is not None
    assert found["standoff_cm"] == pytest.approx(volume.height_of(on_face, n, d), abs=0.5)


def test_hold_face_returns_nothing_for_a_hold_off_the_volume():
    n, d, gravity, wall_point = scene(16, 8)
    triangle = [(-35, -25), (35, -25), (0, 40)]
    base = np.array([wall_point(*corner) for corner in triangle])
    apex = wall_point(*np.mean(triangle, axis=0), 30.0)
    fit = volume.fit_pyramid(volume.project(base, K),
                             volume.project(apex.reshape(1, 3), K)[0], n, d, K)
    assert fit is not None

    far_away = wall_point(300, 200)
    assert volume.hold_face(volume.project(far_away.reshape(1, 3), K)[0], fit, K, n, d) is None


# --- outline reduction and ridge convergence ---------------------------------

@pytest.mark.parametrize("k", [3, 4, 5, 6])
def test_dominant_corners_returns_exactly_the_requested_count(k):
    """run_detection hands over ~14 points, far more than a volume's real
    corner count, so the fitter has to reduce them."""
    rng = np.random.default_rng(0)
    circle = np.array([[np.cos(a), np.sin(a)] for a in np.linspace(0, 2 * np.pi, 40, endpoint=False)])
    #A rounded k-gon: a polygon with k dominant corners and rounding between.
    polygon = np.array([[np.cos(a), np.sin(a)] for a in np.linspace(0, 2 * np.pi, k, endpoint=False)])
    dense = []
    for i in range(k):
        a, b = polygon[i], polygon[(i + 1) % k]
        for t in np.linspace(0, 1, 8, endpoint=False):
            dense.append(a + t * (b - a))
    dense = np.array(dense) * 400 + 800 + rng.normal(0, 0.3, (len(dense), 2))

    reduced = volume.dominant_corners(dense, k)
    assert reduced is not None
    assert len(reduced) == k
    assert circle.shape[1] == 2  # sanity on the helper above


def test_converge_point_finds_where_ridge_lines_meet():
    """A pyramid's ridges meet at its apex; that is how the apex is found when
    it projects inside the outline and is no outline vertex at all."""
    apex = np.array([640.0, 480.0])
    segments = []
    for angle in (0.3, 1.9, 3.4, 5.0):
        direction = np.array([np.cos(angle), np.sin(angle)])
        segments.append([*(apex + 40 * direction), *(apex + 200 * direction)])

    found = volume.converge_point(np.array(segments), tolerance_px=3.0)
    assert found is not None
    point, inliers = found
    assert point == pytest.approx(apex, abs=1.0)
    assert inliers == len(segments)


def test_converge_point_refuses_two_lines_as_evidence():
    """Two lines always meet somewhere, so two is not an apex."""
    segments = np.array([[0.0, 0.0, 100.0, 0.0], [0.0, 0.0, 0.0, 100.0]])
    assert volume.converge_point(segments, tolerance_px=3.0) is None


# --- the correspondence layer, which is where every real failure was -------

def _render_mask(vertices, shape=(HEIGHT, WIDTH)):
    """The silhouette of a convex solid, as a mask, the way a detection would
    hand it over."""
    import cv2
    pixels = volume.project(vertices, K)
    hull = cv2.convexHull(pixels.astype(np.float32).reshape(-1, 1, 2))
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.round(hull).astype(np.int32), 1)
    return mask.astype(bool)


@pytest.mark.parametrize("rotation", [0, 1, 2, 3, 4, 5])
def test_wedge_is_found_whatever_phase_its_outline_starts_on(rotation):
    """A wedge's outline interleaves base and ridge corners, so where the
    contour happens to start decides which index pair is the ridge. One of
    those phases silently lost the wedge until the base was listed in cyclic
    order, so every phase is checked.
    """
    n, d, gravity, wall_point = scene(16, 8)
    quad = [(-40, -30), (40, -30), (40, 30), (-40, 30)]
    base = np.array([wall_point(*corner) for corner in quad])
    ridge = np.array([(base[1] + base[2]) / 2 + 28.0 * n,
                      (base[3] + base[0]) / 2 + 28.0 * n])

    #The six silhouette corners, in cyclic order, started at `rotation`.
    hexagon = np.array([base[0], ridge[1], base[3], base[2], ridge[0], base[1]])
    outline = np.roll(volume.project(hexagon, K), -rotation, axis=0)

    found = None
    for i in range(3):
        cyclic = [(i + 1) % 6, (i + 2) % 6, (i + 4) % 6, (i + 5) % 6]
        for shift in (0, 2):
            base_idx = cyclic[shift:] + cyclic[:shift]
            for pair in ([(i + 3) % 6, i], [i, (i + 3) % 6]):
                fit = volume.fit_ridge(outline[base_idx], outline[pair], n, d, K)
                if fit and fit["reprojection_px"] < 5.0:
                    found = fit
    assert found is not None, "no base roll / ridge order recovered this wedge"
    assert found["heights"][0] == pytest.approx(28.0, abs=1.0)


def _silhouette_corners(base, top):
    """Which of a box's eight corners reach its outline, in the hull's cyclic
    order, as ("B" or "T", index, px). Taken from the projection itself, so
    the test assumes nothing about which corners show."""
    import cv2
    pixels = volume.project(np.vstack([base, top]), K)
    hull = cv2.convexHull(pixels.astype(np.float32), returnPoints=False).ravel()
    return [("B" if i < 4 else "T", int(i) % 4, pixels[i]) for i in hull]


@pytest.mark.parametrize("wall_deg, pitch_deg, offset", [(16, 8, (0, 0)), (0, 5, (80, 0)),
                                                        (-10, 2, (0, 120)), (30, 15, (0, 120))])
def test_box_with_only_two_faces_visible_is_still_solvable(wall_deg, pitch_deg, offset):
    """A box showing its top and one side reaches the outline as TWO base and
    FOUR top corners (never four base and two top: the top is nearer the
    camera, so it covers the base). The height and every face still follow."""
    n, d, gravity, wall_point = scene(wall_deg, pitch_deg)
    quad = [(-35, -30), (35, -30), (35, 30), (-35, 30)]
    base = np.array([wall_point(offset[0] + a, offset[1] + b) for a, b in quad])
    top = base + 22.0 * n
    corners = _silhouette_corners(base, top)
    assert "".join(c[0] for c in corners).count("B") == 2, "scene is not a two-face view"

    best = None
    for start in range(6):
        for step in (1, -1):
            outline = np.array([corners[(start + step * i) % 6][2] for i in range(6)])
            fit = volume.fit_box_partial(outline, n, d, K)
            if fit and (best is None or fit["reprojection_px"] < best["reprojection_px"]):
                best = fit
    assert best is not None
    assert best["h_source"] == "box-two-face"
    assert best["reprojection_px"] < 1.0
    assert best["heights"][0] == pytest.approx(22.0, abs=0.5)
    assert worst_face_error_deg(best, truth_normals(base, top)) < 1.0


def test_fit_volume_finds_a_two_face_box_from_its_mask():
    """End to end from a rendered mask: the two-face box is chosen, trusted,
    and right."""
    n, d, gravity, wall_point = scene(16, 8)
    quad = [(-35, -30), (35, -30), (35, 30), (-35, 30)]
    base = np.array([wall_point(a, b) for a, b in quad])
    top = base + 22.0 * n
    mask = _render_mask(np.vstack([base, top]))
    fit = volume.fit_volume(volume.outline_from_mask(mask), n, d, K, mask, None, gravity)
    assert fit is not None
    assert fit["shape"] in ("box-two-face", "box-hexagon")
    assert fit["trusted"]
    assert fit["depth_cm"] == pytest.approx(22.0, abs=2.0)
    assert worst_face_error_deg(fit, truth_normals(base, top)) < 3.0


def test_a_pyramid_whose_apex_is_only_an_outline_corner_is_never_trusted():
    """With no ridge evidence the apex can only be guessed from an outline
    corner, and the centroid assumption then fits almost any corner - real
    photos passed the reprojection gate at 55-119 cm deep this way. Such a fit
    may still be returned, but never as trusted."""
    #A square pyramid low in the frame: its apex projects outside the base, so
    #with no greyscale (no ridges) the apex can only come from the outline.
    n, d, gravity, wall_point = scene(16, 8)
    quad = [(-40, -280), (40, -280), (40, -220), (-40, -220)]
    base = np.array([wall_point(*corner) for corner in quad])
    apex = base.mean(axis=0) + 25.0 * n
    mask = _render_mask(np.vstack([base, apex]))
    fit = volume.fit_volume(volume.outline_from_mask(mask), n, d, K, mask, None, gravity)
    assert fit is not None
    assert fit["h_source"] == "centroid-assumed" and fit["apex_source"] == "outline"
    assert fit["guessed_apex"]
    assert not fit["trusted"]


def test_box_face_angles_do_not_depend_on_the_fitted_height():
    """Why the box family is the most robust: its top face is parallel to the
    wall and its sides contain the wall normal, so the face angles follow from
    the observed base alone."""
    n, d, gravity, wall_point = scene(16, 8)
    quad = [(-35, -30), (35, -30), (35, 30), (-35, 30)]
    base = np.array([wall_point(*corner) for corner in quad])
    base_px, top_px = volume.project(base, K), volume.project(base + 30.0 * n, K)

    angles = []
    for height in (10.0, 30.0, 60.0, 110.0):
        fit = volume.fit_box(base_px, top_px, n, d, K, height_cm=height)
        assert fit is not None
        angles.append(sorted(
            round(volume.describe_face(f["normal"], n, gravity)["steepness_deg"], 1)
            for f in fit["faces"] if f["visible"]))
    assert all(a == angles[0] for a in angles), angles


def test_a_clipped_volume_is_not_trusted_even_though_it_looks_consistent():
    """The one way a confident wrong answer could still reach production: a
    base cut off by the frame is self-consistent on the corners that remain,
    so the reprojection gate cannot see it and the border test has to."""
    n, d, gravity, wall_point = scene(16, 8)
    quad = [(-40, -30), (40, -30), (40, 30), (-40, 30)]
    base = np.array([wall_point(*corner) for corner in quad])
    vertices = np.vstack([base, base + 25.0 * n])

    inside = _render_mask(vertices)
    assert not volume.touches_frame_border(inside)

    clipped = inside.copy()
    clipped[-1, clipped.shape[1] // 2] = True  # runs off the bottom edge
    assert volume.touches_frame_border(clipped)


def test_facing_is_not_reported_for_a_near_horizontal_face():
    """A face looking straight up has no meaningful facing: its horizontal
    component is tiny, so the angle swings the full range on a pixel of
    noise. It is reported as undefined rather than as a confident sidepull."""
    n, d, gravity, _ = scene(0, 0)
    straight_up = -gravity
    described = volume.describe_face(straight_up, n, gravity)
    assert described["facing"] == "undefined"
    assert described["facing_deg"] is None
    assert described["steepness_deg"] == pytest.approx(-90.0, abs=0.5)


def test_outline_from_mask_keeps_the_sixth_corner_detection_drops():
    """`run_detection`'s 0.005 tolerance reduces a box's and a wedge's
    six-corner outline to five points, and five is not enough to fit either -
    so the fit takes its own outline at a finer tolerance."""
    import cv2
    n, d, gravity, wall_point = scene(16, 8)
    quad = [(-35, -30), (35, -30), (35, 30), (-35, 30)]
    base = np.array([wall_point(*corner) for corner in quad])
    mask = _render_mask(np.vstack([base, base + 30.0 * n]))

    fine = volume.outline_from_mask(mask)
    coarse = volume.outline_from_mask(mask, eps=0.005)
    assert fine is not None and coarse is not None
    assert len(fine) >= 6
    assert len(fine) >= len(coarse)
    assert cv2.contourArea(fine.astype(np.float32)) > 0


def test_direction_families_separates_a_box_edge_directions():
    """A box shows three edge directions; each family meets at its own
    vanishing point."""
    segments = []
    for angle in (0.0, np.pi / 2, np.pi / 4):
        direction = np.array([np.cos(angle), np.sin(angle)])
        for offset in range(3):
            start = np.array([100.0 + 30 * offset, 100.0 + 30 * offset])
            segments.append([*start, *(start + 150 * direction)])

    families = volume.direction_families(np.array(segments))
    assert len(families) == 3
    assert all(len(family) == 3 for family in families)
