"""DEV ONLY - how well volume.py recovers volume face angles, measured against
fakewall.py's synthetic scenes, where every face angle and height is exact.
Not used by the API.

The outline handed to `fit_volume` is built the way run_detection builds one:
the volume's silhouette from the ground-truth face-id map, `cv2.findContours`,
then `cv2.approxPolyDP` at `detection.POLYGON_SIMPLIFY_EPS * arcLength`. The
greyscale image goes in too, so the ridge detector runs.

Two fit paths are reported, because they fail for different reasons:
  full    fit_volume on that outline - what production would do.
  oracle  the right fitter called with the TRUE base pixels and the TRUE
          raised pixels (fit_pyramid / fit_ridge / fit_box). Nothing is
          mis-parsed, so what is left is the geometry itself: the pyramid's
          centroid assumption, focal error, wall-plane error.

Estimated faces are matched to truth faces by smallest angle between normals,
one truth face to one estimated face (greedy, no reuse), and a truth face with
no match is reported as missed rather than scored.

Usage (from backend/):
  uv run python fakewall.py                      # render the scenes first
  uv run python eval_volume.py                   # every experiment
  uv run python eval_volume.py --experiment clean noise
  uv run python eval_volume.py --scenes sq_centre over_40 --experiment report
"""

import argparse
import time
from pathlib import Path

import cv2
import numpy as np

import detection
import fakewall
import scale
import volume

#Go/no-go bars from the brief.
BAR_STEEPNESS_DEG = 5.0
BAR_BUCKET_FRACTION = 0.90
#A face flatter than this counts as "flat" for the slab/overhang sign test, so
#a 0.2 deg face is not called a sign flip.
SIGN_DEAD_ZONE_DEG = 2.0
#A truth face with no estimated normal within this angle counts as missed.
MATCH_LIMIT_DEG = 60.0
#A box now reports its h_source as its shape, so all three box forms - the
#eight-corner one, the three-plus-three hexagon and the two-faces-visible one -
#count as the box family.
FAMILY_OF_SHAPE = {"pyramid-3": "pyramid3", "pyramid-4": "pyramid4",
                   "pyramid-5": "pyramid5", "wedge": "wedge", "box": "box",
                   "box-hexagon": "box", "box-two-face": "box", "box-translate": "box"}

_LATTICE: dict[str, object] = {}


# -------------------------------------------------------------------------
# scene plumbing
# -------------------------------------------------------------------------

def inputs(sc: dict, f_scale: float = 1.0, plane: str = "truth") -> tuple:
    """(K, n, d, gravity) for one scene. `plane` picks where the wall comes
    from: the exact truth, or volume.wall_plane off the rendered bolt grid
    (which is what production does, and which moves when f is wrong)."""
    m = sc["meta"]
    K = volume.camera_matrix((fakewall.WIDTH, fakewall.HEIGHT), m["f_px"] * f_scale)
    g = np.array(m["down"])
    if plane == "truth":
        return K, np.array(m["wall_normal"]), float(m["d_cm"]), g
    name = m["scene"]
    if name not in _LATTICE:
        _LATTICE[name] = scale.fit_lattice(np.array(m["bolts_px"]))
    centre = np.array([fakewall.WIDTH / 2, fakewall.HEIGHT / 2])
    wp = volume.wall_plane(_LATTICE[name], centre, K, m["bolt_spacing_cm"])
    if wp is None:
        return K, np.array(m["wall_normal"]), float(m["d_cm"]), g
    return K, wp["n"], float(wp["d"]), g


def volume_mask(sc: dict, v: dict) -> np.ndarray:
    """The silhouette a segmentation model would draw: the volume's faces plus
    any hold sitting on one of them. A hold on the WALL in front of the base
    is left out, so it occludes the volume exactly as it does in the photo."""
    ids = sc["ids"]
    mask = np.isin(ids, v["face_ids"])
    for hold in sc["meta"]["holds"]:
        if hold["volume"] == v["index"]:
            mask |= ids == hold["id"]
    return mask


def outline(mask: np.ndarray, eps: float = detection.POLYGON_SIMPLIFY_EPS) -> np.ndarray | None:
    """run_detection's own polygon: biggest external contour, simplified at
    POLYGON_SIMPLIFY_EPS of its perimeter."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    return cv2.approxPolyDP(contour, eps * cv2.arcLength(contour, True),
                            True).reshape(-1, 2).astype(float)


def truth_faces(v: dict) -> list[dict]:
    return [f for f in v["faces"] if f.get("visible")]


def oracle_fit(v: dict, K, n, d, g, mask: np.ndarray | None = None) -> dict | None:
    """The right fitter, fed the true base and true raised pixels. With `mask`,
    the same `reprojection_norm` / `trusted` fit_volume would have attached."""
    base = np.array(v["base_px"], dtype=float)
    raised = np.array(v["raised_px"], dtype=float)
    family = v["family"]
    if family.startswith("pyramid"):
        fit = volume.fit_pyramid(base, raised[0], n, d, K)
        shape = f"pyramid-{len(base)}"
    elif family == "wedge":
        fit = volume.fit_ridge(base, raised, n, d, K)
        shape = "wedge"
    elif family == "box":
        fit = volume.fit_box(base, raised, n, d, K)
        shape = "box"
    else:
        return None
    if fit is None:
        return None
    fit.update(shape=shape, considered=1, iou=float("nan"), apex_source="truth",
               ridge_inliers=0, ridge_segments=0,
               depth_cm=round(float(np.max(fit["heights"])), 1))
    if mask is not None:
        size = np.sqrt(max(float(np.asarray(mask).astype(bool).sum()), 1.0))
        fit["reprojection_norm"] = round(fit["reprojection_px"] / size, 3)
        fit["clipped_by_frame"] = volume.touches_frame_border(mask)
        #Same rule as fit_volume (2026-11-20): a centroid-assumed pyramid is
        #never trusted.
        fit["trusted"] = bool(fit["reprojection_norm"] <= volume.MAX_REPROJECTION_FRACTION
                              and not fit["clipped_by_frame"]
                              and fit["h_source"] != "centroid-assumed")
        fit["iou"] = volume.silhouette_iou(fit["vertices"], K, mask)
    for face in fit["faces"]:
        face.update(volume.describe_face(face["normal"], n, g))
    return fit


# -------------------------------------------------------------------------
# scoring
# -------------------------------------------------------------------------

def _wrap(delta: float) -> float:
    return abs((delta + 180.0) % 360.0 - 180.0)


def _agg(values, how: str = "median", q: float = 90.0) -> float:
    """median / p90 / max / mean over the finite entries, NaN when there are
    none (numpy's nan* versions warn instead, and these tables are full of
    volumes that produced no fit at all)."""
    v = np.array([x for x in np.ravel(values) if np.isfinite(x)], dtype=float)
    if not len(v):
        return float("nan")
    return float({"median": np.median(v), "p90": np.percentile(v, q),
                  "max": v.max(), "mean": v.mean()}[how])


def match_faces(truth: list[dict], fit: dict | None) -> list[dict]:
    """One row per visible truth face, greedily matched to the closest unused
    estimated normal. `matched` is False when nothing came within
    MATCH_LIMIT_DEG - that face was not produced and is not scored."""
    estimates = [f for f in (fit or {}).get("faces", []) if f.get("visible")]
    normals = [np.asarray(f["normal"], dtype=float) for f in estimates]
    used, rows = set(), []
    pairs = []
    for ti, t in enumerate(truth):
        tn = np.asarray(t["normal"], dtype=float)
        for ei, en in enumerate(normals):
            pairs.append((float(np.degrees(np.arccos(np.clip(tn @ en, -1, 1)))), ti, ei))
    taken_truth = {}
    for angle_deg, ti, ei in sorted(pairs):
        if ti in taken_truth or ei in used or angle_deg > MATCH_LIMIT_DEG:
            continue
        taken_truth[ti] = (ei, angle_deg)
        used.add(ei)
    for ti, t in enumerate(truth):
        if ti not in taken_truth:
            rows.append({"truth": t, "matched": False})
            continue
        ei, angle_deg = taken_truth[ti]
        e = estimates[ei]
        flip = (abs(t["steepness_deg"]) > SIGN_DEAD_ZONE_DEG
                and abs(e["steepness_deg"]) > SIGN_DEAD_ZONE_DEG
                and np.sign(t["steepness_deg"]) != np.sign(e["steepness_deg"]))
        #describe_face now returns facing None / "undefined" for a face within
        #5 deg of horizontal, where the angle is meaningless. Those are counted
        #as "not reported", never as a wrong bucket; a face where only ONE side
        #declines to report it is counted separately again, as a disagreement.
        t_known, e_known = t["facing_deg"] is not None, e["facing_deg"] is not None
        state = "scored" if (t_known and e_known) else (
            "not_reported" if not (t_known or e_known) else "disagree")
        rows.append({
            "truth": t, "est": e, "matched": True, "normal_deg": angle_deg,
            "steep_err": abs(t["steepness_deg"] - e["steepness_deg"]),
            "facing_err": _wrap(t["facing_deg"] - e["facing_deg"]) if state == "scored" else float("nan"),
            "bucket_ok": (t["facing"] == e["facing"]) if state == "scored" else None,
            "facing_state": state, "truth_facing_known": t_known,
            "sign_flip": bool(flip),
        })
    return rows


def summarise(rows: list[dict]) -> dict:
    """Aggregate face rows into the go/no-go numbers."""
    matched = [r for r in rows if r["matched"]]
    steep = np.array([r["steep_err"] for r in matched]) if matched else np.zeros(0)
    scored = [r for r in matched if r["facing_state"] == "scored"]
    #The facing bar is only meaningful over faces whose facing the truth
    #reports at all: a face within 5 deg of horizontal has no facing.
    reportable = [r for r in rows if r["truth"]["facing_deg"] is not None]
    ok = sum(r["bucket_ok"] for r in scored)
    return {
        "faces": len(rows), "matched": len(matched),
        "coverage": len(matched) / len(rows) if rows else float("nan"),
        "steep_med": float(np.median(steep)) if len(steep) else float("nan"),
        "steep_p90": float(np.percentile(steep, 90)) if len(steep) else float("nan"),
        "steep_max": float(steep.max()) if len(steep) else float("nan"),
        "facing_med": _agg([r["facing_err"] for r in scored]),
        "bucket": (ok / len(scored)) if scored else float("nan"),
        "bucket_all": (ok / len(reportable)) if reportable else float("nan"),
        "scored": len(scored), "reportable": len(reportable),
        "not_reported": sum(r["facing_state"] == "not_reported" for r in matched),
        "disagree": sum(r["facing_state"] == "disagree" for r in matched),
        "flips": int(sum(r["sign_flip"] for r in matched)),
    }


def fit_volume_for(sc, v, K, n, d, g, gray=None, mask=None, poly=None):
    mask = volume_mask(sc, v) if mask is None else mask
    poly = outline(mask) if poly is None else poly
    if poly is None or len(poly) < 3:
        return None, mask, poly
    return volume.fit_volume(poly, n, d, K, mask, gray, g), mask, poly


def volume_row(sc, v, fit, rows) -> dict:
    s = summarise(rows)
    true_h = float(v["height_cm"])
    return {
        "scene": sc["meta"]["scene"], "name": v["name"], "family": v["family"],
        "true_h": true_h,
        "shape": None if fit is None else fit["shape"],
        "family_ok": bool(fit is not None and FAMILY_OF_SHAPE.get(fit["shape"]) == v["family"]),
        "h": float("nan") if fit is None else float(fit["depth_cm"]),
        "h_err": float("nan") if fit is None else abs(float(fit["depth_cm"]) - true_h),
        "h_source": None if fit is None else fit["h_source"],
        "iou": float("nan") if fit is None else float(fit["iou"]),
        "gain": float("nan") if fit is None else float(fit["offcentre_gain"]),
        "reproj": float("nan") if fit is None else float(fit["reprojection_px"]),
        "reproj_norm": float("nan") if fit is None else float(fit.get("reprojection_norm", float("nan"))),
        "trusted": None if fit is None else bool(fit.get("trusted", False)),
        "clipped": None if fit is None else bool(fit.get("clipped_by_frame", False)),
        **s,
    }


VOL_HEAD = ("scene            volume     family    | shape      fam  h_true   h_fit   h_err | "
            "steep med  p90  max | face med bkt | cov | iou   gain  reproj  norm  trust")


def print_volume_row(r: dict) -> None:
    print(f"{r['scene']:16s} {r['name']:10s} {r['family']:9s} | {str(r['shape']):10s} "
          f"{'ok ' if r['family_ok'] else 'NO ':3s} {r['true_h']:6.1f} {r['h']:7.1f} {r['h_err']:7.1f} | "
          f"{r['steep_med']:9.1f} {r['steep_p90']:4.1f} {r['steep_max']:4.1f} | "
          f"{r['facing_med']:8.1f} {r['bucket']:4.2f} | {r['matched']}/{r['faces']} | "
          f"{r['iou']:5.3f} {r['gain']:5.1f} {r['reproj']:6.1f} {r['reproj_norm']:5.3f} "
          f"{'' if r['trusted'] is None else ('yes' if r['trusted'] else 'NO ')}")


def totals(rows: list[dict], label: str) -> None:
    s = summarise(rows)
    print(f"  [{label:22s}] faces {s['matched']}/{s['faces']}  steep med {s['steep_med']:5.2f} "
          f"p90 {s['steep_p90']:5.2f} max {s['steep_max']:6.2f}  facing med {s['facing_med']:5.2f}  "
          f"bucket {s['bucket']:.2f} over {s['scored']} scored (of {s['reportable']} truth faces with a "
          f"facing: {s['bucket_all']:.2f}), not reported {s['not_reported']}, one-sided "
          f"{s['disagree']}  sign flips {s['flips']}")


# -------------------------------------------------------------------------
# mask noise (experiment 2)
# -------------------------------------------------------------------------

def _resample(contour: np.ndarray, count: int) -> np.ndarray:
    pts = contour.reshape(-1, 2).astype(float)
    closed = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    want = np.linspace(0.0, s[-1], count, endpoint=False)
    return np.column_stack([np.interp(want, s, closed[:, 0]), np.interp(want, s, closed[:, 1])])


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """Circular moving average along the contour."""
    window = max(1, int(window))
    if window < 2:
        return values
    kernel = np.ones(window) / window
    out = np.empty_like(values)
    for c in range(values.shape[1]):
        padded = np.concatenate([values[-window:, c], values[:, c], values[:window, c]])
        out[:, c] = np.convolve(padded, kernel, mode="same")[window:window + len(values)]
    return out


def noisy_mask(mask: np.ndarray, rng, jitter_px: float = 0.0, morph_px: int = 0,
               round_px: float = 0.0, samples: int = 400) -> np.ndarray:
    """A silhouette wrong the way a YOLO mask is wrong: a smooth wander of the
    boundary (jitter_px, one sigma), a systematic dilate/erode (morph_px), and
    corners rounded off over round_px of boundary."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask
    contour = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(contour, True)
    pts = _resample(contour, samples)
    step = perimeter / samples
    if round_px > 0:
        pts = _smooth(pts, round(round_px / step))
    if jitter_px > 0:
        #Low-pass noise: a real mask wanders over tens of px, it does not
        #rattle per vertex.
        noise = _smooth(rng.normal(0.0, 1.0, (samples, 2)), 9)
        noise *= jitter_px / max(noise.std(), 1e-9)
        pts = pts + noise
    out = np.zeros(mask.shape, np.uint8)
    cv2.fillPoly(out, [np.round(pts).astype(np.int32)], 1)
    if morph_px:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * abs(morph_px) + 1,) * 2)
        out = cv2.dilate(out, k) if morph_px > 0 else cv2.erode(out, k)
    return out.astype(bool)


# -------------------------------------------------------------------------
# relaxed ridge segments (experiment 6)
# -------------------------------------------------------------------------

def relaxed_segments(gray: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """volume.ridge_segments with the one rule that kills it replaced: keep a
    long segment when its MIDPOINT is well inside the mask, instead of
    requiring both ENDS inside. A pyramid's ridges run from the apex to the
    outline corners, so their ends are always on the boundary."""
    mask = np.asarray(mask).astype(bool)
    area = float(mask.sum())
    if area <= 0:
        return np.zeros((0, 4))
    size = np.sqrt(area)
    inset = max(1.0, volume.RIDGE_INSET_FRACTION * size)
    found = cv2.createLineSegmentDetector().detect(np.where(mask, gray, 0).astype(np.uint8))[0]
    if found is None or len(found) == 0:
        return np.zeros((0, 4))
    segments = np.asarray(found, dtype=float).reshape(-1, 4)
    length = np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1])
    keep = length >= volume.RIDGE_MIN_LENGTH_FRACTION * size
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)
    h, w = mask.shape
    mid = np.column_stack([(segments[:, 0] + segments[:, 2]) / 2,
                           (segments[:, 1] + segments[:, 3]) / 2])
    x = np.clip(np.round(mid[:, 0]).astype(int), 0, w - 1)
    y = np.clip(np.round(mid[:, 1]).astype(int), 0, h - 1)
    return segments[keep & (distance[y, x] >= inset)]


# -------------------------------------------------------------------------
# experiments
# -------------------------------------------------------------------------

def report(sc: dict, gray: bool = True, plane: str = "truth") -> list[dict]:
    """One printed block per scene: every volume, full fit and oracle fit."""
    K, n, d, g = inputs(sc, plane=plane)
    m = sc["meta"]
    print(f"\n{m['scene']}: wall {m['wall_deg']:+g} deg, pitch {m['pitch_deg']:+g} deg, "
          f"{m['distance_cm']:g} cm, f {m['f_px']:.0f} px, plane {plane} | {m['note']}")
    print("  " + VOL_HEAD)
    out, all_rows, oracle_rows = [], [], []
    for v in m["volumes"]:
        truth = truth_faces(v)
        fit, mask, poly = fit_volume_for(sc, v, K, n, d, g, sc["gray"] if gray else None)
        rows = match_faces(truth, fit)
        all_rows += rows
        r = volume_row(sc, v, fit, rows)
        r["poly_points"] = 0 if poly is None else len(poly)
        print("  ", end="")
        print_volume_row(r)
        oracle = oracle_fit(v, K, n, d, g)
        orows = match_faces(truth, oracle)
        oracle_rows += orows
        ro = volume_row(sc, v, oracle, orows)
        ro["name"] = "  (oracle)"
        print("  ", end="")
        print_volume_row(ro)
        out.append(r)
    totals(all_rows, "full, this scene")
    totals(oracle_rows, "oracle, this scene")
    return out


def experiment_clean(scenes: list[str]) -> None:
    print("\n=== 1. Per shape family, clean masks (noise-free silhouette) ===")
    print("  one volume per family, the true outline, truth wall plane and truth f")
    print("  " + VOL_HEAD)
    for name in ("tri_centre", "sq_centre", "wedge_centre", "box_centre"):
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            truth = truth_faces(v)
            mask = volume_mask(sc, v)
            fit, _, poly = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
            print("  ", end="")
            print_volume_row(volume_row(sc, v, fit, match_faces(truth, fit)))
            oracle = oracle_fit(v, K, n, d, g, mask)
            r = volume_row(sc, v, oracle, match_faces(truth, oracle))
            r["name"] = "  (oracle)"
            print("  ", end="")
            print_volume_row(r)
            own = volume.outline_from_mask(mask)
            print(f"     outline {len(poly)} points as run_detection hands it over, "
                  f"{len(own)} from volume.outline_from_mask; {len(v['base_px'])} base + "
                  f"{len(v['raised_px'])} raised vertices; raised project to "
                  f"{np.round(np.array(v['raised_px']), 0).tolist()}")


NOISE_SETTINGS = [
    ("clean", 0.0, 0, 0.0),
    ("jitter 2px", 2.0, 0, 0.0),
    ("jitter 5px", 5.0, 0, 0.0),
    ("jitter 10px", 10.0, 0, 0.0),
    ("dilate 4px", 0.0, 4, 0.0),
    ("erode 4px", 0.0, -4, 0.0),
    ("round 30px", 0.0, 0, 30.0),
    ("round 60px", 0.0, 0, 60.0),
    ("jitter5+round30", 5.0, 0, 30.0),
    ("j5+r30+dil3", 5.0, 3, 30.0),
]


VERTEX_NOISE = [("clean", 0.0, 0.0), ("jitter 1px", 1.0, 0.0), ("jitter 2px", 2.0, 0.0),
                ("jitter 5px", 5.0, 0.0), ("jitter 10px", 10.0, 0.0), ("jitter 20px", 20.0, 0.0),
                ("swell +5px", 0.0, 5.0), ("shrink -5px", 0.0, -5.0),
                ("swell +10px", 0.0, 10.0), ("jitter5+swell5", 5.0, 5.0)]


def _noisy_vertices(points: np.ndarray, centre: np.ndarray, rng, jitter: float,
                    swell: float) -> np.ndarray:
    """Vertex pixels moved the way a wrong mask moves them: independent jitter
    (one sigma, px) plus a coherent swell/shrink of the whole outline (px,
    radially from the silhouette centre - what a dilate or erode does)."""
    out = np.asarray(points, dtype=float).copy()
    if jitter:
        out = out + rng.normal(0.0, jitter, out.shape)
    if swell:
        direction = out - centre
        out = out + swell * direction / np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-9)
    return out


def experiment_noise(repeats: int = 4) -> None:
    print("\n=== 2. Mask noise ===")
    picks = [("tri_centre", 0), ("sq_centre", 0), ("wedge_centre", 0), ("box_centre", 0),
             ("vertical_00", 0), ("vertical_00", 1), ("vertical_00", 2), ("vertical_00", 3)]
    loaded = {name: fakewall.load(name) for name in {p[0] for p in picks}}

    print("\n  2a. Vertex noise on the ORACLE path: the right fitter, right correspondence,")
    print("      but every observed vertex pixel moved. This is the geometry's own")
    print("      sensitivity, which is what matters once the outline parsing is fixed.")
    print(f"\n  {'setting':16s} {'family':9s} | {'reps':4s} | {'steep med':9s} {'p90':5s} {'max':5s} | "
          f"{'facing med':10s} | {'bucket':6s} | {'h_err med':9s} {'h_err p90':9s} | "
          f"{'reproj med':9s} {'reproj max':9s} | {'rejected':8s}")
    for label, jitter, swell in VERTEX_NOISE:
        by_family: dict[str, list] = {}
        rejected: dict[str, int] = {}
        for scene_name, vi in picks:
            sc = loaded[scene_name]
            K, n, d, g = inputs(sc)
            v = sc["meta"]["volumes"][vi]
            truth = truth_faces(v)
            base_true = np.array(v["base_px"], dtype=float)
            raised_true = np.array(v["raised_px"], dtype=float)
            centre = np.vstack([base_true, raised_true]).mean(axis=0)
            for rep in range(repeats if (jitter or swell) else 1):
                rng = np.random.default_rng(7000 * rep + hash(scene_name) % 991 + vi)
                noisy = dict(v)
                noisy["base_px"] = _noisy_vertices(base_true, centre, rng, jitter, swell).tolist()
                noisy["raised_px"] = _noisy_vertices(raised_true, centre, rng, jitter, swell).tolist()
                fit = oracle_fit(noisy, K, n, d, g)
                rejected.setdefault(v["family"], 0)
                rejected[v["family"]] += fit is None
                by_family.setdefault(v["family"], []).append(
                    volume_row(sc, v, fit, match_faces(truth, fit)))
        for family in ("pyramid3", "pyramid4", "wedge", "box"):
            rs = by_family.get(family, [])
            if not rs:
                continue
            steep = np.array([r["steep_med"] for r in rs], dtype=float)
            print(f"  {label:16s} {family:9s} | {len(rs):4d} | {_agg(steep):9.1f} "
                  f"{_agg(steep, 'p90'):5.1f} {_agg(steep, 'max'):5.1f} | "
                  f"{_agg([r['facing_med'] for r in rs]):10.1f} | "
                  f"{_agg([r['bucket'] for r in rs], 'mean'):6.2f} | "
                  f"{_agg([r['h_err'] for r in rs]):9.1f} "
                  f"{_agg([r['h_err'] for r in rs], 'p90'):9.1f} | "
                  f"{_agg([r['reproj'] for r in rs]):9.1f} "
                  f"{_agg([r['reproj'] for r in rs], 'max'):9.1f} | "
                  f"{rejected[family]:8d}")

    print("\n  2b. Mask noise on the FULL path (fit_volume): the silhouette itself is")
    print("      perturbed before the contour is taken - smooth boundary wander (jitter,")
    print("      one sigma), dilate/erode, corners rounded off over N px of boundary.")
    print(f"\n  {'setting':16s} {'family':9s} | fits | steep med  p90   max | facing med | "
          f"bucket | cov  | h_err med | family ok")
    for label, jitter, morph, round_px in NOISE_SETTINGS:
        by_family: dict[str, list] = {}
        for scene_name, vi in picks:
            sc = loaded[scene_name]
            K, n, d, g = inputs(sc)
            v = sc["meta"]["volumes"][vi]
            truth = truth_faces(v)
            base_mask = volume_mask(sc, v)
            for rep in range(repeats if (jitter or morph or round_px) else 1):
                rng = np.random.default_rng(1000 * rep + hash(scene_name) % 997 + vi)
                mask = noisy_mask(base_mask, rng, jitter, morph, round_px)
                #The greyscale goes in: ridge_segments now finds apexes, so
                #leaving it out would understate the pipeline.
                fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
                rows = match_faces(truth, fit)
                by_family.setdefault(v["family"], []).append(volume_row(sc, v, fit, rows))
        for family in ("pyramid3", "pyramid4", "wedge", "box"):
            rs = by_family.get(family, [])
            if not rs:
                continue
            steep = np.array([r["steep_med"] for r in rs])
            print(f"  {label:16s} {family:9s} | {len(rs):4d} | "
                  f"{_agg(steep):9.1f} {_agg(steep, "p90"):5.1f} "
                  f"{_agg(steep, "max"):5.1f} | "
                  f"{_agg([r['facing_med'] for r in rs]):10.1f} | "
                  f"{_agg([r['bucket'] for r in rs], 'mean'):6.2f} | "
                  f"{_agg([r['coverage'] for r in rs], 'mean'):4.2f} | "
                  f"{_agg([r['h_err'] for r in rs]):9.1f} | "
                  f"{np.mean([r['family_ok'] for r in rs]):.2f}")

    #2b above mixes volumes the pipeline still cannot fit at all with ones it
    #can, and a discrete change of winning hypothesis swamps the noise level.
    #This restricts the sweep to the volumes whose CLEAN full-path fit is
    #already right, which is the only set on which "error vs noise" means
    #anything.
    print("\n  2d. Mask noise on the volumes the clean full path already fits correctly")
    print("      (every volume in the scenes below whose clean fit is usable and trusted):")
    scan = ["box_centre", "sq_centre", "tri_centre", "wedge_centre", "vertical_00", "over_20",
            "over_40", "offaxis_pyr", "pyr_off00", "occluded_base", "rotated_mix", "slab_m10",
            "holds_on_faces", "curved", "dark_on_dark"]
    by_setting: dict[str, list] = {}
    kept = []
    for scene_name in scan:
        sc = fakewall.load(scene_name)
        K, n, d, g = inputs(sc)
        for vi, v in enumerate(sc["meta"]["volumes"]):
            base_mask = volume_mask(sc, v)
            if not base_mask.any():
                continue
            truth = truth_faces(v)
            clean, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=base_mask)
            if clean is None:
                continue
            row = volume_row(sc, v, clean, match_faces(truth, clean))
            if _is_bad(row) or not row["trusted"]:
                continue
            kept.append(f"{scene_name}/{v['name']}")
            for label, jitter, morph, round_px in NOISE_SETTINGS:
                for rep in range(repeats if (jitter or morph or round_px) else 1):
                    rng = np.random.default_rng(1000 * rep + hash(scene_name) % 997 + vi)
                    mask = noisy_mask(base_mask, rng, jitter, morph, round_px)
                    fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
                    by_setting.setdefault(label, []).append(
                        volume_row(sc, v, fit, match_faces(truth, fit)))
    print(f"      {len(kept)} volumes: {', '.join(kept)}")
    print(f"\n  {'setting':16s} | fits | steep med  p90   max | h_err med  p90 | cov  | "
          f"trusted | still usable")
    for label, _, _, _ in NOISE_SETTINGS:
        rs = by_setting.get(label, [])
        if not rs:
            continue
        steep = np.array([r["steep_med"] for r in rs])
        print(f"  {label:16s} | {len(rs):4d} | {_agg(steep):9.1f} {_agg(steep, 'p90'):5.1f} "
              f"{_agg(steep, 'max'):5.1f} | {_agg([r['h_err'] for r in rs]):9.1f} "
              f"{_agg([r['h_err'] for r in rs], 'p90'):4.1f} | "
              f"{_agg([r['coverage'] for r in rs], 'mean'):4.2f} | "
              f"{np.mean([bool(r['trusted']) for r in rs]):7.2f} | "
              f"{np.mean([not _is_bad(r) for r in rs]):.2f}")


def _nearest_vertex(point: np.ndarray, poly: np.ndarray) -> tuple[np.ndarray, float]:
    i = int(np.argmin(np.linalg.norm(poly - point, axis=1)))
    return poly[i], float(np.linalg.norm(poly[i] - point))


def experiment_occlusion() -> None:
    print("\n=== 2c. Occluded, clipped, dark and curved outlines ===")
    print("  What the outline itself loses when holds cover a base edge, the frame cuts the")
    print("  base off, or the volume is dark. Each true vertex is snapped to the nearest")
    print("  vertex of the real outline (within 80 px, else left where it was), and the")
    print("  right fitter is run on the snapped vertices - i.e. a perfect correspondence")
    print("  step on an imperfect outline.")
    print(f"\n  {'scene':16s} {'vol':10s} {'poly':4s} {'snap err px: med':16s} {'max':6s} "
          f"{'unsnapped':9s} | {'steep med':9s} {'max':6s} | {'h_err':6s} | truth-vertex fit")
    for name in ("occluded_base", "clipped_base", "holds_on_faces", "dark_on_dark",
                 "light_vol", "lowcontrast", "curved", "sq_centre"):
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            if v["family"] == "cylinder":
                continue
            mask = volume_mask(sc, v)
            poly = outline(mask)
            if poly is None:
                continue
            truth = truth_faces(v)
            base = np.array(v["base_px"], dtype=float)
            raised = np.array(v["raised_px"], dtype=float)
            snapped, errs, unsnapped = [], [], 0
            for group in (base, raised):
                out = []
                for p in group:
                    q, dist = _nearest_vertex(p, poly)
                    if dist <= 80.0:
                        out.append(q)
                        errs.append(dist)
                    else:
                        out.append(p)
                        unsnapped += 1
                snapped.append(np.array(out))
            noisy = dict(v, base_px=snapped[0].tolist(), raised_px=snapped[1].tolist())
            fit = oracle_fit(noisy, K, n, d, g)
            row = volume_row(sc, v, fit, match_faces(truth, fit))
            clean = volume_row(sc, v, oracle_fit(v, K, n, d, g), match_faces(truth, oracle_fit(v, K, n, d, g)))
            print(f"  {name:16s} {v['name']:10s} {len(poly):4d} {_agg(errs):16.1f} "
                  f"{_agg(errs, 'max'):6.1f} {unsnapped:9d} | {row['steep_med']:9.1f} "
                  f"{row['steep_max']:6.1f} | {row['h_err']:6.1f} | "
                  f"steep {clean['steep_med']:.1f} h_err {clean['h_err']:.1f}")


def experiment_offaxis() -> None:
    print("\n=== 3. Off-axis sweep ===")
    print("  the same volume at five positions in the frame. `gain` is the fit's own")
    print("  offcentre_gain; `pred h_err` is gain x the true anchor error (0 for a box or")
    print("  wedge, whose anchors are observed, and the apex offset for a pyramid).")
    print(f"\n  {'scene':16s} {'vol':5s} {'r/half-diag':11s} {'gain':5s} | {'oracle h_err':12s} "
          f"{'pred':6s} {'reproj':6s} {'px/cm':6s} | {'oracle steep med':16s} {'max':5s} | "
          f"{'full h_err':10s} {'full steep med':14s} shape")
    half = np.hypot(fakewall.WIDTH, fakewall.HEIGHT) / 2
    for name in ("offaxis_pyr", "offaxis_box", "offaxis_wedge", "offaxis_pyr_off"):
        if not (fakewall.OUT_DIR / f"{name}.json").exists():
            continue
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            truth = truth_faces(v)
            centroid = np.array(v["base_px"]).mean(axis=0)
            radius = np.linalg.norm(centroid - np.array([fakewall.WIDTH / 2, fakewall.HEIGHT / 2]))
            oracle = oracle_fit(v, K, n, d, g)
            orow = volume_row(sc, v, oracle, match_faces(truth, oracle))
            fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"])
            frow = volume_row(sc, v, fit, match_faces(truth, fit))
            anchor_err = float(np.linalg.norm(v["apex_offset_cm"])) if v["family"].startswith("pyramid") else 0.0
            pred = orow["gain"] * anchor_err
            ratio = orow["reproj"] / orow["h_err"] if orow["h_err"] > 1e-6 else float("nan")
            print(f"  {name:16s} {v['name']:5s} {radius / half:11.2f} {orow['gain']:5.1f} | "
                  f"{orow['h_err']:12.1f} {pred:6.1f} {orow['reproj']:6.1f} {ratio:6.1f} | "
                  f"{orow['steep_med']:16.1f} {orow['steep_max']:5.1f} | "
                  f"{frow['h_err']:10.1f} {frow['steep_med']:14.1f} {str(frow['shape']):10s}")


def experiment_offcentre() -> None:
    print("\n=== 4. Pyramid off-centre apex penalty ===")
    print("  the same square pyramid at the same place in the frame, apex moved off the")
    print("  base centroid. `pred h_err` = offcentre_gain x true offset.")
    print(f"\n  {'scene':12s} {'offset':6s} {'gain':5s} {'pred':6s} | {'oracle: h_fit':13s} "
          f"{'h_err':6s} {'steep med':9s} {'max':5s} {'reproj':7s} {'iou':5s} | "
          f"{'full: h_err':11s} {'steep med':9s} {'reproj':7s} {'iou':5s} shape")
    for off in (0, 4, 8, 16, 24):
        name = f"pyr_off{off:02d}"
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        v = sc["meta"]["volumes"][0]
        truth = truth_faces(v)
        oracle = oracle_fit(v, K, n, d, g)
        orows = match_faces(truth, oracle)
        orow = volume_row(sc, v, oracle, orows)
        #IoU is not part of an oracle fit, so score it the same way fit_volume does.
        mask = volume_mask(sc, v)
        orow["iou"] = volume.silhouette_iou(oracle["vertices"], K, mask)
        fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
        frow = volume_row(sc, v, fit, match_faces(truth, fit))
        offset = float(np.linalg.norm(v["apex_offset_cm"]))
        print(f"  {name:12s} {offset:6.1f} {orow['gain']:5.1f} {orow['gain'] * offset:6.1f} | "
              f"{orow['h']:13.1f} {orow['h_err']:6.1f} {orow['steep_med']:9.1f} "
              f"{orow['steep_max']:5.1f} {orow['reproj']:7.1f} {orow['iou']:5.3f} | "
              f"{frow['h_err']:11.1f} {frow['steep_med']:9.1f} {frow['reproj']:7.1f} "
              f"{frow['iou']:5.3f} {str(frow['shape']):10s}")


FOCAL_SCALES = (0.85, 0.90, 1.0, 1.10, 1.15)


def experiment_focal(scenes: list[str]) -> None:
    print("\n=== 5. Focal-length sensitivity ===")
    print("  truth unchanged; f is wrong by the given factor. `plane=truth` keeps the wall")
    print("  plane exact (isolating the rays); `plane=bolts` re-derives it from the bolt")
    print("  grid with the wrong f, which is what production does.")
    use = [s for s in scenes if s in ("sq_centre", "wedge_centre", "box_centre",
                                      "tri_centre", "vertical_00", "over_20")]
    for plane in ("truth", "bolts"):
        print(f"\n  plane = {plane}")
        print(f"  {'f err':7s} | {'oracle steep med':16s} {'p90':5s} {'max':5s} | "
              f"{'h_err med':9s} {'h_err %':8s} | {'facing med':10s} {'bucket':6s} | "
              f"{'full steep med':14s} {'full h_err':10s}")
        for fs in FOCAL_SCALES:
            orows, frows, h_rel, h_abs, f_steep, f_h = [], [], [], [], [], []
            for name in use:
                sc = fakewall.load(name)
                K, n, d, g = inputs(sc, f_scale=fs, plane=plane)
                for v in sc["meta"]["volumes"]:
                    truth = truth_faces(v)
                    oracle = oracle_fit(v, K, n, d, g)
                    orows += match_faces(truth, oracle)
                    if oracle is not None:
                        err = float(oracle["depth_cm"]) - v["height_cm"]
                        h_abs.append(abs(err))
                        h_rel.append(100 * err / v["height_cm"])
                    fit, _, _ = fit_volume_for(sc, v, K, n, d, g, None)
                    rows = match_faces(truth, fit)
                    frows += rows
                    r = volume_row(sc, v, fit, rows)
                    f_steep.append(r["steep_med"])
                    f_h.append(r["h_err"])
            s, fsum = summarise(orows), summarise(frows)
            print(f"  {100 * (fs - 1):+6.0f}% | {s['steep_med']:16.2f} {s['steep_p90']:5.2f} "
                  f"{s['steep_max']:5.2f} | {np.median(h_abs):9.2f} {np.median(h_rel):+7.1f}% | "
                  f"{s['facing_med']:10.2f} {s['bucket']:6.2f} | "
                  f"{_agg(f_steep):14.2f} {_agg(f_h):10.2f}")


def experiment_ridge(scenes: list[str]) -> None:
    print("\n=== 6. Ridge detection (ridge_segments + converge_point) ===")
    print("  per volume: segments LSD finds, how many volume.ridge_segments keeps, whether")
    print("  converge_point returns an apex, and how far that apex is from the true one.")
    print("  `relaxed` is the same pipeline with ridge_segments' both-ends-inside test")
    print("  replaced by a midpoint-inside test (see relaxed_segments).")
    print(f"\n  {'scene':16s} {'vol':10s} {'fam':9s} {'apex in':7s} | {'shipped: kept':13s} "
          f"{'apex':5s} | {'relaxed: kept':13s} {'apex':5s} {'inl':4s} {'err px':7s} | "
          f"{'best outline vertex err px':26s}")
    shipped_found = relaxed_found = pyramids = inside = 0
    rows = []
    for name in scenes:
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            mask = volume_mask(sc, v)
            if not mask.any():
                continue
            size = np.sqrt(float(mask.sum()))
            tol = volume.RIDGE_INLIER_FRACTION * size
            kept = volume.ridge_segments(sc["gray"], mask)
            found = volume.converge_point(kept, tol)
            relaxed = relaxed_segments(sc["gray"], mask)
            rfound = volume.converge_point(relaxed, tol)
            poly = outline(mask)
            is_pyramid = v["family"].startswith("pyramid")
            apex_true = np.array(v["raised_px"][0], dtype=float)
            in_poly = (poly is not None
                       and cv2.pointPolygonTest(poly.astype(np.float32), tuple(apex_true), False) > 0)
            vertex_err = (float(np.min(np.linalg.norm(poly - apex_true, axis=1)))
                          if poly is not None else float("nan"))
            rerr = float(np.linalg.norm(rfound[0] - apex_true)) if rfound else float("nan")
            if is_pyramid:
                pyramids += 1
                inside += int(in_poly)
                shipped_found += int(found is not None)
                relaxed_found += int(rfound is not None)
                rows.append({"scene": name, "vol": v["name"], "inside": in_poly,
                             "relaxed": rfound is not None, "rerr": rerr,
                             "vertex_err": vertex_err, "v": v, "sc": sc,
                             "rapex": None if rfound is None else rfound[0]})
            print(f"  {name:16s} {v['name']:10s} {v['family']:9s} {str(in_poly):7s} | "
                  f"{len(kept):13d} {str(found is not None):5s} | {len(relaxed):13d} "
                  f"{str(rfound is not None):5s} {0 if rfound is None else rfound[1]:4d} "
                  f"{rerr:7.1f} | {vertex_err:26.1f}")
    print(f"\n  pyramids: {pyramids}, apex projects INSIDE its own outline on {inside} "
          f"({100 * inside / max(pyramids, 1):.0f}%)")
    print(f"  apex found by shipped ridge_segments: {shipped_found}/{pyramids}; "
          f"by relaxed: {relaxed_found}/{pyramids}")

    print("\n  Does a ridge apex beat an outline vertex? Same base (true base px), apex from")
    print("  each source, fit_pyramid, face error against truth:")
    print(f"  {'scene':16s} {'vol':10s} {'apex src':9s} {'apex err px':11s} {'h_fit':6s} "
          f"{'h_err':6s} {'steep med':9s} {'steep max':9s}")
    stats = {"ridge": [], "vertex": []}
    for r in rows:
        sc, v = r["sc"], r["v"]
        K, n, d, g = inputs(sc)
        truth = truth_faces(v)
        base = np.array(v["base_px"], dtype=float)
        poly = outline(volume_mask(sc, v))
        apex_true = np.array(v["raised_px"][0], dtype=float)
        best_vertex = poly[np.argmin(np.linalg.norm(poly - apex_true, axis=1))]
        for src, apex in (("ridge", r["rapex"]), ("vertex", best_vertex)):
            if apex is None:
                print(f"  {r['scene']:16s} {r['vol']:10s} {src:9s} {'-':>11s} (no apex found)")
                continue
            fit = volume.fit_pyramid(base, apex, n, d, K)
            if fit is None:
                print(f"  {r['scene']:16s} {r['vol']:10s} {src:9s} "
                      f"{np.linalg.norm(apex - apex_true):11.1f} (rejected as implausible)")
                continue
            for face in fit["faces"]:
                face.update(volume.describe_face(face["normal"], n, g))
            fit["depth_cm"] = round(float(np.max(fit["heights"])), 1)
            fit["shape"], fit["iou"] = "pyramid-%d" % len(base), float("nan")
            mrows = match_faces(truth, fit)
            row = volume_row(sc, v, fit, mrows)
            stats[src].append(row)
            print(f"  {r['scene']:16s} {r['vol']:10s} {src:9s} "
                  f"{np.linalg.norm(apex - apex_true):11.1f} {row['h']:6.1f} {row['h_err']:6.1f} "
                  f"{row['steep_med']:9.1f} {row['steep_max']:9.1f}")
    for src in ("ridge", "vertex"):
        rs = stats[src]
        if rs:
            print(f"  [{src:6s}] n={len(rs):2d}  median h_err {_agg([x['h_err'] for x in rs]):6.1f} cm"
                  f"  median steep err {_agg([x['steep_med'] for x in rs]):5.1f} deg")


def experiment_holds() -> None:
    print("\n=== 7. hold_face: which face a hold sits on, and its standoff ===")
    print("  standoff_cm is how far the hold stands off the wall. The 'as wall' column is")
    print("  what the pipeline reports today (back-project onto the wall plane: 0 cm off),")
    print("  so it is the error hold_face is meant to remove.")
    print(f"\n  {'scene':16s} {'vol':6s} {'face':4s} | {'true standoff':13s} | "
          f"{'oracle: face':12s} {'standoff':8s} {'err':6s} | {'full: face':10s} "
          f"{'standoff':8s} {'err':6s} | {'as-wall err':11s}")
    for name in ("holds_on_faces", "occluded_base"):
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for hold in sc["meta"]["holds"]:
            if hold["on_wall"] or hold.get("hidden"):
                continue
            v = sc["meta"]["volumes"][hold["volume"]]
            truth = truth_faces(v)
            hpx = np.array(hold["px"], dtype=float)
            cells = []
            for label, fit in (("oracle", oracle_fit(v, K, n, d, g)),
                               ("full", fit_volume_for(sc, v, K, n, d, g, sc["gray"])[0])):
                if fit is None:
                    cells.append(("none", float("nan"), float("nan")))
                    continue
                found = volume.hold_face(hpx, fit, K, n, d)
                if found is None:
                    cells.append(("miss", float("nan"), float("nan")))
                    continue
                #Which truth face did it pick? Match by normal.
                est = fit["faces"][found["face_index"]]
                en = np.asarray(est["normal"], dtype=float)
                angles = [float(np.degrees(np.arccos(np.clip(en @ np.asarray(t["normal"]), -1, 1))))
                          for t in truth]
                picked = truth[int(np.argmin(angles))]
                right = "ok" if picked["face_index"] == hold["face"] else f"->{picked['face_index']}"
                cells.append((right, found["standoff_cm"],
                              abs(found["standoff_cm"] - hold["standoff_cm"])))
            print(f"  {name:16s} {v['name']:6s} {hold['face']:4d} | {hold['standoff_cm']:13.1f} | "
                  f"{cells[0][0]:12s} {cells[0][1]:8.1f} {cells[0][2]:6.1f} | "
                  f"{cells[1][0]:10s} {cells[1][1]:8.1f} {cells[1][2]:6.1f} | "
                  f"{hold['standoff_cm']:11.1f}")


def experiment_family(scenes: list[str]) -> None:
    print("\n=== 8. Shape-family confusion ===")
    print(f"  {'true family':12s} | {'n':3s} | chosen shapes (count) | median steep err when "
          f"right / wrong")
    chosen: dict[str, dict[str, int]] = {}
    right: dict[str, list] = {}
    wrong: dict[str, list] = {}
    for name in scenes:
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            mask = volume_mask(sc, v)
            if not mask.any():
                continue
            truth = truth_faces(v)
            fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
            row = volume_row(sc, v, fit, match_faces(truth, fit))
            shape = str(row["shape"])
            chosen.setdefault(v["family"], {}).setdefault(shape, 0)
            chosen[v["family"]][shape] += 1
            (right if row["family_ok"] else wrong).setdefault(v["family"], []).append(row)
    for family, counts in sorted(chosen.items()):
        total = sum(counts.values())
        spread = " ".join(f"{k}:{c}" for k, c in sorted(counts.items(), key=lambda kv: -kv[1]))
        r = right.get(family, [])
        w = wrong.get(family, [])
        rr = _agg([x["steep_med"] for x in r])
        ww = _agg([x["steep_med"] for x in w])
        print(f"  {family:12s} | {total:3d} | {spread:40s} | {rr:6.1f} / {ww:6.1f}")
    print(f"  overall right family: {sum(len(v) for v in right.values())}/"
          f"{sum(len(v) for v in right.values()) + sum(len(v) for v in wrong.values())}")


#A fit counts as unusable when it would break a go/no-go bar or lie about the
#depth by more than the margin a hold standoff can absorb.
BAD_STEEP_DEG = 5.0
BAD_HEIGHT_CM = 5.0


def _is_bad(row: dict) -> bool:
    return bool(not np.isfinite(row["steep_max"]) or row["steep_max"] > BAD_STEEP_DEG
                or not np.isfinite(row["h_err"]) or row["h_err"] > BAD_HEIGHT_CM
                or row["coverage"] < 0.999)


def experiment_gate(scenes: list[str], noise_px: float = 5.0) -> None:
    """Calibrate MAX_REPROJECTION_FRACTION: the reprojection_norm distribution
    of fits that are right against fits that are wrong."""
    print("\n=== 10. Gate calibration: reprojection_norm ===")
    print(f"  A fit is 'unusable' when any matched face is more than {BAD_STEEP_DEG:g} deg out, or the")
    print(f"  height is more than {BAD_HEIGHT_CM:g} cm out, or it failed to produce every visible face.")
    print(f"  Two populations: every full-path fit_volume result, and the same volumes fitted")
    print(f"  with the right correspondence and vertices wrong by {noise_px:g} px (realistic mask noise).")
    rows = []
    for name in scenes:
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            mask = volume_mask(sc, v)
            if not mask.any():
                continue
            truth = truth_faces(v)
            fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
            if fit is not None:
                r = volume_row(sc, v, fit, match_faces(truth, fit))
                r.update(population="full", offset=float(np.linalg.norm(v["apex_offset_cm"])))
                rows.append(r)
            if v["family"] == "cylinder":
                continue
            rng = np.random.default_rng(len(rows))
            base = np.array(v["base_px"], dtype=float)
            raised = np.array(v["raised_px"], dtype=float)
            centre = np.vstack([base, raised]).mean(axis=0)
            noisy = dict(v, base_px=_noisy_vertices(base, centre, rng, noise_px, 0.0).tolist(),
                         raised_px=_noisy_vertices(raised, centre, rng, noise_px, 0.0).tolist())
            nfit = oracle_fit(noisy, K, n, d, g, mask)
            if nfit is not None:
                r = volume_row(sc, v, nfit, match_faces(truth, nfit))
                r.update(population="oracle+noise", offset=float(np.linalg.norm(v["apex_offset_cm"])))
                rows.append(r)

    print(f"\n  {'population':13s} {'verdict':8s} |   n | reprojection_norm: "
          f"min     p25     median  p75     max")
    for population in ("full", "oracle+noise"):
        for verdict in (False, True):
            picked = [r for r in rows if r["population"] == population and _is_bad(r) == verdict]
            if not picked:
                continue
            norms = np.sort([r["reproj_norm"] for r in picked])
            print(f"  {population:13s} {'UNUSABLE' if verdict else 'usable':8s} | {len(picked):3d} | "
                  f"{norms.min():7.3f} {np.percentile(norms, 25):7.3f} {np.median(norms):7.3f} "
                  f"{np.percentile(norms, 75):7.3f} {norms.max():7.3f}")

    good = [r for r in rows if not _is_bad(r)]
    bad = [r for r in rows if _is_bad(r)]
    print(f"\n  threshold sweep over all {len(rows)} fits ({len(good)} usable, {len(bad)} unusable):")
    print(f"  {'thresh':7s} | {'norm only: suppressed':21s} {'dropped':9s} | "
          f"{'norm+border: suppressed':23s} {'dropped':9s} | {'kept and unusable':17s}")
    for threshold in (0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.50):
        suppressed = sum(r["reproj_norm"] > threshold for r in bad)
        dropped = sum(r["reproj_norm"] > threshold for r in good)
        sup_b = sum((r["reproj_norm"] > threshold or r["clipped"]) for r in bad)
        drop_b = sum((r["reproj_norm"] > threshold or r["clipped"]) for r in good)
        print(f"  {threshold:7.2f} | {suppressed:3d}/{len(bad):<3d} "
              f"({suppressed / max(len(bad), 1):5.1%})      {dropped:3d}/{len(good):<3d}   | "
              f"{sup_b:3d}/{len(bad):<3d} ({sup_b / max(len(bad), 1):5.1%})        "
              f"{drop_b:3d}/{len(good):<3d}   | {len(bad) - sup_b:17d}")

    print("\n  the cases that decide the threshold:")
    for r in sorted(rows, key=lambda r: r["reproj_norm"]):
        interesting = (r["family"] == "cylinder" or r["offset"] > 0
                       or (not _is_bad(r)) != bool(r["trusted"]))
        if not interesting:
            continue
        print(f"    {r['scene']:16s} {r['name']:10s} {r['family']:9s} {r['population']:12s} "
              f"offset {r['offset']:4.0f} cm | norm {r['reproj_norm']:6.3f} clipped "
              f"{str(r['clipped']):5s} trusted {str(r['trusted']):5s} | steep max {r['steep_max']:5.1f} "
              f"h_err {r['h_err']:6.1f} cov {r['matched']}/{r['faces']} -> "
              f"{'UNUSABLE' if _is_bad(r) else 'usable'}")

    kept_bad = [r for r in rows if r["trusted"] and _is_bad(r)]
    dropped_good = [r for r in rows if not r["trusted"] and not _is_bad(r)]
    print(f"\n  at the shipped MAX_REPROJECTION_FRACTION = {volume.MAX_REPROJECTION_FRACTION} "
          f"plus the frame-border test: `trusted` keeps {len(kept_bad)} unusable fit(s) and "
          f"rejects {len(dropped_good)} usable one(s), out of {len(rows)}.")
    for r in kept_bad:
        print(f"    STILL TRUSTED AND UNUSABLE: {r['scene']}/{r['name']} ({r['family']}, "
              f"{r['population']}) norm {r['reproj_norm']:.3f} steep max {r['steep_max']:.1f} "
              f"h_err {r['h_err']:.1f} cov {r['matched']}/{r['faces']}")


def experiment_corners(scenes: list[str]) -> None:
    """What a better corner selection could buy, as an upper bound.

    Only wedges: all six of a wedge's vertices reach its silhouette, so the
    question is purely whether the reduction to six corners picks them. Each
    true vertex is snapped to the nearest point of the RAW contour (no
    simplification), which is the best any corner selector could do with the
    same mask, and fit_ridge is run on the result.
    """
    print("\n=== 11. Ceiling of a better corner selection (wedges) ===")
    print("  `outline` is what volume.outline_from_mask gives; `six?` whether dominant_corners")
    print("  can reduce it to exactly six; `snap` is how far the true vertices sit from the raw")
    print("  contour. The last columns are fit_ridge on the snapped vertices - the ceiling.")
    print(f"\n  {'scene':16s} {'vol':10s} {'outline':7s} {'six?':5s} {'now':12s} | "
          f"{'snap max px':11s} | {'ceiling h':9s} {'true h':6s} {'reproj':7s} {'steep max':9s}")
    now_ok = ceiling_ok = total = 0
    for name in scenes:
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            if v["family"] != "wedge":
                continue
            mask = volume_mask(sc, v)
            if not mask.any():
                continue
            total += 1
            truth = truth_faces(v)
            out = volume.outline_from_mask(mask)
            six = volume.dominant_corners(out, 6)
            fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
            row = volume_row(sc, v, fit, match_faces(truth, fit))
            good_now = fit is not None and not _is_bad(row)
            now_ok += good_now
            contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_NONE)
            raw = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(float)
            snapped, errs = [], []
            for group in (np.array(v["base_px"], dtype=float), np.array(v["raised_px"], dtype=float)):
                picked = []
                for p in group:
                    i = int(np.argmin(np.linalg.norm(raw - p, axis=1)))
                    picked.append(raw[i])
                    errs.append(float(np.linalg.norm(raw[i] - p)))
                snapped.append(np.array(picked))
            ceiling = volume.fit_ridge(snapped[0], snapped[1], n, d, K)
            crow = None
            if ceiling is not None:
                for face in ceiling["faces"]:
                    face.update(volume.describe_face(face["normal"], n, g))
                ceiling.update(shape="wedge", depth_cm=round(float(np.max(ceiling["heights"])), 1),
                               iou=float("nan"))
                crow = volume_row(sc, v, ceiling, match_faces(truth, ceiling))
                ceiling_ok += not _is_bad(crow)
            print(f"  {name:16s} {v['name']:10s} {len(out):7d} "
                  f"{('yes' if six is not None else 'NO'):5s} "
                  f"{(str(row['shape']) + (' ok' if good_now else ' BAD')):12s} | "
                  f"{_agg(errs, 'max'):11.1f} | "
                  f"{(ceiling['depth_cm'] if ceiling else float('nan')):9.1f} {v['height_cm']:6.1f} "
                  f"{(ceiling['reprojection_px'] if ceiling else float('nan')):7.1f} "
                  f"{(crow['steep_max'] if crow else float('nan')):9.1f}")
    print(f"\n  wedges usable now: {now_ok}/{total}; with a perfect corner selection on the same "
          f"mask: {ceiling_ok}/{total} (+{ceiling_ok - now_ok})")

    print("\n  Two-face boxes: what IS on the silhouette, and the ceiling for that composition.")
    print("  `composition` counts how many of the six dominant corners are base (B) and how many")
    print("  are top (T) vertices. The ceiling solves the height from the two observed base")
    print("  corners and the two top corners above them, then derives the hidden base corners")
    print("  from the other two top corners - i.e. the 2-base + 4-top reading of the outline.")
    print(f"\n  {'scene':16s} {'vol':10s} {'vis':4s} {'composition':11s} {'now':14s} | "
          f"{'ceiling h':9s} {'true h':6s} {'reproj':7s} {'steep max':9s} {'faces':6s}")
    box_now = box_ceiling = box_total = 0
    for name in scenes:
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            if v["family"] != "box":
                continue
            mask = volume_mask(sc, v)
            if not mask.any():
                continue
            box_total += 1
            truth = truth_faces(v)
            vis = sum(1 for f in v["faces"] if f.get("visible"))
            fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
            row = volume_row(sc, v, fit, match_faces(truth, fit))
            good_now = fit is not None and not _is_bad(row)
            box_now += good_now
            contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_NONE)
            raw = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(float)
            base_px = np.array(v["base_px"], dtype=float)
            top_px = np.array(v["raised_px"], dtype=float)
            on_base = [i for i, p in enumerate(base_px)
                       if np.linalg.norm(raw - p, axis=1).min() <= 3.0]
            on_top = [i for i, p in enumerate(top_px)
                      if np.linalg.norm(raw - p, axis=1).min() <= 3.0]
            ceiling = crow = None
            if len(on_base) == 2 and len(on_top) == 4:
                anchors = volume.backproject(base_px[on_base], n, d, K)
                solved = volume._solve_height(anchors, top_px[on_base], n, d, K)
                if solved is not None and np.isfinite(anchors).all():
                    h = solved[0]
                    rays = volume.rays(top_px, K)
                    top = np.vstack([volume.point_at_height(r, n, d, h) for r in rays])
                    base = top - h * np.asarray(n, dtype=float)
                    if volume._plausible(base, h):
                        faces = volume.faces_from_top(base, top)
                        for face in faces:
                            face.update(volume.describe_face(face["normal"], n, g))
                        ceiling = {"faces": faces, "shape": "box", "depth_cm": round(h, 1),
                                   "h_source": "box-two-face", "iou": float("nan"),
                                   "reprojection_px": round(solved[1], 1),
                                   "offcentre_gain": solved[2]}
                        crow = volume_row(sc, v, ceiling, match_faces(truth, ceiling))
                        box_ceiling += not _is_bad(crow)
            print(f"  {name:16s} {v['name']:10s} {vis}/5  "
                  f"{f'{len(on_base)}B + {len(on_top)}T':11s} "
                  f"{(str(row['shape']) + (' ok' if good_now else ' BAD')):14s} | "
                  f"{(ceiling['depth_cm'] if ceiling else float('nan')):9.1f} {v['height_cm']:6.1f} "
                  f"{(ceiling['reprojection_px'] if ceiling else float('nan')):7.1f} "
                  f"{(crow['steep_max'] if crow else float('nan')):9.1f} "
                  f"{(f'{crow['matched']}/{crow['faces']}' if crow else '-'):6s}")
    print(f"\n  boxes usable now: {box_now}/{box_total}; reading the two-face outline as "
          f"2 base + 4 top instead: {box_ceiling} more would fit")


def experiment_timing(scenes: list[str], repeats: int = 3) -> None:
    print("\n=== 9. Timing (ms per volume) ===")
    rows = []
    for name in scenes[:8]:
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            mask = volume_mask(sc, v)
            if not mask.any():
                continue
            poly = outline(mask)
            for label, gray in (("with ridges", sc["gray"]), ("no ridges", None)):
                best = []
                for _ in range(repeats):
                    t = time.perf_counter()
                    volume.fit_volume(poly, n, d, K, mask, gray, g)
                    best.append(1000 * (time.perf_counter() - t))
                rows.append((label, float(np.min(best))))
            t = time.perf_counter()
            volume.ridge_segments(sc["gray"], mask)
            rows.append(("ridge_segments only", 1000 * (time.perf_counter() - t)))
    for label in ("with ridges", "no ridges", "ridge_segments only"):
        ms = np.array([t for lab, t in rows if lab == label])
        print(f"  {label:20s} n={len(ms):3d}  mean {ms.mean():7.1f} ms  median "
              f"{np.median(ms):7.1f}  max {ms.max():7.1f}")


def _fold(tilt_deg: float, facing_deg: float) -> tuple[float, float]:
    """A face tilted past 90 deg from vertical is past straight-up (or
    straight-down) and `steepness_deg` cannot say so: arcsin folds it back and
    the face now points the other way round the gravity axis. Hand expectations
    have to fold the same way before they can be compared."""
    t = (tilt_deg + 180.0) % 360.0 - 180.0
    if t > 90.0:
        return 180.0 - t, facing_deg + 180.0
    if t < -90.0:
        return -180.0 - t, facing_deg + 180.0
    return t, facing_deg


def experiment_convention() -> None:
    print("\n=== 0. describe_face convention check (hand-computed cases) ===")
    print("  the five faces of a box on a wall at `wall`, each with a normal written down")
    print("  by hand. Expectations are folded into arcsin's +-90 range (see _fold).")
    bad = 0
    for wall_deg in (-10.0, 0.0, 20.0, 40.0):
        fr = fakewall.frames(fakewall.Scene("probe", wall_deg, 0.0, 300.0))
        cases = [("top (parallel to wall)", fr["n_world"], wall_deg, 0.0),
                 ("upward-facing side", fr["u_world"], wall_deg - 90.0, 0.0),
                 ("downward-facing side", -fr["u_world"], wall_deg + 90.0, 0.0),
                 ("right-facing side", fr["r_world"], 0.0, 90.0),
                 ("left-facing side", -fr["r_world"], 0.0, -90.0)]
        for label, normal_world, tilt, facing in cases:
            steep, face_to = _fold(tilt, facing)
            described = volume.describe_face(fr["R"] @ normal_world, fr["n"], fr["gravity"])
            #Within FACING_UNDEFINED_STEEPNESS_DEG of horizontal the facing is
            #meaningless and describe_face now declines to report it.
            known = abs(steep) <= volume.FACING_UNDEFINED_STEEPNESS_DEG
            ok = abs(_wrap(described["steepness_deg"] - steep)) < 0.1
            ok &= (abs(_wrap(described["facing_deg"] - face_to)) < 0.1 if known
                   else described["facing_deg"] is None)
            bad += not ok
            got = ("undefined" if described["facing_deg"] is None
                   else f"{described['facing_deg']:+6.1f}")
            print(f"  wall {wall_deg:+5.1f}  {label:24s} expect steep {steep:+6.1f} facing "
                  f"{f'{face_to:+6.1f}' if known else 'undefined':>9s} | got "
                  f"{described['steepness_deg']:+6.1f} {got:>9s} "
                  f"({described['facing']:>12s}) {'ok' if ok else 'MISMATCH'}")
    print(f"  {bad} mismatches")


def _diagnostic_table(label: str, rows: list[dict], key: str, edges) -> None:
    print(f"  {label} by {key}:")
    for low, high in zip(edges[:-1], edges[1:]):
        picked = [r for r in rows if np.isfinite(r[key]) and low <= r[key] < high]
        if not picked:
            continue
        print(f"    {key} {low:6.2f}-{high:<6.2f} n={len(picked):3d} | steep med "
              f"{_agg([r['steep_med'] for r in picked]):5.1f} max "
              f"{_agg([r['steep_max'] for r in picked], 'max'):5.1f} | h_err med "
              f"{_agg([r['h_err'] for r in picked]):6.1f} max "
              f"{_agg([r['h_err'] for r in picked], 'max'):6.1f}")


def experiment_gonogo(scenes: list[str]) -> None:
    print("\n=== Go / no-go, full pipeline over every scene ===")
    per_family: dict[str, list] = {}
    all_rows, oracle_all = [], []
    diag_full, diag_good = [], []
    #Two gated views: what `trusted` actually accepts (reprojection AND the
    #frame-border test), and reprojection alone, to show what the border test
    #is worth on its own.
    gated: dict[str, list] = {
        f"trusted (norm<={volume.MAX_REPROJECTION_FRACTION:g} + border)": [],
        f"norm<={volume.MAX_REPROJECTION_FRACTION:g} only": [],
    }
    gate_keys = list(gated)
    for name in scenes:
        sc = fakewall.load(name)
        K, n, d, g = inputs(sc)
        for v in sc["meta"]["volumes"]:
            mask = volume_mask(sc, v)
            if not mask.any():
                continue
            truth = truth_faces(v)
            fit, _, _ = fit_volume_for(sc, v, K, n, d, g, sc["gray"], mask=mask)
            rows = match_faces(truth, fit)
            all_rows += rows
            per_family.setdefault(v["family"], []).extend(rows)
            if fit is not None:
                diag_full.append(volume_row(sc, v, fit, rows))
                #What production would actually report: only the fits the
                #reprojection gate trusts. Scored at the shipped threshold and
                #at the one this evaluation recommends.
                if fit["trusted"]:
                    gated[gate_keys[0]] += rows
                if fit["reprojection_norm"] <= volume.MAX_REPROJECTION_FRACTION:
                    gated[gate_keys[1]] += rows
            oracle = oracle_fit(v, K, n, d, g, mask)
            oracle_all += match_faces(truth, oracle)
            #The "good fit, realistic noise" population a gate must not reject:
            #right correspondence, vertices wrong by 5 px.
            if v["family"] != "cylinder":
                rng = np.random.default_rng(len(diag_good))
                base = np.array(v["base_px"], dtype=float)
                raised = np.array(v["raised_px"], dtype=float)
                centre = np.vstack([base, raised]).mean(axis=0)
                noisy = dict(v, base_px=_noisy_vertices(base, centre, rng, 5.0, 0.0).tolist(),
                             raised_px=_noisy_vertices(raised, centre, rng, 5.0, 0.0).tolist())
                nfit = oracle_fit(noisy, K, n, d, g, mask)
                if nfit is not None:
                    diag_good.append(volume_row(sc, v, nfit, match_faces(truth, nfit)))
    print(f"  {'family':10s} | {'faces':11s} | {'steep med':9s} {'p90':6s} {'max':6s} | "
          f"{'facing med':10s} | {'bucket':6s} {'bkt/rep':7s} {'notrep':6s} {'1-side':6s} | {'flips':5s}")
    for family, rows in sorted(per_family.items()):
        s = summarise(rows)
        print(f"  {family:10s} | {s['matched']:4d}/{s['faces']:<6d} | {s['steep_med']:9.1f} "
              f"{s['steep_p90']:6.1f} {s['steep_max']:6.1f} | {s['facing_med']:10.1f} | "
              f"{s['bucket']:6.2f} {s['bucket_all']:7.2f} {s['not_reported']:6d} {s['disagree']:6d} | {s['flips']:5d}")
    s = summarise(all_rows)
    o = summarise(oracle_all)
    print(f"  {'ALL (full)':10s} | {s['matched']:4d}/{s['faces']:<6d} | {s['steep_med']:9.1f} "
          f"{s['steep_p90']:6.1f} {s['steep_max']:6.1f} | {s['facing_med']:10.1f} | "
          f"{s['bucket']:6.2f} {s['bucket_all']:7.2f} {s['not_reported']:6d} {s['disagree']:6d} | {s['flips']:5d}")
    print(f"  {'ALL (oracle)':10s} | {o['matched']:4d}/{o['faces']:<6d} | {o['steep_med']:9.1f} "
          f"{o['steep_p90']:6.1f} {o['steep_max']:6.1f} | {o['facing_med']:10.1f} | "
          f"{o['bucket']:6.2f} {o['bucket_all']:7.2f} {o['not_reported']:6d} {o['disagree']:6d} | {o['flips']:5d}")
    for key in gate_keys:
        t = summarise(gated[key])
        print(f"  {key:10.10s} | {t['matched']:4d}/{t['faces']:<6d} | {t['steep_med']:9.1f} "
              f"{t['steep_p90']:6.1f} {t['steep_max']:6.1f} | {t['facing_med']:10.1f} | "
              f"{t['bucket']:6.2f} {t['bucket_all']:7.2f} {t['not_reported']:6d} {t['disagree']:6d} | "
              f"{t['flips']:5d}")
    for label, s2 in (("full", s), ("oracle", o),
                      *[(k, summarise(gated[k])) for k in gate_keys]):
        print(f"  [{label}] steepness median {s2['steep_med']:.2f} deg "
              f"(bar {BAR_STEEPNESS_DEG}) -> {'PASS' if s2['steep_med'] <= BAR_STEEPNESS_DEG else 'FAIL'}"
              f" | facing bucket {s2['bucket_all']:.2f} of the {s2['reportable']} truth faces that have one "
              f"(bar {BAR_BUCKET_FRACTION}) -> "
              f"{'PASS' if s2['bucket_all'] >= BAR_BUCKET_FRACTION else 'FAIL'}"
              f" | sign flips {s2['flips']} -> {'PASS' if s2['flips'] == 0 else 'FAIL'}")

    print("\n  Can a diagnostic gate a bad fit? Every full-path fit, bucketed by its own")
    print("  reprojection_px and iou, against the error it actually made:")
    _diagnostic_table("full-path fits", diag_full, "reproj_norm", [0, 0.02, 0.05, 0.10, 0.30, 1e9])
    _diagnostic_table("full-path fits", diag_full, "iou", [0, 0.8, 0.9, 0.95, 0.98, 1.01])
    print("  the population a gate must NOT reject - right correspondence, vertices wrong")
    print("  by 5 px (so these are the fits worth keeping):")
    _diagnostic_table("good fits", diag_good, "reproj_norm", [0, 0.02, 0.05, 0.10, 0.30, 1e9])
    print(f"    of {len(diag_good)} good fits, reproj_norm max "
          f"{_agg([r['reproj_norm'] for r in diag_good], 'max'):.3f}, "
          f"p90 {_agg([r['reproj_norm'] for r in diag_good], 'p90'):.3f} "
          f"(experiment 10 calibrates the threshold)")


EXPERIMENTS = ("convention", "report", "clean", "noise", "occlusion", "offaxis", "offcentre",
               "focal", "ridge", "holds", "family", "gate", "corners", "timing", "gonogo")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=fakewall.OUT_DIR)
    parser.add_argument("--scenes", nargs="*", default=None)
    parser.add_argument("--experiment", nargs="*", default=["all"],
                        help=f"any of: all, {', '.join(EXPERIMENTS)}")
    parser.add_argument("--repeats", type=int, default=4, help="mask-noise repeats per setting")
    args = parser.parse_args()
    fakewall.OUT_DIR = args.out
    scenes = args.scenes or [p.stem for p in sorted(args.out.glob("*.json"))]
    scenes = [s for s in scenes if (args.out / f"{s}_faces.npy").exists()]
    want = EXPERIMENTS if "all" in args.experiment else args.experiment
    for name in want:
        if name == "convention":
            experiment_convention()
        elif name == "report":
            for scene in scenes:
                report(fakewall.load(scene))
        elif name == "clean":
            experiment_clean(scenes)
        elif name == "noise":
            experiment_noise(args.repeats)
        elif name == "occlusion":
            experiment_occlusion()
        elif name == "offaxis":
            experiment_offaxis()
        elif name == "offcentre":
            experiment_offcentre()
        elif name == "focal":
            experiment_focal(scenes)
        elif name == "ridge":
            experiment_ridge(scenes)
        elif name == "holds":
            experiment_holds()
        elif name == "family":
            experiment_family(scenes)
        elif name == "gate":
            experiment_gate(scenes)
        elif name == "corners":
            experiment_corners(scenes)
        elif name == "timing":
            experiment_timing(scenes)
        elif name == "gonogo":
            experiment_gonogo(scenes)


if __name__ == "__main__":
    main()
