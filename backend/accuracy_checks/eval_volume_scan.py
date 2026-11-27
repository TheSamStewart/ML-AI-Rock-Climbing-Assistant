"""DEV ONLY - replay saved volume scans and score them against measured faces.

Re-runs volume_scan.scan_volume on scans saved by POST /dev/volume-scan
(backend/field_captures_scans/<scan_id>/: photo.jpg, frame_NN.jpg, scan.json),
so a change to the scan can be judged on real gym data without a gym visit.
Spec: docs/milestones/v0.2/38-volume-scan-trial/spec.md, acceptance criteria 6 and 7.

For each scan it prints
  - every burst photo: wall matches, RANSAC inliers, baseline, sharpness,
    whether it was used and, if not, why (failed scans included);
  - AC 6: whether at least LINEUP_SHARE of the burst photos lined up;
  - each measured face (truth.json) paired with an app face, the error, and
    whether the sign is right (AC 7: faces at least SIGN_DEAD_BAND_DEG from
    vertical; a face with no app face counts as wrong).

Pairing: truth.json gives each measured face an approximate outline on the
photo. A pair's score is the share of the app face's outline inside the
measured face's; pairs are taken one-to-one, highest share first, and only
when the app face lies mostly (more than MIN_SHARE) on the measured face.
Pairing by position, not by angle, so a wrong angle can't pick its own
partner. An app face spread over two measured faces pairs with neither.

Detections (YOLO, used to keep wall features off holds) are cached per scan in
<scan>/replay_detections.json, only for scans under SCANS_DIR, and re-run
when the model file changes or with --refresh-detections.

Usage (from backend/):
  uv run python -m accuracy_checks.eval_volume_scan                     # every scan in truth.json
  uv run python -m accuracy_checks.eval_volume_scan 2026-11-27_104222_ab74269e
  uv run python -m accuracy_checks.eval_volume_scan --as-sent           # the bolt spacing the app sent
  uv run python -m accuracy_checks.eval_volume_scan --focal-35mm 29.5   # override the (missing) EXIF focal
  uv run python -m accuracy_checks.eval_volume_scan --json <temp>/replay.json   # also write the numbers
Overlays go to <temp>/eval_volume_scan unless --out.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from wall_analysis import detection
from wall_analysis import volume_scan

BACKEND = Path(__file__).resolve().parents[1]
SCANS_DIR = BACKEND / "field_captures_scans"
TRUTH = BACKEND / "field_captures_volumes" / "scan_trial_2026-11-27" / "truth.json"
LINEUP_SHARE = 0.75        # AC 6: 6 of 8 burst photos
SIGN_DEAD_BAND_DEG = 10.0  # AC 7: faces nearer vertical than this don't count for the sign
MIN_SHARE = 0.5            # "mostly": share of an app face's outline inside a measured face, to pair them
RASTER = 1000              # pairing raster, px on the short side
BASE_PROBE_PX = 10         # how far inside a base-edge face's edge to look (raster px; thin faces need it small)
COLOURS = [(0, 255, 255), (255, 0, 255), (255, 200, 0), (0, 255, 0), (255, 80, 80), (120, 120, 255)]


def lineup_needed(n_frames: int) -> int:
    return math.ceil(LINEUP_SHARE * n_frames)


def deg(value, signed=True) -> str:
    """An angle for printing; '-' when not measured."""
    if value is None:
        return "-"
    return f"{value:+.1f}°" if signed else f"{value:.1f}°"


def open_upright(path: Path) -> tuple[Image.Image, float | None]:
    """As main._open_upright: the focal is read before the EXIF rotation."""
    image = Image.open(path)
    try:
        focal = image.getexif().get_ifd(0x8769).get(41989)
        focal = float(focal) if focal else None
    except Exception:  # noqa: BLE001 - optional metadata
        focal = None
    image.load()
    return ImageOps.exif_transpose(image).convert("RGB"), focal


def _model_stamp() -> str:
    try:
        st = Path(detection.MODEL_PATH).stat()
        return f"{Path(detection.MODEL_PATH).name}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return "missing"


def detections_for(folder: Path, image: Image.Image, refresh: bool) -> list[dict]:
    """YOLO on the photo, cached beside the scan when it lives under SCANS_DIR
    (gitignored). The cache is keyed on the model file, so a retrained
    best.pt (#37) re-runs detection."""
    cache = folder / "replay_detections.json"
    cacheable = SCANS_DIR.resolve() in folder.resolve().parents
    stamp = _model_stamp()
    if cacheable and cache.is_file() and not refresh:
        saved = json.loads(cache.read_text())
        if isinstance(saved, dict) and saved.get("model") == stamp:
            return saved["detections"]
    dets = detection.run_detection(image)
    if cacheable:
        cache.write_text(json.dumps({"model": stamp, "detections": dets}, default=float))
    return dets


def _raster(polygon_norm, size) -> np.ndarray:
    w, h = size
    mask = np.zeros((h, w), np.uint8)
    pts = np.array([[x * w, y * h] for x, y in polygon_norm], np.float64)
    if len(pts) >= 3:
        cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 1)
    return mask.astype(bool)


def _base_probe(face, app_mask, size):
    """For a base-edge face, a raster pixel just inside its base edge's middle
    (BASE_PROBE_PX towards the face's outline centre); else None."""
    base = face.get("base")
    if not base or len(base) != 2:
        return None
    w, h = size
    (x1, y1), (x2, y2) = [(p["x"] * w, p["y"] * h) for p in base]
    mid = np.array([(x1 + x2) / 2, (y1 + y2) / 2])
    ys, xs = np.nonzero(app_mask)
    inward = (np.array([xs.mean(), ys.mean()]) - mid) if len(xs) else np.zeros(2)
    norm = float(np.linalg.norm(inward))
    probe = mid + (inward / norm * BASE_PROBE_PX if norm > 1e-9 else 0)
    return np.clip(np.round(probe).astype(int), 0, [w - 1, h - 1])


def pair_faces(truth_faces: list[dict], app_faces: list[dict], aspect: float) -> list[dict]:
    """One row per measured face: its app face (or None), error, sign, the
    share of the app face's outline on the measured face, and the outline
    overlap (IoU) as a measure of how well the app outlined it. `aspect` is
    the photo's height / width (normalised outlines are rasterised at it)."""
    size = (RASTER, max(1, round(RASTER * aspect))) if aspect >= 1 else (max(1, round(RASTER / aspect)), RASTER)
    #Shrunk by a pixel: two measured faces share their border, and those
    #pixels would otherwise count for both (a 50/50 split read as 50.x %).
    tm = [cv2.erode(_raster(t["polygon"], size).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
          for t in truth_faces]
    am = [_raster([(p["x"], p["y"]) for p in f["outline"]], size) for f in app_faces]
    pairs = []
    for ai, a in enumerate(am):
        area = float(a.sum())
        probe = _base_probe(app_faces[ai], am[ai], size)
        for ti, t in enumerate(tm):
            if probe is not None:
                #A base-edge face IS the face rising from its base edge: pair it
                #with the measured face holding a point just inside that edge.
                share = 1.0 if t[probe[1], probe[0]] else 0.0
            else:
                share = float((a & t).sum()) / area if area else 0.0
            if share > MIN_SHARE:
                pairs.append((-share, ti, ai))
    taken, used = {}, set()
    for neg_share, ti, ai in sorted(pairs):
        if ti in taken or ai in used:
            continue
        taken[ti] = (ai, -neg_share)
        used.add(ai)
    rows = []
    for ti, t in enumerate(truth_faces):
        row = {"name": t["name"], "truth": t.get("angle_deg"), "app": None, "app_face": None,
               "err": None, "sign_counts": t.get("angle_deg") is not None and abs(t["angle_deg"]) >= SIGN_DEAD_BAND_DEG}
        if ti in taken:
            ai, share = taken[ti]
            f = app_faces[ai]
            inter, union = float((am[ai] & tm[ti]).sum()), float((am[ai] | tm[ti]).sum())
            row.update(app=f["steepness_deg"], app_face=ai + 1, facing=f["facing"], n_points=f["n_points"],
                       share=round(share, 2), iou=round(inter / union, 2) if union else 0.0)
            if t.get("angle_deg") is not None:
                row["err"] = round(abs(f["steepness_deg"] - t["angle_deg"]), 1)
        if row["sign_counts"]:
            row["sign_ok"] = bool(row["app"] is not None and np.sign(row["app"]) == np.sign(t["angle_deg"]))
        rows.append(row)
    return rows


def overlay(photo: Image.Image, polygon, truth_faces, result, path: Path, title: str) -> None:
    w, h = photo.size
    im = photo.copy()
    d = ImageDraw.Draw(im)
    for t in truth_faces:
        pts = [(x * w, y * h) for x, y in t["polygon"]]
        d.line(pts + pts[:1], fill=(255, 255, 255), width=3)
        cx, cy = np.mean(pts, 0)
        d.text((cx, cy), f"{t['name']} {deg(t.get('angle_deg'))}", fill=(255, 255, 255))
    for i, f in enumerate((result or {}).get("faces", [])):
        pts = [(p["x"] * w, p["y"] * h) for p in f["outline"]]
        c = COLOURS[i % len(COLOURS)]
        d.line(pts + pts[:1], fill=c, width=5)
        d.text(pts[0], f"app {i + 1}: {f['steepness_deg']:+.0f} {f['facing']}", fill=c)
    xs, ys = [p["x"] for p in polygon], [p["y"] for p in polygon]
    box = (max(0, (min(xs) - 0.08) * w), max(0, (min(ys) - 0.05) * h),
           min(w, (max(xs) + 0.08) * w), min(h, (max(ys) + 0.05) * h))
    crop = im.crop(tuple(int(v) for v in box))
    ImageDraw.Draw(crop).text((5, 5), title, fill=(255, 255, 0))
    crop.save(path, quality=85)


def run_one(folder: Path, truth: dict, args, out_dir: Path) -> dict:
    record = json.loads((folder / "scan.json").read_text())
    photo, focal = open_upright(folder / "photo.jpg")
    frames = [open_upright(p)[0] for p in sorted(folder.glob("frame_*.jpg"))]
    spacing = (record.get("bolt_spacing_cm") or args.spacing) if args.as_sent else args.spacing
    focal = args.focal_35mm if args.focal_35mm is not None else focal
    started = time.perf_counter()
    #AC 6 counts the frames the scan actually works on: at most MAX_FRAMES are kept.
    out = {"scan_id": folder.name, "image": truth.get("image"), "frames_sent": len(frames),
           "needed": lineup_needed(min(len(frames), volume_scan.MAX_FRAMES)),
           "bolt_spacing_cm": spacing, "focal_35mm": focal, "wall_features": None}
    result = None
    try:
        dets = detections_for(folder, photo, args.refresh_detections)
        result = volume_scan.scan_volume(photo, frames, record["volume_polygon"], dets,
                                         gravity_reading=record.get("gravity"), focal_35mm=focal,
                                         bolt_spacing_cm=spacing)
        out.update(error=None, frames_used=result["frames_used"], diagnostics=result["frame_diagnostics"],
                   wall_angle_deg=result["wall_angle_deg"], depth_cm=result["depth_cm"],
                   wall_features=result.get("wall_features"), focal_px=result.get("focal_px"),
                   focal_check_px=result.get("focal_check_px"),
                   faces=[{k: f[k] for k in ("steepness_deg", "facing", "facing_deg", "n_points")}
                          for f in result["faces"]])
    except volume_scan.ScanError as e:
        out.update(error=str(e), diagnostics=e.diagnostics,
                   frames_used=sum(bool(d.get("used")) for d in (e.diagnostics or [])), faces=[])
    except Exception as e:  # noqa: BLE001 - one bad scan mustn't stop the replay
        out.update(error=f"internal error: {type(e).__name__}: {e}", diagnostics=None, frames_used=0, faces=[])
    out["seconds"] = round(time.perf_counter() - started, 1)
    out["lineup_ok"] = out["frames_used"] >= out["needed"]
    out["pairs"] = pair_faces(truth.get("faces", []), result["faces"] if result else [],
                              photo.size[1] / photo.size[0])
    if record.get("volume_polygon"):
        overlay(photo, record["volume_polygon"], truth.get("faces", []), result,
                out_dir / f"{folder.name}.jpg", f"{folder.name} image {truth.get('image')}")
    return out


def report(o: dict, truth: dict) -> None:
    print(f"\n== {o['scan_id']}  (image {o['image']}: {truth.get('volume')})")
    print(f"   line-up: {o['frames_used']}/{o['frames_sent']} (need {o['needed']}) "
          f"{'PASS' if o['lineup_ok'] else 'FAIL'}   spacing {o['bolt_spacing_cm']} cm, focal {o['focal_35mm']}, "
          f"photo wall features {o['wall_features'] if o['wall_features'] is not None else '-'}, {o['seconds']} s")
    if o["diagnostics"]:
        print("     #  matches  inliers  photo  ncc/peak    baseline  turn  from  sharp  used  reason")
        for d in o["diagnostics"]:
            ncc = f"{d['wall_ncc']}/{d.get('wall_ncc_peak', '-')}" if d.get("wall_ncc") is not None else "-"
            src = "-" if "linked_from" not in d else ("photo" if d["linked_from"] is None else str(d["linked_from"]))
            print(f"    {d.get('source_frame', d['frame']):>2}  {d['wall_matches']:>7}  {str(d.get('wall_inliers', '-')):>7}  "
                  f"{str(d.get('photo_inliers', '-')):>5}  {ncc:>9}  {str(d.get('baseline_cm', '-')):>8}  "
                  f"{str(d.get('turn_deg', '-')):>4}  {src:>5}  {d.get('sharpness', '-'):>5}  "
                  f"{'yes' if d.get('used') else 'no':>4}  {d.get('reason', '')}")
    if o["error"]:
        print(f"   ERROR: {o['error']}")
        return
    tw = truth.get("wall_angle_deg")
    print(f"   wall {deg(o['wall_angle_deg'])} (measured {deg(tw)}), depth {o['depth_cm']} cm, "
          f"focal {o.get('focal_px')} px (bolt-grid check {o.get('focal_check_px') or '-'} px)")
    for i, f in enumerate(o["faces"]):
        print(f"   app {i + 1}: {f['steepness_deg']:+.1f}° {f['facing']} ({f['facing_deg']}), {f['n_points']} pts")
    for r in o["pairs"]:
        sign = "" if not r["sign_counts"] else ("sign ok" if r.get("sign_ok") else "SIGN WRONG")
        app = ("not found" if r["app"] is None
               else f"{deg(r['app'])} (app {r['app_face']}, {r['share']:.0%} on it, IoU {r['iou']})")
        err = "" if r["err"] is None else f"err {r['err']}°"
        print(f"   {r['name']:>7} {deg(r['truth'])}  ->  {app}  {err}  {sign}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scans", nargs="*", help="scan ids or folders (default: every scan in truth.json)")
    ap.add_argument("--truth", type=Path, default=TRUTH)
    ap.add_argument("--spacing", type=float, default=None, help="bolt spacing, cm (default: truth.json's)")
    ap.add_argument("--as-sent", action="store_true", help="use the bolt spacing the app sent")
    ap.add_argument("--focal-35mm", type=float, default=None)
    ap.add_argument("--refresh-detections", action="store_true")
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "eval_volume_scan")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    truth_all = json.loads(args.truth.read_text())
    if args.spacing is None:
        args.spacing = float(truth_all.get("bolt_spacing_cm", 25.0))
    ids = args.scans or list(truth_all["scans"])
    folders = [Path(s) if Path(s).is_dir() else SCANS_DIR / s for s in ids]
    args.out.mkdir(parents=True, exist_ok=True)

    results = []
    for folder in folders:
        if not (folder / "scan.json").is_file():
            print(f"\n== {folder.name}: no scan.json, skipped")
            continue
        truth = truth_all["scans"].get(folder.name, {"faces": []})
        o = run_one(folder, truth, args, args.out)
        report(o, truth)
        results.append(o)

    print("\n== Summary")
    lined = [o for o in results if o["lineup_ok"]]
    print(f"   AC 6 line-up: {len(lined)}/{len(results)} scans pass "
          f"({', '.join(f'{o['frames_used']}/{o['frames_sent']}' for o in results)})")
    counted = [r for o in results for r in o["pairs"] if r["sign_counts"]]
    right = [r for r in counted if r.get("sign_ok")]
    errs = [r["err"] for o in results for r in o["pairs"] if r["err"] is not None]
    print(f"   AC 7 signs: {len(right)}/{len(counted)} measured faces found with the right sign")
    if errs:
        print(f"   face error: median {np.median(errs):.1f}°, max {max(errs):.1f}° over {len(errs)} paired faces")
    print(f"   overlays: {args.out}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=1, default=float))


if __name__ == "__main__":
    main()
