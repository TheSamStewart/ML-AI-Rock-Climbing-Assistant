"""Volume face geometry from one photo: the wall plane from the bolt grid, the
volume's base back-projected onto it, and the faces that follow.

Why this works without a depth model: a climbing volume is bolted flush to the
wall, and `scale.panel_homographies` already pins the wall in 3D - unit normal
plus distance in cm (the bolt grid is a known square and the focal length is
known, so the homography splits into a real pose). Any pixel on the wall
therefore back-projects to an exact point in cm, with no scale ambiguity. The
volume's base corners are such pixels, so they are free; only the apex (or
ridge) stands off the wall, and that is where the unknowns are.

The depth ambiguity, which drives the whole design
--------------------------------------------------
An apex seen at one pixel lies somewhere along one ray. Sliding it along that
ray does not move its projection, so **the outline is identical for every apex
height**. Interior ridge lines are no help either: they join base-corner
pixels to the apex pixel whatever the height. So a single-apex pyramid has
exactly one unknown that no amount of outline work can recover - its height
`h` above the wall - and every face normal rotates about its own base edge as
`h` changes. A pyramid therefore needs one extra assumption (`fit_pyramid`,
which stands the apex over the base centroid and reports how badly that fitted).

Volumes whose raised vertices sit over a KNOWN point of the base are
different, and all three fitters here are the same solve with different
anchors (`_solve_height`): a raised vertex is `anchor + h n`, and requiring it
to lie on its own observed ray is two equations for one unknown, so the fit is
over-determined and exact.

- `fit_box`: the top face is the base translated off the wall, so each top
  corner's anchor is the base corner below it - all observed. Exact.
- `fit_ridge` (a wedge): the ridge ends sit over the midpoints of two
  opposite base edges - also observed. Exact.
- `fit_pyramid`: the only anchor available is the base centroid, which is an
  ASSUMPTION about where the apex stands. An apex that is really off-centre
  by `e` cm comes back with its height wrong by about `e / tan(a)`, where `a`
  is the angle between the apex ray and the wall normal - about 10 deg near
  the middle of the frame, so a 6x amplification there, falling to 1x out at
  the edges. `offcentre_gain` reports that factor per fit, because the
  leftover least-squares residual badly understates the error (a 5 cm
  off-centre apex showed a 2.6 cm residual while its height was 27 cm out).

`h_source` on every result says which case applied, so a margin can be set
per case instead of one number for all volumes. Pass `height_cm` to any
fitter to supply `h` from outside (a catalogue size, a shading cue, the user)
and skip its anchor assumption entirely.

An earlier attempt pinned a wedge from its ridge being parallel to the base
edge below it. That is structurally degenerate and was removed: both ridge
ends share one height, so the ridge direction is `(d + h)(u2 - u1)` for any
`h` at all and the constraint says nothing about height.

Conventions (same as angle.py)
- Camera frame: x right, y down, z forward (out of the lens).
- Wall plane: points X with `n . X = d`, in cm. `n` is the unit normal facing
  the camera, so it points roughly back down -z and `d` comes out NEGATIVE
  (a wall 300 cm away has d of about -300). Because `n` points towards the
  camera, standing off the wall INCREASES `n . X`: a point `h` cm off the
  wall has `n . X = d + h`, with `h > 0` for a volume.
- A face is reported as a steepness (degrees from vertical, positive =
  overhanging, the same sign convention as angle.py) and a facing angle
  (degrees about the gravity axis away from the wall's own facing, positive =
  to the climber's right).
"""

import cv2
import numpy as np

#Volume depth (how far the apex stands off the wall) accepted as physical.
#Commercial volumes run from a ~10 cm riser to about a metre on the big
#pyramids; outside this a fit is wrong, not a big volume.
MIN_DEPTH_CM = 5.0
MAX_DEPTH_CM = 120.0
#A base edge shorter than this is noise on the outline, longer than this is
#not one volume. Used to reject a hypothesis, not to choose between them.
MIN_BASE_EDGE_CM = 10.0
MAX_BASE_EDGE_CM = 250.0
#The square bolt grid's two axes must come out equal, so the ratio is a free
#check on the homography split (0.2% on the field captures). Past this the
#panel fit is not worth back-projecting against.
MAX_AXIS_RATIO_DEVIATION = 0.08
#Bolts pooled to decide which panel a volume sits on.
PANEL_NEIGHBOURS = 12
#Outline rasterised at this long side when scoring: the score only has to
#rank hypotheses, and a 4k rasterisation per hypothesis is wasted work.
RASTER_LONG_SIDE = 512
#Ridge segments (idea 2): LSD output is kept when it is at least this fraction
#of the volume's own size, and when both ends sit inside the mask shrunk by
#RIDGE_INSET_FRACTION of that size - the outline boundary fires hard on LSD
#and would otherwise dominate the convergence fit.
RIDGE_MIN_LENGTH_FRACTION = 0.18
RIDGE_INSET_FRACTION = 0.06
#A ridge votes for an apex when the apex is within this far of its line, as a
#fraction of the volume's size.
RIDGE_INLIER_FRACTION = 0.04
#Fewer than this many agreeing ridges is "no apex found": two lines always
#meet somewhere, so two is not evidence.
RIDGE_MIN_INLIERS = 3
#Directions within this angle are one family when looking for vanishing points.
DIRECTION_CLUSTER_DEG = 12.0
#approxPolyDP tolerance for the fit's own outline, finer than
#detection.POLYGON_SIMPLIFY_EPS (0.005): at 0.005 a box's and a wedge's sixth
#silhouette corner is dropped and neither can be fitted at all.
VOLUME_SIMPLIFY_EPS = 0.002
#A fit is not trusted past this reprojection error, as a fraction of the
#volume's size (sqrt of its mask area), while `iou` could not separate a
#right fit from a wrong one at all. Normalised rather than a bare px count
#because px per cm of error varied 1.7-3.3x with frame position.
#Calibrated on the Tester's corpus (2026-11-20): fits that are still usable
#under a realistic 5 px of mask noise top out at 0.035, so this sits just
#above that with a margin, and it is the knee of the curve - it suppresses
#50 of 54 unusable fits while wrongly dropping 2 of 71 usable ones. The
#deciding case was the off-centre-apex pyramid: at 0.10 a 4-10 cm offset
#passed as trusted while being 9-34 cm out, which would corrupt every hold
#standoff on that volume; at 0.05 all of them are rejected.
MAX_REPROJECTION_FRACTION = 0.05
#A mask within this many pixels of the frame edge is treated as clipped.
BORDER_MARGIN_PX = 2
#Facing is not reported for a face this close to horizontal: its horizontal
#component is near zero, so the facing angle swings between -90 and +90 on a
#pixel of noise while the steepness stays put.
FACING_UNDEFINED_STEEPNESS_DEG = 85.0
#Preference given to an exactly-solved family over an assumed apex height when
#the outline scores them equally, which it generally does (see the docstring).
EXACT_FIT_BONUS = 0.02


def camera_matrix(size: tuple[int, int], f: float) -> np.ndarray:
    """Pinhole intrinsics with the principal point at the image centre."""
    width, height = size
    return np.array([[f, 0.0, width / 2], [0.0, f, height / 2], [0.0, 0.0, 1.0]])


def unit(v: np.ndarray) -> np.ndarray:
    """`v` scaled to length 1 along its last axis; a zero vector is left be."""
    v = np.asarray(v, dtype=float)
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(norm < 1e-12, 1.0, norm)


def wall_plane(lattice, point: np.ndarray, K: np.ndarray, spacing_cm: float) -> dict | None:
    """The wall as (n, d) in cm at a px `point`, from the homography of the
    panel most of the nearest bolts belong to.

    H maps grid units to px, so K^-1 H is [r1 r2 t] up to one scale, which the
    two columns' lengths give (they are unit vectors in the plane). Unlike the
    per-bolt metric in angle.py this split has no mirror twin: it fixes which
    way the plane leans. `axis_ratio` should be 1 because the grid is square,
    so it doubles as a quality check on the fit.
    """
    from wall_analysis import scale  # local import: scale is large and this module's maths stands alone

    homographies = scale.panel_homographies(lattice)
    if not homographies:
        return None
    idx, _ = scale.knn(np.asarray([point], dtype=float).reshape(1, 2), lattice.xy, PANEL_NEIGHBOURS)
    near = [int(lattice.panel[i]) for i in idx[0] if i >= 0 and int(lattice.panel[i]) in homographies]
    if not near:
        return None
    panel = max(set(near), key=near.count)

    A = np.linalg.inv(K) @ homographies[panel]
    len1, len2 = np.linalg.norm(A[:, 0]), np.linalg.norm(A[:, 1])
    if len1 < 1e-12 or len2 < 1e-12:
        return None
    s = 2.0 / (len1 + len2)
    r1, r2, t = s * A[:, 0], s * A[:, 1], s * A[:, 2]
    if t[2] < 0:  #the plane has to be in front of the camera
        r1, r2, t = -r1, -r2, -t
    n = unit(np.cross(r1, r2))
    if n @ t > 0:  #point the normal back at the camera
        n = -n
    ratio = float(len1 / len2)
    return {
        "panel": panel,
        "n": n,
        "d": float(n @ (t * spacing_cm)),
        "axis_ratio": ratio,
        "trusted": bool(abs(ratio - 1.0) <= MAX_AXIS_RATIO_DEVIATION),
        "panel_bolts": int((lattice.panel == panel).sum()),
    }


def rays(pixels: np.ndarray, K: np.ndarray) -> np.ndarray:
    """Unit direction in the camera frame for each px point: (M, 2) -> (M, 3)."""
    pixels = np.asarray(pixels, dtype=float).reshape(-1, 2)
    homogeneous = np.column_stack([pixels, np.ones(len(pixels))])
    return unit(homogeneous @ np.linalg.inv(K).T)


def backproject(pixels: np.ndarray, n: np.ndarray, d: float, K: np.ndarray) -> np.ndarray:
    """Px points (M, 2) -> cm points (M, 3) on the plane n . X = d. NaN for a
    ray parallel to the plane or pointing away from it."""
    r = rays(pixels, K)
    denominator = r @ n
    with np.errstate(divide="ignore", invalid="ignore"):
        t = d / denominator
    out = r * t[:, None]
    #`n` faces the camera and `d` is negative, so a visible wall point has
    #r . n < 0 and t > 0. Only the range matters, not the sign of either part.
    out[(np.abs(denominator) <= 1e-9) | (t <= 0)] = np.nan
    return out


def project(points: np.ndarray, K: np.ndarray) -> np.ndarray:
    """cm points (M, 3) -> px (M, 2). NaN for anything behind the camera."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    uv = points @ K.T
    z = uv[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        out = uv[:, :2] / z[:, None]
    out[z <= 1e-9] = np.nan
    return out


def point_at_height(ray: np.ndarray, n: np.ndarray, d: float, h: float) -> np.ndarray:
    """The point on `ray` standing `h` cm off the wall, towards the camera."""
    denominator = float(np.asarray(ray) @ n)
    if abs(denominator) < 1e-9:
        return np.full(3, np.nan)
    return np.asarray(ray) * ((d + h) / denominator)


def height_of(point: np.ndarray, n: np.ndarray, d: float) -> float:
    """How far a cm point stands off the wall, towards the camera."""
    return float(n @ np.asarray(point, dtype=float) - d)


def dominant_corners(polygon: np.ndarray, k: int) -> np.ndarray | None:
    """The outline reduced to exactly `k` vertices, by bisecting approxPolyDP's
    tolerance. None when no tolerance gives `k`.

    Needed because run_detection already simplified the mask to ~14 points,
    which is far more than a volume's real corner count.
    """
    contour = np.asarray(polygon, dtype=np.float32).reshape(-1, 1, 2)
    if len(contour) < k:
        return None
    if len(contour) == k:
        return contour.reshape(-1, 2).astype(float)
    perimeter = cv2.arcLength(contour, True)
    if perimeter <= 0:
        return None
    low, high = 0.0, 0.5
    for _ in range(40):
        mid = (low + high) / 2
        reduced = cv2.approxPolyDP(contour, mid * perimeter, True).reshape(-1, 2)
        if len(reduced) == k:
            return reduced.astype(float)
        if len(reduced) > k:
            low = mid
        else:
            high = mid
    return None


def ridge_segments(gray: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Interior line segments of one volume: (L, 4) as x1, y1, x2, y2.

    Volumes are matte and single-coloured, so neighbouring faces at different
    angles differ in brightness and their shared ridge shows up as a step edge
    even with no texture at all. The outline boundary fires just as hard on
    LSD, so the mask is shrunk first and only segments wholly inside it keep.
    """
    mask = np.asarray(mask).astype(bool)
    area = float(mask.sum())
    if area <= 0:
        return np.zeros((0, 4))
    size = np.sqrt(area)

    #Crop to the volume before running LSD. A volume covers only 3-10% of a
    #phone frame, and detecting over the whole 1776x3840 cost 511 ms of the
    #535 ms per volume (Tester, 2026-11-20).
    ys, xs = np.nonzero(mask)
    pad = max(2, int(round(0.02 * size)))
    y0, y1 = max(0, ys.min() - pad), min(mask.shape[0], ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(mask.shape[1], xs.max() + 1 + pad)
    sub_mask = mask[y0:y1, x0:x1]
    sub_gray = np.where(sub_mask, np.asarray(gray)[y0:y1, x0:x1], 0).astype(np.uint8)

    detector = cv2.createLineSegmentDetector()
    found = detector.detect(sub_gray)[0]
    if found is None or len(found) == 0:
        return np.zeros((0, 4))
    segments = np.asarray(found, dtype=float).reshape(-1, 4)
    length = np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1])
    keep = length >= RIDGE_MIN_LENGTH_FRACTION * size

    #Test the segment's MIDPOINT against its distance from the outline, not
    #its endpoints. A volume's ridges run from the apex out to the silhouette
    #corners, so one endpoint is always on the boundary - requiring both ends
    #to be inset discarded every real ridge and left fewer than the three
    #needed to converge, on all 66 test volumes (Tester, 2026-11-20).
    distance = cv2.distanceTransform(sub_mask.astype(np.uint8), cv2.DIST_L2, 5)
    mid_x = np.clip(np.round((segments[:, 0] + segments[:, 2]) / 2).astype(int), 0, sub_mask.shape[1] - 1)
    mid_y = np.clip(np.round((segments[:, 1] + segments[:, 3]) / 2).astype(int), 0, sub_mask.shape[0] - 1)
    keep &= distance[mid_y, mid_x] >= RIDGE_INSET_FRACTION * size

    segments = segments[keep]
    segments[:, [0, 2]] += x0  #back to full-frame pixels
    segments[:, [1, 3]] += y0
    return segments


def outline_from_mask(mask: np.ndarray, eps: float = None) -> np.ndarray | None:
    """The volume's outline taken straight from its mask.

    `run_detection` simplifies at `POLYGON_SIMPLIFY_EPS` = 0.005, which is
    right for tap matching but drops the SIXTH silhouette corner of a box and
    of a wedge - and without that corner neither can be fitted at all
    (Tester, 2026-11-20). So the fit derives its own outline at a finer
    tolerance instead of inheriting that one.
    """
    mask = np.asarray(mask).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(contour, True)
    if perimeter <= 0:
        return None
    tolerance = VOLUME_SIMPLIFY_EPS if eps is None else eps
    return cv2.approxPolyDP(contour, tolerance * perimeter, True).reshape(-1, 2).astype(float)


def _lines(segments: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each segment as a normalised line (normal, offset): normal . x = offset."""
    p1, p2 = segments[:, :2], segments[:, 2:]
    direction = unit(p2 - p1)
    normal = np.column_stack([-direction[:, 1], direction[:, 0]])
    return normal, np.einsum("ij,ij->i", normal, p1)


def converge_point(segments: np.ndarray, tolerance_px: float) -> tuple[np.ndarray, int] | None:
    """The point most segment lines pass through, and how many do: a pyramid's
    apex, where its ridges meet. Every pair is intersected, the pair with most
    lines agreeing wins, then least squares over those. None when fewer than
    RIDGE_MIN_INLIERS agree.

    This matters because a pyramid's apex often projects INSIDE its own
    outline, so it is not an outline vertex at all and cannot be guessed from
    the polygon.
    """
    segments = np.asarray(segments, dtype=float).reshape(-1, 4)
    if len(segments) < 2:
        return None
    normal, offset = _lines(segments)
    best_point, best_count = None, 0
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            A = normal[[i, j]]
            if abs(np.linalg.det(A)) < 1e-9:  #parallel: no intersection
                continue
            candidate = np.linalg.solve(A, offset[[i, j]])
            count = int((np.abs(normal @ candidate - offset) <= tolerance_px).sum())
            if count > best_count:
                best_point, best_count = candidate, count
    if best_point is None or best_count < RIDGE_MIN_INLIERS:
        return None
    inliers = np.abs(normal @ best_point - offset) <= tolerance_px
    A = normal[inliers].T @ normal[inliers]
    b = normal[inliers].T @ offset[inliers]
    try:
        refined = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        refined = best_point
    return refined, int(inliers.sum())


def direction_families(segments: np.ndarray) -> list[np.ndarray]:
    """Segments grouped by image direction (modulo 180 deg), biggest group
    first. A box's three edge directions come out as three families, each of
    which meets at a vanishing point."""
    segments = np.asarray(segments, dtype=float).reshape(-1, 4)
    if len(segments) == 0:
        return []
    angle = np.degrees(np.arctan2(segments[:, 3] - segments[:, 1],
                                  segments[:, 2] - segments[:, 0])) % 180.0
    length = np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1])
    used = np.zeros(len(segments), dtype=bool)
    families = []
    for i in np.argsort(-length):
        if used[i]:
            continue
        delta = np.abs(angle - angle[i])
        close = (np.minimum(delta, 180.0 - delta) <= DIRECTION_CLUSTER_DEG) & ~used
        used |= close
        families.append(segments[close])
    return sorted(families, key=len, reverse=True)


def _polygon_area_3d(corners: np.ndarray) -> float:
    """Area of a planar polygon in 3D, by the vector cross-product sum."""
    corners = np.asarray(corners, dtype=float)
    total = np.zeros(3)
    for i in range(len(corners)):
        total = total + np.cross(corners[i], corners[(i + 1) % len(corners)])
    return float(np.linalg.norm(total) / 2)


def _face(corners: np.ndarray, middle: np.ndarray) -> dict | None:
    """One planar face from its cm corners.

    `normal` is returned facing the camera so it can be compared with the wall
    normal directly. `visible` is the separate question of whether this face is
    the one being looked at: its OUTWARD normal (away from the solid's middle)
    has to point back towards the camera, else the face is round the far side.
    """
    corners = np.asarray(corners, dtype=float).reshape(-1, 3)
    if len(corners) < 3 or not np.isfinite(corners).all():
        return None
    cross = np.cross(corners[1] - corners[0], corners[-1] - corners[0])
    if np.linalg.norm(cross) < 1e-9:
        return None
    normal = unit(cross)
    centre = corners.mean(axis=0)
    outward = normal if normal @ (centre - middle) > 0 else -normal
    return {
        "normal": outward if outward @ centre < 0 else -outward,
        "visible": bool(outward @ centre < 0),
        "corners": corners,
        "area_cm2": round(_polygon_area_3d(corners), 1),
    }


def faces_from_apex(base: np.ndarray, apex: np.ndarray) -> list[dict]:
    """One face per base edge, each spanned by that edge and the single apex."""
    base = np.asarray(base, dtype=float).reshape(-1, 3)
    apex = np.asarray(apex, dtype=float).reshape(3)
    middle = np.vstack([base, apex]).mean(axis=0)
    faces = []
    for i in range(len(base)):
        face = _face(np.vstack([base[i], base[(i + 1) % len(base)], apex]), middle)
        if face:
            faces.append(face)
    return faces


def faces_from_top(base: np.ndarray, top: np.ndarray) -> list[dict]:
    """Faces of a solid with a raised polygon rather than a single apex:
    the sides plus the top. Covers a wedge (a ridge of two points) and a box
    (a raised copy of the base)."""
    base = np.asarray(base, dtype=float).reshape(-1, 3)
    top = np.asarray(top, dtype=float).reshape(-1, 3)
    middle = np.vstack([base, top]).mean(axis=0)
    groups = []
    if len(top) == len(base):
        for i in range(len(base)):
            j = (i + 1) % len(base)
            groups.append([base[i], base[j], top[j], top[i]])
        groups.append(list(top[::-1]))
    elif len(top) == 2 and len(base) == 4:
        #A wedge: top[0] stands over the middle of base[1]-base[2] and top[1]
        #over the middle of base[3]-base[0], so the ridge runs across those two
        #edges. Two sloping faces, two triangular ends.
        groups.append([base[0], base[1], top[0], top[1]])
        groups.append([base[2], base[3], top[1], top[0]])
        groups.append([base[1], base[2], top[0]])
        groups.append([base[3], base[0], top[1]])
    faces = []
    for group in groups:
        face = _face(np.asarray(group), middle)
        if face:
            faces.append(face)
    return faces


def describe_face(normal: np.ndarray, wall_normal: np.ndarray, gravity: np.ndarray) -> dict:
    """A face as a climber meets it: how steep, and which way it points.

    `steepness_deg` is degrees from vertical, positive = overhanging, the same
    convention angle.py reports for the wall. `facing_deg` is how far the face
    is turned away from the wall's own direction about the gravity axis,
    positive = to the climber's right. A face turned 90 deg is a sidepull, and
    steepness on its own would call it vertical - which is why the human asked
    for both numbers.
    """
    normal, wall_normal, gravity = unit(normal), unit(wall_normal), unit(gravity)
    steepness = float(np.degrees(np.arcsin(np.clip(normal @ gravity, -1.0, 1.0))))

    def horizontal(v):
        return v - (v @ gravity) * gravity

    a, b = horizontal(normal), horizontal(wall_normal)
    #A face within a few degrees of horizontal (a box's top looking straight
    #up, say) has almost no horizontal component, so its facing angle is
    #meaningless - it swung the full -90 to +90 on a pixel of mask noise in
    #testing while the steepness stayed at 89.9. Report it as undefined
    #rather than as a confident sidepull.
    undefined = (abs(steepness) > FACING_UNDEFINED_STEEPNESS_DEG
                 or np.linalg.norm(a) < 1e-6 or np.linalg.norm(b) < 1e-6)
    if undefined:
        facing, label = None, "undefined"
    else:
        a, b = unit(a), unit(b)
        facing = float(-np.degrees(np.arctan2(np.cross(b, a) @ gravity, a @ b)))
        if abs(facing) <= 30:
            label = "out"
        elif abs(facing) >= 150:
            label = "into the wall"
        else:
            label = "right" if facing > 0 else "left"
    return {
        "steepness_deg": round(steepness, 1),
        "facing_deg": None if facing is None else round(facing, 1),
        "facing": label,
        "off_wall_deg": round(float(np.degrees(np.arccos(np.clip(normal @ wall_normal, -1.0, 1.0)))), 1),
    }


def silhouette_iou(vertices: np.ndarray, K: np.ndarray, mask: np.ndarray) -> float:
    """IoU of a convex solid's projected outline against a detection mask.

    Scored on a shrunk raster: the number only has to rank hypotheses. Note
    what it CANNOT do - sliding the apex along its ray leaves the outline
    unchanged, so this never ranks apex height, only which pixels are base and
    which is the apex.
    """
    mask = np.asarray(mask).astype(bool)
    projected = project(vertices, K)
    if not np.isfinite(projected).all():
        return 0.0
    height, width = mask.shape
    s = min(1.0, RASTER_LONG_SIDE / max(height, width))
    small = cv2.resize(mask.astype(np.uint8), (max(1, int(width * s)), max(1, int(height * s))),
                       interpolation=cv2.INTER_NEAREST).astype(bool)
    hull = cv2.convexHull((projected * s).astype(np.float32).reshape(-1, 1, 2))
    rendered = np.zeros(small.shape, dtype=np.uint8)
    cv2.fillConvexPoly(rendered, np.round(hull).astype(np.int32), 1)
    rendered = rendered.astype(bool)
    union = int((rendered | small).sum())
    return float((rendered & small).sum() / union) if union else 0.0


def _plausible(base: np.ndarray, heights) -> bool:
    """A fit is rejected outright when its cm numbers are not physical."""
    base = np.asarray(base, dtype=float)
    if not np.isfinite(base).all() or len(base) < 3:
        return False
    edges = np.linalg.norm(base - np.roll(base, -1, axis=0), axis=1)
    if edges.min() < MIN_BASE_EDGE_CM or edges.max() > MAX_BASE_EDGE_CM:
        return False
    heights = np.atleast_1d(np.asarray(heights, dtype=float))
    return bool(np.isfinite(heights).all()
                and (heights >= MIN_DEPTH_CM).all() and (heights <= MAX_DEPTH_CM).all())


def _solve_height(anchors: np.ndarray, top_px: np.ndarray, n, d, K) -> tuple[float, float, float] | None:
    """The one height `h` for which every `anchor + h n` lies on its observed
    ray. Returns (h, worst reprojection px, off-centre gain).

    Each raised vertex contributes two equations for the single unknown:
      perp . (anchor + h n) = 0   =>   h (perp . n) = -perp . anchor
    where `perp` spans the directions across that vertex's ray.

    `gain` is 1 / tan(angle between the mean ray and the wall normal): how
    many cm of height error one cm of ANCHOR error produces. It is ~6 near the
    middle of the frame and ~1 at the edges, and it is what makes the pyramid
    case weak and the box case strong.
    """
    anchors = np.asarray(anchors, dtype=float).reshape(-1, 3)
    top_px = np.asarray(top_px, dtype=float).reshape(-1, 2)
    #A degenerate mask can hand over a non-finite pixel; np.linalg.svd raises
    #on NaN rather than returning, so it is caught here and reported as "no
    #fit" like any other hypothesis that does not work out.
    if (len(anchors) != len(top_px) or not np.isfinite(anchors).all()
            or not np.isfinite(top_px).all()):
        return None
    top_rays = rays(top_px, K)
    if not np.isfinite(top_rays).all():
        return None
    rows, targets = [], []
    for anchor, ray in zip(anchors, top_rays):
        perp = np.linalg.svd(ray.reshape(1, 3))[2][1:]
        rows.append((perp @ n).reshape(-1, 1))
        targets.append(-perp @ anchor)
    rows = np.vstack(rows)
    if np.abs(rows).max() < 1e-9:  #ray parallel to the normal: no information
        return None
    solution, *_ = np.linalg.lstsq(rows, np.concatenate(targets), rcond=None)
    h = float(solution[0])
    reprojected = project(anchors + h * n, K)
    if not np.isfinite(reprojected).all():
        return None
    mean_ray = unit(top_rays.mean(axis=0))
    cosine = float(np.clip(abs(mean_ray @ n), -1.0, 1.0))
    angle = np.arccos(cosine)
    gain = float(1.0 / np.tan(angle)) if angle > 1e-6 else float("inf")
    return h, float(np.abs(reprojected - top_px).max()), gain


def fit_pyramid(base_px: np.ndarray, apex_px: np.ndarray, n, d, K,
                height_cm: float | None = None) -> dict | None:
    """A single-apex volume.

    The apex height cannot be seen from the outline (module docstring), so
    unless `height_cm` is supplied the apex is ASSUMED to stand over the base
    centroid. `offcentre_gain` says what that assumption costs: multiply it by
    however far off-centre the real apex might be to get the height error, and
    treat the face angles as untrustworthy when the product is large.
    """
    n = np.asarray(n, dtype=float)
    base = backproject(base_px, n, d, K)
    if not np.isfinite(base).all() or len(base) < 3:
        return None
    apex_px = np.asarray(apex_px, dtype=float).reshape(1, 2)
    if not np.isfinite(apex_px).all():
        return None
    ray = rays(apex_px, K)[0]
    if not np.isfinite(ray).all():
        return None

    if height_cm is not None:
        h, reprojection, source = float(height_cm), 0.0, "given"
        solved = _solve_height(base.mean(axis=0).reshape(1, 3), apex_px, n, d, K)
        gain = solved[2] if solved else float("nan")
    else:
        solved = _solve_height(base.mean(axis=0).reshape(1, 3), apex_px, n, d, K)
        if solved is None:
            return None
        h, reprojection, gain = solved
        source = "centroid-assumed"
    if not _plausible(base, h):
        return None
    apex = point_at_height(ray, n, d, h)
    if not np.isfinite(apex).all():
        return None
    return {
        "base": base, "apex": apex, "top": None, "heights": np.array([h]),
        "h_source": source, "reprojection_px": round(reprojection, 1),
        "offcentre_gain": round(gain, 1),
        "faces": faces_from_apex(base, apex),
        "vertices": np.vstack([base, apex]),
    }


def fit_ridge(base_px: np.ndarray, ridge_px: np.ndarray, n, d, K,
              height_cm: float | None = None) -> dict | None:
    """A wedge: four base corners plus a two-point ridge.

    The ridge of a wedge runs over the midpoints of the two base edges
    base[1]-base[2] and base[3]-base[0], and those midpoints are observed, not
    assumed - so the height is solved exactly with no shape prior, and
    `reprojection_px` checks that the solid really is a wedge.
    """
    n = np.asarray(n, dtype=float)
    base = backproject(base_px, n, d, K)
    ridge_px = np.asarray(ridge_px, dtype=float).reshape(-1, 2)
    if (not np.isfinite(base).all() or not np.isfinite(ridge_px).all()
            or len(base) != 4 or len(ridge_px) != 2):
        return None
    anchors = np.vstack([(base[1] + base[2]) / 2, (base[3] + base[0]) / 2])

    if height_cm is not None:
        h, reprojection, source = float(height_cm), 0.0, "given"
        solved = _solve_height(anchors, ridge_px, n, d, K)
        gain = solved[2] if solved else float("nan")
    else:
        solved = _solve_height(anchors, ridge_px, n, d, K)
        if solved is None:
            return None
        h, reprojection, gain = solved
        source = "ridge-anchored"
    if not _plausible(base, h):
        return None
    top = anchors + h * n
    return {
        "base": base, "apex": None, "top": top, "heights": np.full(2, h),
        "h_source": source, "reprojection_px": round(reprojection, 1),
        "offcentre_gain": round(gain, 1),
        "faces": faces_from_top(base, top),
        "vertices": np.vstack([base, top]),
    }


def fit_box(base_px: np.ndarray, top_px: np.ndarray, n, d, K,
            height_cm: float | None = None) -> dict | None:
    """A box or riser: the top face is the base translated straight off the
    wall, so each top corner's anchor is the base corner below it.

    Every anchor is observed, so there is no assumption to pay for: the
    height is solved from 2x4 equations for one unknown and
    `reprojection_px` is a free check on whether the solid really is a box.
    """
    n = np.asarray(n, dtype=float)
    base = backproject(base_px, n, d, K)
    top_px = np.asarray(top_px, dtype=float).reshape(-1, 2)
    if (not np.isfinite(base).all() or not np.isfinite(top_px).all()
            or len(top_px) != len(base) or len(base) < 3):
        return None

    if height_cm is not None:
        h, reprojection, source = float(height_cm), 0.0, "given"
        solved = _solve_height(base, top_px, n, d, K)
        gain = solved[2] if solved else float("nan")
    else:
        solved = _solve_height(base, top_px, n, d, K)
        if solved is None:
            return None
        h, reprojection, gain = solved
        source = "box-translate"
    if not _plausible(base, h):
        return None
    top = base + h * n
    return {
        "base": base, "apex": None, "top": top, "heights": np.full(len(base), h),
        "h_source": source, "reprojection_px": round(reprojection, 1),
        "offcentre_gain": round(gain, 1),
        "faces": faces_from_top(base, top),
        "vertices": np.vstack([base, top]),
    }


def fit_box_hexagon(outline_px: np.ndarray, n, d, K,
                    height_cm: float | None = None) -> dict | None:
    """A box seen the way a box actually looks: a hexagon of three base
    corners followed by three top corners.

    A cuboid has eight vertices but only six reach its silhouette - three of
    the base and three of the top; the other two are interior. So `fit_box`'s
    eight-corner form is never reachable from a real outline, and across 66
    test volumes it was never once selected (Tester, 2026-11-20).

    The hidden fourth base corner is recovered rather than guessed: the base
    is a parallelogram, so the corner opposite the middle one is
    `B_i + B_k - B_j`. Every anchor is then available and the height is
    solved, not assumed. A box's face angles happen to be independent of its
    height anyway (the top face is parallel to the wall and the sides contain
    the normal), which is why this family is the most robust of the three.
    """
    n = np.asarray(n, dtype=float)
    outline_px = np.asarray(outline_px, dtype=float).reshape(-1, 2)
    if len(outline_px) != 6 or not np.isfinite(outline_px).all():
        return None
    base_px, top_px = outline_px[:3], outline_px[3:]
    seen = backproject(base_px, n, d, K)
    if not np.isfinite(seen).all():
        return None
    b_i, b_j, b_k = seen
    b_l = b_i + b_k - b_j                      # the corner hidden behind the box
    base = np.vstack([b_i, b_j, b_k, b_l])
    #Going round the hexagon, the top run is T_k, T_l, T_i.
    anchors = np.vstack([b_k, b_l, b_i])

    solved = _solve_height(anchors, top_px, n, d, K)
    if solved is None:
        return None
    if height_cm is not None:
        h, reprojection, source = float(height_cm), 0.0, "given"
        gain = solved[2]
    else:
        h, reprojection, gain = solved
        source = "box-hexagon"
    if not _plausible(base, h):
        return None
    top = base + h * n
    return {
        "base": base, "apex": None, "top": top, "heights": np.full(4, h),
        "h_source": source, "reprojection_px": round(reprojection, 1),
        "offcentre_gain": round(gain, 1),
        "faces": faces_from_top(base, top),
        "vertices": np.vstack([base, top]),
    }


def fit_box_partial(outline_px: np.ndarray, n, d, K,
                    height_cm: float | None = None) -> dict | None:
    """A box with only TWO faces visible: its top face and one side.

    The silhouette is then TWO base corners and FOUR top ones, in cyclic order
    B0, B1, T1, T2, T3, T0, where T_i stands over B_i. The top face is closer
    to the camera than the base, so it always covers at least half of the
    base's outline; a box never shows four base corners and two top ones.
    (This function first assumed 4 base + 2 top, which no real view produces,
    so it never fitted a real box - 2 of 16 synthetic boxes right, 2026-11-20.
    Checked by projecting exact boxes from 20 viewpoints: every outline was
    3B + 3T, 2B + 4T, or the head-on 4T where the height cannot be seen.)

    The height is solved from T0 and T1 over their observed base corners. T2
    and T3 then lie on the top plane `n . X = d + h`, which gives the two
    hidden base corners below them. The base must be a parallelogram, so B3 is
    predicted a second way, as B0 + B2 - B1, and its disagreement with the
    observed T3 goes into `reprojection_px`. That keeps a wedge or pyramid
    whose outline happens to have six corners from passing as a box.
    """
    n = np.asarray(n, dtype=float)
    outline_px = np.asarray(outline_px, dtype=float).reshape(-1, 2)
    if len(outline_px) != 6 or not np.isfinite(outline_px).all():
        return None
    b01 = backproject(outline_px[:2], n, d, K)
    if not np.isfinite(b01).all():
        return None
    #T1 is outline[2] and T0 is outline[5].
    solved = _solve_height(b01, outline_px[[5, 2]], n, d, K)
    if solved is None:
        return None
    if height_cm is not None:
        h, reprojection, source = float(height_cm), 0.0, "given"
        gain = solved[2]
    else:
        h, reprojection, gain = solved
        source = "box-two-face"
    t23 = backproject(outline_px[3:5], n, d + h, K)
    if not np.isfinite(t23).all():
        return None
    b2, b3 = t23 - h * n
    base = np.vstack([b01[0], b01[1], b2, b3])
    predicted_t3 = project((base[0] + base[2] - base[1] + h * n).reshape(1, 3), K)[0]
    if not np.isfinite(predicted_t3).all():
        return None
    if height_cm is None:
        reprojection = max(reprojection, float(np.linalg.norm(predicted_t3 - outline_px[4])))
    if not _plausible(base, h):
        return None
    top = base + h * n
    return {
        "base": base, "apex": None, "top": top, "heights": np.full(4, h),
        "h_source": source, "reprojection_px": round(reprojection, 1),
        "offcentre_gain": round(gain, 1),
        "faces": faces_from_top(base, top),
        "vertices": np.vstack([base, top]),
    }


def touches_frame_border(mask: np.ndarray, margin_px: int = BORDER_MARGIN_PX) -> bool:
    """Whether a volume's mask runs off the edge of the photo.

    This has to be checked separately because the reprojection gate provably
    cannot see it: a base cut off by the frame is still perfectly
    self-consistent on the corners that ARE visible, so a clipped volume came
    back at reprojection 0.000 with its height 14 cm out and its worst face
    16 deg out - the only confident-and-wrong case left after gating
    (Tester, 2026-11-20).
    """
    mask = np.asarray(mask).astype(bool)
    m = max(1, int(margin_px))
    return bool(mask[:m].any() or mask[-m:].any() or mask[:, :m].any() or mask[:, -m:].any())


def fit_volume(polygon_px: np.ndarray, n, d, K, mask: np.ndarray,
               gray: np.ndarray | None = None, gravity: np.ndarray | None = None) -> dict | None:
    """Best-scoring solid for one volume outline.

    Tries the shape families in turn. Where `gray` is given, interior ridge
    lines (idea 2) look for the apex first, which matters because a pyramid's
    apex often projects inside its own outline and is then not an outline
    vertex at all. Each hypothesis is scored by outline IoU; because the
    outline cannot separate an assumed apex height from a solved one, the
    exactly-solved families get EXACT_FIT_BONUS so they win a tie.

    Returns the winning fit with `faces` (each carrying steepness and facing
    when `gravity` is given), `h_source`, `iou` and the diagnostics the
    evaluation needs, or None when nothing plausible fitted.
    """
    mask = np.asarray(mask).astype(bool)
    size = np.sqrt(max(float(mask.sum()), 1.0))
    #The fit derives its own outline, at a finer tolerance than the one
    #run_detection hands over; see outline_from_mask.
    outline = outline_from_mask(mask)
    if outline is None:
        outline = np.asarray(polygon_px, dtype=float).reshape(-1, 2)
    candidates = []

    apex_from_ridges, ridge_inliers, segments = None, 0, np.zeros((0, 4))
    if gray is not None:
        segments = ridge_segments(gray, mask)
        found = converge_point(segments, RIDGE_INLIER_FRACTION * size)
        if found is not None:
            apex_from_ridges, ridge_inliers = found

    for k in (3, 4, 5):
        corners = dominant_corners(outline, k)
        if corners is None:
            continue
        #Apex found by its own ridges: every outline corner is then a base
        #corner. This is the path that matters - the apex projects INSIDE the
        #outline on 85% of pyramids, where no outline vertex can ever be it.
        if apex_from_ridges is not None:
            fit = fit_pyramid(corners, apex_from_ridges, n, d, K)
            if fit:
                fit.update(shape=f"pyramid-{k}", apex_px=apex_from_ridges,
                           apex_source="ridges", ridge_inliers=ridge_inliers)
                candidates.append(fit)
        #Fallback: each corner in turn is the apex and the rest are the base.
        #Costs 20 cm and up to 33 deg against a ridge apex, so it is a last
        #resort that the reprojection gate is expected to reject.
        for i in range(k):
            base = np.delete(corners, i, axis=0)
            fit = fit_pyramid(base, corners[i], n, d, K)
            if fit:
                fit.update(shape=f"pyramid-{k - 1}", apex_px=corners[i],
                           apex_source="outline", ridge_inliers=0)
                candidates.append(fit)

    six = dominant_corners(outline, 6)
    if six is not None:
        #A wedge's hexagonal outline INTERLEAVES base and ridge corners
        #(base, base, ridge, base, base, ridge), so its two ridge corners sit
        #opposite each other, three apart - never adjacent. With the base
        #taken in cyclic order, the ridge corner between base[1] and base[2]
        #is the one fit_ridge anchors first, and the pairing can run either
        #way round, so both orders are tried.
        #The base has to be listed in CYCLIC order starting after a ridge
        #corner, not in increasing index order: listing it as [0,1,3,4] only
        #lands on fit_ridge's anchoring when the lowest base index happens to
        #follow a ridge corner, which is true for the ridge pairs (0,3) and
        #(2,5) and false for (1,4) - and that one phase lost 8 of 15 wedges
        #(Tester, 2026-11-20). Both rolls and both ridge orders are tried so
        #no phase depends on getting the convention right by luck.
        for i in range(3):
            cyclic = [(i + 1) % 6, (i + 2) % 6, (i + 4) % 6, (i + 5) % 6]
            for shift in (0, 2):
                base_idx = cyclic[shift:] + cyclic[:shift]
                for ridge in ([(i + 3) % 6, i], [i, (i + 3) % 6]):
                    fit = fit_ridge(six[base_idx], six[ridge], n, d, K)
                    if fit:
                        fit.update(shape="wedge", apex_px=None, apex_source="outline",
                                   ridge_inliers=ridge_inliers)
                        candidates.append(fit)
        #A box reaches its outline as three base corners then three top ones
        #when three faces are visible, or as FOUR base and two top when only
        #two are - which is the common case in a portrait frame, and left 7 of
        #16 box views unfitted until it was handled. Which corner starts the
        #run is unknown, and so is the winding.
        for start in range(6):
            order = np.roll(np.arange(6), -start)
            for sequence in (order, order[::-1]):
                for fitter in (fit_box_hexagon, fit_box_partial):
                    fit = fitter(six[sequence], n, d, K)
                    if fit:
                        fit.update(shape=fit["h_source"], apex_px=None,
                                   apex_source="outline", ridge_inliers=ridge_inliers)
                        candidates.append(fit)

    if not candidates:
        return None
    for fit in candidates:
        fit["iou"] = silhouette_iou(fit["vertices"], K, mask)
        fit["reprojection_norm"] = round(fit["reprojection_px"] / size, 3)
        #Rank on reprojection, not on IoU. IoU cannot separate a right fit
        #from a wrong one at all - broken fits scored 0.98-1.01 while being
        #35 cm out - because sliding a vertex along its ray leaves the
        #outline untouched. Reprojection measures whether the anchors and the
        #observed vertices actually agree, which is a different question.
        exact = fit["h_source"] != "centroid-assumed"
        fit["rank"] = (-fit["reprojection_norm"]
                       + fit["iou"]
                       + (EXACT_FIT_BONUS if exact else 0.0))
    best = max(candidates, key=lambda f: f["rank"])
    best["considered"] = len(candidates)
    best["ridge_segments"] = int(len(segments))
    best["depth_cm"] = round(float(np.max(best["heights"])), 1)
    #The gate production depends on. A curved volume with no primitive here
    #came back as a confident pyramid at iou 0.972 and three times its real
    #depth, and only the reprojection error gave it away. The frame-border
    #test is separate because reprojection cannot see a clipped base - see
    #touches_frame_border.
    best["clipped_by_frame"] = touches_frame_border(mask)
    #A pyramid whose apex is an outline corner AND whose height comes from the
    #centroid assumption is never trusted. That fit has two equations for one
    #unknown, so almost any outline corner is self-consistent, and on real
    #photos it passed the reprojection gate at 55-119 cm deep on volumes a
    #quarter of that (field captures, 2026-11-20). An apex found from the
    #volume's own ridges is independent evidence and keeps its trust.
    #And no centroid-assumed pyramid is trusted at all, ridge apex or not.
    #Catalogue research (2026-11-20): about half of commercial pyramids are
    #sold as offset or asymmetric, with the apex 15-25% of the base span off
    #centre - 7-12 cm on a 50 cm base, which the off-centre gain turns into
    #15 cm or more of height. A depth prior (median 0.33 x longest base edge,
    #p10-p90 0.25-0.45) still leaves about 7 deg of face error. So a pyramid
    #needs its height from outside - `height_cm`, e.g. a second photo - before
    #its faces can be trusted. `centroid_assumed` keeps the reason visible.
    best["guessed_apex"] = bool(best["h_source"] == "centroid-assumed"
                                and best.get("apex_source") == "outline")
    best["centroid_assumed"] = bool(best["h_source"] == "centroid-assumed")
    best["trusted"] = bool(best["reprojection_norm"] <= MAX_REPROJECTION_FRACTION
                           and not best["clipped_by_frame"]
                           and not best["centroid_assumed"])
    if gravity is not None:
        for face in best["faces"]:
            face.update(describe_face(face["normal"], n, gravity))
    return best


def hold_face(hold_px: np.ndarray, fit: dict, K: np.ndarray, n, d) -> dict | None:
    """Which of a volume's faces a hold sits on, and where that puts it in cm.

    This is what fixes a hold on a volume being measured as if it were on the
    wall: the hold's centroid is back-projected onto its FACE plane instead,
    so `standoff_cm` is how far it really stands off the wall. The nearest
    visible face wins when a ray crosses more than one.
    """
    n = np.asarray(n, dtype=float)
    ray = rays(np.asarray(hold_px, dtype=float).reshape(1, 2), K)[0]
    best = None
    for index, face in enumerate(fit["faces"]):
        if not face["visible"]:
            continue
        corners = face["corners"]
        normal = face["normal"]
        denominator = float(ray @ normal)
        if abs(denominator) < 1e-9:
            continue
        t = float(normal @ corners[0]) / denominator
        if t <= 0:
            continue
        point = ray * t
        #Inside the face? Test the triangle fan from corner 0, with a little
        #slack so a hold right on a ridge still lands on one of its faces.
        inside = False
        for i in range(1, len(corners) - 1):
            m = np.column_stack([corners[i] - corners[0], corners[i + 1] - corners[0]])
            coefficients, *_ = np.linalg.lstsq(m, point - corners[0], rcond=None)
            if (coefficients >= -0.02).all() and coefficients.sum() <= 1.02:
                inside = True
                break
        if not inside:
            continue
        if best is None or t < best["range_cm"]:
            best = {"face_index": index, "point_cm": point, "range_cm": t,
                    "standoff_cm": round(height_of(point, n, d), 1)}
    return best
