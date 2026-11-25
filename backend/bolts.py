import cv2
import numpy as np

#T-nut bolt-hole detection (classical OpenCV, no ML) - the scale reference
#for wall size and hold distances. See docs/features/wall_size_hold_distance.md.
#
#Two stages:
#  1. Candidates: dark, round-ish blobs (SimpleBlobDetector on a CLAHE'd grey
#     image) at a few pyramid levels, so a 10 px hole on a far wall and an
#     80 px hole in a close-up can both be found. Blobs inside HOLD/VOLUME
#     polygons are dropped (screw holes in holds aren't wall bolts), as are
#     blobs barely darker than the wall around them (wood grain, shading).
#  2. Lattice support: paint speckle, wood knots and screws are also dark
#     round blobs, often far more of them than bolts, and of no fixed size
#     relative to the bolts. What they don't do is line up. A blob is kept
#     only if it sits in an evenly spaced line of similar-sized blobs
#     (c-v, c, c+v or c, c+v, c+2v) along at least two different directions.
#     That test only uses each blob's own neighbour distance, so it doesn't
#     depend on photo resolution or distance to the wall. Rejected blobs
#     that line up with accepted bolts are then re-admitted ("grow").
#
#Tuned by eye on the reference photos with eval_scale.py.

#Bolt detection doesn't need more than a phone's native resolution - bigger
#uploads are shrunk to this first to bound runtime.

MAX_SIDE = 4096

#Pyramid levels candidates are searched at (1 = full res). Each level's blob
#size limits are the same in its own pixels, so together they cover
#~4 px to ~4 x 50 px holes.

PYRAMID_FACTORS = (1, 2, 4)

BLOB_PARAMS = {
    "minThreshold": 20,
    "maxThreshold": 160,
    "thresholdStep": 20,
    "minArea": 12,
    "maxArea": 2000,
    "minCircularity": 0.5,
    "minConvexity": 0.8,
    "minInertiaRatio": 0.15,
}

#Neighbours checked when merging the same hole found at several levels.

DEDUP_NEIGHBOURS = 8

CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID = (8, 8)

#A bolt hole is much darker than the wall right around it; wood grain and
#shading that CLAHE turns into blobs aren't. Contrast = (ring median - core
#mean) / ring median on the raw grey image, core = 0.6 r, ring = 1.5-2.5 r.

MIN_CONTRAST = 0.3

#Smallest hole diameter (half-depth, full-res px) treated as a possible bolt.
#Below this, paint speckle dominates and blobs are too small to measure; on
#a phone photo even the farthest panel's holes are ~7 px.

MIN_DIAMETER_PX = 5.0

#Neighbours checked per blob, and how far (as a fraction of the neighbour
#distance) the third point of a line may sit from where an exact lattice
#would put it - loose enough for perspective across 3 bolts, tight enough
#that randomly placed speckle rarely lines up by chance.

NEIGHBOURS = 6
LINE_TOLERANCE = 0.15

#Blobs on one panel are within this size ratio of each other - stops a
#bolt being "supported" by speckle or a large hole-like feature.

SIZE_RATIO = 1.5

#Two line directions closer than this (radians) count as one direction.

MIN_DIRECTION_SEPARATION = 0.35

SUPPORT_ITERATIONS = 3

#Rejected candidates are re-admitted when they line up with accepted bolts
#along two directions... - recovers holes whose own neighbourhood was too
#cluttered with speckle to pass the first test.

GROW_TOLERANCE = 0.1
GROW_ITERATIONS = 3

#...or along one direction, if that line's step is within this ratio of the
#anchor bolt's own nearest-neighbour spacing.

GROW_STEP_RATIO = 1.2

#A bolt closer to its nearest neighbour than this fraction of the local
#nearest-neighbour spacing (median over SPACING_NEIGHBOURS nearby bolts) is
#dropped - grid bolts are evenly spaced, speckle clumps aren't.

MIN_SPACING_FRACTION = 0.7
SPACING_NEIGHBOURS = 9

#Physical prior: on a 20 cm grid, diagonal neighbours are ~14 cm apart and a
#hole is ~1.2-1.8 cm across, so measured nn spacing / diameter is ~8-12 on
#the reference photos; lined-up speckle clumps sit at ~3-6. Assumes a grid
#of roughly >= 12 cm - revisit if a gym with a denser grid shows up.

MIN_SPACING_TO_DIAMETER = 5.0


def _candidates(gray: np.ndarray) -> np.ndarray:
    """(N, 3) array of x, y, diameter in full-res pixels, de-duplicated across levels."""
    params = cv2.SimpleBlobDetector_Params()
    params.filterByColor = True
    params.blobColor = 0
    params.filterByArea = params.filterByCircularity = True
    params.filterByConvexity = params.filterByInertia = True
    for key, value in BLOB_PARAMS.items():
        setattr(params, key, value)
    detector = cv2.SimpleBlobDetector_create(params)
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID)

    h, w = gray.shape
    found = []
    for f in PYRAMID_FACTORS:
        if min(h, w) // f < 16:
            break
        level = gray if f == 1 else cv2.resize(gray, (w // f, h // f), interpolation=cv2.INTER_AREA)
        for kp in detector.detect(clahe.apply(level)):
            found.append((kp.pt[0] * f, kp.pt[1] * f, kp.size * f))
    if not found:
        return np.zeros((0, 3))

    #The same hole shows up at more than one level - keep the largest
    #detection and drop anything centred inside it.
    cands = np.array(found)
    cands = cands[np.argsort(-cands[:, 2])]
    idx, dist = knn(cands[:, :2], cands[:, :2], DEDUP_NEIGHBOURS)
    keep = np.ones(len(cands), bool)
    for i in range(len(cands)):
        if keep[i]:
            #Sorted largest first, so higher indices are the smaller duplicates.
            close = idx[i][(idx[i] > i) & (dist[i] < cands[i, 2] / 2)]
            keep[close] = False
    return cands[keep]


def _measure(gray: np.ndarray, cands: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per candidate: relative contrast, and diameter at half depth (area darker
    than midway between core and ring, as an equal-area circle).

    The blob detector's own size includes the soft edge and whatever its
    upper thresholds merge in - often 1.5x the real hole - which skews the
    size and spacing checks below, so they use this diameter instead."""
    h, w = gray.shape
    contrast = np.zeros(len(cands))
    diameter = cands[:, 2].copy()
    for i, (x, y, d) in enumerate(cands):
        r = max(2.0, d / 2)
        R = 2.5 * r
        x0, x1 = int(max(0, x - R)), int(min(w, x + R + 1))
        y0, y1 = int(max(0, y - R)), int(min(h, y + R + 1))
        patch = gray[y0:y1, x0:x1].astype(np.float32)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        rr = np.hypot(xx - x, yy - y)
        core = patch[rr <= 0.6 * r]
        ring = patch[(rr >= 1.5 * r) & (rr <= R)]
        if len(core) and len(ring):
            bg = float(np.median(ring))
            depth = float(core.mean())
            contrast[i] = (bg - depth) / max(bg, 1.0)
            dark = np.count_nonzero(patch[rr < 1.5 * r] < (bg + depth) / 2)
            if dark:
                diameter[i] = 2.0 * np.sqrt(dark / np.pi)
    return contrast, diameter


def _outside_holds(cands: np.ndarray, detections: list[dict], shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    mask = np.zeros((h, w), np.uint8)
    for det in detections:
        pts = np.array([[p["x"] * w, p["y"] * h] for p in det["polygon"]], np.int32)
        if len(pts) >= 3:
            cv2.fillPoly(mask, [pts], 255)
    xs = np.clip(cands[:, 0].astype(int), 0, w - 1)
    ys = np.clip(cands[:, 1].astype(int), 0, h - 1)
    return cands[mask[ys, xs] == 0]


def knn(query: np.ndarray, train: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Exact k nearest neighbours (brute force in C). Returns (indices, distances),
    each (len(query), k), padded with -1 / inf when train has fewer than k points.

    The matches are copied out in bulk (slice 13): copying them one by one in
    Python cost as much as the search itself on segment_lengths' ~300k sample
    points. A pure-numpy search was tried and was 3x slower at that size."""
    k_eff = min(k, len(train))
    idx = np.full((len(query), k), -1)
    dist = np.full((len(query), k), np.inf)
    if k_eff == 0 or len(query) == 0:
        return idx, dist
    matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(query.astype(np.float32), train.astype(np.float32), k=k_eff)
    flat = [m for row in matches for m in row]
    if len(flat) == len(query) * k_eff:
        idx[:, :k_eff] = np.fromiter((m.trainIdx for m in flat), dtype=np.int64, count=len(flat)).reshape(-1, k_eff)
        dist[:, :k_eff] = np.fromiter((m.distance for m in flat), dtype=np.float64, count=len(flat)).reshape(-1, k_eff)
        return idx, dist
    for r, row in enumerate(matches):  # a short row: fill one by one
        for c, m in enumerate(row):
            idx[r, c] = m.trainIdx
            dist[r, c] = m.distance
    return idx, dist


def _similar_size(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.maximum(a, b) / np.minimum(a, b) <= SIZE_RATIO


#Size bands for neighbour search: points are queried band by band against
#only the anchors whose size could pass SIZE_RATIO, so a bolt's neighbours
#aren't crowded out by the (often far more numerous) smaller speckle.

SIZE_BAND_RATIO = 1.25


def _line_hits_band(xy, size, axy, asize, tolerance):
    idx, dist = knn(xy, axy, NEIGHBOURS + 1)
    valid = (idx >= 0) & (dist > 1e-6)
    valid &= _similar_size(size[:, None], asize[np.maximum(idx, 0)])
    order = np.argsort(~valid, axis=1, kind="stable")[:, :NEIGHBOURS]
    nb = np.take_along_axis(idx, order, axis=1)
    nb_valid = np.take_along_axis(valid, order, axis=1)

    v = axy[np.maximum(nb, 0)] - xy[:, None, :]
    length = np.hypot(v[..., 0], v[..., 1])
    hit = np.zeros(nb.shape, bool)
    for target in (xy[:, None, :] - v, xy[:, None, :] + 2 * v):
        t_idx, t_dist = knn(target.reshape(-1, 2), axy, 1)
        t_idx, t_dist = t_idx[:, 0].reshape(nb.shape), t_dist[:, 0].reshape(nb.shape)
        ok = (t_idx >= 0) & (t_dist < tolerance * length)
        ok &= _similar_size(size[:, None], asize[np.maximum(t_idx, 0)])
        hit |= ok
    hit &= nb_valid
    return hit, np.arctan2(v[..., 1], v[..., 0]) % np.pi, length, nb


def _line_hits(points: np.ndarray, anchors: np.ndarray, tolerance: float):
    """For each point and each of its NEIGHBOURS nearest similar-sized anchors
    (vector v), whether a similar-sized anchor also sits at point - v or
    point + 2v. Returns (N, K) arrays: hit (bool), angle of v in [0, pi),
    |v|, and the neighbour's index into anchors (-1 if none)."""
    shape = (len(points), NEIGHBOURS)
    hit, angle = np.zeros(shape, bool), np.zeros(shape)
    length, nb = np.full(shape, np.inf), np.full(shape, -1)
    if len(points) == 0 or len(anchors) == 0:
        return hit, angle, length, nb

    band = np.floor(np.log(points[:, 2]) / np.log(SIZE_BAND_RATIO)).astype(int)
    for b in np.unique(band):
        rows = band == b
        lo, hi = SIZE_BAND_RATIO ** b, SIZE_BAND_RATIO ** (b + 1)
        near = (anchors[:, 2] >= lo / SIZE_RATIO) & (anchors[:, 2] <= hi * SIZE_RATIO)
        if not near.any():
            continue
        h, a, l, n = _line_hits_band(
            points[rows, :2], points[rows, 2], anchors[near, :2], anchors[near, 2], tolerance
        )
        hit[rows], angle[rows], length[rows] = h, a, l
        nb[rows] = np.where(n >= 0, np.flatnonzero(near)[np.maximum(n, 0)], -1)
    return hit, angle, length, nb


def _distinct_directions(hit: np.ndarray, angle: np.ndarray) -> np.ndarray:
    counts = np.zeros(len(hit), int)
    for r in range(len(hit)):
        dirs: list[float] = []
        for a in angle[r][hit[r]]:
            if all(min(abs(a - d), np.pi - abs(a - d)) > MIN_DIRECTION_SEPARATION for d in dirs):
                dirs.append(a)
        counts[r] = len(dirs)
    return counts


def _lattice_filter(cands: np.ndarray) -> np.ndarray:
    bolts = cands
    for _ in range(SUPPORT_ITERATIONS):
        if len(bolts) < 3:
            return bolts[:0]
        hit, angle, _, _ = _line_hits(bolts, bolts, LINE_TOLERANCE)
        keep = _distinct_directions(hit, angle) >= 2
        if keep.all():
            break
        bolts = bolts[keep]

    bolts = _spacing_filter(bolts)

    for _ in range(GROW_ITERATIONS):
        if len(bolts) < 3:
            break
        accepted = {(x, y) for x, y, _ in bolts}
        rest = np.array([c for c in cands if (c[0], c[1]) not in accepted]).reshape(-1, 3)
        if len(rest) == 0:
            break
        hit, angle, length, nb = _line_hits(rest, bolts, GROW_TOLERANCE)
        anchor_nn = _nn_distance(bolts)

        #One line is enough when its step matches the anchor bolt's own grid
        #step - a hole beside a hold often has its other lines hidden.
        step = anchor_nn[np.maximum(nb, 0)]
        on_step = hit & (length >= step / GROW_STEP_RATIO) & (length <= step * GROW_STEP_RATIO)
        ok = (_distinct_directions(hit, angle) >= 2) | on_step.any(axis=1)

        #No two bolts on a grid are closer than its step - a candidate
        #crowding an accepted bolt is speckle next to a real hole.
        near_idx, near_dist = knn(rest[:, :2], bolts[:, :2], 1)
        ok &= near_dist[:, 0] >= MIN_SPACING_FRACTION * anchor_nn[near_idx[:, 0]]

        new = rest[ok]
        if len(new) == 0:
            break
        bolts = _spacing_filter(np.vstack([bolts, new]))
    return bolts



def _nn_distance(points: np.ndarray) -> np.ndarray:
    _, dist = knn(points[:, :2], points[:, :2], 2)
    return dist[:, 1]


def _spacing_filter(bolts: np.ndarray) -> np.ndarray:
    """Drop bolts much closer to their nearest neighbour than the bolts
    around them are - clumps of lined-up speckle, or a speckle beside a hole."""
    for _ in range(2):
        if len(bolts) < 3:
            return bolts
        nn = _nn_distance(bolts)
        idx, _ = knn(bolts[:, :2], bolts[:, :2], SPACING_NEIGHBOURS)
        local = np.median(np.where(idx >= 0, nn[np.maximum(idx, 0)], np.nan), axis=1)
        keep = (nn >= MIN_SPACING_FRACTION * local) & (nn >= MIN_SPACING_TO_DIAMETER * bolts[:, 2])
        if keep.all():
            break
        bolts = bolts[keep]
    return bolts


def find_candidates(image) -> dict:
    """The part of bolt detection that needs only the photo: grey, shrunk to
    MAX_SIDE, and the blob candidates. /detect runs it at the same time as
    YOLO (slice 13) and hands the result to detect_bolt_holes."""
    gray = np.asarray(image.convert("L"))
    h0, w0 = gray.shape
    shrink = max(h0, w0) / MAX_SIDE
    if shrink > 1:
        gray = cv2.resize(gray, (round(w0 / shrink), round(h0 / shrink)), interpolation=cv2.INTER_AREA)
    else:
        shrink = 1.0
    return {"gray": gray, "shrink": shrink, "cands": _candidates(gray), "size": image.size}


def detect_bolt_holes(image, detections: list[dict], candidates: dict | None = None) -> list[dict]:
    """PIL image (full resolution, same orientation the detections were made
    in) + /detect's detections -> [{"x", "y", "diameter"}, ...].

    x, y are normalized (0-1) like detection centroids; diameter is in
    full-res pixels of `image`. Order is not meaningful. `candidates` is
    find_candidates(image), when already computed; anything else (or another
    image's) is ignored and recomputed.
    """
    if candidates is None or candidates.get("size") != image.size:
        candidates = find_candidates(image)
    gray, shrink = candidates["gray"], candidates["shrink"]
    h, w = gray.shape

    cands = candidates["cands"].copy()
    if len(cands):
        cands = _outside_holds(cands, detections, (h, w))
    if len(cands):
        contrast, cands[:, 2] = _measure(gray, cands)
        cands = cands[(contrast >= MIN_CONTRAST) & (cands[:, 2] >= MIN_DIAMETER_PX / shrink)]
    bolts = _lattice_filter(cands) if len(cands) else cands

    return [
        {"x": float(x / w), "y": float(y / h), "diameter": float(d * shrink)}
        for x, y, d in bolts
    ]
