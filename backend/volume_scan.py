"""Volume face angles from one photo plus a sideways burst (test feature).

Spec: docs/features/volume_scan.md. Not used by /detect or /analysis.

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

The design history (and what failed) is in docs/features/handover.md, slice 11.
Synthetic test cases: backend/experiments/two_photo/synth.py.
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from PIL import Image

import angle
import bolts
import scale
import volume

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
#SIFT features are found at this scale; FLANN matches pass Lowe's ratio test.
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
MAX_BASELINE_CM = 300.0
MIN_FRAMES = 2
MAX_FRAMES = 12
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


class ScanError(ValueError):
    """A scan that can't run, with a message fit for the user."""


def _gray(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)


def _polygon_mask(polygon_norm, size) -> np.ndarray:
    w, h = size
    pts = np.array([[float(p["x"]) * w, float(p["y"]) * h] for p in polygon_norm], np.float64)
    if len(pts) < 3 or not np.isfinite(pts).all():
        raise ScanError("The volume outline is not a polygon.")
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
    if des_a is None or des_b is None or len(des_a) < 2 or len(des_b) < 2:
        return np.zeros((0, 2), int)
    flann = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))
    pairs = [(m[0].queryIdx, m[0].trainIdx)
             for m in flann.knnMatch(des_a.astype(np.float32), des_b.astype(np.float32), k=2)
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
    return {"R": R, "t": t * spacing_cm, "panel": panel, "axis_ratio": float(l1 / l2)}


def _frame_pose(Kp, Kf, R, t, xa, xb):
    """A frame's R, t from the photo->frame wall homography; None if unusable."""
    if len(xa) < MIN_WALL_INLIERS:
        return None
    H, inliers = cv2.findHomography(xa, xb, cv2.RANSAC, WALL_RANSAC_PX)
    if H is None or inliers is None or int(inliers.sum()) < MIN_WALL_INLIERS:
        return None
    n_c = R @ np.array([0.0, 0.0, 1.0])
    off = float((R.T @ t)[2])  # the wall in the photo's camera: n_c . X = off
    want = n_c * np.sign(off)  # cv2's normal convention: n . X = d > 0
    G = np.linalg.inv(Kf) @ H @ Kp
    _, Rs, ts, ns = cv2.decomposeHomographyMat(G, np.eye(3))
    k = int(np.argmax([float(n.ravel() @ want) for n in ns]))
    Rrel, trel = Rs[k], ts[k].ravel() * abs(off)
    Rf, tf = Rrel @ R, Rrel @ t + trel
    baseline = float(np.linalg.norm(-R.T @ t + Rf.T @ tf))
    return {"R": Rf, "t": tf, "wall_inliers": int(inliers.sum()), "baseline_cm": baseline}


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
    if len(frames) > MAX_FRAMES:  # evenly spread, keeping both ends of the step
        keep = np.unique(np.round(np.linspace(0, len(frames) - 1, MAX_FRAMES)).astype(int))
        frames = [frames[i] for i in keep]
    size = photo.size
    mask = _polygon_mask(volume_polygon, size)
    Kp = volume.camera_matrix(size, angle.focal_px(size, focal_35mm))
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
    xy_p, des_p = _features(gray)
    ij = np.clip(np.round(xy_p).astype(int), 0, [size[0] - 1, size[1] - 1])
    nn, _ = scale.knn(xy_p, lattice.xy, 6)
    on_panel = np.array([np.mean(lattice.panel[r[r >= 0]] == pose["panel"]) > 0.5 if (r >= 0).any() else False
                         for r in nn])
    wall_p = ~any_det[ij[:, 1], ij[:, 0]] & on_panel

    posed, diagnostics = [], []
    for k, frame in enumerate(frames):
        fsize = frame.size
        Kf = volume.camera_matrix(fsize, angle.focal_px(fsize, focal_35mm))
        fgray = _gray(frame)
        xy_f, des_f = _features(fgray)
        M = _match(des_p, des_f)
        M = M[wall_p[M[:, 0]]] if len(M) else M
        fp = _frame_pose(Kp, Kf, R, t, xy_p[M[:, 0]], xy_f[M[:, 1]]) if len(M) else None
        info = {"frame": k, "wall_matches": int(len(M))}
        if fp is not None:
            info.update(wall_inliers=fp["wall_inliers"], baseline_cm=round(fp["baseline_cm"], 1))
            if MIN_BASELINE_CM <= fp["baseline_cm"] <= MAX_BASELINE_CM:
                small = cv2.resize(fgray, None, fx=SWEEP_SCALE, fy=SWEEP_SCALE,
                                   interpolation=cv2.INTER_AREA).astype(np.float32)
                posed.append({**fp, "K": Kf, "small": small})
                info["used"] = True
        info.setdefault("used", False)
        diagnostics.append(info)
    if len(posed) < MIN_FRAMES:
        raise ScanError("Couldn't line up enough burst photos with the wall. "
                        "Keep the volume and the wall around it in frame, and step sideways slowly.")

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

    faces = []
    rng = np.random.default_rng(0)
    if len(X) >= 3 * MIN_FACE_POINTS:
        interior = np.array([*np.median(X[:, :2], 0), 0.0])
        remaining = np.arange(len(X))
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
            d = volume.describe_face(R @ n, wall_n, g)
            hull = cv2.convexHull(np.column_stack([gx[patch] + x0, gy[patch] + y0]).astype(np.float32)).reshape(-1, 2)
            outline = [{"x": round(float(px) / SWEEP_SCALE / size[0], 5), "y": round(float(py) / SWEEP_SCALE / size[1], 5)}
                       for px, py in hull]
            faces.append({"steepness_deg": d["steepness_deg"], "facing": d["facing"], "facing_deg": d["facing_deg"],
                          "outline": outline, "n_points": int(len(patch)),
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
        "photo_axis_ratio": round(pose["axis_ratio"], 3),
        "frame_diagnostics": diagnostics,
        "seconds": round(time.perf_counter() - started, 1),
    }
