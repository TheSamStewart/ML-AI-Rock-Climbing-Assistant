"""DEV ONLY - how well the photo-only wall angle (angle.py) matches the
angles measured by hand (panels.json, from measurements.md). Not used by the API.

For each outlined panel, takes the bolts inside it, estimates the wall angle at
each (angle.consensus_normals), and compares the median with the measured
angle. The photos carry no phone-tilt reading, so the camera pitch is either
assumed (--pitch, default angle.DEFAULT_PITCH_DEG) or back-solved per photo as
the pitch that fits the measured angles best, which shows how much knowing the
true tilt would matter.

Usage (from backend/):
  uv run python -m accuracy_checks.eval_angle ../mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/IMG_7500.jpeg ...
  uv run python -m accuracy_checks.eval_angle <photos...> --pitch 10
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from wall_analysis import angle
from wall_analysis import bolts
from wall_analysis import detection
from accuracy_checks import eval_scale
from wall_analysis import scale

PITCH_SCAN_DEG = range(-30, 61)
#Walls with no outlines but a known start-to-end angle range, bottom to top.
RANGES = {"IMG_7552": (5.0, 10.0)}


def fit_photo(path: Path):
    image = ImageOps.exif_transpose(Image.open(path))
    image.load()
    w, h = image.size
    f35 = Image.open(path).getexif().get_ifd(0x8769).get(41989)
    detections = detection.run_detection(image)
    found = bolts.detect_bolt_holes(image, detections)
    lattice = scale.fit_lattice(np.array([[b["x"] * w, b["y"] * h] for b in found]))
    return image.size, float(f35) if f35 else None, lattice


def panel_estimates(path: Path, lattice, size, f, pitch: float | None):
    """[(angle_true, [per-bolt estimates at gravity for `pitch`])] per panel, or
    the unit normals when pitch is None, so the pitch can be scanned cheaply."""
    w, h = size
    entry = json.loads(eval_scale.PANELS_FILE.read_text()).get(path.stem, [])
    cands = angle.bolt_candidates(lattice, size, f)
    out = []
    for panel in entry:
        poly = np.array([[x * w, y * h] for x, y in panel["polygon"]], np.float32)
        inside = np.array([cv2.pointPolygonTest(poly, (float(x), float(y)), False) >= 0 for x, y in lattice.xy])
        if inside.sum() < 5:
            continue
        pts = lattice.xy[inside]
        out.append((panel["angle_deg"], pts))
    return cands, out


def report(path: Path, pitch_assumed: float) -> list[tuple[float, float]]:
    size, f35, lattice = fit_photo(path)
    f = angle.focal_px(size, f35)
    cands, panels = panel_estimates(path, lattice, size, f, None)
    print(f"{path.name}: {len(lattice.xy)} bolts, focal {'EXIF' if f35 else 'default'} {f35 or angle.DEFAULT_FOCAL_35MM:g} mm, f = {f:.0f} px")

    def run(pitch):
        g = angle.gravity_from_pitch(pitch)
        rows = []
        for true, pts in panels:
            normals, _ = angle.consensus_normals(lattice, cands, pts, g)
            est = angle.angles_from_normals(normals, g)
            rows.append((true, float(np.nanmedian(est)) if np.isfinite(est).any() else np.nan, int(len(pts))))
        return rows

    if not panels:
        span = RANGES.get(path.stem)
        if span:
            g = angle.gravity_from_pitch(pitch_assumed)
            top, bottom = np.percentile(lattice.xy[:, 1], [10, 90])
            for name, y, true in (("top 10%", top, span[1]), ("bottom 10%", bottom, span[0])):
                near = lattice.xy[np.abs(lattice.xy[:, 1] - y) < 0.1 * size[1]]
                normals, _ = angle.consensus_normals(lattice, cands, near, g)
                est = float(np.nanmedian(angle.angles_from_normals(normals, g)))
                print(f"  {name:10s} measured {true:4.0f} | estimated {est:5.1f} at pitch {pitch_assumed:g}")
        return []

    best = min(PITCH_SCAN_DEG, key=lambda p: np.nanmedian([abs(t - e) for t, e, _ in run(p)]))
    print(f"  pitch assumed {pitch_assumed:g} deg | back-solved best {best} deg")
    pairs = []
    for label, pitch in (("assumed", pitch_assumed), ("back-solved", best)):
        rows = run(pitch)
        errs = [abs(t - e) for t, e, _ in rows if np.isfinite(e)]
        print(f"  [{label:11s}] " + "  ".join(f"{t:g}->{e:.0f}" for t, e, _ in rows) + f" | median err {np.nanmedian(errs):.1f}  max {max(errs):.1f}")
        if label == "assumed":
            pairs = [(t, e) for t, e, _ in rows]
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("photos", nargs="+", type=Path)
    parser.add_argument("--pitch", type=float, default=angle.DEFAULT_PITCH_DEG, help="assumed camera pitch, degrees above horizontal")
    args = parser.parse_args()
    for path in args.photos:
        report(path, args.pitch)


if __name__ == "__main__":
    main()
