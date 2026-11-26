"""DEV ONLY - debug overlay for bolt-hole detection. Not used by the API.

Runs hold detection + detect_bolt_holes on reference photos and saves a copy
of each with the results drawn on, so a human can check by eye what the
detector found:
  green ring  = accepted bolt hole
  red ring    = rejected candidate (--candidates only)
  grey fill   = HOLD/VOLUME polygon (blobs inside are ignored)

Usage (from backend/):
  uv run python -m accuracy_checks.eval_scale ../mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/IMG_7500.jpeg
  uv run python -m accuracy_checks.eval_scale <photos...> --out <dir> --candidates

Overlays go to --out (default: <system temp>/eval_scale), outside the repo.
"""

import argparse
import json
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from wall_analysis import bolts
from wall_analysis import detection
from wall_analysis import scale

#Held-out accuracy (--accuracy): bolts are split into folds; the lattice is
#fitted without one fold, and distances between that fold's bolts (same
#lattice patch only) are compared to the ground truth from the full fit's
#integer lattice coordinates - bolt_spacing x |lattice offset|.

ACCURACY_FOLDS = 5
ACCURACY_MAX_PAIRS_PER_FOLD = 3000
ACCURACY_SEED = 0

#Panel outlines digitised from the coloured lines on the annotated reference
#photos (normalized x, y, EXIF-upright). Photos without an entry are scored
#on same-patch pairs only.
PANELS_FILE = Path(__file__).resolve().parents[2] / "mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/panels.json"

#Tape measurements (--tape): hold pairs and wall edges, normalized x, y.
TAPE_FILE = PANELS_FILE.with_name("pairs.json")

#Distance bands (grid units) for the error breakdown. Reach range is what the
#LLM margin is for: hold-to-hold moves of roughly 30-250 cm at a 20 cm grid.
REACH_RANGE_UNITS = (1.5, 12.5)
DISTANCE_BANDS_UNITS = [(0, 1.5), (1.5, 4), (4, 8), (8, 12.5), (12.5, np.inf)]


def load_panels(path: Path, width: int, height: int) -> list[np.ndarray]:
    """Pixel polygons for this photo's panels, [] if it has no outlines."""
    if not PANELS_FILE.exists():
        return []
    entry = json.loads(PANELS_FILE.read_text()).get(path.stem, [])
    return [np.array([[x * width, y * height] for x, y in p["polygon"]], np.float32) for p in entry]


def _panel_of(xy: np.ndarray, panels: list[np.ndarray]) -> np.ndarray:
    #-1 = outside every panel
    out = np.full(len(xy), -1)
    for k, poly in enumerate(panels):
        inside = np.array([cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0 for x, y in xy])
        out[(out < 0) & inside] = k
    return out


def _nn_stats(points: list[dict], width: int, height: int) -> str:
    #Nearest-neighbour spacing in px - on a clean bolt grid this is tight
    #(spacing / sqrt(2) on each flat panel), on random speckle it isn't.
    if len(points) < 2:
        return "nn spacing: n/a"
    xy = np.array([[p["x"] * width, p["y"] * height] for p in points])
    d = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    np.fill_diagonal(d, np.inf)
    nn = d.min(axis=1)
    return f"nn spacing px: median {np.median(nn):.0f}, IQR/median {(np.subtract(*np.percentile(nn, [75, 25])) / np.median(nn)):.2f}"


def accuracy(found: list[dict], width: int, height: int, refit: bool = False,
             panels: list[np.ndarray] | None = None) -> dict:
    """Held-out relative errors for one photo. Returns {"all": errors,
    "top": ..., "bottom": ...} where top/bottom are pairs with both bolts
    in the top/bottom 40% of the photo (IMG_7500: the 23 deg and 6 deg panels).

    Default ("leave-own-J-out"): the lattice is fitted on all bolts, then the
    held-out bolts' own Jacobians are dropped from the field, so the distance
    between them comes only from other bolts - like measuring between two
    holds, which have no Jacobian of their own, on a photo where every bolt
    was used. refit=True also refits without the held-out bolts (strict
    k-fold): harsher than production on sparse walls, since removing 20% of
    bolts also costs their neighbours' fits.

    With panels, "panel" holds errors for pairs with both bolts inside the
    same panel outline (the spec's in-panel target) and "panel_truth" their
    true length in grid units; "cross"/"cross_truth" the same for pairs in two
    different outlines whose grids share one frame (index_lattice), measured
    through the seam. "field" is the in-panel error of the interpolated field
    alone (no panel homographies, the slices 4–6 method), for comparison."""
    xy = np.array([[b["x"] * width, b["y"] * height] for b in found]).reshape(-1, 2)
    full = scale.fit_lattice(xy)
    coords, component = scale.index_lattice(full)
    rng = np.random.default_rng(ACCURACY_SEED)
    fold = rng.integers(0, ACCURACY_FOLDS, len(full.xy))
    panel = _panel_of(full.xy, panels or [])
    field_only = scale.Lattice(full.xy, full.jacobian, full.metric, full.spacing_px)

    errors, regions, truths, in_panel, cross, field = [], [], [], [], [], []
    for f in range(ACCURACY_FOLDS):
        held = np.flatnonzero(fold == f)
        if refit:
            train = scale.fit_lattice(full.xy[fold != f])
        else:
            train = full.take(fold != f)
        if len(held) < 2 or len(train.xy) == 0:
            continue
        a, b = np.triu_indices(len(held), k=1)
        a, b = held[a], held[b]
        same = component[a] == component[b]
        a, b = a[same], b[same]
        if len(a) > ACCURACY_MAX_PAIRS_PER_FOLD:
            pick = rng.choice(len(a), ACCURACY_MAX_PAIRS_PER_FOLD, replace=False)
            a, b = a[pick], b[pick]
        truth = np.hypot(*(coords[a] - coords[b]).T)
        nonzero = truth > 0  #two detections indexed onto one lattice site
        a, b, truth = a[nonzero], b[nonzero], truth[nonzero]
        pred = scale.segment_lengths(train, full.xy[a], full.xy[b])
        errors.append(np.abs(pred - truth) / truth)
        truths.append(truth)
        in_panel.append((panel[a] >= 0) & (panel[a] == panel[b]))
        cross.append((panel[a] >= 0) & (panel[b] >= 0) & (panel[a] != panel[b]))
        if not refit:
            field_pred = scale.segment_lengths(field_only.take(fold != f), full.xy[a], full.xy[b])
            field.append(np.abs(field_pred - truth) / truth)
        y = full.xy[:, 1] / height
        regions.append(np.where((y[a] < 0.4) & (y[b] < 0.4), 1, np.where((y[a] > 0.6) & (y[b] > 0.6), 2, 0)))
    if not errors:
        return {}
    err, reg = np.concatenate(errors), np.concatenate(regions)
    truth, same_panel, seam = np.concatenate(truths), np.concatenate(in_panel), np.concatenate(cross)
    field_err = np.concatenate(field) if field else np.zeros(0)
    return {"all": err, "top": err[reg == 1], "bottom": err[reg == 2], "truth": truth,
            "panel": err[same_panel], "panel_truth": truth[same_panel], "panels": len(panels or []),
            "cross": err[seam], "cross_truth": truth[seam],
            "field": field_err[same_panel] if len(field_err) else field_err,
            "fitted": len(full.xy), "lattice": full,
            "components": int(np.bincount(component).size), "largest": int(np.bincount(component).max())}


def segmentation_match(lattice: scale.Lattice, panels: list[np.ndarray]) -> dict:
    """How the segmented panels line up with the outlines in panels.json.
    purity: of bolts in both a segmented panel and an outline, the fraction
    whose segmented panel's majority outline is their own. coverage: of
    fitted bolts inside an outline, the fraction in some segmented panel.
    split: segmented panels per outline (a panel can be split where its
    sheets don't share one homography; purity is what keeps distances right)."""
    outline = _panel_of(lattice.xy, panels)
    seg = lattice.panel if lattice.panel is not None else np.full(len(lattice.xy), -1)
    both = (seg >= 0) & (outline >= 0)
    right = 0
    for k in np.unique(seg[both]):
        m = both & (seg == k)
        right += np.bincount(outline[m]).max()
    split = [len(np.unique(seg[(outline == o) & (seg >= 0)])) for o in range(len(panels))]
    return {"purity": right / max(both.sum(), 1), "coverage": (seg[outline >= 0] >= 0).mean() if (outline >= 0).any() else 0.0,
            "split": split, "segments": len(np.unique(seg[seg >= 0]))}


def _pct(err: np.ndarray) -> str:
    if len(err) == 0:
        return "n/a"
    p50, p95 = np.percentile(err, [50, 95]) * 100
    return f"p50 {p50:.1f}% p95 {p95:.1f}% (n={len(err)})"


def _bands(err: np.ndarray, truth: np.ndarray) -> str:
    parts = []
    for lo, hi in DISTANCE_BANDS_UNITS:
        m = (truth >= lo) & (truth < hi)
        if m.any():
            parts.append(f"[{lo:g}-{hi:g}u) p95 {np.percentile(err[m], 95) * 100:.1f}% n={m.sum()}")
    return " | ".join(parts)


def _reach(err: np.ndarray, truth: np.ndarray) -> np.ndarray:
    lo, hi = REACH_RANGE_UNITS
    return err[(truth >= lo) & (truth <= hi)]


def overlay(path: Path, out_dir: Path, show_candidates: bool, show_accuracy: bool) -> dict | None:
    #exif_transpose so overlays are upright; detection and bolts both see
    #the same pixels, so they stay aligned either way.
    image = ImageOps.exif_transpose(Image.open(path))
    image.load()
    w, h = image.size

    t0 = time.perf_counter()
    detections = detection.run_detection(image)
    t1 = time.perf_counter()
    found = bolts.detect_bolt_holes(image, detections)
    t2 = time.perf_counter()

    canvas = np.asarray(image.convert("RGB")).copy()
    shade = canvas.copy()
    for det in detections:
        pts = np.array([[p["x"] * w, p["y"] * h] for p in det["polygon"]], np.int32)
        cv2.fillPoly(shade, [pts], (128, 128, 128))
    canvas = cv2.addWeighted(shade, 0.35, canvas, 0.65, 0)

    line = max(2, round(max(w, h) / 1000))
    if show_candidates:
        gray = np.asarray(image.convert("L"))
        for x, y, d in bolts._candidates(gray):
            cv2.circle(canvas, (int(x), int(y)), int(d / 2 + line), (255, 0, 0), 1)
    for b in found:
        cv2.circle(canvas, (int(b["x"] * w), int(b["y"] * h)), int(b["diameter"] / 2 + 2 * line), (0, 255, 0), line)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{path.stem}_bolts.jpg"
    Image.fromarray(canvas).save(out, quality=90)
    print(
        f"{path.name}: {len(found)} bolts, {len(detections)} holds | "
        f"{_nn_stats(found, w, h)} | yolo {t1 - t0:.1f}s, bolts {t2 - t1:.1f}s -> {out}"
    )
    if show_accuracy:
        panels = load_panels(path, w, h)
        acc = accuracy(found, w, h, panels=panels)
        strict = accuracy(found, w, h, refit=True, panels=panels)
        if not acc:
            print("  accuracy: n/a (no lattice fit)")
            return None
        else:
            wall = scale.wall_length_units(scale.fit_lattice(np.array([[b["x"] * w, b["y"] * h] for b in found])))
            wall_text = f"{wall:.2f} units" if wall else "n/a"
            print(f"  lattice: {acc['fitted']} fitted bolts, {acc['components']} patches (largest {acc['largest']}), wall {wall_text}")
            print(f"  held-out pairs: all {_pct(acc['all'])} | top 40% {_pct(acc['top'])} | bottom 40% {_pct(acc['bottom'])}")
            print(f"  strict k-fold refit: all {_pct(strict['all'])}")
            print(f"  by distance (all pairs): {_bands(acc['all'], acc['truth'])}")
            if panels:
                match = segmentation_match(acc["lattice"], panels)
                print(f"  panels: {match['segments']} segmented | purity {match['purity']:.0%} | coverage {match['coverage']:.0%} | segmented panels per outline {match['split']}")
                print(f"  in-panel ({acc['panels']} outlines): {_pct(acc['panel'])} | reach range {_pct(_reach(acc['panel'], acc['panel_truth']))} | strict {_pct(strict['panel'])}")
                print(f"  in-panel reach range, field only (no homographies): {_pct(_reach(acc['field'], acc['panel_truth']))}")
                print(f"  cross-seam (same grid frame): {_pct(acc['cross'])} | reach range {_pct(_reach(acc['cross'], acc['cross_truth']))}")
                print(f"  by distance (in-panel): {_bands(acc['panel'], acc['panel_truth'])}")
            else:
                print("  in-panel: n/a (no outlines in panels.json)")
            return {"photo": path.stem, "acc": acc, "strict": strict, "has_panels": bool(panels)}
    return None


def summary(results: list[dict]) -> None:
    """Pooled numbers across photos - what the LLM margin is derived from.
    Photos with panel outlines contribute in-panel pairs, others same-patch
    pairs; every photo is weighted equally (its pairs are subsampled to the
    smallest photo's count) so one dense photo can't dominate."""
    if not results:
        return
    per_photo = []
    for r in results:
        key = ("panel", "panel_truth") if r["has_panels"] else ("all", "truth")
        per_photo.append(_reach(r["acc"][key[0]], r["acc"][key[1]]))
    per_photo = [e for e in per_photo if len(e)]
    n = min(len(e) for e in per_photo)
    rng = np.random.default_rng(ACCURACY_SEED)
    pooled = np.concatenate([rng.choice(e, n, replace=False) for e in per_photo])
    print(f"SUMMARY (reach range {REACH_RANGE_UNITS[0]}-{REACH_RANGE_UNITS[1]} u, in-panel where outlined):")
    for r, e in zip(results, per_photo):
        print(f"  {r['photo']}: {_pct(e)}")
    print(f"  pooled (equal weight): {_pct(pooled)}")
    print(f"  worst photo p95: {max(np.percentile(e, 95) for e in per_photo) * 100:.1f}%")
    seams = [(r["photo"], _reach(r["acc"]["cross"], r["acc"]["cross_truth"])) for r in results if r["has_panels"]]
    print("  cross-seam reach range: " + " | ".join(f"{name} {_pct(e)}" for name, e in seams))


def tape_check(path: Path, spacing_cm: float) -> list[dict]:
    """Compare the app's distances with tape measurements in pairs.json.

    Each pair is measured twice: "points" between the two points exactly as
    recorded (the bolt holes the tape ran between, so its error is the scale
    error alone), and "holds" between the nearest detected hold centroids,
    which is what the app hands the LLM (scale error plus where a centroid
    sits relative to the hold's bolt). A pair with "snap": false has no holds
    (bare wall bolts) and is measured on points only. Each hold pair gets its
    tier and the worker's margin_cm, and whether the tape falls inside it.
    Edges are measured on points. Reports cm per grid unit implied by the
    points measurements, i.e. the bolt spacing the tape implies. Returns one
    row per item for pooling across photos."""
    from coaching import worker  #lazy: only the margin constants are needed

    entry = json.loads(TAPE_FILE.read_text()).get(path.stem) if TAPE_FILE.exists() else None
    if not entry:
        print(f"{path.name}: no tape data in pairs.json")
        return []
    image = ImageOps.exif_transpose(Image.open(path))
    image.load()
    w, h = image.size
    detections = detection.run_detection(image)
    found = bolts.detect_bolt_holes(image, detections)
    lattice = scale.fit_lattice(np.array([[b["x"] * w, b["y"] * h] for b in found]))
    if not len(lattice.xy):
        print("  tape: no lattice fit")
        return []
    holds = np.array([[d["centroid"]["x"] * w, d["centroid"]["y"] * h] for d in detections]).reshape(-1, 2)
    size = np.array([w, h])
    print(f"{path.name}: tape check at {spacing_cm:g} cm/unit ({len(found)} bolts, {len(holds)} holds)")
    rows, implied = [], []
    for kind in ("pairs", "edges"):
        for item in entry.get(kind, []):
            a, b = np.array(item["from"]) * size, np.array(item["to"]) * size
            points_cm = float(scale.segment_lengths(lattice, a, b)[0]) * spacing_cm
            implied.append(item["cm"] / points_cm * spacing_cm)
            row = {"photo": path.stem, "kind": kind[:-1], "name": item["name"], "tape": item["cm"], "points": points_cm,
                   "holds": None, "tier": None, "margin": None}
            text = f"  {kind[:-1]:5s} {item['name']:28s} tape {item['cm']:5.0f} | points {points_cm:6.1f} ({(points_cm / item['cm'] - 1) * 100:+4.0f}%)"
            if kind == "pairs" and item.get("snap", True) and len(holds):
                ha, hb = holds[np.argmin(((holds - a) ** 2).sum(1))], holds[np.argmin(((holds - b) ** 2).sum(1))]
                holds_cm = round(float(scale.segment_lengths(lattice, ha, hb)[0]) * spacing_cm, 1)
                support = float(scale.segment_support(lattice, ha, hb)[0])
                tier = "A" if support <= scale.TIER_A_MAX_SUPPORT else "C"
                margin = worker._margin_cm(holds_cm, tier)
                inside = abs(holds_cm - item["cm"]) <= margin
                row.update(holds=holds_cm, tier=tier, margin=margin)
                text += (f" | holds {holds_cm:6.1f} ({holds_cm - item['cm']:+5.1f} cm) tier {tier} margin {margin:4.1f} "
                         f"{'inside' if inside else 'OUTSIDE'} | centroid shift {holds_cm - points_cm:+5.1f} cm")
            rows.append(row)
            print(text)
    if implied:
        print(f"  implied spacing (points): median {np.median(implied):.1f} cm/unit (range {min(implied):.1f}-{max(implied):.1f})")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("photos", nargs="+", type=Path)
    parser.add_argument("--tape", type=float, metavar="SPACING_CM", help="compare with tape measurements in pairs.json at this bolt spacing")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "eval_scale")
    parser.add_argument("--candidates", action="store_true", help="also draw every rejected blob candidate")
    parser.add_argument("--accuracy", action="store_true", help="also print held-out bolt-pair distance error")
    args = parser.parse_args()
    if args.tape:
        for path in args.photos:
            tape_check(path, args.tape)
        return
    results = [overlay(path, args.out, args.candidates, args.accuracy) for path in args.photos]
    if args.accuracy:
        summary([r for r in results if r])


if __name__ == "__main__":
    main()
