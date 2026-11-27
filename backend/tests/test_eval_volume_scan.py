"""Replay tool accuracy_checks/eval_volume_scan.py (#38, slice 4): tests written
from docs/milestones/v0.2/38-volume-scan-trial/spec.md ("Contracts (for the
Tester)", AC 6 and AC 7) and the trial-1 truth file
backend/field_captures_volumes/scan_trial_2026-11-27/truth.json.

    pair_faces(truth_faces, app_faces, aspect) -> one row per measured face, in order
        truth face: {name, angle_deg, polygon: [[x, y], ...]}   (normalised, on the photo)
        app face:   {steepness_deg, facing, n_points, outline: [{x, y}, ...]}
        row keys include name, truth, app (None when no app face lies mostly on
        the measured face), err, sign_counts (|angle_deg| >= 10) and sign_ok
        (when sign_counts; a missed face counts as wrong).
        Pairing is by position, not by angle.
        Slice 5: "mostly" is more than 50% of the app face inside the measured
        face's polygon; pairs are one-to-one, taken highest share first; a
        paired row carries `share`.
    lineup_needed(n) = ceil(0.75 n)

The spec doesn't say whether `truth` / `app` hold the angle or the whole face,
or whether `err` is signed, so the tests read an angle from either and compare
|err| with |app - truth|. It also doesn't say whether `share` is a fraction or
a percentage; paired shares are over 50%, so a value above 1 is read as a
percentage. "Share of the outline inside" is read as the share of the app
face's area (the outline is its polygon).
"""
import json
from pathlib import Path

import numpy as np
import pytest

from accuracy_checks import eval_volume_scan as evs

BACKEND = Path(__file__).resolve().parents[1]
TRUTH_JSON = BACKEND / "field_captures_volumes" / "scan_trial_2026-11-27" / "truth.json"

# Trial-1 photos reach the server as 3840 x 1776. Pairing in the cases below
# must not depend on the aspect (faces are fully inside, or far away), so
# tests that care run with both orientations.
ASPECTS = [3840 / 1776, 1776 / 3840, 1.0]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _square(cx, cy, half):
    return [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]


def _truth(name, angle, poly):
    return {"name": name, "angle_deg": angle, "polygon": [[x, y] for x, y in poly]}


def _app(steepness, poly, facing="out", n_points=150):
    return {"steepness_deg": steepness, "facing": facing, "facing_deg": 0.0, "n_points": n_points,
            "outline": [{"x": x, "y": y} for x, y in poly]}


def _shrink(poly, k):
    """Scale a (convex) polygon towards its centroid; k < 1 keeps it inside."""
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    return [(cx + k * (x - cx), cy + k * (y - cy)) for x, y in poly]


def _deg(value, what):
    """The angle in a row's `truth` / `app` entry: a number or a face dict."""
    if isinstance(value, dict):
        for key in ("steepness_deg", "angle_deg"):
            if key in value:
                return value[key]
        raise AssertionError(f"{what} is a dict without an angle: {value}")
    assert isinstance(value, (int, float)) and not isinstance(value, bool), f"{what} is {value!r}"
    return value


def _flag(row, key):
    """A row's yes/no field as a bool (numpy bools are fine: the spec doesn't fix the type)."""
    value = row[key]
    assert isinstance(value, (bool, np.bool_)), f"{key} is {value!r} in {row}"
    return bool(value)


def _share(row):
    """A paired row's share as a fraction (a percentage is accepted, see the module docstring)."""
    assert "share" in row, f"paired row without share: {row}"
    value = row["share"]
    assert isinstance(value, (int, float, np.floating)) and not isinstance(value, bool), f"share is {value!r}"
    value = float(value)
    return value / 100.0 if value > 1.0 + 1e-9 else value


def _rows(truth_faces, app_faces, aspect=1.0):
    rows = evs.pair_faces(truth_faces, app_faces, aspect)
    rows = list(rows)
    assert len(rows) == len(truth_faces), f"{len(rows)} rows for {len(truth_faces)} measured faces: {rows}"
    for row, t in zip(rows, truth_faces):
        assert isinstance(row, dict), row
        assert {"name", "truth", "app", "err", "sign_counts"} <= set(row), f"row keys {sorted(row)}"
        assert row["name"] == t["name"], f"rows out of order: {[r['name'] for r in rows]}"
        assert _deg(row["truth"], "truth") == t["angle_deg"], row
        if _flag(row, "sign_counts"):
            assert "sign_ok" in row, f"sign_counts row without sign_ok: {row}"
        if row["app"] is not None:
            # Slice 5: paired only when more than 50% of the app face is on the measured face.
            assert 0.5 < _share(row) <= 1.0 + 1e-6, f"paired with share {row['share']}: {row}"
    # One-to-one: no app face on two rows (the tests never pass two identical app faces).
    paired = [json.dumps(r["app"], sort_keys=True, default=str) for r in rows if isinstance(r["app"], dict)]
    assert len(paired) == len(set(paired)), f"one app face paired with two measured faces: {rows}"
    return rows


def _paired_angle(row):
    assert row["app"] is not None, f"{row['name']}: expected a paired app face, got None ({row})"
    return _deg(row["app"], "app")


def _assert_err(row):
    app, truth = _paired_angle(row), _deg(row["truth"], "truth")
    assert row["err"] is not None, row
    assert abs(abs(row["err"]) - abs(app - truth)) < 1e-6, f"err {row['err']} for app {app} vs truth {truth}"


# Two measured faces well apart, as on a wedge: A on the left, B on the right.
A_POLY = _square(0.30, 0.50, 0.10)
B_POLY = _square(0.70, 0.50, 0.10)


def _two_faces(angle_a=-40, angle_b=53):
    return [_truth("A", angle_a, A_POLY), _truth("B", angle_b, B_POLY)]


# ---------------------------------------------------------------------------
# pair_faces
# ---------------------------------------------------------------------------

def test_no_app_faces_one_unpaired_row_per_measured_face_in_order():
    truth = [_truth("left", -48, _square(0.2, 0.2, 0.05)),
             _truth("right", 7, _square(0.5, 0.5, 0.05)),
             _truth("bottom", 30, _square(0.8, 0.8, 0.05))]
    rows = _rows(truth, [])
    assert [r["name"] for r in rows] == ["left", "right", "bottom"]
    assert all(r["app"] is None for r in rows), rows


@pytest.mark.parametrize("aspect", ASPECTS)
def test_app_face_inside_measured_face_pairs_with_it(aspect):
    app = [_app(-35, _square(0.30, 0.50, 0.04))]  # entirely inside A
    rows = _rows(_two_faces(), app, aspect)
    assert _paired_angle(rows[0]) == -35
    _assert_err(rows[0])
    assert abs(rows[0]["err"]) == 5
    assert rows[1]["app"] is None, rows[1]


@pytest.mark.parametrize("aspect", ASPECTS)
def test_far_away_app_face_pairs_with_nothing(aspect):
    app = [_app(-40, _square(0.50, 0.08, 0.04)), _app(53, _square(0.92, 0.92, 0.04))]
    rows = _rows(_two_faces(), app, aspect)
    assert all(r["app"] is None for r in rows), rows


@pytest.mark.parametrize("aspect", ASPECTS)
def test_pairing_is_by_position_not_angle(aspect):
    # Each app face carries the *other* measured face's angle.
    app = [_app(53, _square(0.30, 0.50, 0.05)), _app(-40, _square(0.70, 0.50, 0.05))]
    rows = _rows(_two_faces(-40, 53), app, aspect)
    assert _paired_angle(rows[0]) == 53, rows[0]
    assert _paired_angle(rows[1]) == -40, rows[1]
    for row in rows:
        _assert_err(row)
        assert abs(row["err"]) == 93
        assert _flag(row, "sign_counts") is True
        assert _flag(row, "sign_ok") is False, row


def test_app_face_order_does_not_matter():
    a_face, b_face = _app(-38, _square(0.30, 0.50, 0.05)), _app(50, _square(0.70, 0.50, 0.05))
    for app in ([a_face, b_face], [b_face, a_face]):
        rows = _rows(_two_faces(), app)
        assert _paired_angle(rows[0]) == -38
        assert _paired_angle(rows[1]) == 50


def test_more_app_faces_than_measured_faces_still_one_row_each():
    app = [_app(-38, _square(0.30, 0.50, 0.05)), _app(50, _square(0.70, 0.50, 0.05)),
           _app(10, _square(0.10, 0.10, 0.03)), _app(-5, _square(0.90, 0.10, 0.03))]
    rows = _rows(_two_faces(), app)
    assert _paired_angle(rows[0]) == -38
    assert _paired_angle(rows[1]) == 50


def test_app_face_barely_touching_is_not_mostly_on_it():
    # Overlap with A is a 0.02 x 0.02 corner: ~1% of the app face and of A.
    app = [_app(-40, [(0.38, 0.58), (0.60, 0.58), (0.60, 0.80), (0.38, 0.80)])]
    rows = _rows(_two_faces(), app)
    assert rows[0]["app"] is None, rows[0]
    assert rows[1]["app"] is None, rows[1]


@pytest.mark.parametrize("aspect", ASPECTS)
def test_app_face_mostly_on_one_measured_face_pairs_with_that_one(aspect):
    # 0.15 wide: 0.12 of it over A (80%), the rest over the gap between A and B.
    app = [_app(-42, [(0.28, 0.45), (0.43, 0.45), (0.43, 0.55), (0.28, 0.55)])]
    rows = _rows(_two_faces(), app, aspect)
    assert _paired_angle(rows[0]) == -42
    assert abs(_share(rows[0]) - 0.8) <= 0.02, rows[0]  # share is an area ratio, so aspect-free
    assert rows[1]["app"] is None, rows[1]


@pytest.mark.parametrize("aspect", ASPECTS)
def test_share_of_app_face_wholly_inside_is_one(aspect):
    rows = _rows(_two_faces(), [_app(-35, _square(0.30, 0.50, 0.04))], aspect)
    assert abs(_share(rows[0]) - 1.0) <= 0.02, rows[0]


def test_two_app_faces_on_one_measured_face_pairs_one_of_them():
    # Both wholly inside A (equal shares), so either may be the pair.
    app = [_app(-30, [(0.22, 0.42), (0.29, 0.42), (0.29, 0.58), (0.22, 0.58)]),
           _app(-45, [(0.31, 0.42), (0.38, 0.42), (0.38, 0.58), (0.31, 0.58)])]
    rows = _rows(_two_faces(), app)
    assert _paired_angle(rows[0]) in (-30, -45), rows[0]
    _assert_err(rows[0])
    assert rows[1]["app"] is None, rows[1]


# Slice 5 boundary cases on two measured faces that share an edge at x = 0.5:
# L = [0.25, 0.5] x [0.375, 0.625], R = [0.5, 0.75] x [0.375, 0.625].
# Coordinates are exact in binary and the aspects are powers of two, so a
# share of exactly one half is computed exactly.
L_POLY = [(0.25, 0.375), (0.5, 0.375), (0.5, 0.625), (0.25, 0.625)]
R_POLY = [(0.5, 0.375), (0.75, 0.375), (0.75, 0.625), (0.5, 0.625)]
EXACT_ASPECTS = [1.0, 2.0, 0.5]


def _adjacent_faces():
    return [_truth("L", -40, L_POLY), _truth("R", 30, R_POLY)]


def _rect(x0, x1, y0=0.4375, y1=0.5625):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


@pytest.mark.parametrize("aspect", EXACT_ASPECTS)
def test_app_face_split_50_50_across_two_faces_pairs_with_neither(aspect):
    # Half of the app face on L, half on R: not "more than 50%" on either.
    rows = _rows(_adjacent_faces(), [_app(-35, _rect(0.4375, 0.5625))], aspect)
    assert rows[0]["app"] is None, rows[0]
    assert rows[1]["app"] is None, rows[1]


@pytest.mark.parametrize("aspect", ASPECTS)
def test_app_face_under_half_on_each_of_two_faces_pairs_with_neither(aspect):
    # 0.2 wide and 0.25 tall, centred on the shared edge, its top 0.05 above
    # both faces: 40% on L, 40% on R, 20% outside every measured face.
    app = [_app(-35, [(0.4, 0.325), (0.6, 0.325), (0.6, 0.575), (0.4, 0.575)])]
    rows = _rows(_adjacent_faces(), app, aspect)
    assert rows[0]["app"] is None, rows[0]
    assert rows[1]["app"] is None, rows[1]


@pytest.mark.parametrize("aspect", EXACT_ASPECTS)
def test_app_face_half_on_one_face_half_off_pairs_with_nothing(aspect):
    # Half on L, half to the left of it (outside every measured face).
    rows = _rows(_adjacent_faces(), [_app(-35, _rect(0.1875, 0.3125))], aspect)
    assert rows[0]["app"] is None, rows[0]
    assert rows[1]["app"] is None, rows[1]


@pytest.mark.parametrize("aspect", ASPECTS)
def test_app_face_just_over_half_on_one_face_pairs_with_it(aspect):
    # 0.125 wide: 0.075 on L (60%), 0.05 on R (40%).
    rows = _rows(_adjacent_faces(), [_app(-35, _rect(0.425, 0.55))], aspect)
    assert _paired_angle(rows[0]) == -35, rows[0]
    assert abs(_share(rows[0]) - 0.6) <= 0.02, rows[0]
    assert rows[1]["app"] is None, rows[1]


@pytest.mark.parametrize("order", ["low-first", "high-first"])
def test_highest_share_pairs_first(order):
    # Both app faces are mostly on A: X has 70% on A (the rest in the gap),
    # Y lies wholly inside. A pairs with Y, whatever the order of the app faces.
    x = _app(-31, [(0.26, 0.45), (0.46, 0.45), (0.46, 0.55), (0.26, 0.55)])   # 0.2 wide, 0.14 over A
    y = _app(-44, _square(0.30, 0.50, 0.05))
    app = [x, y] if order == "low-first" else [y, x]
    rows = _rows(_two_faces(), app)
    assert _paired_angle(rows[0]) == -44, rows[0]
    assert abs(_share(rows[0]) - 1.0) <= 0.02, rows[0]
    assert rows[1]["app"] is None, rows[1]


def test_pairs_are_one_to_one_highest_share_first_across_overlapping_faces():
    # Measured faces A = [0.2, 0.5] and B = [0.35, 0.7] wide (same height)
    # overlap. App face X is wholly on A (share 1.0) and 87% on B; app face Y
    # is 83% on B and 17% on A. Highest share first: X -> A, then X is taken,
    # so B gets Y, not X.
    a = _truth("A", -40, [(0.2, 0.4), (0.5, 0.4), (0.5, 0.6), (0.2, 0.6)])
    b = _truth("B", 53, [(0.35, 0.4), (0.7, 0.4), (0.7, 0.6), (0.35, 0.6)])
    x = _app(-38, [(0.33, 0.42), (0.48, 0.42), (0.48, 0.58), (0.33, 0.58)])
    y = _app(50, [(0.45, 0.42), (0.75, 0.42), (0.75, 0.58), (0.45, 0.58)])
    for app in ([x, y], [y, x]):
        rows = _rows([a, b], app)
        assert _paired_angle(rows[0]) == -38, rows[0]
        assert _paired_angle(rows[1]) == 50, rows[1]
        assert abs(_share(rows[1]) - 0.25 / 0.30) <= 0.02, rows[1]


@pytest.mark.parametrize("angle, counts", [
    (-48, True), (30, True), (53, True), (-40, True), (10, True), (-10, True),
    (9.9, False), (-9.9, False), (7, False), (-5, False), (0, False),
])
def test_sign_counts_when_at_least_10_deg_from_vertical(angle, counts):
    rows = _rows([_truth("f", angle, A_POLY)], [])
    assert _flag(rows[0], "sign_counts") is counts, rows[0]


@pytest.mark.parametrize("truth_angle, app_angle, ok", [
    (-48, -40, True), (30, 22, True), (53, 60, True),
    (-48, 12, False), (30, -20, False), (-40, 35, False),
])
def test_sign_ok_compares_signs(truth_angle, app_angle, ok):
    rows = _rows([_truth("f", truth_angle, A_POLY)], [_app(app_angle, _square(0.30, 0.50, 0.05))])
    assert _flag(rows[0], "sign_counts") is True
    assert _flag(rows[0], "sign_ok") is ok, rows[0]


def test_missed_face_counts_as_wrong_sign():
    rows = _rows([_truth("f", -48, A_POLY)], [_app(-48, _square(0.85, 0.85, 0.05))])
    assert rows[0]["app"] is None
    assert _flag(rows[0], "sign_counts") is True
    assert _flag(rows[0], "sign_ok") is False, rows[0]


def test_near_vertical_face_error_still_reported():
    # AC 7: faces within 10 deg of vertical don't count for the sign, but their error is reported.
    rows = _rows([_truth("right", 7, A_POLY)], [_app(-5, _square(0.30, 0.50, 0.05))])
    assert _flag(rows[0], "sign_counts") is False
    _assert_err(rows[0])
    assert abs(rows[0]["err"]) == 12


# ---------------------------------------------------------------------------
# pair_faces on the trial-1 truth (reference data)
# ---------------------------------------------------------------------------

def _truth_scans():
    if not TRUTH_JSON.is_file():
        pytest.skip(f"{TRUTH_JSON} missing")
    return json.loads(TRUTH_JSON.read_text())["scans"]


@pytest.mark.parametrize("aspect", ASPECTS[:2])
def test_trial1_faces_that_count_for_the_sign(aspect):
    # AC 7: exactly 4 faces are >= 10 deg from vertical; with nothing found, each is wrong.
    counted = set()
    for scan_id, scan in _truth_scans().items():
        faces = [f for f in scan["faces"] if f.get("angle_deg") is not None]
        rows = _rows(faces, [], aspect)
        for row in rows:
            assert row["app"] is None
            if row["sign_counts"]:
                assert _flag(row, "sign_ok") is False, f"{scan_id} {row['name']}: missed face must count as wrong"
                counted.add((scan["image"], row["name"], _deg(row["truth"], "truth")))
    assert counted == {(1, "left", -48), (1, "bottom", 30), (2, "top", -40), (2, "bottom", 53)}, counted


@pytest.mark.parametrize("aspect", ASPECTS[:2])
def test_trial1_image1_faces_pair_with_faces_drawn_inside_them(aspect):
    # Image 1's three triangles, each with an app face at half size inside it,
    # given in reverse order, with the right signs.
    scan = next(s for s in _truth_scans().values() if s["image"] == 1 and s["faces"])
    faces = scan["faces"]
    app_angle = {"left": -41, "right": 3, "bottom": 36}
    app = [_app(app_angle[f["name"]], _shrink([tuple(p) for p in f["polygon"]], 0.5)) for f in reversed(faces)]
    rows = _rows(faces, app, aspect)
    for row, face in zip(rows, faces):
        assert _paired_angle(row) == app_angle[face["name"]], row
        _assert_err(row)
        assert _flag(row, "sign_counts") is (abs(face["angle_deg"]) >= 10)
        if row["sign_counts"]:
            assert _flag(row, "sign_ok") is True, row


# ---------------------------------------------------------------------------
# lineup_needed (AC 6: at least 75% of the burst photos line up)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n, needed", [(8, 6), (9, 7), (7, 6)])
def test_lineup_needed_spec_examples(n, needed):
    assert evs.lineup_needed(n) == needed


@pytest.mark.parametrize("n", range(1, 25))
def test_lineup_needed_is_ceil_three_quarters(n):
    got = evs.lineup_needed(n)
    assert isinstance(got, int) and not isinstance(got, bool), repr(got)
    assert got == -(-3 * n // 4), f"lineup_needed({n}) = {got}"
