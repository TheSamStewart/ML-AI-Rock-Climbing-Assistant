"""DEV ONLY - replay the real-phone field captures through the current code and
score them against the tester's measurements. Not used by the API.

Each folder in field_captures/ (see its README) holds the photo, the phone's
tilt reading and the exact detections and bolts /detect saw on the day, plus a
hand-filled truth.json. This re-runs scale.compute_scale on those same inputs
(no YOLO, so it is fast and deterministic) and prints, per measured angle and
tape distance:

  truth | baseline (what the app said on the day) | now (current code)

Baseline comes from each capture.json's saved `scale`, so a change that makes
any number worse than the day shows up here. Distances use the wall's real
25 cm bolt spacing (the first 11 captures were taken with the app at 20 cm;
grid units are unaffected, see the README). Holds on a volume are listed but
left out of the summary: the wall angle is not the volume face's (slice 14).

Usage (from backend/):
  uv run python eval_field.py                 # every capture
  uv run python eval_field.py 173933 174933   # only folders containing these
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import scale
import worker

CAPTURES = Path(__file__).resolve().parent / "field_captures"
SPACING_CM = 25.0


def load(folder: Path) -> dict:
    capture = json.loads((folder / "capture.json").read_text())
    truth = json.loads((folder / "truth.json").read_text())
    image = ImageOps.exif_transpose(Image.open(folder / capture["photo"]["file"]))
    return {"capture": capture, "truth": truth, "size": image.size}


def replay(case: dict) -> dict:
    capture = case["capture"]
    return scale.compute_scale(
        capture["detections"],
        case["size"],
        capture["bolts"],
        gravity=capture["sensor"]["gravity_sent"],
        focal_35mm=capture["photo"]["focal_35mm"],
    )


def _index(capture: dict) -> dict[int, int]:
    return {d["id"]: i for i, d in enumerate(capture["detections"])}


def score(folder: Path) -> tuple[list[dict], list[dict]]:
    """(angle rows, distance rows) for one capture."""
    case = load(folder)
    capture, truth = case["capture"], case["truth"]
    before, now = capture["scale"], replay(case)
    index = _index(capture)
    name = folder.name[11:17]

    angles = []
    for entry in truth.get("wall_angles") or []:
        on_volume = "volume" in (entry.get("where", "") + entry.get("source", "")).lower()
        for hold in entry["hold_ids"]:
            i = index[hold]
            angles.append({
                "capture": name, "hold": hold, "truth": entry["angle_deg"], "on_volume": on_volume,
                "before": (before.get("angles_deg") or [None] * (i + 1))[i],
                "now": (now.get("angles_deg") or [None] * (i + 1))[i],
            })

    distances = []
    for pair in truth.get("tape_pairs") or []:
        if pair.get("cm") is None:
            continue
        i, j = index[pair["from_hold_id"]], index[pair["to_hold_id"]]
        #174741's "tape" is the app's own reading, confirmed by eye: listed, not scored.
        from_app = "app value" in pair.get("notes", "")
        row = {"capture": name, "pair": f"{pair['from_hold_id']}-{pair['to_hold_id']}", "truth": pair["cm"], "from_app": from_app}
        for label, sc in (("before", before), ("now", now)):
            units = (sc.get("distances_units") or [[None]])[i][j] if sc.get("distances_units") else None
            tier = sc["tiers"][i][j] if sc.get("tiers") else worker.DEFAULT_TIER
            cm = None if units is None else round(units * SPACING_CM, 1)
            row[label] = cm
            row[f"{label}_tier"] = tier
            row[f"{label}_margin"] = worker._margin_cm(cm, tier)
        distances.append(row)
    return angles, distances


def _err(value, truth):
    return None if value is None else round(value - truth, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("only", nargs="*", help="substrings of folder names to keep")
    args = parser.parse_args()

    folders = sorted(p for p in CAPTURES.iterdir() if (p / "capture.json").exists())
    if args.only:
        folders = [p for p in folders if any(s in p.name for s in args.only)]

    all_angles, all_distances = [], []
    for folder in folders:
        a, d = score(folder)
        all_angles += a
        all_distances += d

    print("ANGLES (deg, + overhang / - slab)        truth   before    now   err before -> now")
    for r in all_angles:
        flag = "  (on a volume, not scored)" if r["on_volume"] else ""
        eb, en = _err(r["before"], r["truth"]), _err(r["now"], r["truth"])
        worse = "  <-- WORSE" if not r["on_volume"] and eb is not None and (en is None or abs(en) > abs(eb) + 0.5) else ""
        print(f"  {r['capture']} hold {r['hold']:>3}                  {r['truth']:>6}   {str(r['before']):>6} {str(r['now']):>6}   {str(eb):>5} -> {str(en):>5}{flag}{worse}")

    print("\nDISTANCES (cm, bolt spacing 25)          truth   before (tier, margin)   now (tier, margin)   inside now?")
    for r in all_distances:
        inside = None if r["now"] is None else abs(r["now"] - r["truth"]) <= r["now_margin"]
        eb, en = _err(r["before"], r["truth"]), _err(r["now"], r["truth"])
        worse = "  <-- WORSE" if eb is not None and (en is None or abs(en) > abs(eb) + 0.5) else ""
        flag = "  (tape = app value, not scored)" if r["from_app"] else ""
        print(f"  {r['capture']} {r['pair']:>7}                       {r['truth']:>6}   {r['before']} ({r['before_tier']}, {r['before_margin']})"
              f"   {r['now']} ({r['now_tier']}, {r['now_margin']})   {inside}{flag}{worse}")

    scored = [r for r in all_angles if not r["on_volume"]]
    for label in ("before", "now"):
        errs = np.array([abs(r[label] - r["truth"]) for r in scored if r[label] is not None])
        missing = sum(r[label] is None for r in scored)
        if len(errs):
            print(f"\nSUMMARY angles [{label:6s}]: n={len(errs)} median {np.median(errs):.1f}  p90 {np.percentile(errs, 90):.1f}  max {errs.max():.1f}  no angle: {missing}")
    for label in ("before", "now"):
        rows = [r for r in all_distances if r[label] is not None and not r["from_app"]]
        inside = sum(abs(r[label] - r["truth"]) <= r[f"{label}_margin"] for r in rows)
        print(f"SUMMARY distances [{label:6s}]: {inside}/{len(rows)} inside margin")


if __name__ == "__main__":
    main()
