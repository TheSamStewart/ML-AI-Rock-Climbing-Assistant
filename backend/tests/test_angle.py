"""Slice 5d: pure maths of angle.py, written from the spec's Contracts only.

Frames
- Camera: x right, y down, z forward (pinhole, principal point at the image centre).
- Device (sensor): x right, y up the screen, z out of the screen, back camera along -z.
  Phone upright (portrait). camera = (dx, -dy, -dz).
- Camera looking `p` degrees above horizontal: down vector in the camera frame is
  (0, cos p, -sin p).
- Wall angle: degrees from vertical, positive = overhanging, = asin(normal . down)
  for the wall normal facing the camera.
"""
import math

import numpy as np
import pytest

import angle

G = 9.81


def _android(down_dev):
    # Android reports the reaction to gravity: up = -gravity.
    return [-c * G for c in down_dev]


def _ios(down_dev):
    return [c * G for c in down_dev]


def _down_dev(pitch_deg):
    # True gravity direction in the device frame for an upright phone whose back
    # camera looks `pitch_deg` above horizontal.
    p = math.radians(pitch_deg)
    return (0.0, -math.cos(p), math.sin(p))


# --- gravity_from_pitch -----------------------------------------------------


@pytest.mark.parametrize("pitch", [-30, -10, 0, 12, 25, 60, 90])
def test_gravity_from_pitch_is_unit_down_vector_in_camera_frame(pitch):
    d = np.asarray(angle.gravity_from_pitch(pitch), dtype=float)

    p = math.radians(pitch)
    assert d.shape == (3,)
    assert np.linalg.norm(d) == pytest.approx(1.0)
    assert d == pytest.approx([0.0, math.cos(p), -math.sin(p)], abs=1e-9)


def test_gravity_from_pitch_level_camera_down_is_image_down():
    assert np.asarray(angle.gravity_from_pitch(0.0)) == pytest.approx([0, 1, 0], abs=1e-9)


def test_default_pitch_constant_and_margins():
    assert angle.DEFAULT_PITCH_DEG == 12
    assert angle.MARGIN_SENSOR_DEG == 8
    assert angle.MARGIN_ASSUMED_DEG == 15


# --- gravity_from_sensor ----------------------------------------------------


@pytest.mark.parametrize("pitch", [-15, -5, 0, 5, 12, 14, 25, 40])
def test_gravity_from_sensor_android_and_ios_agree(pitch):
    down_dev = _down_dev(pitch)

    a = angle.gravity_from_sensor(_android(down_dev))
    i = angle.gravity_from_sensor(_ios(down_dev))

    assert a is not None and i is not None
    (down_a, pitch_a), (down_i, pitch_i) = a, i
    assert np.asarray(down_a) == pytest.approx(np.asarray(down_i), abs=1e-6)
    assert pitch_a == pytest.approx(pitch_i, abs=1e-6)
    assert pitch_a == pytest.approx(pitch, abs=0.01)
    assert np.linalg.norm(down_a) == pytest.approx(1.0)
    assert np.asarray(down_a) == pytest.approx(np.asarray(angle.gravity_from_pitch(pitch)), abs=1e-6)


def test_gravity_from_sensor_ignores_magnitude():
    d = _down_dev(14)

    small = angle.gravity_from_sensor([c * 1.0 for c in _android(d)])
    big = angle.gravity_from_sensor([c * 3.0 for c in _android(d)])

    assert np.asarray(small[0]) == pytest.approx(np.asarray(big[0]), abs=1e-6)
    assert small[1] == pytest.approx(big[1], abs=1e-6)


def test_gravity_from_sensor_accepts_tuples_and_arrays():
    reading = _android(_down_dev(14))

    from_list = angle.gravity_from_sensor(list(reading))
    from_tuple = angle.gravity_from_sensor(tuple(reading))
    from_array = angle.gravity_from_sensor(np.array(reading))

    assert from_list[1] == pytest.approx(from_tuple[1]) == pytest.approx(from_array[1])


def test_gravity_from_sensor_small_roll_still_unit_and_android_ios_agree():
    reading = [0.3, 9.4, -2.4]

    a = angle.gravity_from_sensor(reading)
    i = angle.gravity_from_sensor([-c for c in reading])

    assert a is not None and i is not None
    assert np.linalg.norm(a[0]) == pytest.approx(1.0)
    assert np.asarray(a[0]) == pytest.approx(np.asarray(i[0]), abs=1e-6)


@pytest.mark.parametrize(
    "reading",
    [
        [0.0, 0.5, -9.8],     # phone lying flat (y almost 0)
        [0.0, -0.5, 9.8],     # flat, face down
        [9.8, 0.3, 0.0],      # on its side (landscape)
        [-9.8, -0.3, 0.0],
        [0.0, 0.4 * 9.81, -math.sqrt(1 - 0.16) * 9.81],   # y axis 66 deg from vertical: |y|/|g| = 0.4 < 0.5
        [0.0, -0.4 * 9.81, math.sqrt(1 - 0.16) * 9.81],
    ],
)
def test_gravity_from_sensor_flat_or_sideways_phone_is_none(reading):
    assert angle.gravity_from_sensor(reading) is None


@pytest.mark.parametrize("y_frac", [0.6, 0.8, 1.0])
def test_gravity_from_sensor_accepts_y_axis_within_60_degrees_of_vertical(y_frac):
    z = -math.sqrt(1 - y_frac**2) * G

    assert angle.gravity_from_sensor([0.0, y_frac * G, z]) is not None
    assert angle.gravity_from_sensor([0.0, -y_frac * G, -z]) is not None


@pytest.mark.parametrize(
    "reading",
    [
        None,
        "abc",
        [],
        [1.0, 2.0],
        [float("nan"), float("nan"), float("nan")],
        [0.0, float("nan"), -9.8],
        [float("inf"), 0.0, 0.0],
        [0.0, float("inf"), 0.0],
        [0.0, 0.0, 0.0],
        ["a", "b", "c"],
    ],
)
def test_gravity_from_sensor_garbage_is_none(reading):
    assert angle.gravity_from_sensor(reading) is None


# --- focal_px ---------------------------------------------------------------


def test_focal_px_scales_linearly_with_35mm_focal_length():
    size = (4000, 3000)

    assert angle.focal_px(size, 52.0) == pytest.approx(2 * angle.focal_px(size, 26.0))


def test_focal_px_scales_with_image_size_and_is_plausible_for_26mm():
    f = angle.focal_px((4000, 3000), 26.0)

    assert angle.focal_px((2000, 1500), 26.0) == pytest.approx(f / 2)
    # A 26 mm-equivalent lens: focal length is 0.6-0.85 of the long side
    # (36 mm width or 43.3 mm diagonal reference both fall in this band).
    assert 0.6 * 4000 < f < 0.85 * 4000


def test_focal_px_is_orientation_independent():
    assert angle.focal_px((3000, 4000), 26.0) == pytest.approx(angle.focal_px((4000, 3000), 26.0), rel=0.03)


# --- plane_normals + wall_angle_deg on a synthetic plane ---------------------

SIZE = (4000, 3000)
F = angle.focal_px(SIZE, 26.0)
CX, CY = SIZE[0] / 2, SIZE[1] / 2
PX_PER_UNIT = 60.0


def _synth(angle_deg, tilt_deg, point):
    """Exact metric of a plane at `angle_deg` (overhang +) seen by a camera
    looking `tilt_deg` above horizontal, at pixel `point` (u, v)."""
    t, a = math.radians(tilt_deg), math.radians(angle_deg)
    down = np.array([0.0, math.cos(t), -math.sin(t)])
    fwd_h = np.array([0.0, math.sin(t), math.cos(t)])          # horizontal, away from camera
    n = -math.cos(a) * fwd_h + math.sin(a) * down              # faces the camera, n.down = sin(a)
    q = np.array([(point[0] - CX) / F, (point[1] - CY) / F])
    ray = np.array([q[0], q[1], 1.0])
    assert n @ ray < 0, "synthetic plane must face the camera at this point"
    e1 = np.cross(n, down)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    E = np.stack([e1, e2], axis=1)                              # 3x2 orthonormal basis of the plane
    proj = np.array([[1.0, 0.0, -q[0]], [0.0, 1.0, -q[1]]])
    J = PX_PER_UNIT * proj @ E                                  # px per grid unit, (f L / Z) = PX_PER_UNIT
    M = np.linalg.inv(J @ J.T)                                  # px displacement -> grid units^2
    return M, n, down


POINTS = [
    (CX, CY),
    (CX - 900, CY - 600),
    (CX + 900, CY + 600),
    (CX + 1200, CY - 800),
    (CX - 1000, CY + 700),
]
TILTS = [-10, 0, 15, 25]
OVERHANGS = [0, 6, 14, 25, 31, 45]


@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("wall", OVERHANGS)
def test_plane_normals_contain_true_normal_and_mirror(wall, tilt):
    for pt in POINTS:
        M, n_true, _ = _synth(wall, tilt, pt)

        normals = np.asarray(angle.plane_normals(M, pt, SIZE, F), dtype=float)

        assert normals.shape == (2, 3)
        assert np.linalg.norm(normals, axis=1) == pytest.approx([1.0, 1.0], abs=1e-6)
        assert np.all(normals[:, 2] < 0), "normals must face the camera"
        errs = [math.degrees(math.acos(min(1.0, float(n @ n_true)))) for n in normals]
        assert min(errs) < 1.0, (wall, tilt, pt, errs)


def _per_normal_angles(normals, down):
    return [float(angle.wall_angle_deg([n], down)) for n in normals]


@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("wall", OVERHANGS)
def test_wall_angle_recovers_overhang_from_exact_metric(wall, tilt):
    # From one point the two mirror solutions cannot be told apart (the vote across
    # neighbouring bolts does that), so one of the two per-normal angles must be the
    # true wall angle, at any point in the frame.
    down = angle.gravity_from_pitch(tilt)
    for pt in POINTS:
        M, _, _ = _synth(wall, tilt, pt)
        normals = angle.plane_normals(M, pt, SIZE, F)

        angles = _per_normal_angles(normals, down)

        assert min(abs(a - wall) for a in angles) < 1.0, (wall, tilt, pt, angles)


@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("wall", [0, 14, 31])
def test_wall_angle_takes_the_overhanging_of_the_two_normals(wall, tilt):
    down = angle.gravity_from_pitch(tilt)
    for pt in POINTS:
        M, _, _ = _synth(wall, tilt, pt)
        normals = angle.plane_normals(M, pt, SIZE, F)

        both = float(angle.wall_angle_deg(normals, down))

        assert both == pytest.approx(max(_per_normal_angles(normals, down)), abs=1e-6)


@pytest.mark.parametrize("wall", [0, 6, 14, 25, 31, 45])
def test_wall_angle_level_camera_centre_returns_overhang_exactly(wall):
    # Level camera, plane seen at the image centre: the mirror solution is exactly
    # -wall, so the overhanging one (the returned value) is the true angle.
    down = angle.gravity_from_pitch(0)
    M, _, _ = _synth(wall, 0, (CX, CY))

    result = angle.wall_angle_deg(angle.plane_normals(M, (CX, CY), SIZE, F), down)

    assert float(result) == pytest.approx(wall, abs=1.0)


def test_wall_angle_uses_the_down_vector_given():
    # Same image metric, different assumed camera tilt: the answer must move.
    M, _, _ = _synth(14, 15, (CX, CY))
    normals = angle.plane_normals(M, (CX, CY), SIZE, F)

    right = _per_normal_angles(normals, angle.gravity_from_pitch(15))
    wrong = _per_normal_angles(normals, angle.gravity_from_pitch(0))

    assert min(abs(a - 14) for a in right) < 1.0
    assert min(abs(a - 14) for a in wrong) > 5.0
