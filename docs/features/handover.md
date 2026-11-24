# Handover: wall size and hold distance

The one place for slice status, open questions and what happened in each slice. The spec (`wall_size_hold_distance.md`) holds the contracts, decisions and accuracy tables. The volume retrain side task has its own doc (`volume_retrain.md`).

Compiled on 2026-11-24 from four older files (`handover_wall_size_hold_distance.md`, `slice_5_split.md`, `plan_after_5b.md`, and the logs in the spec). Their full text is in git history (commit `Wall size / hold distance: slices 1-11 snapshot`).

---

## Overview (for the human)

**What the feature does.** It uses the grid of bolt holes on a climbing wall as a ruler. From one photo it measures the distance between holds, the wall's length and the steepness under each hold. It sends all of that, with honest error margins, to the coaching AI.

**Where we are.** Slices 1–10 are done and work end to end on a real phone. Slice 11 (volumes) has gone as far as it can until volumes are measured. **Next is slice 12, the wall-angle fixes.**

| # | Old # | Slice | Status |
|---|---|---|---|
| 1 | 0 | Spec and agent setup | ✅ Done |
| 2 | 1 | Walking skeleton: settings, lines between holds, distances to the AI (all stubbed) | ✅ Done |
| 3 | 2 | Find the bolt holes in the photo | ✅ Done |
| 4 | 3 | Fit the bolt grid: real distances and wall length | ✅ Done |
| 5 | 4 | Measure the accuracy and set the AI's error margin | ✅ Done |
| 6 | 5a | √2 fix: stop reading a square's diagonal as its side | ✅ Done |
| 7 | 5b | Split the wall into flat panels, measure each one separately | ✅ Done |
| 8 | 5c | Confidence tiers: a wider margin where bolts are hidden | ✅ Done |
| 9 | 5d | Wall steepness under each hold (bolt grid + phone tilt) | ✅ Done |
| 10 | 6 | Tape-measure check: 5 cm hold-centre allowance confirmed | ✅ Done |
| 11 | 6b steps 1–2 | Volumes: can we measure a volume face's angle? | ⏸ Paused, needs measured volumes |
| **12** | 5e | **Wall-angle fixes, field replay script, slab check** | **▶ Next** |
| 13 | 7 | Speed: `/detect` from 7–15 s down to 4–5 s | To do |
| 14 | 6b step 3 | Volumes, finish: holds on volumes, face angles to the AI | To do, needs the volume retrain |
| 15 | 8 | Volume distance fix and more coaching info (cm positions, height, ape index, hold colour) | To do |
| 16 | 9 | Speed re-check, planned with you | To do |
| 17 | End | Final docs write-up | To do |
| 18 | new | **Fable review** of all the work (see below) | To do |

**Order:** 12 → 13 → 14 → 15 → 16 → 17 → 18.
- 12 goes before 13 because both rewrite `scale.py` and `angle.py`. Speeding up code that is about to change wastes the work.
- 12 also rebuilds the field replay script, which every later slice uses to prove nothing got worse.
- 16 exists because 14 and 15 add work to each photo after 13 has made it fast.

**Needs from you:**
1. **Slab photos** (for slice 12). For each: the wall angle, a few tape distances, and the phone's tilt when the photo was taken. More detail under slice 12 below.
2. **Measured volumes** (unblocks slice 11). The list is under slice 11 below.
3. **Volume retrain data** (unblocks slice 14). See `volume_retrain.md`; parked until you have gathered it.
4. **Before slice 17:** decide what "wall length" should mean. Today it is the wall *in the photo*: the same wall read 10.7 to 20.5 grid units as you stepped back. See the Field test entry.

---

## Slice 18: Fable review

**Once every slice is complete, Fable goes over all the completed work** and makes any changes it sees necessary for efficiency, unneeded code, bugs and so on. Done when Fable's findings are fixed or consciously accepted by the human, the test suite is green, and the accuracy numbers (`eval_scale.py --accuracy`, `--tape`, `eval_angle.py`, the field replay) are unchanged or better.

What Fable should check:

**Efficiency**
- Pure-Python loops left in `scale.py`, `bolts.py`, `angle.py`, `volume.py` after slice 13.
- Work done twice per request: the photo decoded, rotated or converted more than once; metrics recomputed per hold rather than once.
- The N×N `distances_units` and `tiers` in the `/detect` response: does the app need all of it?
- YOLO cold start (9.8 s once): is the model warmed when the server starts?
- `volume.fit_volume` tries many shape hypotheses per volume. Is the cost bounded when a photo has 10+ volumes?

**Unneeded code**
- Dev-only scripts in `backend/`: `eval_scale.py`, `eval_angle.py`, `eval_volume.py`, `eval_volume_field.py`, `fakewall.py`, `draw_volume_corners.py`, `experiments/`. Keep, move to a `tools/` folder, or delete.
- Compatibility code for scales cached before a slice ("a scale cached before slice 8 has no tiers"). The cache lasts 1 hour, so these can likely go.
- Leftovers from the stub and from tier B, constants nothing reads, the old 640×640 test photo in `assets/images/`.
- Comments pointing at tools that no longer exist (`field_capture.py`, `/dev/test-capture`).

**Bugs and edge cases**
- Bad input reaching the maths: empty or degenerate masks, NaN or infinite values, zero bolts, one panel, a photo over 4096 px, no EXIF.
- Phone sends a cropped 1776×3840 frame with no EXIF, so the focal length falls back to 26 mm, about 12% wrong. Angles survive this; anything in cm on a volume does not.
- Sign conventions: degrees from vertical, + overhang / − slab, must match across `angle.py`, `volume.py`, `worker.py` and the app.
- The Android sensor sign has never been tested on a real Android phone.
- Landscape or rolled phone: the tilt reading is ignored. Check that this is clear to the user.
- Errors: a failure in angle or volume code must never fail `/detect`. Check that every path returns nulls rather than a 500.

**Tests**
- Tests that pin how the code works rather than what it should produce.
- xfails that are no longer expected to fail; slow tests that never run in CI.
- The fast suite takes about 5 minutes. Find out what dominates.

**Thin calibration.** Fable reports these to the human and doesn't change them alone:
- Distance margins: 6% (tier A), 14% (tier C), 5 cm hold-centre allowance. One phone, two gyms, 12 tape pairs.
- Angle margins: 8° (sensor) and 15° (assumed); `DEFAULT_PITCH_DEG = 12`.
- `MAX_REPROJECTION_FRACTION = 0.05`, tuned on one synthetic set; the VOLUME confidence floor of 0.25.

**Safety and housekeeping**
- No upload size limit on `/detect`; error messages must not leak internals; the API key stays server-side.
- The YOLO model is AGPL-3.0. Check what that means if the app ships.
- Mobile: the two existing lint errors (`useTestPhoto` hook in a callback, `ModeSlider` refs during render); backend and app types kept in sync by hand (`ClimbStep`, `Scale`).
- Docs vs code: the spec, `architecture.md` and `decisions.md` still match the code.

---

## Rules for agents

1. **At the start of a session**, read the Overview and the newest log entry for your slice.
2. **At the end of each slice**, update the Overview table and add an entry at the **top** of the Slice log, using the template below.
3. Don't rewrite past entries. If one was wrong, correct it in your new entry. (The 2026-11-24 compile condensed the old entries once, at the human's request.)
4. **Source control is the human's** (see `AGENTS.md`). On 2026-11-24 the human asked Claude to make two commits on `feat/more-detail-for-LLM-and-output-format`. That was a one-off, not a change to the rule.
5. Be specific: file paths, function names, exact test output. Keep it short: what the next session needs, not a diary.

<details>
<summary>Entry template</summary>

```markdown
### YYYY-MM-DD · Slice <n>: <title>

**Status:** Complete / Partial / Blocked

**What changed**
- `path/to/file`: what and why

**Results**
- Tests: `<command>` → `<X passed, Y failed>`
- Against the done-when: met / not met, with numbers

**Decisions** (recorded in spec: yes/no)

**Questions for the human**

**Known issues / context for the next session**

**Human:** Reviewed: <yes/no> · Notes:
```
</details>

---

## Slice log (newest first)

### Slice 12 (next): wall-angle fixes

**Status:** Not started. It was approved on 2026-11-13. On 2026-11-20 work went straight to volumes (slice 11), and nothing recorded the skip. `angle.py` is unchanged since 2026-11-09.

**Scope:**
1. Group bolts by their own wall direction before giving holds an angle. This fixes epic_wall P14, which reads 14° as 25–27° on a smooth seam.
2. A confidence per hold: no angle when the evidence is thin or the two mirror answers tie.
3. A synthetic-wall test of the angle vote. Today no unit test covers it.
4. **Re-create `eval_field.py`.** The first version was written and later removed, but its data is in `backend/field_captures/` (15 captures, each a `photo.jpg` plus a `truth.json`). It replays them through the current code and compares against the Field test baseline.
5. **Slab vs overhang.** One photo can't tell a slab from an overhang (IMG_7503's −26° slab reads +26°). `volume.wall_plane` (slice 11) gets the wall from a panel homography with no mirror twin, so it may fix this. Test it on your slab photos.

**Slab photos needed from you:** a few photos of a slab wall, ideally with a vertical or overhanging panel in the same shot. For each:
- the wall angle, measured on the wall with a phone inclinometer (− for slab)
- 2–3 tape distances, bolt to bolt
- **the phone's tilt when you took the photo.** Normal-camera JPEGs carry no tilt reading, and the in-app capture tool was removed. Either note the tilt from a level app, or ask for a small dev capture endpoint that saves the photo plus the tilt. Without the tilt, the angle check would be circular.

**Done when:** P14 is within 10° without regressing the other 18 panels in `eval_angle.py`; the confidence rule is tested; the field replay shows no hold angle or distance worse than the baseline.

---

### 2026-11-20 · Slice 11: volume feasibility (old 6b steps 1–2)

**Status:** Paused. The maths is built and scored on synthetic walls. It is blocked on real measured volumes.

**What was built**
- `backend/volume.py`, dev-facing only, with no API change:
  - `wall_plane` puts the wall in cm from a panel homography. It has no mirror twin; see slice 12.
  - Three shape fitters: box, wedge, pyramid.
  - `fit_volume` reduces the outline to corners, finds the apex from ridge lines (LSD), tries each shape, and ranks by normalised reprojection error.
  - `describe_face` gives each face's steepness and the direction it faces.
  - `hold_face` gives how far a hold stands off the wall.
- `backend/fakewall.py` renders synthetic walls with exact truth (25 scenes, 66 volumes). `eval_volume.py` scores them; `eval_volume_field.py` scores real photos. `draw_volume_corners.py` is a corner-clicking tool, not yet used by hand.
- `backend/experiments/surface_normals/`: the Metric3D v2 test, run in a separate environment. Nothing was added to `pyproject.toml`.
- `tests/test_volume.py`: 63 tests.

**The key finding.** In one photo, sliding a volume's tip along the camera ray changes neither its outline nor its ridges, so a single photo can't see how far a volume stands off the wall.
- **Boxes and wedges:** fine, because their tops sit over base points we can see.
- **Pyramids:** have to *assume* the tip is over the centre. A tip 5 cm off-centre near the middle of the frame becomes 27 cm of height error and 17° of face error.

**Results**
- Synthetic, gated on `trusted`: steepness median 0.3°, p90 0.8°; 4 of 125 trusted fits unusable (the half-cylinder plus three noise cases).
- Real (15 field captures, 62 volumes): after the rules below, **none is trusted**. All five that were trusted before were guessed pyramids, and the existing captures contain no clean box or wedge.
- Surface-normal network: about 3.3 s per photo on CPU, real-wall median error 8.4°, under-reads overhangs. The verdict waits on the measured volumes.

**Decisions**
- Only `trusted` fits are reported. An untrusted volume says nothing, to either the AI or the user (human, 2026-11-20).
- No pyramid with an assumed tip is ever trusted, even with a ridge apex.
- A volume whose base touches the frame edge is never trusted.
- Volumes are ranked on reprojection error, not outline overlap: overlap was 0.98+ on fits that were 35 cm out.
- Facing is reported as `"undefined"` past 85° of steepness.
- Curved volumes: say nothing.
- **Dead ends, don't retry:** a depth model plus the wall plane (volumes came out 2–3 cm deep); a wedge from a ridge parallel to its base (mathematically degenerate).

**Recommended route for pyramids:** a second photo, 50 cm–1 m to the side. Both camera poses are solved together from the shared bolts, then the tip is triangulated. The fallback is a surface-normal network, if the real data supports it.

**Measured volumes needed from you** (15–25 volumes):
- per volume: the shape; each face's angle (+ overhang / − slab); how far the tip stands off the wall; how far the tip is off-centre; the wall angle beside it; base edge lengths
- a few tape distances from a hold on a volume to a hold on the wall
- spread: a mix of colours, including dark-on-dark; a slab and an overhang; each volume once near the middle of the frame and once near the side; a second photo from the side as a bonus

**Context:** photos must be JPEG (HEIC isn't readable). Run `eval_volume_field.py --survey` on new photos first to get detection ids.

---

### 2026-11-18 · Field test (real phone, between slices 10 and 11)

15 captures through the app, one gym, one iPhone, with the tilt recorded. Data in `backend/field_captures/`, with ground truth in each `truth.json`. The first 11 captures were taken at the app's 20 cm spacing and recomputed at the wall's real 25 cm.

- **Distances:** all 9 independent pairs are inside their margins. One pair photographed at three tilts reads 69.6 / 69.3 / 69.6 cm.
- **Angles:** 29 holds, median error 1.2°, worst 5.2°, all inside the 8° margin. A 54° overhang read 54.5°. The iOS sensor path is confirmed.
- **Problems found:**
  1. Holds on volumes: distances are measured as if on the wall (`173933`, +19%), and the angle is the wall's, not the volume face's. → slices 11, 14, 15.
  2. `/detect` took 6.6–15.3 s. → slice 13.
  3. The phone sends a cropped 1776×3840 frame with no EXIF, so the focal length is guessed. → slices 13 and 15.
  4. Wall length is the wall in the photo, not the whole wall. → decision needed before slice 17.
- Not yet tested: Android, a real slab, a second gym.

---

### 2026-11-13 · Slice 10: tape check and centroid allowance (old 6)

**Status:** Complete.

- **Bolt spacing is 25 cm** on epic_wall and IMG_7552 (human). The earlier "+6% error" was the wrong spacing (26 cm).
- `eval_scale.py --tape` measures each pair twice: between the recorded points, which shows the scale error alone, and between hold centres, which is what the AI gets.
- **All 12 trusted pairs on three walls are inside their margin.** Hold-centre shift has a median of about 1.5 cm; 11 of 12 are within 5 cm. Bolt-to-bolt errors are +1% to +4% (one −5%), so tier A's 6% holds.
- **Decisions:**
  - The 5 cm allowance stays: confirmed, but not tightened, because 12 pairs is thin.
  - Bad tape measurements were deleted, not just flagged.
- **Known issue:** one big jug's centre sat 10.3 cm from its bolt. If this repeats, the allowance should scale with hold size.

---

### 2026-11-09 · Slice 9: wall angle per hold (old 5d)

**Status:** Complete; the phone check was done in the Field test.

- `backend/angle.py`: at each bolt, the grid's local shape gives two mirror-image wall directions. The one that most of the 50 nearest bolts agree on wins, and ties go to overhang. Gravity comes from the phone's accelerometer (`expo-sensors`); without it, a 12° camera tilt is assumed. Focal length comes from EXIF, else 26 mm.
- `/detect` takes an optional `gravity` field. `scale` gains `angles_deg`, `angle_source`, `angle_margin_deg`. Each hold sent to the AI gets `wall_angle_deg`, and PhotoPreview shows `≈N°`.
- **Results:** 19 measured panels, median error 1° with the true tilt (3° assumed); 16 of 19 within 10°. Misses:
  - a slab read as an overhang (mirror)
  - a sparse 34° panel
  - epic_wall P14 on a smooth seam
- **Decisions:**
  - Angle per hold, not per panel.
  - Ties go to overhang.
  - Margins: 8° with the sensor, 15° assumed.
  - `Accelerometer` rather than `DeviceMotion`, to avoid an iOS permission prompt.
- **Context:** `scale.py` imports `angle` at the top, and `angle.py` imports `scale` inside functions. Keep it that way to avoid a circular import.

---

### 2026-11-04 · Slice 8: confidence tiers (old 5c)

**Status:** Complete.

- Each distance is **tier A** when every one of its 16 sample points is within 1.5 bolt spacings of a fitted bolt; otherwise **tier C** (scale borrowed from further away).
- Margins: **A 6%, C 14%**, plus 5 cm on both. C's 14% comes from cutting random holes in the bolt grid on 5 photos and measuring across them (pooled p95 13.4%).
- `scale.tiers` is N strings of N characters (`"AACA"`), to keep `/detect` small.
- **Tier B (hole size as a ruler) dropped**, approved by the human 2026-11-09. Holes in one photo varied nearly 2× in apparent size. IMG_7501 stays `insufficient_bolts`.

---

### 2026-10-20 · Slice 7: panels and a homography per panel (old 5b)

**Status:** Complete.

- `scale.segment_panels`: competing local homographies; bolts join the panel whose grid they fit, then panels are merged and split. Each panel then measures with its own homography.
- **Results:** in-panel p95 1.0 / 1.7 / 2.7 / 2.9% on IMG_7500 / 7502 / 7503 / 7504 (pooled 2.2%). The target of 7% is now met on every reference photo.
- **IMG_7502's old 12.6%** was mostly the ground truth slipping one bolt site, not the measuring.
- **Context:**
  - The guards in `segment_panels` are all needed on real photos (see spec Decisions).
  - Region growing was tried first and swallowed whole walls; don't retry it.
  - `compute_scale` went from 1.8–3.3 s to 2.2–3.7 s.
- New reference photo IMG_7552 (5 tape pairs, 4 edges).

---

### 2026-10-19 · Slice 6: the √2 fix (old 5a)

**Status:** Complete.

- **The problem:** where holds hide every centre bolt, the corner bolts look like the normal grid 1.41× coarser, so distances come out about 30% short.
- **The fix:** after the vote, bolts are grouped by agreement. Where two touching groups differ by exactly √2, the coarser group is re-read. Two guards are needed on real photos: the misread group must continue the finer group's grid, and the finer group needs at least 7 bolts.
- **Rejected:** a hole-size prior; a wider vote.

---

### 2026-10-19 · Slice 5: accuracy and the AI's margin (old 4)

**Status:** Complete.

- `panels.json`: panel outlines digitised from your drawn photos.
- `eval_scale.py --accuracy` reports in-panel, reach-range (30–250 cm) and pooled numbers.
- **Margin = 6%** (pooled reach-range p95, 5.2%, rounded up) **+ 5 cm** hold-centre allowance. Each pair gets a precomputed `margin_cm`, so the AI doesn't do the arithmetic.
- Pooled rather than worst photo: using the worst would make every wall twice as lenient to cover one sparse wall.
- **Photo resolution needed:** about 6 px per cm of wall, roughly 3200 px on the long side. Below that, bolts drop out and the wall length collapses. **Never resize or recompress uploads.**
- "Use Test Photo" now loads the full-resolution IMG_7504.
- To re-derive the margin: run `--accuracy` on all reference photos and read the SUMMARY pooled p95.

---

### 2026-10-16 · Slice 4: bolt-grid fit, real distances, wall length (old 3)

**Status:** Complete. IMG_7502/7503 missed 7% at the time; fixed in slice 7.

- `scale.fit_lattice`: a local 2×2 stretch per bolt, chosen from candidate fits by neighbour agreement. That handles a sheared grid, the √2 reading and false detections.
- Distances integrate the local metric along the line between hold centres (16 samples).
- Wall length runs top bolt to bottom bolt.
- `/detect` now applies the EXIF rotation.
- **Decision:** interpolate the metric, not the stretch, so the grid's symmetries don't matter.
- **Dead ends:** a smooth spacing-field filter; per-bolt "most square" or "coarsest" tie-breaks.
- **Gotcha:** in `_fit_candidates`, the occupancy filter must come before squareness, or finer grids win.

---

### 2026-10-16 · Slice 3: bolt-hole detection (old 2)

**Status:** Complete. IMG_7501 is deferred and later dropped in slice 8.

- `backend/bolts.py`: OpenCV blob detection at three zoom levels; drops anything inside a hold, low in contrast or under 5 px.
- The key filter: a candidate must sit on evenly spaced lines of similar blobs in 2 directions. Paint speckle and wood grain outnumber bolts 10–20×, and regularity is what separates them.
- Hole size is measured at half depth, because the blob detector's own size is up to 1.7× too big under uneven light.
- Minimum bolt spacing setting raised to 10 cm.
- No scipy; neighbour search uses `cv2.BFMatcher`.

---

### 2026-10-16 · Slice 2: walking skeleton (old 1)

**Status:** Complete.

- Settings modal with the bolt spacing, stored in AsyncStorage.
- `/detect` returns a stub `scale`.
- PhotoPreview draws labelled lines between consecutive picks.
- `/analysis` takes `bolt_spacing_cm`; the worker converts to cm and sends `distances_cm` plus a placeholder 10% margin.
- **Decisions:**
  - The backend works in grid units, and cm conversion happens in the worker and the app, so changing the spacing rescales without re-running detection.
  - The scale is cached under its own Redis key.
  - `select_holds` returns a flat list in pick order.

---

### 2026-10-16 · Slice 1: spec and agent setup (old 0)

**Status:** Complete. The spec was written; Tester and Reviewer agent files were created in `.claude/agents/`. The test command is `cd backend && uv run python -m pytest`.
