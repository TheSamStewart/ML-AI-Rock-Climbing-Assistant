"""DEV ONLY - volume.py on REAL photos, scored against hand-measured volumes.
Not used by the API. The synthetic counterpart is eval_volume.py.

Input is a capture folder: `photo.jpg` plus `truth.json`, and optionally the
`capture.json` the old in-app capture tool wrote (it carries the phone's
gravity reading). A plain phone photo works too - see "Gravity" below.

Three fit paths per volume, mirroring eval_volume.py's full / oracle split so
a miss can be blamed on the right stage:

  full      fit_volume on the volume's YOLO mask - what production would do.
            The mask is the model's RAW mask, re-run here, not the saved
            polygon: run_detection simplifies at POLYGON_SIMPLIFY_EPS, which
            drops the sixth corner of a box or wedge (handover 2026-11-20,
            bug 4), so the saved polygon would understate the method.
  oracle    the right fitter on hand-clicked corners (`base_px` / `raised_px`
            in truth.json, from draw_volume_corners.py). No correspondence
            problem, so what is left is the real geometry: wall plane, focal
            length, a volume that is not an ideal solid, and - for pyramids -
            the apex-over-centroid assumption.
  depth     the oracle again with the MEASURED depth passed as `height_cm`.
            This is the answer to the open pyramid question: it shows what a
            catalogue / user-typed depth would buy over the centroid
            assumption, on real volumes.

Gravity (needed for face steepness): the capture's sensor reading when there
is one; otherwise solved from the wall angle measured beside the volume
(`wall_angle_deg`) with the phone assumed upright (no roll); otherwise
angle.DEFAULT_PITCH_DEG with a warning. The second is slightly circular for
the WALL angle, so the wall-angle column is not scored in that case - only
the faces are.

With no `volumes` in truth.json, `--survey` still fits every VOLUME detection
and reports coverage and how many fits are `trusted`, which needs no
measurements at all.

Usage (from backend/):
  uv run python eval_volume_field.py                       # every folder in field_captures/
  uv run python eval_volume_field.py path/to/capture ...   # chosen folders
  uv run python eval_volume_field.py field_captures_volumes/V0*   # measured volumes, A/B/edge photos
                                                           #   (volume.json; see load_volume_folder)
  uv run python eval_volume_field.py --survey              # also fit unmeasured VOLUME detections
  uv run python eval_volume_field.py --volume-conf 0.05    # lower YOLO's VOLUME floor
Overlays (one crop per volume) go to <temp>/eval_volume_field unless --out.

truth.json "volumes" entry (all fields optional except `id`; null = not
recorded):
  {
    "id": "V1",                        free label, also on the overlay
    "detection_id": 9,                 id on overlay_<n>.jpg / this script's survey overlay
    "base_px": [[x, y], ...],          normalised, from draw_volume_corners.py
    "raised_px": [[x, y], ...],        apex (1), ridge ends (2) or top corners (as many as base)
    "shape": "square pyramid",         triangular pyramid / square pyramid / wedge / box / curved / other
    "faces": [{"name": "left", "angle_deg": 35, "facing": "left"}],
                                       angle: level along the face's STEEPEST line,
                                       degrees from vertical, + overhang, - slab.
                                       facing: out / left / right / up / down
    "depth_cm": 25,                    apex/top off the wall, square to the wall
    "apex_offset_cm": {"right": 0, "up": 3},
    "base_edges_cm": [60, 60, 60, 60],
    "wall_angle_deg": -2,              wall just beside the volume
    "colour": "black", "wall_colour": "plywood",
    "base_corner_hidden": "none",      none / partly / fully
    "notes": ""
  }
"""

import argparse
import json
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

import angle
import bolts
import detection
import scale
import volume

CAPTURES = Path(__file__).parent / "field_captures"
#Same go/no-go bars as eval_volume.py, so synthetic and real numbers compare.
BAR_STEEPNESS_DEG = 5.0
BAR_BUCKET_FRACTION = 0.90
SIGN_DEAD_ZONE_DEG = 2.0
#Cost of pairing a truth face with an estimated face that points another way,
#in degrees of steepness: large enough that facing decides the pairing, small
#enough that a face with a wrong facing still gets scored on steepness.
FACING_MISMATCH_COST = 30.0
#A truth face further than this from every estimate is "not produced".
MATCH_LIMIT_DEG = 45.0
#A YOLO mask is the volume named in truth.json when it overlaps the saved
#polygon this much.
MATCH_IOU = 0.5
#Overlay crop: the volume's box grown by this fraction on each side.
CROP_MARGIN = 0.35
DEFAULT_BOLT_SPACING_CM = 25.0
FACING_ALIASES = {"up": "undefined", "down": "undefined", "flat": "undefined",
                  "towards you": "out", "toward you": "out", "out": "out",
                  "left": "left", "right": "right", "undefined": "undefined"}
FAMILY_OF_SHAPE = {"pyramid-3": "triangular pyramid", "pyramid-4": "square pyramid",
                   "pyramid-5": "pyramid-5", "wedge": "wedge", "box": "box",
                   "box-hexagon": "box", "box-two-face": "box", "box-translate": "box"}


# -------------------------------------------------------------------------
# loading
# -------------------------------------------------------------------------

def _photo(folder: Path) -> Path | None:
    for name in ("photo.jpg", "photo.jpeg", "photo.png"):
        if (folder / name).exists():
            return folder / name
    found = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    found = [p for p in found if not p.name.startswith("overlay")]
    return found[0] if found else None


def load(folder: Path) -> dict | None:
    photo = _photo(folder)
    if photo is None:
        print(f"{folder.name}: no photo (HEIC is not readable - export as JPEG)")
        return None
    raw = Image.open(photo)
    exif = raw.getexif().get_ifd(0x8769)
    image = ImageOps.exif_transpose(raw)
    image.load()
    image = image.convert("RGB")

    def read(name):
        p = folder / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    capture, truth = read("capture.json"), read("truth.json")
    f35 = (capture.get("photo") or {}).get("focal_35mm") or exif.get(41989)
    return {"folder": folder, "image": image, "capture": capture, "truth": truth,
            "focal_35mm": float(f35) if f35 else None}


# -------------------------------------------------------------------------
# pipeline inputs
# -------------------------------------------------------------------------

def yolo(image, volume_conf: float) -> list[dict]:
    """run_detection's list, plus each detection's raw full-res mask, with the
    VOLUME floor lowered to `volume_conf`. HOLD keeps its floor, because the
    big volumes in 174933 come back as HOLD and must stay matchable by id."""
    floors = dict(detection.CONFIDENCE_FLOORS)
    floors["VOLUME"] = min(floors["VOLUME"], volume_conf)
    model = detection.get_model()
    small = image.copy()
    small.thumbnail((detection.MAX_INPUT_SIDE, detection.MAX_INPUT_SIDE))
    result = model.predict(small, conf=min(floors.values()), verbose=False,
                           **detection.PREDICT_KWARGS)[0]
    out = []
    if result.masks is None:
        return out
    width, height = image.size
    for mask, class_id, conf in zip(result.masks.data, result.boxes.cls, result.boxes.conf):
        name = model.names[int(class_id)]
        if float(conf) < floors.get(name, max(floors.values())):
            continue
        m = mask.cpu().numpy().astype(np.float32)
        polygon = detection._mask_to_polygon(mask, result.orig_shape)
        if polygon.shape[0] == 0:
            continue
        out.append({"id": len(out), "class_name": name, "confidence": float(conf),
                    "polygon": [{"x": float(x), "y": float(y)} for x, y in polygon],
                    "_raw": m})
    for det in out:  #to full res only now, keeping the list light until needed
        det["_size"] = (width, height)
    return out


def full_mask(det: dict) -> np.ndarray:
    width, height = det["_size"]
    return cv2.resize(det["_raw"], (width, height), interpolation=cv2.INTER_LINEAR) > 0.5


def polygon_mask(points_norm, size) -> np.ndarray:
    width, height = size
    pts = np.array([[p["x"] * width, p["y"] * height] if isinstance(p, dict)
                    else [p[0] * width, p[1] * height] for p in points_norm], np.float32)
    mask = np.zeros((height, width), np.uint8)
    cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 1)
    return mask.astype(bool)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = int((a | b).sum())
    return float((a & b).sum() / union) if union else 0.0


def gravity_for(cap: dict, n_wall: np.ndarray | None, wall_angle: float | None):
    """(gravity, source). See the module docstring."""
    reading = (cap["capture"].get("sensor") or {}).get("gravity_sent")
    if reading is not None:
        solved = angle.gravity_from_sensor(reading)
        if solved is not None:
            return solved[0], "sensor"
    if n_wall is not None and wall_angle is not None:
        pitches = np.arange(-30.0, 60.0, 0.1)
        err = [abs(volume.describe_face(n_wall, n_wall, angle.gravity_from_pitch(p))["steepness_deg"]
                   - wall_angle) for p in pitches]
        best = float(pitches[int(np.argmin(err))])
        return angle.gravity_from_pitch(best), f"wall-angle (pitch {best:.1f})"
    return angle.gravity_from_pitch(angle.DEFAULT_PITCH_DEG), f"ASSUMED pitch {angle.DEFAULT_PITCH_DEG:g}"


# -------------------------------------------------------------------------
# fits
# -------------------------------------------------------------------------

def _finish(fit: dict | None, mask, K, n, g, shape: str, source: str) -> dict | None:
    """The bookkeeping fit_volume does for its own winner, for a fit made by
    calling one fitter directly (the oracle and depth paths)."""
    if fit is None:
        return None
    size = np.sqrt(max(float(mask.sum()), 1.0)) if mask is not None else float("nan")
    fit.update(shape=shape, apex_source=source,
               depth_cm=round(float(np.max(fit["heights"])), 1),
               reprojection_norm=round(fit["reprojection_px"] / size, 3),
               clipped_by_frame=volume.touches_frame_border(mask) if mask is not None else False)
    #Same rule as fit_volume: a centroid-assumed pyramid is never trusted.
    fit["trusted"] = bool(fit["reprojection_norm"] <= volume.MAX_REPROJECTION_FRACTION
                          and not fit["clipped_by_frame"]
                          and fit["h_source"] != "centroid-assumed")
    for face in fit["faces"]:
        face.update(volume.describe_face(face["normal"], n, g))
    return fit


def oracle(base_px, raised_px, n, d, K, g, mask, height_cm=None) -> dict | None:
    """The fitter named by the clicked corners. The wedge's ridge order and the
    box's corner pairing are tried every way round, as fit_volume does, and the
    lowest reprojection wins - the human only has to click, not to know
    fit_ridge's anchoring convention."""
    base, raised = np.asarray(base_px, float), np.asarray(raised_px, float)
    tag = "depth" if height_cm is not None else "clicked"
    if len(raised) == 1:
        return _finish(volume.fit_pyramid(base, raised[0], n, d, K, height_cm=height_cm),
                       mask, K, n, g, f"pyramid-{len(base)}", tag)
    tries = []
    if len(raised) == 2 and len(base) == 4:
        for roll in range(4):
            b = np.roll(base, -roll, axis=0)
            for r in (raised, raised[::-1]):
                tries.append(("wedge", volume.fit_ridge(b, r, n, d, K, height_cm=height_cm)))
    elif len(raised) == len(base) >= 3:
        tries.append(("box", volume.fit_box(base, raised, n, d, K, height_cm=height_cm)))
    tries = [(s, f) for s, f in tries if f is not None]
    if not tries:
        return None
    shape, fit = min(tries, key=lambda t: t[1]["reprojection_px"])
    return _finish(fit, mask, K, n, g, shape, tag)


# -------------------------------------------------------------------------
# scoring
# -------------------------------------------------------------------------

def _facing(label) -> str | None:
    return None if label is None else FACING_ALIASES.get(str(label).strip().lower(), str(label))


def match(truth_faces: list[dict], fit: dict | None) -> list[dict]:
    """Pair each measured face with one visible fitted face, cheapest first:
    steepness difference plus FACING_MISMATCH_COST when both sides name a
    different facing. Measured faces carry no normal, so this is the closest a
    tape-and-level truth can be matched."""
    est = [f for f in (fit or {}).get("faces", []) if f.get("visible")]
    pairs = []
    for ti, t in enumerate(truth_faces):
        if t.get("angle_deg") is None:
            continue
        tf = _facing(t.get("facing"))
        for ei, e in enumerate(est):
            cost = abs(t["angle_deg"] - e["steepness_deg"])
            if tf and tf != "undefined" and e["facing"] != "undefined" and tf != e["facing"]:
                cost += FACING_MISMATCH_COST
            pairs.append((cost, ti, ei))
    taken, used = {}, set()
    for cost, ti, ei in sorted(pairs):
        if ti in taken or ei in used or cost > MATCH_LIMIT_DEG + FACING_MISMATCH_COST:
            continue
        taken[ti], _ = ei, used.add(ei)
    rows = []
    for ti, t in enumerate(truth_faces):
        if t.get("angle_deg") is None:
            continue
        if ti not in taken:
            rows.append({"name": t.get("name"), "truth": t["angle_deg"], "matched": False})
            continue
        e = est[taken[ti]]
        tf = _facing(t.get("facing"))
        both = tf not in (None, "undefined") and e["facing"] != "undefined"
        rows.append({
            "name": t.get("name"), "truth": t["angle_deg"], "est": e["steepness_deg"],
            "matched": True, "steep_err": abs(t["angle_deg"] - e["steepness_deg"]),
            "facing_truth": tf, "facing_est": e["facing"],
            "bucket_ok": (tf == e["facing"]) if both else None,
            "sign_flip": bool(abs(t["angle_deg"]) > SIGN_DEAD_ZONE_DEG
                              and abs(e["steepness_deg"]) > SIGN_DEAD_ZONE_DEG
                              and np.sign(t["angle_deg"]) != np.sign(e["steepness_deg"])),
        })
    return rows


def summary(label: str, rows: list[dict]) -> None:
    """rows: one per volume per path, each with `faces` from match()."""
    faces = [f for r in rows for f in r["faces"]]
    if not faces:
        print(f"  {label:22s} no measured faces")
        return
    m = [f for f in faces if f["matched"]]
    err = np.array([f["steep_err"] for f in m]) if m else np.zeros(0)
    buckets = [f["bucket_ok"] for f in m if f["bucket_ok"] is not None]
    depth = [abs(r["depth_err"]) for r in rows if r.get("depth_err") is not None]
    print(f"  {label:22s} volumes {len(rows):2d} | faces {len(m)}/{len(faces)}"
          f" | steep med {np.median(err) if len(err) else float('nan'):5.1f}"
          f" p90 {np.percentile(err, 90) if len(err) else float('nan'):5.1f}"
          f" | bucket {np.mean(buckets) if buckets else float('nan'):.2f}"
          f" | flips {sum(f['sign_flip'] for f in m)}"
          f" | depth err med {np.median(depth) if depth else float('nan'):5.1f} cm"
          f"  (bars: steep med <= {BAR_STEEPNESS_DEG:g}, bucket >= {BAR_BUCKET_FRACTION:g}, flips 0)")


# -------------------------------------------------------------------------
# overlay
# -------------------------------------------------------------------------

def overlay(image, mask, fits: dict, K, title: str, path: Path, clicked=None) -> None:
    rgb = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    mx, my = int((x1 - x0) * CROP_MARGIN) + 20, int((y1 - y0) * CROP_MARGIN) + 20
    x0, y0 = max(0, x0 - mx), max(0, y0 - my)
    x1, y1 = min(rgb.shape[1], x1 + mx), min(rgb.shape[0], y1 + my)
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(rgb, contours, -1, (0, 255, 255), 3)
    colours = {"full": (0, 200, 0), "oracle": (255, 128, 0), "depth": (255, 0, 255)}
    lines = [title]
    for name, fit in fits.items():
        if fit is None:
            lines.append(f"{name}: no fit")
            continue
        colour = colours[name] if fit["trusted"] else (0, 0, 255)
        for face in fit["faces"]:
            if not face["visible"]:
                continue
            px = volume.project(face["corners"], K)
            if np.isfinite(px).all():
                cv2.polylines(rgb, [np.round(px).astype(np.int32)], True, colour, 2)
        steep = ", ".join(f"{f['steepness_deg']:+.0f}{f['facing'][0]}" for f in fit["faces"] if f["visible"])
        lines.append(f"{name}: {fit['shape']} {'TRUSTED' if fit['trusted'] else 'untrusted'}"
                     f" rep {fit['reprojection_norm']:.3f} depth {fit['depth_cm']:.0f}cm [{steep}]")
    if clicked is not None:
        for p in clicked[0]:
            cv2.circle(rgb, tuple(int(v) for v in p), 9, (255, 0, 0), -1)
        for p in clicked[1]:
            cv2.circle(rgb, tuple(int(v) for v in p), 9, (255, 0, 255), -1)
    crop = rgb[y0:y1, x0:x1].copy()
    scale_px = max(1.0, crop.shape[1] / 900)
    for i, text in enumerate(lines):
        org = (8, int((24 + 26 * i) * scale_px))
        cv2.putText(crop, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale_px, (0, 0, 0), int(4 * scale_px))
        cv2.putText(crop, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale_px, (255, 255, 255), int(1.5 * scale_px))
    cv2.imwrite(str(path), crop)


def survey_overlay(image, dets: list[dict], path: Path) -> None:
    """The whole photo with this script's detection ids, so truth.json can
    name a volume by `detection_id` on a photo the app never saw."""
    rgb = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    w, h = image.size
    for det in dets:
        pts = np.array([[p["x"] * w, p["y"] * h] for p in det["polygon"]], np.int32)
        colour = (255, 0, 255) if det["class_name"] == "VOLUME" else (0, 0, 255)
        cv2.polylines(rgb, [pts], True, colour, 3)
        c = pts.mean(axis=0).astype(int)
        cv2.putText(rgb, str(det["id"]), tuple(c), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 8)
        cv2.putText(rgb, str(det["id"]), tuple(c), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
    cv2.imwrite(str(path), rgb)


# -------------------------------------------------------------------------
# per capture
# -------------------------------------------------------------------------

def _facing_from_points(points: str | None) -> str | None:
    """volume.json's free-text 'points' (left / right / up / down / at me, or
    a mix) as the matcher's facing. describe_face's facing is the turn about
    gravity, so up / down / at me all mean 'out'; a mix of a side with
    anything else is ambiguous, and is left unset (steepness alone matches)."""
    words = {w.strip() for w in (points or "").lower().split(",") if w.strip()}
    sides = words & {"left", "right"}
    if not words:
        return None
    if sides:
        return sides.pop() if words == sides else None
    return "out"


def load_volume_folder(folder: Path) -> list[dict]:
    """One capture per photo in a field_captures_volumes/ folder (photo_A,
    photo_B, photo_edge), in the shape run() takes. The truth is volume.json,
    converted to a truth.json 'volumes' entry; the volume's id on each photo is
    `detection_ids[role]` (ids of the day's /detect in capture.json). Faces with
    `"score": false` are left out of the scoring."""
    vol = json.loads((folder / "volume.json").read_text(encoding="utf-8"))
    capture = json.loads((folder / "capture.json").read_text(encoding="utf-8"))
    ids = vol.get("detection_ids") or {}
    faces = [{"name": f"{f.get('number')} {f.get('name', '')}".strip(),
              "angle_deg": f.get("angle_deg") if f.get("score", True) else None,
              "facing": _facing_from_points(f.get("points"))}
             for f in vol.get("faces") or []]
    caps = []
    for entry in capture.get("photos") or []:
        role = entry["role"]
        raw = Image.open(folder / entry["file"])
        image = ImageOps.exif_transpose(raw)
        image.load()
        image = image.convert("RGB")
        v = {"id": f"{vol['volume']}-{role}", "detection_id": ids.get(role),
             "shape": vol.get("shape"), "faces": faces, "depth_cm": vol.get("depth_cm"),
             "wall_angle_deg": vol.get("wall_angle_beside_deg")}
        f35 = (entry.get("photo") or {}).get("focal_35mm")
        caps.append({"folder": folder, "name": f"{folder.name}-{role}", "image": image,
                     "capture": {"sensor": entry.get("sensor"),
                                 "detections": (entry.get("detect") or {}).get("detections") or []},
                     "truth": {"volumes": [v] if v["detection_id"] is not None else [],
                               "bolt_spacing_cm_measured": vol.get("bolt_spacing_cm")},
                     "focal_35mm": float(f35) if f35 else None})
    return caps


def run(folder: Path, args, out_dir: Path, cap: dict | None = None) -> list[dict]:
    """Score one capture. `cap` is an already-loaded capture (a volume folder's
    photo, see load_volume_folder); without it the old one-photo folder is
    loaded."""
    cap = cap or load(folder)
    if cap is None:
        return []
    label = cap.get("name", folder.name)
    image, truth = cap["image"], cap["truth"]
    size = image.size
    measured = truth.get("volumes") or []
    if not measured and not args.survey:
        return []

    t0 = time.perf_counter()
    dets = yolo(image, args.volume_conf)
    found = bolts.detect_bolt_holes(image, dets)
    lattice = scale.fit_lattice(np.array([[b["x"] * size[0], b["y"] * size[1]] for b in found]))
    f = angle.focal_px(size, cap["focal_35mm"])
    K = volume.camera_matrix(size, f)
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    spacing = float(truth.get("bolt_spacing_cm_measured") or DEFAULT_BOLT_SPACING_CM)
    survey_overlay(image, dets, out_dir / f"{label}__ids.jpg")
    print(f"\n{label}: {len(found)} bolts, {len(dets)} detections"
          f" ({sum(d['class_name'] == 'VOLUME' for d in dets)} VOLUME at floor {args.volume_conf:g}),"
          f" focal {'EXIF ' + format(cap['focal_35mm'], 'g') if cap['focal_35mm'] else 'default'},"
          f" spacing {spacing:g} cm, {time.perf_counter() - t0:.1f} s")

    saved = cap["capture"].get("detections") or []
    targets = []
    for v in measured:
        targets.append(dict(v, _measured=True))
    if args.survey:
        named = {v.get("detection_id") for v in measured}
        for det in dets:
            if det["class_name"] == "VOLUME" and det["id"] not in named:
                targets.append({"id": f"det{det['id']}", "_det": det, "_measured": False})

    rows = []
    for v in targets:
        mask, det, mask_source = None, v.get("_det"), ""
        if det is None and v.get("detection_id") is not None:
            #The id is the one on the capture's own overlay when there is a
            #capture.json, else the one on this script's __ids overlay.
            ref = next((s for s in saved if s["id"] == v["detection_id"]), None)
            if ref is not None:
                ref_mask = polygon_mask(ref["polygon"], size)
                scored = [(_iou(ref_mask, full_mask(d)), d) for d in dets]
                best = max(scored, key=lambda t: t[0], default=(0.0, None))
                det = best[1] if best[0] >= MATCH_IOU else None
                if det is None:
                    mask, mask_source = ref_mask, "saved polygon (no raw mask matched)"
            else:
                det = next((d for d in dets if d["id"] == v["detection_id"]), None)
        if det is not None:
            mask, mask_source = full_mask(det), f"yolo {det['class_name']} {det['confidence']:.2f}"
        base_px = raised_px = None
        if v.get("base_px"):
            base_px = np.array(v["base_px"], float) * size
            raised_px = np.array(v.get("raised_px") or [], float).reshape(-1, 2) * size
            if mask is None:
                hull = cv2.convexHull(np.vstack([base_px, raised_px]).astype(np.float32))
                mask = polygon_mask((hull.reshape(-1, 2) / size).tolist(), size)
                mask_source = "hull of clicked corners"
        if mask is None or not mask.any():
            print(f"  {v['id']}: no mask - give a detection_id or click its corners")
            continue

        ys, xs = np.nonzero(mask)
        centre = np.array([xs.mean(), ys.mean()])
        wp = volume.wall_plane(lattice, centre, K, spacing)
        if wp is None:
            print(f"  {v['id']}: no wall plane at the volume (no fitted panel nearby) - skipped")
            continue
        n, d = wp["n"], wp["d"]
        g, g_source = gravity_for(cap, n, v.get("wall_angle_deg"))
        wall_est = volume.describe_face(n, n, g)["steepness_deg"]

        fits = {}
        t1 = time.perf_counter()
        outline = volume.outline_from_mask(mask)
        fits["full"] = volume.fit_volume(outline if outline is not None else np.zeros((0, 2)),
                                         n, d, K, mask, gray, g)
        full_ms = (time.perf_counter() - t1) * 1000
        if base_px is not None and len(raised_px):
            fits["oracle"] = oracle(base_px, raised_px, n, d, K, g, mask)
            if v.get("depth_cm"):
                fits["depth"] = oracle(base_px, raised_px, n, d, K, g, mask, height_cm=float(v["depth_cm"]))

        wall_measured = v.get("wall_angle_deg")
        print(f"  {v['id']}: mask {mask_source}; wall {wall_est:+.1f}"
              f"{'' if wall_measured is None else f' (measured {wall_measured:+g})'}"
              f" axis_ratio {wp['axis_ratio']:.3f}{'' if wp['trusted'] else ' UNTRUSTED'}; gravity {g_source};"
              f" fit {full_ms:.0f} ms")
        for name, fit in fits.items():
            faces = match(v.get("faces") or [], fit)
            depth_err = (fit["depth_cm"] - v["depth_cm"]) if (fit and v.get("depth_cm")) else None
            row = {"capture": label, "volume": v["id"], "path": name,
                   "measured": v["_measured"], "fit": fit is not None,
                   "trusted": bool(fit and fit["trusted"]), "faces": faces,
                   "depth_err": None if name == "depth" else depth_err,
                   "shape": fit["shape"] if fit else None, "truth_shape": v.get("shape")}
            rows.append(row)
            if fit is None:
                print(f"    {name:6s} no fit")
                continue
            print(f"    {name:6s} {fit['shape']:13s} {fit.get('h_source', ''):16s}"
                  f" {'TRUSTED  ' if fit['trusted'] else 'untrusted'}"
                  f" rep {fit['reprojection_norm']:.3f}{' CLIPPED' if fit['clipped_by_frame'] else ''}"
                  f" depth {fit['depth_cm']:5.1f}{'' if depth_err is None else f' ({depth_err:+.1f})'}"
                  f" gain {fit.get('offcentre_gain', float('nan'))}")
            for face in faces:
                if face["matched"]:
                    print(f"           face {face['name'] or '?':8s} measured {face['truth']:+5.1f}"
                          f" fitted {face['est']:+5.1f} (err {face['steep_err']:4.1f})"
                          f" facing {face['facing_truth']}/{face['facing_est']}"
                          f"{' SIGN FLIP' if face['sign_flip'] else ''}")
                else:
                    print(f"           face {face['name'] or '?':8s} measured {face['truth']:+5.1f} NOT PRODUCED")
            if not faces:
                print("           " + ", ".join(f"{f['steepness_deg']:+.1f} {f['facing']}"
                                                for f in fit["faces"] if f["visible"]))
        overlay(image, mask, fits, K, f"{label} {v['id']} wall {wall_est:+.1f}",
                out_dir / f"{label}__{v['id']}.jpg",
                None if base_px is None else (base_px, raised_px))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folders", nargs="*", type=Path)
    parser.add_argument("--survey", action="store_true",
                        help="also fit every VOLUME detection that truth.json does not name")
    parser.add_argument("--volume-conf", type=float, default=detection.CONFIDENCE_FLOORS["VOLUME"])
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "eval_volume_field")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    folders = args.folders or sorted(p for p in CAPTURES.iterdir() if p.is_dir())

    rows = []
    for folder in folders:
        if (folder / "volume.json").exists():
            for cap in load_volume_folder(folder):
                rows += run(folder, args, args.out, cap)
        else:
            rows += run(folder, args, args.out)

    print("\nSUMMARY")
    for path in ("full", "oracle", "depth"):
        scored = [r for r in rows if r["path"] == path and r["measured"]]
        if scored:
            summary(f"{path}, all", scored)
            summary(f"{path}, trusted only", [r for r in scored if r["trusted"]])
    full = [r for r in rows if r["path"] == "full"]
    if full:
        print(f"  coverage (full path): {sum(r['fit'] for r in full)}/{len(full)} fitted,"
              f" {sum(r['trusted'] for r in full)}/{len(full)} trusted")
        shapes = {}
        for r in full:
            if r["trusted"]:
                shapes[r["shape"]] = shapes.get(r["shape"], 0) + 1
        print(f"  trusted fits by shape: {shapes}")
    (args.out / "results.json").write_text(json.dumps(rows, indent=1, default=float))
    print(f"\noverlays and results.json in {args.out}")


if __name__ == "__main__":
    main()
