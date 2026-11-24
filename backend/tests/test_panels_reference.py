"""Sanity checks on the panel-outline reference data (spec: Reference data).

panels.json holds outlines digitised from IMG_7500, 7502, 7503 and 7504
(IMG_7504's are drawn on IMG_7504.heic; the .jpeg stays clean), normalized
x, y on the EXIF-upright photo, with angles from measurements.md.
"""

import json
from pathlib import Path

import pytest

KNOWN = Path(__file__).resolve().parents[2] / "mobile" / "ML-Rock-Climbing-App" / "assets" / "known_measurements" / "reference"
PANELS = KNOWN / "panels.json"

pytestmark = pytest.mark.skipif(not PANELS.exists(), reason="panels.json reference data missing")

# Transcribed from known_measurements/measurements.md: photo -> {colour: angle_deg}.
MEASURED_ANGLES = {
    "IMG_7500": {"red": 6, "yellow": 14, "green": 17, "blue": 23},
    "IMG_7502": {"yellow": 34, "red": 9},
    "IMG_7503": {"red": 14, "yellow": -26},
    "IMG_7504": {"red": 23, "yellow": 13},
}

# epic_wall has ten red outlines (P7-P16, colours repeat), so it is an ordered
# list of angles in measurement order, not a colour dict.
EPIC_WALL_ANGLES = [25, 25, 29, 29, 31, 30, 29, 14, 14, 14]
OUTLINED = sorted([*MEASURED_ANGLES, "epic_wall"])


@pytest.fixture(scope="module")
def panels():
    return json.loads(PANELS.read_text(encoding="utf-8"))


def _photos(panels):
    return {k: v for k, v in panels.items() if not k.startswith("_")}


def test_photos_with_outlines(panels):
    # Only IMG_7501 has no outlines drawn.
    assert set(_photos(panels)) == set(OUTLINED)


@pytest.mark.parametrize("photo", OUTLINED)
def test_polygons_are_normalized_with_at_least_three_points(panels, photo):
    entries = panels[photo]
    assert entries
    for entry in entries:
        poly = entry["polygon"]
        assert len(poly) >= 3, f"{photo} {entry.get('colour')}"
        for point in poly:
            assert len(point) == 2
            x, y = point
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, f"{photo} {entry.get('colour')}: {point}"


@pytest.mark.parametrize("photo", OUTLINED)
def test_angles_match_measurements_md(panels, photo):
    if photo == "epic_wall":
        assert [e["angle_deg"] for e in panels[photo]] == EPIC_WALL_ANGLES
        return
    got = {e["colour"]: e["angle_deg"] for e in panels[photo]}
    assert got == MEASURED_ANGLES[photo]
