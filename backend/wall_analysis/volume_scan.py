"""Volume face angles from one photo plus a sideways burst (test feature).

Spec: docs/milestones/v0.2/38-volume-scan-trial/spec.md. Not used by /detect or /analysis.

How it works
------------
1. The photo's camera pose comes from the bolt grid: the homography of the
   panel under the volume (grid units -> px), split with K into R, t in cm.
   Wall frame = that panel's grid in cm, z = 0 on the wall.
2. Each burst frame's pose comes from the WALL homography between the photo
   and the frame (RANSAC over SIFT matches on plain wall on the same panel),
   decomposed with the photo's known wall plane: H = Kf (R + t n^T / d) Kp^-1.
   This needs no bolts in the frames.
3. A plane sweep: for heights 0..H_MAX_CM off the wall, each frame is warped
   onto the photo through the wall-parallel plane at that height; the windowed
   NCC is averaged over the frames, and each pixel keeps its best height.
4. Faces are sequential RANSAC planes on the resulting 3D points. A plane only
   counts as one compact patch in the photo (scattered outliers don't form one).
   Steepness and facing come from volume.describe_face.

The design history (and what failed) is in docs/features_deprecated/wall_size_hold_distance_handover.md, slice 11.
Synthetic test cases: backend/experiments/two_photo/synth.py.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from PIL import Image

from wall_analysis import angle
from wall_analysis import bolts
from wall_analysis import scale
from wall_analysis import volume

#Sweep resolution: the photo is processed at this scale (bolt holes are not
#needed here, only texture), and heights are tried every H_STEP_CM up to H_MAX_CM.
SWEEP_SCALE = 0.5
H_MAX_CM = 90.0
H_STEP_CM = 1.0
#NCC window (px at SWEEP_SCALE) and the tests a pixel's best height must pass:
#a good match, some texture in the window, and a clear winner over heights at
#least UNIQUE_SEP_CM away.
NCC_WIN = 13
MIN_NCC = 0.55
#Grey-level spread a window needs. Kept low on purpose: a face turned away from
#the light (an underside) is darker, so the same texture is fewer grey levels.
#At 4.0 the 4-sided pyramid's down-facing face lost most of its points and was
#missed; at 2.0 all four faces are found within 0.8°. The real guard against
#matching noise is MIN_NCC and MIN_GAP: noise doesn't correlate between photos.
MIN_STD = 2.0
MIN_GAP = 0.04
UNIQUE_SEP_CM = 4.0
#Context kept around the volume in the sweep crop (px at SWEEP_SCALE).
CROP_MARGIN = 40
#SIFT features are found at this scale; brute-force matches pass Lowe's ratio test.
FEATURE_SCALE = 0.5
RATIO = 0.8
#Wall homography: RANSAC tolerance (full-res px) and the support a frame needs.
WALL_RANSAC_PX = 3.0
MIN_WALL_INLIERS = 30
#Detections are grown by this much (full-res px) before "outside every
#detection" picks wall features.
DETECTION_DILATE_PX = 25
#A frame closer than this to the photo's camera gives no usable parallax; one
#further than this is a wrong pose, not a step.
MIN_BASELINE_CM = 5.0
MAX_BASELINE_CM = 500.0
MIN_FRAMES = 2
MAX_FRAMES = 12
#An outline smaller than this (full-res px^2) is no volume: a mis-tap, or a
#collinear / single-point polygon.
MIN_POLYGON_AREA_PX = 100.0
#Faces: RANSAC tolerance (cm), minimum points per face, the share of a
#plane's inliers that must form one patch, and the share of all points a face
#needs to count towards the depth.
PLANE_TOL_CM = 2.0
MIN_FACE_POINTS = 75
COMPACT_FRAC = 0.6
DEPTH_FACE_FRAC = 0.03
MAX_FACES = 10
RANSAC_ITERATIONS = 600
RANSAC_SAMPLE = 4000
#A plane within this of the wall, and parallel to it, is wall seen through
#the outline, not a face.
WALL_PLANE_H_CM = 4.0
WALL_PARALLEL_COS = 0.97

#Line-up (slice 5). Each burst photo gets a wall homography (photo -> frame):
#  - directly, when enough of the photo's wall features match it (an anchor), or
#  - through a posed neighbour (up to CHAIN_REACH photos away in the burst):
#    the neighbour -> frame homography on all features, tried for up to
#    CHAIN_PLANES planes, composed with the neighbour's own.
#Either way the guess is then refined against the photo: the frame is warped
#into the photo's view (so the wall looks as it does in the photo, however far
#round the user walked), and the photo's wall features are matched to it near
#where the guess puts them (GATE_COARSE_PX, then GATE_FINE_PX), together with
#the posed neighbours' wall features. The refined homography is kept only if
#it passes the pose check: MIN_WALL_INLIERS inliers, MIN_PHOTO_INLIERS of
#them straight from the photo (so chained errors can't drift unchecked), and
#the wall agreeing with the photo once warped. "Agreeing" is a peak test, not
#a level: a correct pose must beat the same pose nudged NCC_NUDGE_PX by
#MIN_NCC_PEAK. On trial 1 a level couldn't work - an oblique frame's warp is
#soft, so a correct pose scored 0.11-0.24 while a near-frontal pose 15 px off
#still scored up to 0.23 - but every correct pose beat its nudged copies by
#0.11 or more, and the nudged copies sat at -0.16..0.09.
ANCHOR_MIN_INLIERS = 12
GATE_COARSE_PX = 80.0
GATE_FINE_PX = 20.0
COARSE_RANSAC_PX = 8.0
CHAIN_RANSAC_PX = 8.0
CHAIN_PLANES = 3
CHAIN_REACH = 2
MIN_PHOTO_INLIERS = 8
MIN_WALL_NCC = 0.08
MIN_NCC_PEAK = 0.06
NCC_NUDGE_PX = 12.0
MIN_NCC_PIXELS = 2000
#High-pass for the wall check (sigma, px at FEATURE_SCALE): lighting changes
#between views, texture doesn't.
NCC_HIGHPASS_SIGMA = 6.0
#Faces from the base outline (slice 7). Real volume faces are mostly smooth
#plastic with nothing for the sweep to match: on trial 1 only edges and ridges
#came back as 3D points, so planes fitted to dense points found few faces
#(synthetic faces are speckled, which is why that passed AC 1). A face that
#meets the wall is found from its base edge instead. The volume is convex, so
#the face's plane is the supporting plane through that edge: the steepest tilt
#up from the wall that the raised points beside the edge reach
#(BASE_TILT_PERCENTILE, against stray matches), refined to the median tilt of
#the points within SUPPORT_DEG of it. An outline edge only counts as a base
#edge when the sweep puts the points along it on the wall (a raised edge seen
#from the side, like a box's front edge from above, is not one). Faces that
#don't meet the wall still come from the dense plane fit below.
BASE_SIMPLIFY_FRAC = 0.03     # of the outline's perimeter (cv2.approxPolyDP)
MIN_BASE_EDGE_CM = 8.0
MIN_RAISED_CM = 1.5           # points this far off the wall count as raised
MIN_INSET_CM = 3.0            # raised points nearer the edge than this (in the wall plane) are ignored
BASE_TILT_PERCENTILE = 95
MIN_EDGE_POINTS = 20
SUPPORT_DEG = 4.0
EDGE_BAND_PX = 8.0            # full-res px inside the outline: the points that say if an edge is on the wall
MIN_EDGE_BAND_POINTS = 10
#The band's 25th-percentile height must be under this: a sloping face is a little
#off the wall even 8 px in, and stray matches sit high. Trial 1: base edges
#0-3 cm (the wedge's lower edges 7), raised outline edges 11-15 cm.
BASE_EDGE_LOW_PERCENTILE = 25
BASE_EDGE_MAX_H_CM = 8.0
DUPLICATE_FACE_DEG = 8.0      # a dense-fit face this close to a base-edge face is the same face

#No blur gate: tried in slice 5 (sharpness below a share of the burst's
#median), but trial 1's blurred and sharp frames overlap too much for any
#cut-off (28 vs 28-45 vs 55), and the pose check already decides.
#The wall mask is decided on a grid this coarse (full-res px).
MASK_STEP_PX = 16


#Focal length (slice 6). With no EXIF focal, phones' 26 mm equivalent is for
#the full 4:3 sensor, and a photo cropped to the screen's shape (the app's are
#1776 x 3840) keeps the sensor's long side. angle.focal_px spreads 26 mm over
#the CROP's diagonal instead: 2542 px where 2884 px is right, and with burst
#photos turned 30-45 deg that 13 % error broke the poses (trial 1). For a 4:3
#photo both give the same value. angle.focal_px itself is left alone: /detect
#uses it and must not change in this issue (spec AC 4).
SENSOR_LONG_SIDE_35MM = 0.8 * angle.DIAGONAL_35MM  # a 4:3 frame's long side, in 35 mm-equivalent mm
#The cross-check: oblique views of the square bolt grid fix the focal length
#(its two axes must come out the same length). Views turned less than this
#give no useful estimate.
FOCAL_CHECK_MIN_TURN_DEG = 15.0


def _focal_px(size, focal_35mm: float | None) -> float:
    if focal_35mm:
        return angle.focal_px(size, focal_35mm)  # EXIF's equivalent is for the image as recorded
    return angle.DEFAULT_FOCAL_35MM / SENSOR_LONG_SIDE_35MM * float(max(size))


def _focal_check(H_grid, size) -> float | None:
    """The focal length (px) at which the bolt grid's two axes come out the
    same length, for one view: H_grid maps grid units to that view's pixels.
    Assumes square pixels and the principal point at the centre."""
    w, h = size
    G = np.array([[1, 0, -w / 2], [0, 1, -h / 2], [0, 0, 1.0]]) @ H_grid
    (a1, b1, c1), (a2, b2, c2) = G[:, 0], G[:, 1]
    den = c2 * c2 - c1 * c1
    if abs(den) < 1e-12:
        return None
    f2 = (a1 * a1 + b1 * b1 - a2 * a2 - b2 * b2) / den
    return float(np.sqrt(f2)) if f2 > 0 else None


class ScanError(ValueError):
    """A scan that can't run, with a message fit for the user. `diagnostics`
    is the per-frame list (as in the result's `frame_diagnostics`) when the
    scan got as far as lining frames up, else None."""

    def __init__(self, message: str, diagnostics: list[dict] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics


def _gray(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)


def _polygon_mask(polygon_norm, size) -> np.ndarray:
    w, h = size
    pts = np.array([[float(p["x"]) * w, float(p["y"]) * h] for p in polygon_norm], np.float64)
    if len(pts) < 3 or not np.isfinite(pts).all():
        raise ScanError("The volume outline is not a polygon.")
    #A collinear or single-point outline still fills a line of pixels, so the
    #mask check below alone doesn't catch it. The hull's area, not the
    #polygon's: a self-crossing outline's lobes would cancel.
    if cv2.contourArea(cv2.convexHull(pts.astype(np.float32))) < MIN_POLYGON_AREA_PX:
        raise ScanError("The volume outline is empty.")
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 1)
    if not mask.any():
        raise ScanError("The volume outline is empty.")
    return mask.astype(bool)


def _features(gray: np.ndarray):
    small = cv2.resize(gray, None, fx=FEATURE_SCALE, fy=FEATURE_SCALE, interpolation=cv2.INTER_AREA)
    keypoints, descriptors = cv2.SIFT_create(nfeatures=20000).detectAndCompute(small, None)
    xy = np.array([k.pt for k in keypoints], np.float64).reshape(-1, 2) / FEATURE_SCALE
    return xy, descriptors


def _match(des_a, des_b) -> np.ndarray:
    """Lowe-ratio matches a -> b. Brute force, not FLANN: FLANN's randomised
    trees draw on the C library's rand(), so the same scan gave different
    frames and faces from run to run (slice 4, 2026-11-27)."""
    if des_a is None or des_b is None or len(des_a) < 1 or len(des_b) < 2:
        return np.zeros((0, 2), int)
    bf = cv2.BFMatcher(cv2.NORM_L2)
    pairs = [(m[0].queryIdx, m[0].trainIdx)
             for m in bf.knnMatch(des_a.astype(np.float32), des_b.astype(np.float32), k=2)
             if len(m) == 2 and m[0].distance < RATIO * m[1].distance]
    return np.array(pairs, int).reshape(-1, 2)


def _photo_pose(lattice, centre_px, K, spacing_cm):
    """The photo's camera: R, t (camera <- wall cm), the panel and its homography."""
    homographies = scale.panel_homographies(lattice)
    if not homographies:
        return None
    idx, _ = scale.knn(np.asarray([centre_px], float), lattice.xy, volume.PANEL_NEIGHBOURS)
    near = [int(lattice.panel[i]) for i in idx[0] if i >= 0 and int(lattice.panel[i]) in homographies]
    if not near:
        return None
    panel = max(set(near), key=near.count)
    H = homographies[panel]
    A = np.linalg.inv(K) @ H
    l1, l2 = np.linalg.norm(A[:, 0]), np.linalg.norm(A[:, 1])
    if l1 < 1e-12 or l2 < 1e-12:
        return None
    s = 2.0 / (l1 + l2)
    r1, r2, t = s * A[:, 0], s * A[:, 1], s * A[:, 2]
    if t[2] < 0:
        r1, r2, t = -r1, -r2, -t
    U, _, Vt = np.linalg.svd(np.column_stack([r1, r2, np.cross(r1, r2)]))
    R = U @ Vt
    return {"R": R, "t": t * spacing_cm, "panel": panel, "axis_ratio": float(l1 / l2), "H": H}


def _sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian at FEATURE_SCALE: low = blurred (diagnostic only)."""
    small = cv2.resize(gray, None, fx=FEATURE_SCALE, fy=FEATURE_SCALE, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(small, cv2.CV_64F).var())


def _pose_from_h(Kp, Kf, R, t, H):
    """A frame's R, t from the photo->frame wall homography H, decomposed with
    the photo's known wall plane: H = Kf (R + t n^T / d) Kp^-1."""
    n_c = R @ np.array([0.0, 0.0, 1.0])
    off = float((R.T @ t)[2])  # the wall in the photo's camera: n_c . X = off
    want = n_c * np.sign(off)  # cv2's normal convention: n . X = d > 0
    G = np.linalg.inv(Kf) @ H @ Kp
    _, Rs, ts, ns = cv2.decomposeHomographyMat(G, np.eye(3))
    k = int(np.argmax([float(n.ravel() @ want) for n in ns]))
    Rrel, trel = Rs[k], ts[k].ravel() * abs(off)
    Rf, tf = Rrel @ R, Rrel @ t + trel
    baseline = float(np.linalg.norm(-R.T @ t + Rf.T @ tf))
    turn = float(np.degrees(np.arccos(np.clip((np.trace(Rrel) - 1) / 2, -1.0, 1.0))))
    return {"R": Rf, "t": tf, "baseline_cm": baseline, "turn_deg": turn}


def _wall_mask(size, lattice, panel, excluded) -> np.ndarray:
    """Photo pixels on the volume's panel (most of the 6 nearest bolts are on
    it), outside `excluded`. Decided on a MASK_STEP_PX grid."""
    w, h = size
    gy, gx = np.mgrid[0:h:MASK_STEP_PX, 0:w:MASK_STEP_PX]
    nn, _ = scale.knn(np.column_stack([gx.ravel(), gy.ravel()]).astype(float), lattice.xy, 6)
    valid = nn >= 0
    same = (lattice.panel[np.where(valid, nn, 0)] == panel) & valid
    on = (same.sum(1) > 0.5 * valid.sum(1)) & valid.any(1)
    coarse = on.reshape(gy.shape).astype(np.uint8)
    return cv2.resize(coarse, (w, h), interpolation=cv2.INTER_NEAREST).astype(bool) & ~excluded


def _to(H, xy) -> np.ndarray:
    xy = np.asarray(xy, np.float64).reshape(-1, 1, 2)
    if not len(xy):
        return xy.reshape(0, 2)
    return cv2.perspectiveTransform(xy, H).reshape(-1, 2)


def _gated(xa, da, xb, db, gate) -> np.ndarray:
    """Matches a -> b where a's points are already in b's coordinates: only b's
    features within `gate` px are candidates, and the best must pass the ratio
    test against the second best of those. Brute force per cell, deterministic."""
    if len(xa) == 0 or len(xb) < 2 or da is None or db is None:
        return np.zeros((0, 2), int)
    cell_b = np.floor(xb / gate).astype(np.int64)
    order = np.lexsort((cell_b[:, 1], cell_b[:, 0]))
    cells = {}
    for j in order:
        cells.setdefault((int(cell_b[j, 0]), int(cell_b[j, 1])), []).append(j)
    out = []
    da, db = da.astype(np.float32), db.astype(np.float32)
    for i, (cx, cy) in enumerate(np.floor(xa / gate).astype(np.int64)):
        cand = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in cells.get((int(cx) + dx, int(cy) + dy), ())]
        if not cand:
            continue
        cand = np.array(cand)
        cand = cand[np.hypot(*(xb[cand] - xa[i]).T) <= gate]
        if not len(cand):
            continue
        dist = np.linalg.norm(db[cand] - da[i], axis=1)
        o = np.argsort(dist, kind="stable")
        if len(o) >= 2 and dist[o[0]] >= RATIO * dist[o[1]]:
            continue
        out.append((i, int(cand[o[0]])))
    return np.array(out, int).reshape(-1, 2)


def _rectify(fgray, H, size):
    """The frame warped into the photo's view through H (photo -> frame), at
    FEATURE_SCALE, with its valid-pixel mask."""
    w, h = size
    S = np.diag([FEATURE_SCALE, FEATURE_SCALE, 1.0])
    M = H @ np.linalg.inv(S)
    out = (int(round(w * FEATURE_SCALE)), int(round(h * FEATURE_SCALE)))
    rect = cv2.warpPerspective(fgray, M, out, flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    valid = cv2.warpPerspective(np.full_like(fgray, 255), M, out, flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP)
    return rect, valid


def _highpass(img: np.ndarray) -> np.ndarray:
    img = img.astype(np.float32)
    return img - cv2.GaussianBlur(img, (0, 0), NCC_HIGHPASS_SIGMA)


def _wall_ncc(ctx, fgray, H) -> tuple[float, float] | None:
    """Agreement of the plain wall around the volume, the photo against the
    frame warped into the photo's view through H: (NCC at H, its lead over H
    nudged NCC_NUDGE_PX up / down / left / right in the frame). None with too
    little wall in view."""
    def ncc(Hx, m=None):
        rect, valid = _rectify(fgray, Hx, ctx["size"])
        if m is None:
            m = ctx["wall_small"] & (cv2.erode(valid, np.ones((5, 5), np.uint8)) > 0)
            if m.sum() < MIN_NCC_PIXELS:
                return None, m
        a, b = ctx["photo_hp"][m], _highpass(rect)[m]
        a, b = a - a.mean(), b - b.mean()
        return float((a * b).mean() / (a.std() * b.std() + 1e-6)), m

    at, m = ncc(H)
    if at is None:
        return None
    s = NCC_NUDGE_PX
    nudged = [ncc(np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1.0]]) @ H, m)[0]
              for dx, dy in ((s, 0), (-s, 0), (0, s), (0, -s))]
    return at, at - max(nudged)


def _refine(ctx, k, Hpred, Hs, gate, tol):
    """Photo -> frame k homography from (a) the photo's wall features against
    the frame warped into the photo's view by Hpred, and (b) posed neighbours'
    wall features against frame k, all in photo coordinates. Returns (H, counts)."""
    size, (xk, dk) = ctx["size"], ctx["feats"][k]
    A, B, from_photo = [], [], []
    rect, valid = _rectify(ctx["grays"][k], Hpred, size)
    kp, des = cv2.SIFT_create(nfeatures=20000).detectAndCompute(rect, valid)
    if des is not None and len(kp):
        xr = np.array([p.pt for p in kp], np.float64) / FEATURE_SCALE
        M = _gated(ctx["xy_w"], ctx["des_w"], xr, des, gate)
        if len(M):
            A.append(ctx["xy_w"][M[:, 0]])
            B.append(_to(Hpred, xr[M[:, 1]]))
            from_photo.append(np.ones(len(M), bool))
    w, h = size
    for j in range(max(0, k - CHAIN_REACH), min(len(Hs), k + CHAIN_REACH + 1)):
        if j == k or Hs[j] is None:
            continue
        xj, dj = ctx["feats"][j]
        back = _to(np.linalg.inv(Hs[j]), xj)  # frame j's features in photo px
        ij = np.round(back).astype(int)
        inside = (ij[:, 0] >= 0) & (ij[:, 1] >= 0) & (ij[:, 0] < w) & (ij[:, 1] < h)
        on_wall = np.zeros(len(xj), bool)
        on_wall[inside] = ctx["wall_mask"][ij[inside, 1], ij[inside, 0]]
        if not on_wall.any():
            continue
        M = _gated(_to(Hpred, back[on_wall]), dj[on_wall], xk, dk, gate)
        if len(M):
            A.append(back[on_wall][M[:, 0]])
            B.append(xk[M[:, 1]])
            from_photo.append(np.zeros(len(M), bool))
    if not A or sum(len(a) for a in A) < MIN_WALL_INLIERS:
        return None, {"inliers": 0, "photo_inliers": 0}
    A, B, from_photo = np.vstack(A), np.vstack(B), np.concatenate(from_photo)
    H, inl = cv2.findHomography(A, B, cv2.RANSAC, tol)
    if H is None or inl is None:
        return None, {"inliers": 0, "photo_inliers": 0}
    inl = inl.ravel().astype(bool)
    return H, {"inliers": int(inl.sum()), "photo_inliers": int((inl & from_photo).sum())}


def _try_frame(ctx, k, Hpred, Hs):
    """Refine a guess for frame k (coarse, then fine) and run the pose check.
    Returns (H or None, info)."""
    H1, c1 = _refine(ctx, k, Hpred, Hs, GATE_COARSE_PX, COARSE_RANSAC_PX)
    if H1 is None or c1["inliers"] < MIN_WALL_INLIERS:
        return None, {"reason": "too few wall inliers", "wall_inliers": c1["inliers"]}
    H2, c2 = _refine(ctx, k, H1, Hs, GATE_FINE_PX, WALL_RANSAC_PX)
    info = {"wall_inliers": c2["inliers"], "photo_inliers": c2["photo_inliers"]}
    if H2 is None or c2["inliers"] < MIN_WALL_INLIERS:
        return None, {**info, "reason": "too few wall inliers"}
    if c2["photo_inliers"] < MIN_PHOTO_INLIERS:
        return None, {**info, "reason": "pose check: too few matches with the photo"}
    check = _wall_ncc(ctx, ctx["grays"][k], H2)
    if check is not None:
        info.update(wall_ncc=round(check[0], 2), wall_ncc_peak=round(check[1], 2))
    if check is None or check[0] < MIN_WALL_NCC or check[1] < MIN_NCC_PEAK:
        #Not trusted for the sweep, but close enough to chain the next frame
        #from: that frame is checked against the photo on its own.
        return None, {**info, "reason": "pose check: the wall doesn't agree with the photo", "_link": H2}
    return H2, info


def _line_up(ctx):
    """Photo -> frame wall homographies (None where a frame can't be lined up)
    and per-frame line-up info. Anchors first, then chains outwards. A frame
    that failed only the wall check still serves as a link in a chain."""
    n = len(ctx["grays"])
    Hs, links, info = [None] * n, [None] * n, [{} for _ in range(n)]

    def settle(k, Hk, more, linked_from):
        link = more.pop("_link", None)
        info[k].update(more)
        if Hk is not None:
            Hs[k] = links[k] = Hk
            info[k]["linked_from"] = linked_from
            info[k].pop("reason", None)
        elif link is not None and links[k] is None:
            links[k] = link

    for k in range(n):
        xk, dk = ctx["feats"][k]
        M = _match(ctx["des_w"], dk)
        info[k] = {"wall_matches": int(len(M)), "reason": "too few wall matches"}
        if len(M) < ANCHOR_MIN_INLIERS:
            continue
        H, inl = cv2.findHomography(ctx["xy_w"][M[:, 0]], xk[M[:, 1]], cv2.RANSAC, WALL_RANSAC_PX)
        info[k]["wall_inliers"] = 0 if inl is None else int(inl.sum())
        if H is None or info[k]["wall_inliers"] < ANCHOR_MIN_INLIERS:
            info[k]["reason"] = "too few wall inliers"
            continue
        settle(k, *_try_frame(ctx, k, H, Hs), None)
    tried = set()
    changed = True
    while changed:
        changed = False
        for k in range(n):
            if Hs[k] is not None:
                continue
            reach = sorted(range(max(0, k - CHAIN_REACH), min(n, k + CHAIN_REACH + 1)), key=lambda j: (abs(j - k), j))
            #Retry a pair only when more of k's neighbours have been lined up since.
            support = sum(Hs[j] is not None for j in reach)
            for j in reach:
                if j == k or links[j] is None or (j, k, support) in tried:
                    continue
                tried.add((j, k, support))
                (xj, dj), (xk, dk) = ctx["feats"][j], ctx["feats"][k]
                M = _match(dj, dk)
                a, b = (xj[M[:, 0]], xk[M[:, 1]]) if len(M) else (np.zeros((0, 2)), np.zeros((0, 2)))
                for _ in range(CHAIN_PLANES):
                    if len(a) < MIN_WALL_INLIERS:
                        break
                    Hjk, inl = cv2.findHomography(a, b, cv2.RANSAC, CHAIN_RANSAC_PX)
                    if Hjk is None or inl is None or int(inl.sum()) < MIN_WALL_INLIERS:
                        break
                    had_link = links[k] is not None
                    settle(k, *_try_frame(ctx, k, Hjk @ links[j], Hs), j)
                    if Hs[k] is not None or (links[k] is not None and not had_link):
                        changed = True
                    if Hs[k] is not None:
                        break
                    keep = ~inl.ravel().astype(bool)
                    a, b = a[keep], b[keep]
                if Hs[k] is not None:
                    break
    return Hs, info


def _segment_distance(px: np.ndarray, p: np.ndarray, q: np.ndarray) -> np.ndarray:
    d = q - p
    t = np.clip(((px - p) @ d) / max(float(d @ d), 1e-9), 0.0, 1.0)
    return np.linalg.norm(px - (p + t[:, None] * d), axis=1)


def _base_edge_faces(mask, X, hh, px, backproject, side) -> list[dict]:
    """Faces through the base outline's edges (see BASE_SIMPLIFY_FRAC).
    X: confident 3D points (wall frame, cm), hh their heights off the wall, px
    their full-res photo pixels. `backproject(px, h)` gives wall-frame points.
    Each edge's face uses only the points nearest that edge in the photo (its
    region: for a pyramid or a wedge, the volume split along its ridges), so
    another face's ridge can't lend it a tilt.
    Returns [{"n": outward normal (wall frame), "support": point indices,
    "region": point indices, "base_px": the edge's two photo pixels, "alpha": tilt (deg)}]."""
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs or len(X) == 0:
        return []
    c = max(cs, key=cv2.contourArea)
    poly = cv2.approxPolyDP(c, BASE_SIMPLIFY_FRAC * cv2.arcLength(c, True), True).reshape(-1, 2).astype(float)
    if len(poly) < 3:
        return []
    B = backproject(poly, np.zeros(len(poly)))
    centre = B.mean(0)
    z_hat = np.array([0.0, 0.0, side])
    z = X @ z_hat
    raised = hh >= MIN_RAISED_CM
    edges = [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]
    nearest = np.argmin(np.column_stack([_segment_distance(px, p, q) for p, q in edges]), axis=1)
    out = []
    for i, (p, q) in enumerate(edges):
        a, b = B[i], B[(i + 1) % len(B)]
        length = float(np.linalg.norm(b - a))
        if length < MIN_BASE_EDGE_CM:
            continue
        #On the wall? The confident points in a band just inside this edge.
        band = (nearest == i) & (_segment_distance(px, p, q) <= EDGE_BAND_PX)
        if (band.sum() < MIN_EDGE_BAND_POINTS
                or float(np.percentile(hh[band], BASE_EDGE_LOW_PERCENTILE)) > BASE_EDGE_MAX_H_CM):
            continue
        u = (b - a) / length
        m = np.cross(u, z_hat)
        m /= np.linalg.norm(m)
        if (centre - a) @ m > 0:
            m = -m  # m points out of the volume
        inset = -((X - a) @ m)
        region = np.nonzero(nearest == i)[0]
        idx = region[raised[region] & (inset[region] > MIN_INSET_CM)]
        if len(idx) < MIN_EDGE_POINTS:
            continue
        tilt = np.degrees(np.arctan2(z[idx], inset[idx]))
        alpha0 = float(np.percentile(tilt, BASE_TILT_PERCENTILE))
        sup = np.abs(tilt - alpha0) <= SUPPORT_DEG
        if not sup.any():
            continue
        alpha = float(np.median(tilt[sup]))
        v = -m + np.tan(np.radians(alpha)) * z_hat
        n = np.cross(u, v / np.linalg.norm(v))
        n /= np.linalg.norm(n)
        if n @ m < 0:
            n = -n
        out.append({"n": n, "support": idx[sup], "region": region, "base_px": np.array([p, q]), "alpha": alpha})
    return out


def _box(x):
    return cv2.boxFilter(x, cv2.CV_32F, (NCC_WIN, NCC_WIN))


def _sweep(A, x0, y0, Kp, R, t, frames):
    """Mean NCC over frames, per height, for the photo crop A (at SWEEP_SCALE)."""
    S = np.diag([SWEEP_SCALE, SWEEP_SCALE, 1.0])
    T = np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1.0]])
    Ka_inv = np.linalg.inv(S @ Kp)
    mA = _box(A)
    vA = _box(A * A) - mA ** 2
    hs = np.arange(0.0, H_MAX_CM + 1e-9, H_STEP_CM)
    total = np.zeros((len(hs),) + A.shape, np.float32)
    count = np.zeros((len(hs),) + A.shape, np.float32)
    n_c = R @ np.array([0.0, 0.0, 1.0])
    off = float((R.T @ t)[2])
    side = float(np.sign((-R.T @ t)[2]))  # +1 when the cameras are on the wall frame's +z side
    for f in frames:
        B = f["small"]
        ones = np.ones_like(B)
        Kb = S @ f["K"]
        Rrel = f["R"] @ R.T
        trel = f["t"] - Rrel @ t
        for i, h in enumerate(hs):
            d = side * h + off
            H = Kb @ (Rrel + np.outer(trel, n_c) / d) @ Ka_inv @ T
            Bw = cv2.warpPerspective(B, H, A.shape[::-1], flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
            valid = cv2.warpPerspective(ones, H, A.shape[::-1], flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP)
            mB = _box(Bw)
            vB = _box(Bw * Bw) - mB ** 2
            ncc = (_box(A * Bw) - mA * mB) / np.sqrt(np.maximum(vA * vB, 1e-6))
            ok = (_box(valid) > 0.99) & (vB > MIN_STD ** 2)
            total[i] += np.where(ok, ncc, 0)
            count[i] += ok
    mean = np.where(count > 0, total / np.maximum(count, 1), -2.0)
    return hs, mean, np.sqrt(np.maximum(vA, 0)), side


def _fit_plane(P, rng):
    """RANSAC plane. Candidates are scored on a random sample of at most
    RANSAC_SAMPLE points (the full set was 35 s of a 70 s scan at 100k
    points); the winner then takes its inliers from every point."""
    sample = P if len(P) <= RANSAC_SAMPLE else P[rng.choice(len(P), RANSAC_SAMPLE, replace=False)]
    best, best_count = None, -1
    for _ in range(RANSAC_ITERATIONS):
        s3 = sample[rng.choice(len(sample), 3, replace=False)]
        n = np.cross(s3[1] - s3[0], s3[2] - s3[0])
        norm = np.linalg.norm(n)
        if norm < 1e-6:
            continue
        n = n / norm
        count = int((np.abs((sample - s3[0]) @ n) < PLANE_TOL_CM).sum())
        if count > best_count:
            best, best_count = (s3[0], n), count
    if best is None:
        return None
    inl = np.abs((P - best[0]) @ best[1]) < PLANE_TOL_CM
    if inl.sum() < MIN_FACE_POINTS:
        return None
    Q = P[inl]
    c = Q.mean(0)
    return c, np.linalg.svd(Q - c, full_matrices=False)[2][2]


def scan_volume(photo: Image.Image, frames: list[Image.Image], volume_polygon, detections: list[dict],
                gravity_reading=None, focal_35mm: float | None = None, bolt_spacing_cm: float = 25.0) -> dict:
    """Face angles of one volume from an upright photo and an upright burst.

    `volume_polygon` is the volume's outline, normalised on the photo;
    `detections` are /detect's (to keep bolt and wall features off holds).
    Raises ScanError when the scan can't run.
    """
    started = time.perf_counter()
    if len(frames) < MIN_FRAMES:
        raise ScanError(f"Need at least {MIN_FRAMES} burst photos, got {len(frames)}.")
    source = list(range(len(frames)))  # each frame's index in the burst as sent
    if len(frames) > MAX_FRAMES:  # evenly spread, keeping both ends of the step
        source = [int(i) for i in np.unique(np.round(np.linspace(0, len(frames) - 1, MAX_FRAMES)).astype(int))]
        frames = [frames[i] for i in source]
    size = photo.size
    mask = _polygon_mask(volume_polygon, size)
    Kp = volume.camera_matrix(size, _focal_px(size, focal_35mm))
    gray = _gray(photo)

    found = bolts.detect_bolt_holes(photo, detections)
    if len(found) < 6:
        raise ScanError("No bolt holes found around the volume.")
    lattice = scale.fit_lattice(np.array([[b["x"] * size[0], b["y"] * size[1]] for b in found]))
    ys, xs = np.nonzero(mask)
    pose = _photo_pose(lattice, np.array([xs.mean(), ys.mean()]), Kp, bolt_spacing_cm)
    if pose is None:
        raise ScanError("No bolt grid next to the volume.")
    R, t = pose["R"], pose["t"]

    #Wall features: outside every detection (grown), on the volume's panel.
    any_det = np.zeros((size[1], size[0]), np.uint8)
    for d in detections:
        pts = np.array([[p["x"] * size[0], p["y"] * size[1]] for p in d.get("polygon", [])], np.int32)
        if len(pts) >= 3:
            cv2.fillPoly(any_det, [pts], 1)
    any_det = cv2.dilate(any_det | mask.astype(np.uint8),
                         np.ones((2 * DETECTION_DILATE_PX + 1,) * 2, np.uint8)).astype(bool)
    wall_mask = _wall_mask(size, lattice, pose["panel"], any_det)
    xy_p, des_p = _features(gray)
    ij = np.clip(np.round(xy_p).astype(int), 0, [size[0] - 1, size[1] - 1])
    wall_p = wall_mask[ij[:, 1], ij[:, 0]]
    #Only the photo's wall features are matched: the ratio test looks at the
    #frame's features, so dropping the others changes no match, and it keeps
    #the brute-force matcher fast.
    small_size = (int(round(size[0] * FEATURE_SCALE)), int(round(size[1] * FEATURE_SCALE)))
    grays = [_gray(f) for f in frames]
    ctx = {"size": size, "wall_mask": wall_mask, "xy_w": xy_p[wall_p],
           "des_w": des_p[wall_p] if des_p is not None else None,
           "wall_small": cv2.resize(wall_mask.astype(np.uint8), small_size, interpolation=cv2.INTER_NEAREST).astype(bool),
           "photo_hp": _highpass(cv2.resize(gray, small_size, interpolation=cv2.INTER_AREA)),
           "grays": grays, "feats": [_features(g) for g in grays]}
    Hs, lineup = _line_up(ctx)

    sharp = [_sharpness(g) for g in grays]
    posed, diagnostics = [], []
    for k, frame in enumerate(frames):
        info = {"frame": k, "source_frame": source[k], "sharpness": round(sharp[k], 1), **lineup[k]}
        if Hs[k] is not None:
            Kf = volume.camera_matrix(frame.size, _focal_px(frame.size, focal_35mm))
            fp = _pose_from_h(Kp, Kf, R, t, Hs[k])
            if not (np.isfinite(fp["baseline_cm"]) and np.isfinite(fp["turn_deg"])):
                info["reason"] = "bad pose"
            else:
                info.update(baseline_cm=round(fp["baseline_cm"], 1), turn_deg=round(fp["turn_deg"], 1))
                if not MIN_BASELINE_CM <= fp["baseline_cm"] <= MAX_BASELINE_CM:
                    info["reason"] = "baseline too short" if fp["baseline_cm"] < MIN_BASELINE_CM else "baseline too long"
                else:
                    small = cv2.resize(grays[k], None, fx=SWEEP_SCALE, fy=SWEEP_SCALE,
                                       interpolation=cv2.INTER_AREA).astype(np.float32)
                    posed.append({**fp, "K": Kf, "small": small})
                    info["used"] = True
        info.setdefault("used", False)
        diagnostics.append(info)
    checks = [_focal_check(Hs[d["frame"]] @ pose["H"], frames[d["frame"]].size) for d in diagnostics
              if d["used"] and d.get("turn_deg", 0) >= FOCAL_CHECK_MIN_TURN_DEG]
    checks = [c for c in checks if c is not None]
    focal_check = round(float(np.median(checks))) if len(checks) >= 2 else None
    if len(posed) < MIN_FRAMES:
        raise ScanError("Couldn't line up enough burst photos with the wall. "
                        "Keep the volume and the wall around it in frame, and step sideways slowly.",
                        diagnostics)

    #Sweep on a crop around the volume.
    m_s = cv2.resize(mask.astype(np.uint8), None, fx=SWEEP_SCALE, fy=SWEEP_SCALE,
                     interpolation=cv2.INTER_NEAREST).astype(bool)
    sy, sx = np.nonzero(m_s)
    y0, y1 = max(0, sy.min() - CROP_MARGIN), min(m_s.shape[0], sy.max() + CROP_MARGIN + 1)
    x0, x1 = max(0, sx.min() - CROP_MARGIN), min(m_s.shape[1], sx.max() + CROP_MARGIN + 1)
    small_p = cv2.resize(gray, None, fx=SWEEP_SCALE, fy=SWEEP_SCALE, interpolation=cv2.INTER_AREA).astype(np.float32)
    A = small_p[y0:y1, x0:x1].copy()
    hs, ncc, sA, side = _sweep(A, x0, y0, Kp, R, t, posed)
    best = ncc.max(0)
    hbest = hs[ncc.argmax(0)]
    far = np.abs(hs[:, None, None] - hbest[None]) >= UNIQUE_SEP_CM
    second = np.where(far, ncc, -2.0).max(0)
    inside = cv2.erode(m_s[y0:y1, x0:x1].astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    good = inside & (best > MIN_NCC) & (sA > MIN_STD) & (best - second > MIN_GAP) & (hbest < H_MAX_CM)
    gy, gx = np.nonzero(good)
    hh = hbest[gy, gx]
    Ka_inv = np.linalg.inv(np.diag([SWEEP_SCALE, SWEEP_SCALE, 1.0]) @ Kp)
    Ca = -R.T @ t
    rays = (R.T @ (np.column_stack([gx + x0, gy + y0, np.ones(len(gx))]) @ Ka_inv.T).T).T
    X = Ca + ((side * hh - Ca[2]) / rays[:, 2])[:, None] * rays

    #Gravity and the wall, in the photo's camera.
    solved = angle.gravity_from_sensor(gravity_reading) if gravity_reading is not None else None
    g = solved[0] if solved is not None else angle.gravity_from_pitch(angle.DEFAULT_PITCH_DEG)
    wall_n = R @ np.array([0.0, 0.0, side])
    wall_angle = volume.describe_face(wall_n, wall_n, g)["steepness_deg"]

    faces, normals = [], []
    Kp_inv = np.linalg.inv(Kp)

    def backproject(pix, h):
        pix = np.asarray(pix, np.float64).reshape(-1, 2)
        r = (R.T @ (np.column_stack([pix, np.ones(len(pix))]) @ Kp_inv.T).T).T
        return Ca + ((side * np.asarray(h, np.float64) - Ca[2]) / r[:, 2])[:, None] * r

    px_full = np.column_stack([gx + x0, gy + y0]) / SWEEP_SCALE
    taken = np.zeros(len(X), bool)
    for bf in _base_edge_faces(mask, X, hh, px_full, backproject, side):
        #No "turned away from the camera" test: its points were matched in the
        #photo, so it is seen, and a few degrees of tilt error put a steep
        #underside's plane behind the camera (trial 1's pyramid bottom).
        d = volume.describe_face(R @ bf["n"], wall_n, g)
        pts = np.vstack([bf["base_px"], px_full[bf["region"]]]) * SWEEP_SCALE
        hull = cv2.convexHull(pts.astype(np.float32)).reshape(-1, 2)
        faces.append({"steepness_deg": d["steepness_deg"], "facing": d["facing"], "facing_deg": d["facing_deg"],
                      "outline": [{"x": round(float(px) / SWEEP_SCALE / size[0], 5),
                                   "y": round(float(py) / SWEEP_SCALE / size[1], 5)} for px, py in hull],
                      "n_points": int(len(bf["support"])), "method": "base_edge",
                      "base": [{"x": round(float(bx) / size[0], 5), "y": round(float(by) / size[1], 5)}
                               for bx, by in bf["base_px"]],
                      "_h95": float(np.percentile(hh[bf["support"]], 95)) if len(bf["support"]) else 0.0})
        normals.append(bf["n"])
        taken[bf["support"]] = True

    rng = np.random.default_rng(0)
    if (~taken).sum() >= 3 * MIN_FACE_POINTS:
        interior = np.array([*np.median(X[:, :2], 0), 0.0])
        remaining = np.nonzero(~taken)[0]
        while len(remaining) >= MIN_FACE_POINTS and len(faces) < MAX_FACES:
            fit = _fit_plane(X[remaining], rng)
            if fit is None:
                break
            c, n = fit
            on = np.abs((X[remaining] - c) @ n) < PLANE_TOL_CM
            members, remaining = remaining[on], remaining[~on]
            patch_img = np.zeros(good.shape, np.uint8)
            patch_img[gy[members], gx[members]] = 1
            _, comp = cv2.connectedComponents(cv2.dilate(patch_img, np.ones((5, 5), np.uint8)))
            cid = comp[gy[members], gx[members]]
            patch = members[cid == np.bincount(cid).argmax()]
            if len(patch) < max(MIN_FACE_POINTS, COMPACT_FRAC * len(members)):
                continue
            P = X[patch]
            c = P.mean(0)
            n = np.linalg.svd(P - c, full_matrices=False)[2][2]
            if (c - interior) @ n < 0:
                n = -n
            if abs(c[2]) < WALL_PLANE_H_CM and abs(n[2]) > WALL_PARALLEL_COS:
                continue
            if any(float(n @ m) > np.cos(np.radians(DUPLICATE_FACE_DEG)) for m in normals):
                continue
            normals.append(n)
            d = volume.describe_face(R @ n, wall_n, g)
            hull = cv2.convexHull(np.column_stack([gx[patch] + x0, gy[patch] + y0]).astype(np.float32)).reshape(-1, 2)
            outline = [{"x": round(float(px) / SWEEP_SCALE / size[0], 5), "y": round(float(py) / SWEEP_SCALE / size[1], 5)}
                       for px, py in hull]
            faces.append({"steepness_deg": d["steepness_deg"], "facing": d["facing"], "facing_deg": d["facing_deg"],
                          "outline": outline, "n_points": int(len(patch)), "method": "surface",
                          "_h95": float(np.percentile(hh[patch], 95))})
    big = [f for f in faces if f["n_points"] >= DEPTH_FACE_FRAC * max(1, len(hh))]
    #An uneven grid fit (axes not equal) leaves the wall's DIRECTION right but
    #its distance wrong, so the angles stand and the depth (in cm) does not.
    scale_ok = abs(pose["axis_ratio"] - 1.0) <= volume.MAX_AXIS_RATIO_DEVIATION
    depth = round(max(f["_h95"] for f in big), 1) if big and scale_ok else None
    for f in faces:
        f.pop("_h95")
    return {
        "faces": faces,
        "depth_cm": depth,
        "wall_angle_deg": wall_angle,
        "frames_used": len(posed),
        "frames_sent": len(frames),
        "points": int(len(hh)),
        "wall_features": int(len(ctx["xy_w"])),
        "focal_px": round(float(Kp[0, 0])),
        "focal_check_px": focal_check,
        "photo_axis_ratio": round(pose["axis_ratio"], 3),
        "frame_diagnostics": diagnostics,
        "seconds": round(time.perf_counter() - started, 1),
    }
