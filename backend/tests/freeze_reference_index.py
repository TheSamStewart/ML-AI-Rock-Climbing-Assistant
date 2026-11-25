"""Freeze the reference photos' bolt index for the regression guard.

Run from backend/:  uv run python tests/freeze_reference_index.py

Writes tests/data/reference_bolt_index.json (per outlined photo: image size and
every fitted bolt's px position, index_lattice component and coordinates) and
prints the guard's p95 on it, to paste into REGRESSION_BASELINE_P95 in
tests/test_scale.py.

Only re-freeze when the ground truth (index_lattice) is meant to change, with
the human's approval; otherwise the guard stops guarding.
Needs models/best.pt and the known_measurements photos.
"""

import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]

import numpy as np  # noqa: E402

import test_scale as T  # noqa: E402
from scale import index_lattice  # noqa: E402


def main():
    photos = {}
    for photo in T.OUTLINED_PHOTOS:
        size, lat = T._reference_fit(photo)
        coords, comp = index_lattice(lat)
        xy = np.asarray(lat.xy, float)
        coords, comp = np.asarray(coords, float).reshape(-1, 2), np.asarray(comp, int)
        bolts = [[round(float(x), 2), round(float(y), 2), int(c), float(cx), float(cy)] for (x, y), c, (cx, cy) in zip(xy, comp, coords)]
        photos[photo] = {"size": list(size), "bolts": bolts}
        print(f"{photo}: {len(bolts)} fitted bolts frozen", flush=True)

    T.FROZEN_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    T.FROZEN_INDEX_PATH.write_text(
        json.dumps(
            {
                "_note": "Frozen ground truth for test_reference_photo_in_panel_reach_range_p95_does_not_regress. bolts: [x_px, y_px, index_lattice component, coord_x, coord_y] on the EXIF-upright photo. Regenerate with tests/freeze_reference_index.py only with the human's approval.",
                "_frozen": datetime.date.today().isoformat(),
                "photos": photos,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    baselines = {}
    for photo in T.OUTLINED_PHOTOS:
        size, lat = T._reference_fit(photo)
        errs, matched, n_frozen, n_pairs = T._frozen_in_panel_errors(photo, lat, size)
        baselines[photo] = round(float(np.percentile(errs, 95)), 4)
        print(f"{photo}: matched {matched:.1%}, pairs {n_pairs}/{n_frozen}, scored {len(errs)}, p95 {baselines[photo]:.4f}")
    print("REGRESSION_BASELINE_P95 =", baselines)


if __name__ == "__main__":
    main()
