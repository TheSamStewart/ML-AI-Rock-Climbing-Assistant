"""Wall angle at a point of the photo, from the bolt grid's local shape.

The bolt grid is a known square, so the local metric that scale.py fits
(pixels -> grid units) says how the wall is tilted relative to the camera's
line of sight to that point. Gravity (from the phone's sensor, or an assumed
camera pitch) turns that into an angle from vertical.

Conventions
- Camera frame: x right, y down, z forward (out of the lens), like the image.
- `normal` is the unit wall normal pointing back at the camera.
- `gravity` is the unit "down" direction in the camera frame.
- Wall angle: degrees from vertical, positive = overhanging (the wall leans
  over the climber), 0 = vertical, negative = slab.

One photo cannot tell an overhang from a slab: the metric gives two mirror
normals. We take the overhanging one (OVERHANG_PRIOR), so a slab reads as a
small overhang or as 0.
"""

import numpy as np

#35 mm-equivalent focal length used when the photo's EXIF has none. 26 mm is
#the main camera of almost every recent phone (iPhone, Pixel, Galaxy), the
#lens the app's camera uses.
DEFAULT_FOCAL_35MM = 26.0
DIAGONAL_35MM = 43.27  # mm, diagonal of a 36 x 24 mm frame
#Camera pitch assumed when no sensor reading came with the photo: degrees the
#camera looks above horizontal. The pitch that best fits the measured angles
#was 11-14 deg on every reference photo that has them (eval_angle.py), so 12.
DEFAULT_PITCH_DEG = 12.0
#Margins on the reported angle, in degrees (docs/features/wall_size_hold_distance.md,
#Slice 5d). With the true camera tilt the panels on the reference walls were
#within ~7 deg except sparse or merged panels; an assumed pitch adds the
#spread between people's habits.
MARGIN_SENSOR_DEG = 8.0
MARGIN_ASSUMED_DEG = 15.0
#A reading from a phone not held roughly upright (screen y axis more than 60
#deg from vertical) is not used: roll and landscape holds are not handled.
MIN_UPRIGHT = 0.5


def focal_px(image_size: tuple[int, int], focal_35mm: float | None = None) -> float:
    """Focal length in pixels from the 35 mm-equivalent (which is defined on
    the image diagonal)."""
    width, height = image_size
    return (focal_35mm or DEFAULT_FOCAL_35MM) / DIAGONAL_35MM * float(np.hypot(width, height))


def gravity_from_pitch(pitch_deg: float) -> np.ndarray:
    """Down direction in the camera frame for a camera looking `pitch_deg`
    above horizontal, with no roll."""
    p = np.radians(pitch_deg)
    return np.array([0.0, np.cos(p), -np.sin(p)])


def gravity_from_sensor(reading) -> tuple[np.ndarray, float] | None:
    """Down direction in the camera frame from a phone accelerometer reading
    (x, y, z in the device frame: x right, y up the screen, z out of the
    screen, back camera along -z), the phone held upright (portrait).

    Platforms disagree on the sign: Android reports the reaction to gravity
    (pointing up, so y ~ +1 when upright), iOS native reports gravity (y ~ -1).
    With the phone upright the screen's y axis is within ~90 deg of up either
    way, so the sign of y says which convention it is. Returns
    (gravity, camera pitch in degrees), or None for a bad reading."""
    try:
        a = np.asarray([float(v) for v in reading], dtype=float)
    except (TypeError, ValueError):
        return None
    if a.shape != (3,) or not np.isfinite(a).all():
        return None
    norm = np.linalg.norm(a)
    if norm < 1e-6:
        return None
    up = a / norm
    if up[1] < 0:  # gravity convention, not reaction
        up = -up
    if up[1] < MIN_UPRIGHT:
        return None
    #Device (x right, y up, z out of screen) -> camera (x right, y down, z forward = -z_device).
    g = np.array([-up[0], up[1], up[2]])
    pitch = float(np.degrees(np.arcsin(np.clip(-up[2], -1.0, 1.0))))
    return g, pitch


def plane_normals(metric: np.ndarray, point: np.ndarray, size: tuple[int, int], f: float) -> list[np.ndarray] | None:
    """The two unit normals (facing the camera) a local metric allows.

    `metric` (2, 2) maps a px displacement to grid units: dp' M dp = units^2.
    The plane's image Jacobian is J = s * P E, with P = [I | -q] (q the point's
    normalised image coordinates), E an orthonormal basis of the plane, and s
    an unknown scale. Then M^-1 = J J' = s^2 (I + qq' - mm'), m = P n, which
    is solved for m (up to sign) and then n. None when the metric is not
    consistent with any plane (e.g. it is behind the camera)."""
    width, height = size
    q = np.array([(point[0] - width / 2) / f, (point[1] - height / 2) / f])
    s = np.linalg.inv(np.asarray(metric, dtype=float)) / f**2  # M^-1 in normalised coordinates
    s = (s + s.T) / 2
    a = np.eye(2) + np.outer(q, q)
    #A - tS singular at the generalized eigenvalues; the physical one is the
    #smallest, where A - tS is positive semi-definite of rank 1.
    t = float(np.min(np.linalg.eigvals(np.linalg.solve(s, a)).real))
    r = a - t * s
    r = (r + r.T) / 2
    w, v = np.linalg.eigh(r)
    #A perfectly face-on plane (along the ray) gives m = 0; noise can push the
    #eigenvalue slightly negative, which still means "no tilt".
    m0 = np.sqrt(max(w[-1], 0.0)) * v[:, -1]
    out = []
    for m in (m0, -m0):
        #n_xy = m + q n_z and |n| = 1.
        qa, qb, qc = 1 + q @ q, 2 * (m @ q), m @ m - 1
        disc = qb**2 - 4 * qa * qc
        if disc < 0:
            disc = 0.0
        nz = (-qb - np.sqrt(disc)) / (2 * qa)  # the root facing the camera
        n = np.array([*(m + q * nz), nz])
        out.append(n / np.linalg.norm(n))
    return out


def wall_angle_deg(normals: list[np.ndarray], gravity: np.ndarray) -> float | None:
    """Angle from vertical (positive = overhanging) of the overhanging
    candidate: the larger n . g."""
    if not normals:
        return None
    best = max(float(np.clip(n @ gravity, -1.0, 1.0)) for n in normals)
    return float(np.degrees(np.arcsin(best)))


VOTE_NEIGHBOURS = 50   # bolts pooled around a point to find the wall's normal
VOTE_TOLERANCE_DEG = 5.0   # two bolts agree on a normal when within this angle
MIN_VOTERS = 6


def bolt_candidates(lattice, size: tuple[int, int], f: float) -> np.ndarray:
    """(N, 2, 3): the two candidate normals at each fitted bolt, NaN where the
    local metric allows none."""
    import scale  # local import: scale is large and angle.py's maths stands alone

    out = np.full((len(lattice.xy), 2, 3), np.nan)
    if len(lattice.xy) == 0:
        return out
    metrics = scale.metric_at(lattice, lattice.xy)
    for i, (m, p) in enumerate(zip(metrics, lattice.xy)):
        try:
            c = plane_normals(m, p, size, f)
        except np.linalg.LinAlgError:
            c = None
        if c:
            out[i] = np.stack(c)
    return out


def consensus_normals(lattice, candidates: np.ndarray, points: np.ndarray, gravity: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Wall normal at each px point and how many bolts back it: (normals (M, 3),
    voters (M,)), NaN / 0 where there are too few bolts.

    One bolt's metric leaves two mirror normals; the true one is the same for
    every bolt on the same flat panel, while the mirror one moves with the
    bolt's position in the frame. So the normal that most of the nearest
    bolts can agree on is the true one. Where both mirror candidates are
    backed equally (near the middle of the frame, where the two coincide
    with a plain up/down tilt ambiguity) the overhanging one wins."""
    import scale

    points = np.asarray(points, dtype=float).reshape(-1, 2)
    normals = np.full((len(points), 3), np.nan)
    voters = np.zeros(len(points), dtype=int)
    if len(lattice.xy) == 0 or len(points) == 0:
        return normals, voters
    idx, _ = scale.knn(points, lattice.xy, VOTE_NEIGHBOURS)
    cos_tol = np.cos(np.radians(VOTE_TOLERANCE_DEG))
    for row, near in enumerate(idx):
        near = near[near >= 0]
        pool = candidates[near]                      # (k, 2, 3)
        ok = ~np.isnan(pool[:, 0, 0])
        pool = pool[ok]
        if len(pool) < MIN_VOTERS:
            continue
        flat = pool.reshape(-1, 3)                   # (2k, 3)
        dots = flat @ flat.T                         # (2k, 2k)
        owner = np.repeat(np.arange(len(pool)), 2)
        close = dots >= cos_tol
        #Per candidate: how many OTHER bolts have any candidate close to it.
        hit = np.zeros((len(flat), len(pool)), dtype=bool)
        for b in range(len(pool)):
            hit[:, b] = close[:, owner == b].any(axis=1)
        hit[np.arange(len(flat)), owner] = False     # a bolt doesn't vote for itself
        support = hit.sum(axis=1)
        best = np.max(support)
        top = np.flatnonzero(support >= best)
        pick = top[np.argmax(flat[top] @ gravity)]   # overhang breaks ties
        group = flat[close[pick]]
        n = group.mean(axis=0)
        normals[row] = n / np.linalg.norm(n)
        voters[row] = support[pick] + 1
    return normals, voters


def angles_from_normals(normals: np.ndarray, gravity: np.ndarray) -> np.ndarray:
    """Degrees from vertical (positive = overhanging); NaN where no normal."""
    return np.degrees(np.arcsin(np.clip(normals @ gravity, -1.0, 1.0)))


def angles_at(lattice, points: np.ndarray, size: tuple[int, int], f: float, gravity: np.ndarray) -> np.ndarray:
    """Wall angle (degrees, NaN where unavailable) at each px point."""
    cands = bolt_candidates(lattice, size, f)
    normals, _ = consensus_normals(lattice, cands, points, gravity)
    return angles_from_normals(normals, gravity)
