# Handover Log

Agents use this file to pass context between slices and sessions. Chat history does not carry over, so anything the next session needs must be written here.

## Rules for Agents

1. **At the start of a session**, read the most recent entry for your feature before doing anything else.
2. **At the end of each slice**, add a new entry at the **top** of the *Entries* section, using the template below.
3. **Never edit or delete past entries.** If something in an earlier entry was wrong, correct it in your new entry.
4. **Never commit.** After writing the entry, stop and wait for the human. The human reviews and fills in the *Human* section. There are no commits between slices.
5. **Be specific.** Use file paths, function names, and exact test output. Write for a reader with no memory of this session.
6. **Keep it short.** Aim for what the next session needs, not a diary of everything you tried.

## Entry Template

Copy everything between the lines.

---

### YYYY-MM-DD · `<feature-name>` · Slice `<n>`: `<slice title>`

**Agent:** `<Developer / Tester / Reviewer>`
**Status:** `<Complete / Partial / Blocked>`
**Spec:** `docs/features/<feature-name>.md`

#### What changed
- `path/to/file`: what and why

#### Test results
- Command: `<command run>`
- Result: `<X passed, Y failed>`
- Against acceptance criteria: `<met / not met, with numbers>`

#### Decisions made
- `<decision>`: `<reason>` (also recorded in spec: yes/no)

#### Questions for the human
- `<anything needing a choice or approval before the next slice>`

#### Known issues
- `<stubs, hardcoded values, fragile code, skipped cases>`

#### Context for the next session
- `<things not obvious from the code: gotchas, dead ends already tried, assumptions>`

#### Next slice
- `<what should happen next, and done-when condition>`

#### Human
- Reviewed: `<yes/no>`
- Notes: `<feedback or changes to the plan>`

---

## Entries

<!-- Newest entry first. Agents add new entries directly below this line. -->

---

### 2026-11-13 · `wall_size_hold_distance` · Slice 6: tape check, centroid allowance

**Agent:** Developer
**Status:** Complete. The 5 cm centroid allowance is confirmed by real tape data, so `worker.py` is unchanged.
**Spec:** `docs/features/wall_size_hold_distance.md` ("Slice 6: centroid allowance", slice 6 and 5e rows, Reference data)

#### What changed
- `mobile/.../known_measurements/epic_wall_2.jpg` (new): the same photo as `epic_wall.jpg`, pixel-identical under the drawings. Pairs are labelled with small red digits 3–6 beside each end's bolt hole, and a red vertical line is drawn on it.
- `mobile/.../known_measurements/epic_wall_2_measured.txt` (new): the human's raw tape notes, unedited.
- `mobile/.../known_measurements/pairs.json`:
  - New `epic_wall_2` entry: pairs 3–6 (207, 161, 67, 167 cm) and the red vertical line (457 cm). Points are the bolt hole beside each label, checked on crops. Pair 5 joins two bare wall bolt holes and has `"snap": false`.
  - Deleted as measurement errors (human, 2026-11-13): epic_wall_2 pairs 1 and 2 (30–40% longer than the bolt grid, and than the earlier measurements of the same holds); epic_wall pairs 2 and 6 and the 322 cm vertical line (judged errors on 2026-11-09).
  - Spacing notes changed to 25 cm.
- `backend/eval_scale.py`:
  - `tape_check` measures each pair twice: **points** (between the recorded points: scale error only) and **holds** (between the nearest hold centroids: what the LLM gets).
  - It prints the tier, the worker's `margin_cm`, inside/outside and the centroid shift. It honours `"snap": false` and returns rows.
- Spec: the "Slice 6" section (full table), the Reference data spacing (25 cm), the old 26 cm tape check marked superseded, and the slice 6 and 5e rows.

#### Test results
- Command: `cd backend && uv run python -m pytest -q -m "not slow"`
- Result: **615 passed, 1 xfailed, 27 deselected**. This is unchanged; no test covers `eval_scale.py` or `pairs.json`.
- Tape check: `uv run python eval_scale.py <epic_wall_2.jpg / epic_wall.jpg / IMG_7552.jpeg> --tape 25`.
- Against the done-when (allowance replaced or confirmed, spec says which): **met, confirmed.**
  - All 12 trusted hold pairs on three walls are inside their `margin_cm`.
  - The centroid shift has a median of about 1.5 cm; 11 of the 12 are within 5 cm.
  - At most 4.6 cm is needed beyond the 6% part of the margin.
  - Bolt-to-bolt error on the epic_wall photos is +1% to +4%, plus one at −5%, so tier A's 6% holds on tape.
  - The 457 cm vertical line reads 460.8 (+1%).

#### Decisions made
- **Bolt spacing is 25 cm** on epic_wall / epic_wall_2 / IMG_7552 (human). This replaces 26 cm (from "5 bolts across = 1.04 m") and the 20 cm used for IMG_7552. The earlier "+6% on epic_wall" was this spacing error. (also recorded in spec: yes)
- **Allowance stays 5 cm, not tightened:** 12 pairs is thin. (yes)
- **Bad measurements deleted, not just flagged** (human). (yes)
- **Horizontal line (301 cm) left out:** the human was unsure of it, and the epic_wall top edge already checks it. (yes)
- **Slice 5e (angle fixes) approved**, to run before slice 7. (yes)

#### Questions for the human
- None blocking. The real-phone angle check is planned for 2026-11-14.

#### Known issues
- One big hold (the black jug in epic_wall_2 pair 6) has a centroid 10.3 cm from its bolt, over the 5 cm allowance on its own. The pair stayed inside its margin only because its scale error cancelled it out. If more big holds do this, the allowance should scale with hold size.
- IMG_7552's pair and edge endpoints were read by eye from drawn lines (about ±3 cm), so its numbers are rough. Its edges read −6% to +19% at 25 cm and are not used.
- All tape data is from two gyms and three photos.

#### Context for the next session
- `epic_wall_2.jpg` and `epic_wall.jpg` are the same photo. `panels.json` has outlines only under `epic_wall`; the same outlines apply to `epic_wall_2` if ever needed.
- Scratch scripts are in this session's scratchpad (`holes.py` finds the bolt hole by each label, `probe.py` runs the app and caches bolts), not in the repo.
- `measurements.md` is held until the End row. Its epic_wall "5 bolts across = 1.04 m" still implies 26 cm and needs correcting then.

#### Commit plan (human, 2026-11-13)
- **Nothing is committed yet.** The human commits everything (slices 0 to the end) in one go when the feature is finished. The commit goes on `feat/more-detail-for-LLM-and-output-format`, **not `main`**. Agents still don't commit.
- **Photos:** commit the `.jpeg`/`.jpg` reference photos only. `known_measurements/.gitignore` now ignores `*.heic`; the HEIC originals stay on disk.
- **Docs folder casing, fixed 2026-11-13:**
  - On disk the folder is `docs/`, but git used to track 5 files as `Docs/`, so a plain `git add` would have split it into two folders on Linux.
  - The 5 files (`architecture`, `contributing`, `decisions`, `localhost`, `testing`) were renamed to `docs/` with `git mv -f`. **These renames are staged in the index.**
  - Every `Docs/` reference was changed to `docs/`: README, `backend/Agents.md`, the `detection.py` comment, the `architecture.md` folder diagram and the spec.
  - Use lowercase `docs/` from now on. Before committing, check that `git status` shows no `Docs/` paths.

#### Next slice
- **5e (approved):**
  - Group bolts by their own wall direction before assigning holds (fixes epic_wall P14, which reads 14° as 25–27°).
  - Add a per-hold angle confidence, with no angle when the evidence is thin or the two mirror answers tie.
  - Add a synthetic-wall test of the vote (Tester).
  - Fold in the human's real-phone angle check.
  - Done when P14 is within 10° without regressing the other 18 panels in `eval_angle.py`, and the confidence rule is tested.
- Then slice 7 (speed, 4–5 s), then End.

#### Human
- Reviewed:
- Notes:

---

### 2026-11-09 · `wall_size_hold_distance` · Slice 5d: panel angle (completes slice 5; 5a–5c summarised)

**Agent:** Developer (tests by Tester subagent)
**Status:** Complete in code and tests. The phone-sensor path has not been checked on a real phone yet (the human is doing that). Slice 6 is paused for the human's tape-measured pairs.
**Spec:** `docs/features/wall_size_hold_distance.md` ("Slice 5d: panel angle", "Slice 5d results and contracts", "Accuracy results (epic_wall)", "Slice 5c: confidence tiers"). Detailed logs of 5a–5c: `docs/features/slice_5_split.md`, `docs/features/plan_after_5b.md`.

#### Slice 5 in one place (5a–5c)
- **5a (√2 fix):** `scale._resolve_sqrt2` re-reads a bolt group on the finer grid where a touching group is exactly 2× coarser in metric. Removes the ~40% error where holds hide the centre bolts.
- **5b (panels):** `scale.segment_panels` + one homography per panel; ground truth moved to panel sites. In-panel p95 1.0 / 1.7 / 2.7 / 2.9% on IMG_7500 / 7502 / 7503 / 7504.
- **5c (tiers):** each distance is tier A (bolt grid visible all along) or C (scale borrowed); worker margins A 6%, C 14%, plus 5 cm. **Tier B (hole ellipse) was dropped, approved by the human 2026-11-09**: hole size is not a ruler. IMG_7501 stays `insufficient_bolts`.
- **New reference data:** `IMG_7552` (5 tape pairs, 4 edges) and `epic_wall.jpg` (a second gym wall: 10 outlined panels at 14–31°, bolt square about 26 cm, 6 pairs and 2 lines measured with an iPhone measuring app, so about ±10%). `pairs.json` holds the pairs; `eval_scale.py --tape <spacing_cm>` compares them. epic_wall: in-panel p95 1.8%, cross-seam 0.9% (n=1652); the segmenter finds 3 of the 10 panels (accepted limit, distances unaffected). Tape check: 4 of 6 pairs and the horizontal line match within 11%; pair 2, pair 6 and the vertical line were judged measurement errors.

#### What changed (5d)
- `backend/angle.py` (new): wall angle from the bolt grid's local shape. `plane_normals` gives the two mirror wall normals a local metric allows (pinhole camera, EXIF 35 mm-equivalent focal length, default 26 mm). `consensus_normals` picks the one most of the 50 nearest bolts agree on (within 5°), ties to the overhanging one. `angles_from_normals` = `asin(normal · down)`. `gravity_from_sensor` turns a phone accelerometer reading into a down vector (handles Android and iOS signs; rejects a phone more than 60° from upright). `DEFAULT_PITCH_DEG = 12`, `MARGIN_SENSOR_DEG = 8`, `MARGIN_ASSUMED_DEG = 15`.
- `backend/eval_angle.py` (new, dev only): `uv run python eval_angle.py <photos...> [--pitch N]` scores per-panel angle against panels.json, with the assumed pitch and the back-solved best pitch.
- `backend/scale.py`: `compute_scale(..., gravity=None, focal_35mm=None)`; `scale` gains `angles_deg`, `angle_source` (`"sensor"`/`"assumed"`), `angle_margin_deg` (all null on `insufficient_bolts`; an angle failure is logged and returns nulls, never failing distances). New `select_angles`.
- `backend/main.py`: `/detect` takes an optional `gravity` form field (JSON `[x,y,z]` or `x,y,z`; bad values ignored) and reads EXIF focal length before the EXIF transpose. `/analysis` puts `angles_deg`, `angle_source`, `angle_margin_deg` in `route`.
- `backend/worker.py`: each hold gets `wall_angle_deg` when it has one; a top-level `wall_angle` block `{margin_deg, source, guidance}`; the prompt explains wall angle. A route with no angle fields gives exactly the old payload.
- Mobile: `expo-sensors ~58.0.4` installed (approved). New `hooks/useGravityReading.tsx` (low-passed accelerometer). `CustomCamera.tsx` reads it at the shutter and passes it with the photo; `CameraScreen.tsx` holds it (null for "Use Test Photo"); `PhotoPreview.tsx` sends it to `/detect` and shows `≈N°` above each selected hold; `api/detectHolds.tsx` types and form field. `npx tsc --noEmit` clean.
- Data: `known_measurements/panels.json` gains `epic_wall` (10 red outlines P7–P16); `pairs.json` gains `epic_wall`.
- Tests (Tester): new `tests/test_angle.py` (109 tests) and `tests/test_main_angle.py`; updated `test_main.py`, `test_scale.py`, `test_worker.py`, `test_panels_reference.py` (epic_wall).

#### Test results
- Command: `cd backend && uv run python -m pytest -q -m "not slow"`
- Result: **615 passed, 0 failed, 1 xfailed, 27 deselected (slow)**. The slow epic_wall angle test (simulated 14° pitch, real model) also passes.
- The 13 failures listed in the 5c log did not reproduce: those test files had been updated for the 5c contract on 2026-11-04.
- Against 5d's done-when:
  - **Step 1, angles vs measurements.md (19 panels, 5 walls):** median error **1°** with the true camera tilt (3° at the assumed 12° pitch). Within 10°: **16 of 19 (84%)**, so the proposed 90% bar is **narrowly missed**. Misses: IMG_7503's −26° slab (reads +26°: mirror ambiguity), IMG_7502's sparse 34° panel, epic_wall panel P14 (14° reads 25–27° on a smooth seam). With a level camera the median error is 11–15°; the best-fit pitch was 11–14° on every photo.
  - **Step 2, payload:** met. Hold angle and margin reach the LLM; the worker test checks it.
  - End-to-end on epic_wall with a simulated sensor reading: top holds about 14° (true 14°), lower holds 26–27° (true 25–31°); Android and iOS conventions give identical angles; a flat phone falls back to assumed.

#### Decisions made
- **Per hold, not per panel:** the segmenter merges panels on smooth seams (epic_wall: 3 of 10), so a hold takes its angle from its nearest bolts. (also in spec: yes)
- **Overhang prior:** one photo gives two mirror normals; the overhanging one wins ties. A slab reads as an overhang. Stated in the prompt. (yes)
- **Assumed pitch 12°** when there is no usable sensor reading; margins 8° (sensor) and 15° (assumed), from one person's photos on one phone. (yes)
- **`expo-sensors`** (`Accelerometer`, not `DeviceMotion`, to avoid an iOS motion-permission string); adds no OS floor beyond Expo's own (SDK 57: Android 7+, iOS 16.4+; SDK 58's row not checked). (yes)
- **Angle shown in PhotoPreview and sent to the LLM** (human's choice). (yes)
- **Tier B dropped** (above). (yes)

#### Questions for the human
- Photograph a wall of known angle through the app and compare. This is the only check of the Android/iOS sign handling (`up.y < 0` means gravity convention) and of the margins.
- Go-ahead for two improvements (proposed, not started): (1) group bolts by their own wall direction before assigning holds, which should fix the smooth-seam case; (2) a confidence per hold, returning no angle when evidence is thin or the two mirror answers are equally supported. Also a synthetic-wall test of the vote, which no unit test covers today.
- Slice 6 needs better tape data: real-tape, bolt-to-bolt pairs with a marked photo (`pairs.json` format above).

#### Known issues
- Slabs are read as overhangs; no fix from a single photo (see Questions).
- Wrong angles can come with no warning (the 3 misses above); the margin does not cover them.
- The vote that picks the true normal has no unit test, only `eval_angle.py` and the slow epic_wall test.
- Phone held in landscape or rolled is not handled; the reading is ignored and the assumed tilt used.
- `expo-sensors` on a real phone is untested; no dev build was made.
- All photos are from one gym, mostly one phone (iPhone 14).

#### Context for the next session
- **First thing: ask the human the "Questions for the human" above** (the real-phone angle check result, the go-ahead for the two angle improvements, and the slice 6 tape data), before planning or writing anything. Ask them directly, one at a time if that is easier, and record the answers in the spec.
- `angle.py` imports `scale` lazily inside functions and `scale.py` imports `angle` at the top; keep it that way to avoid a circular import.
- Candidate normals do not depend on gravity, only the final angle and the tie-break do, so `eval_angle.py` scans pitch cheaply.
- No doc other than the spec has been edited for this feature yet except this entry (the human asked to hold `architecture.md`, `testing.md` and `decisions.md` until the feature is complete; the spec's "End" row covers them).
- Scratch scripts (`syn.py`, `syn2.py`, `e2e.py`, `digit.py` for the epic_wall outlines) are in the session scratchpad, not the repo.

#### Next slice
- **Slice 6:** calibrate the 5 cm centroid allowance against tape-measured hold pairs. Blocked on the human's new measurements. Done when the allowance is replaced or confirmed by data, and the spec says which; do not tighten the margin on thin data. After slice 7 (speed), the "End" row updates `architecture.md`, `testing.md` and `decisions.md`.

#### Human
- Reviewed:
- Notes:

---

### 2026-10-19 · `wall_size_hold_distance` · Slice 4: accuracy evaluation + derived LLM margin

**Agent:** Developer (tests by Tester subagent)
**Status:** Complete. IMG_7502 is still over the 7% in-panel target, which you accepted for this slice.
**Spec:** `docs/features/wall_size_hold_distance.md` (new section "Accuracy results", Decisions → "Slice 4 margin", Outputs, slice 7 row)

#### What changed
- `mobile/.../assets/known_measurements/panels.json` (new): panel polygons for IMG_7500 (4 panels), 7502 (2) and 7503 (2), with angles from measurements.md.
  - They were digitised automatically from your Paint outlines: a colour mask on the thin lines, with blob-shaped holds of the same colour removed, then the enclosed regions filled.
  - **Please check them:** overlays are at `C:\Users\samst\AppData\Local\Temp\claude\d--ML-Rock-Climbing-Coach-App-ML-AI-Rock-Climbing-Assistant\cba1aa72-4092-40ba-ad0b-ac2f759ac2a4\scratchpad\IMG_750{0,2,3}_panels.jpg` (temporary).
  - The extractor is `panels.py` in the same scratchpad, not in the repo.
- `backend/eval_scale.py`: `--accuracy` now also prints:
  - in-panel error, using panels.json
  - error by distance band
  - reach-range error (1.5–12.5 units, about 30–250 cm)
  - a `SUMMARY` block across photos (pooled with equal weight per photo, plus the worst photo). The margin is derived from this.
- `backend/worker.py`:
  - The `DISTANCE_MARGIN_PCT = 10` placeholder becomes `6`, derived from the data, plus a new `CENTROID_ALLOWANCE_CM = 5`.
  - Each `distances_cm` entry gains `margin_cm` = cm × 6% + 5 cm, computed from the rounded cm.
  - The `accuracy` block gains `centroid_allowance_cm`. Its guidance states both numbers and the benefit-of-the-doubt rule. The wall length gets the 6% only.
  - The system prompt tells the LLM to use each pair's `margin_cm` as the threshold.
- Tests (Tester): `backend/test_worker.py` is updated to the new contract and gains margin text, formula, rescaling and prompt checks. New `backend/test_panels_reference.py` checks panels.json validity and the angles against measurements.md.
- `mobile/.../components/CameraScreen.tsx`: "Use Test Photo" now loads `assets/known_measurements/IMG_7504.jpeg` (full res, no drawn outlines) instead of the 640×640 dataset image, so distances show on the test path. The old image is no longer referenced but I left it in `assets/images/`; delete it if you like. `npx tsc --noEmit` is clean.
- Spec: Outputs (payload shape), Reference data (panels.json), new "Accuracy results" table, slice 4 decisions, a new **slice 7 (performance)** row, and the upload-resolution open question resolved.

#### Test results
- Command: `cd backend && uv run python -m pytest -q`
- Result: **321 passed, 2 failed, 5 xfailed**.
  - The 2 failures are the known `test_scale.py::test_reference_photo_held_out_bolt_pairs_p95[IMG_7502/IMG_7503]` (10.2% / 8.3% vs 7%). That test scores all same-patch pairs, not in-panel pairs. It is unchanged.
- `uv run python eval_scale.py <IMG_750?.jpeg> --accuracy`, in-panel reach-range p95:

  | Photo | p95 |
  |---|---|
  | 7500 | 1.2% |
  | 7502 | 12.6% |
  | 7503 | 2.7% |
  | 7504 | 5.9% (no outlines, so same-patch pairs) |

  Pooled p95 is **5.2%**, which gives the 6% margin.
- Against the slice 4 done-when:
  - numbers recorded in the spec: met
  - worker test checks the margin text: met
  - AC5 (derived margin, benefit of the doubt): met
- Scoring by panel changes the picture from slice 3. **IMG_7503 drops from 8.2% to 2.7% in-panel**, so its slice 3 miss was mostly cross-panel pairs. 7502 stays high because its 34° panel covers most of the photo and is sparsely fitted.

#### Decisions made
- **Margin = pooled reach-range in-panel p95, rounded up (6%), plus a 5 cm centroid allowance.** I didn't use the worst photo (12.6%), which would make every wall twice as lenient to cover one sparse wall. Per-photo and per-tier margins are slice 5. (recorded in spec: yes)
- **`margin_cm` is precomputed per pair,** so the LLM doesn't do arithmetic. The change is additive to the `distances_cm` shape. (recorded in spec: yes)
- **Optimisation is planned as slice 7**: the latency and N×N payload size, as you asked in slice 3 Q4. (recorded in spec: yes)

#### Questions for the human
1. **Panel outlines:** check the three overlays above. On IMG_7500, the red volume enclosed by the green and yellow lines was left out as "not a panel". Is that right? IMG_7504 has no outlines (measurements.md lists red 23° / yellow 13°). Could you draw them on IMG_7504.jpeg if you want it scored per panel? I have drawn the sections 
2. **Margin choice:** OK with the pooled 6% + 5 cm, or would you rather be more lenient with the worst photo's 13% + 5 cm until slice 5 brings per-photo margins? It is a one-constant change. Dont understand, i trust you to make thge best decisions
3. **Tester's Q1, asked again in plain terms:** your walls have a bolt in the middle of each 20 cm square. If a big patch of those middle bolts is hidden by holds (roughly 6×8 squares or more), or a wall edge only shows the corner bolts, the app can mistake the square's 14 cm diagonal for its 20 cm side, and those distances come out about 40% off. Do you want the app to handle this every time (a must-pass test, possibly costing slice 5 time), or is it acceptable as a rare known failure for now? This must be fixed, being 40% off is unacceptable find a work arounf
4. **Slice 7 latency target:** `/detect` takes about 7–8 s on a 12 MP photo today. What target do you want, e.g. 4 s? lets try for 4-5s but if we can optimise to faster with minimal drawbacks do this
5. **Your slice 3 Q5 note ("no bolt holes found" on the test image):** this is expected. "Use Test Photo" loads a 640×640 dataset image. At that size the bolt holes are only a few pixels wide and blurred by compression: of 86 blob candidates outside holds, only 22 pass the contrast check, and those are too few and too scattered to form the evenly spaced lines the lattice filter needs, so 0 bolts survive (0 even with the 5 px floor removed). Real camera shots use the largest picture size (`CustomCamera.tsx`), so they keep the resolution. To check distances on a device, take a real photo of a wall. **Done after your go-ahead:** "Use Test Photo" now uses full-res IMG_7504 (backend run: 211 bolts, status ok, wall 19.4 units ≈ 3.9 m). Please check on the device that labelled lines appear between picks. A downscaled copy wasn't possible (see Known issues). Solved

#### Known issues
- IMG_7502 has an in-panel p95 of 12.6%, above the margin. Distances on sparse plywood walls can be off by more than the 6% given to the LLM.
- **Bolt detection needs near-camera resolution.** Downscaled to 1500 px tall, IMG_7500 and IMG_7504 find 0 bolts. At 2000 px they find 106 and 43, with the wall length about half the true value. IMG_7504 is still wrong at 2400 px (8.6 vs 19.4 units) and fine at 3200. Any future upload resizing or compression in the app would silently break distances. Slice 7 should keep this in mind, and possibly add a resolution check that returns `insufficient_bolts` with a clearer reason.
- The 5 cm centroid allowance is still a guess until there are tape measurements (slice 6).
- Pairs under 30 cm have a relative error of up to 60% on 7502. The fixed 5 cm allowance covers most of that, since 60% of 10 cm is 6 cm.
- Earlier issues still stand: IMG_7501 has 0 bolts, and the latency and payload size are now planned as slice 7.

#### Context for the next session
- `eval_scale.py` loads panels.json by photo stem. Photos without outlines fall back to same-patch pairs in `SUMMARY`.
- The panel extraction needed a mixed-colour ring check (`share` ≥ 0.6). Regions enclosed by two panels' lines, like the IMG_7500 volume, otherwise come out as fake panels.
- To re-derive the margin after any fit change, run `eval_scale.py --accuracy` on all reference photos and read the `SUMMARY` "pooled" p95. Then update `worker.DISTANCE_MARGIN_PCT`, the spec's Accuracy results table, and `test_worker.test_derived_margin_constants` (owned by the Tester).

#### Next slice
- Slice 5: panel segmentation, a homography per panel, the fallback ladder (A lattice / B hole ellipse / C borrowed), cross-seam distances, and per-tier margins. Done when IMG_7501 gives a scale for every panel, cross-seam bolt pairs are within margin, and every distance has a tier. panels.json is now the ground truth for the segmentation.

#### Human
- Reviewed:
- Notes:

---

### 2026-10-16 · `wall_size_hold_distance` · Slice 3: lattice fit, real distances, wall length (+ EXIF fix, slice 1/2 answers)

**Agent:** Developer (tests by Tester subagent)
**Status:** Partial. Real distances replace the stub and are good on synthetic walls and on IMG_7500/7504. IMG_7502/7503 miss the 7% target.
**Spec:** `docs/features/wall_size_hold_distance.md` (Decisions → "Slice 3 lattice + distances", "EXIF orientation")

#### What changed
- **Slice 1/2 answers applied:**
  - `backend/main.py`: an **empty** `bolt_spacing_cm` returns 422 "No bolt spacing provided." A missing field still defaults to 20. The value is read from the raw form, because FastAPI turns an empty value into the default.
  - `mobile/.../components/SettingsButton.tsx` (new): the ⚙ button. CameraScreen renders it and `SettingsModal` once, over both the camera and PhotoPreview, so the spacing can be changed from PhotoPreview and the labels update live.
  - The bolt spacing minimum is **raised to 10 cm**, in `main.MIN_BOLT_SPACING_CM`, `utils/boltSpacing.ts` and the spec. A spacing of 5–9 cm already saved on a phone falls back to the default 20.
  - Prettier: `PhotoPreview.tsx` was formatted with `--end-of-line crlf`, so only real style fixes changed. The other two files flagged in slice 1 already pass once CRLF is allowed.
  - Tester: `wall_length_cm` is checked exactly, and the regularity test counts the √2 and 2× lattice distances as regular.
- **`backend/scale.py`, rewritten:**
  - `fit_lattice` produces a per-bolt local Jacobian J (px per grid unit), fitted from neighbour vectors pooled over the 5 nearest bolts.
  - The basis is chosen among candidates and resolved jointly with the neighbours. Three readings can each look right locally:
    - a sheared basis
    - the √2 "diagonal vs square side" reading where centre bolts are hidden
    - a finer lattice that explains a false detection
  - An off-lattice removal pass runs, then the fit is redone.
  - `segment_lengths` integrates the metric M = J⁻ᵀJ⁻¹ along each segment at 16 samples. M is interpolated by inverse-square weights over the 6 nearest bolts, so it is invariant to the lattice's symmetries.
  - `wall_length_units`: top bolt to bottom bolt in a ±4-spacing band around the median x, plus 0.5 units at each end.
  - `index_lattice`: integer lattice coordinates per patch, by BFS. It's the ground truth for evaluation.
  - `compute_scale` returns `insufficient_bolts` when no bolt fits.
  - `bolts._knn` is renamed `bolts.knn` (public, shared).
- `backend/main.py`: `/detect` applies `ImageOps.exif_transpose` before YOLO and bolt detection.
- `backend/eval_scale.py`: `--accuracy` prints the lattice/patch/wall summary, leave-own-J-out held-out error (overall, top 40% and bottom 40%), and strict k-fold refit error.
- **Tests (Tester):**
  - `test_scale.py` rewritten: synthetic centred-square lattices under scale, rotation, foreshortening and homography, plus jitter, 30–40% hidden bolts, √2 regions, spurious points, invariances, wall length and `index_lattice`, plus slow held-out tests on the reference photos.
  - `test_main.py` gains EXIF tests and lattice-based fake bolts.

#### Test results
- Command: `cd backend && uv run python -m pytest -q`
- Result: **301 passed, 2 failed, 5 xfailed**.
  - Failing: `test_reference_photo_held_out_bolt_pairs_p95[IMG_7502]` (p95 10.2%) and `[IMG_7503]` (8.3%), against a 7% bar.
  - xfail: IMG_7501, plus large or edge regions with no centre bolts (Tester's Q1 below).
- The Tester's first run caught a real defect: 1% spurious points pushed p95 to 15–17%. The cause was a finer-lattice fit winning near false detections. That is now fixed (synthetic error about 1e-15), with no regression elsewhere.
- Real photos, from `uv run python eval_scale.py <photos> --accuracy`:

  | Photo | Fitted bolts | Patches | Wall length | Leave-own-J-out p95 | Strict refit p95 | Tester slow p95 |
  |---|---|---|---|---|---|---|
  | IMG_7500 | 332/346 | 3 | 26.1 u (5.2 m @ 20 cm) | **4.0%** | 4.8% | 3.9% ✅ |
  | IMG_7502 | 88/116 | 5 | 22.8 u | 12.0% | 12.2% | 10.2% ❌ |
  | IMG_7503 | 150/178 | 10 | 19.3 u | 8.2% | 24.3% | 8.3% ❌ |
  | IMG_7504 | 186/211 | 4 | 19.4 u | **6.1%** | 7.5% | 5.8% ✅ |

  Median (p50) error is 0.4–1.6% everywhere.
- Against the slice 3 done-when:
  - **p95 ≤ 7%:** met on 7500 and 7504, not met on 7502 and 7503.
  - **IMG_7500 6° vs 23° panels:** the top 40% (the 23° panel) gives p95 1.1%. The bottom 40% gives 5.8%, but it mixes the 6° and 14° panels and the side wall. There's no panel ground truth (see questions).
  - The pairs scored are "same patch", not "same panel". Patches now span panel seams, so these numbers include cross-panel pairs, which is harder than the spec's in-panel target.
- Synthetic: a clean homography gives p95 ≈ 1%, and every degraded case is ≤ 7%.

#### Decisions made
- **Interpolate the metric M, not J.** M is invariant to lattice symmetries, so no consistent labelling is needed, and panels whose grids are rotated 45° to each other (seen in IMG_7503) just work. (recorded in spec: yes)
- **Candidate fits plus neighbour consensus,** rather than picking a basis per bolt. Every rule that chose locally failed in some case, as shown in the decision log. (recorded in spec: yes)
- **Accuracy metric:** the headline is "leave-own-J-out", fitting on all bolts and dropping the held-out bolts' own J. That matches how holds are measured. Strict k-fold is reported alongside. (recorded in spec: yes)
- **Wall length band ±4 spacings.** ±1 gave 5.5–25.8 u on IMG_7502 across runs; ±4 is stable. (recorded in spec: yes)
- **EXIF transpose in `/detect`.** (recorded in spec: yes)
- **Tried and reverted:**
  - a smooth spacing-field filter
  - per-bolt "most square" or "coarsest" tie-breaks, each of which broke √2 or hidden-bolt cases

#### Questions for the human
1. **Panel ground truth.** The done-when says "in-panel" pairs and "IMG_7500's 6° and 23° panels", but nothing machine-readable says which pixels belong to which panel. Could you export the coloured outlines from your annotated photos as polygons, or should I digitise them from the images and you check them? With panels, I could score in-panel pairs as the spec intends, and slice 5 needs them anyway. A = confused on this, in paint i drew polygons with coloured outlines to denote the sections - let me know if you need anything further
2. **Target on sparse plywood walls.** 7502 and 7503 are at 8–12% p95, with p50 around 1%. Do you want me to keep pushing that in slice 4, or accept it and let slice 4's margin reflect the measured accuracy, which is what slice 4 is for? fine for slice 4
3. **Tester's Q1:** should √2 regions with no centre bolts across 6×8+ squares, or along a wall edge, be hard requirements? They're currently xfail. dont understand use normal language to ask me this question again
4. **`/detect` latency** is now about 7–8 s on a 12 MP photo: YOLO 1–2.6 s, bolts 0.6–2 s, scale 1.9–3.3 s. Acceptable for now, or should I optimise (the scale fit is pure-Python loops) before slice 4? save optimisation for later slices, make sure htis is planned in
5. **EXIF fix:** check on a device that taps still land on the right holds. If expo-camera already writes upright pixels, nothing changes; if it writes an EXIF rotation, this fixes a sideways mismatch. in test image "no bolt holes found - distances unavailable for this photo" error, hold detectio okay though.

#### Known issues
- IMG_7502/7503 are over 7% p95 (above).
- The `/detect` response carries an N×N matrix of about 240–340 KB for about 200 holds.
- Hold centroids sit in front of the wall surface; that allowance is slice 4.
- The IMG_7501 close-up still has 0 bolts (slice 5).
- `index_lattice` ground truth can carry one-step slips. About a quarter of the large-error pairs match a one-step-off lattice distance, though some of that could be chance.

#### Context for the next session
- Tuning scripts are in the scratchpad (`sweep.py`, `tail.py`, `gtcheck.py`, `spur_dbg.py`, `drawJ.py`), not the repo. `drawJ.py` (fitted diagonals per bolt) is the most useful view of fit quality. The cached bolts are `<scratchpad>/ref/*.bolts.json`.
- Order in `_fit_candidates` matters: the occupancy filter has to come before squareness, or finer lattices win. `COUNT_FRACTION` 0.8 breaks the spurious-point case, and coarsest-first breaks √2 regions.
- The worker and mobile code didn't need changes; they only see grid units and cm.

#### Next slice
- Slice 4: accuracy evaluation. Record `eval_scale.py` numbers in the spec, and derive the LLM margin (p95 held-out error plus a centroid allowance, starting at 5 cm) to replace the 10% placeholder. The worker test checks the margin text. Ideally this follows the answer to Q1 (panels) and Q2 (target).

#### Human
- Reviewed:
- Notes:

---

### 2026-10-16 · `wall_size_hold_distance` · Slice 2: real bolt-hole detection + debug overlay

**Agent:** Developer (tests by Tester subagent)
**Status:** Partial. Detection works on 4 of 5 photos. 2 slow reference tests fail on a metric question for you (below). IMG_7501 is deferred.
**Spec:** `docs/features/wall_size_hold_distance.md` (Decisions → "Slice 2 bolt detection")

#### What changed
- `backend/bolts.py` (new): `detect_bolt_holes(image, detections) -> [{x, y, diameter}]`, built only on OpenCV and numpy with no new dependencies.
  - **Candidates:** `SimpleBlobDetector` on CLAHE grey at pyramid levels ×1, ×2 and ×4, de-duplicated with a KNN pass.
  - **Filters:** a candidate is dropped if it's inside a HOLD/VOLUME polygon, has raw-grey contrast below 0.3, or has a half-depth diameter below 5 px.
  - **Lattice support:** a candidate is kept only if it sits in an evenly spaced line of similar-sized blobs along ≥ 2 directions. Size-banded neighbour search keeps speckle from crowding out bolts.
  - **Spacing filters:** a bolt is dropped if its nearest neighbour is under 0.7× the local median spacing, or under 5× its own diameter.
  - **Grow:** rejected candidates are re-admitted if they line up with accepted bolts along 2 directions, or along 1 direction on the anchor's own grid step.
  - **Neighbour search:** exact brute force through `cv2.BFMatcher`. scipy isn't installed and I didn't add it.
- `backend/scale.py`: the signature is now `compute_scale(detections, image_size, bolts)`. With no bolts it returns `insufficient_bolts` with null distances and wall length; otherwise `bolt_count = len(bolts)`. **Distances are still the slice 1 stub.**
- `backend/main.py`: `/detect` runs `bolts.detect_bolt_holes` on the full-res image, in the same un-rotated orientation YOLO sees, then `compute_scale`. A failure in either returns 500 and caches nothing.
- `backend/eval_scale.py` (new, dev only): runs YOLO and bolt detection on photos and saves overlays (green = bolt, grey = hold mask, `--candidates` shows rejected blobs in red) to `<temp>/eval_scale` by default. It prints bolt count, spacing stats and timings.
- `mobile/.../components/PhotoPreview.tsx`: shows the hint "No bolt holes found - distances unavailable for this photo" when `scale.status === 'insufficient_bolts'`.
- Tests (Tester):
  - new `backend/test_bolts.py`: synthetic lattices for recall, speckle, gradient, rotation, foreshortening, contrast, polygon masking and resolution, plus `slow` reference-photo tests
  - `test_scale.py` and `test_main.py` updated for the new contract
- `docs/features/wall_size_hold_distance.md`: decision block for slice 2.

#### Test results
- Command: `cd backend && uv run python -m pytest -q`
- Result: **200 passed, 2 failed, 1 xfailed**. Slow tests run by default.
  - Failing: `test_reference_photo_bolt_count_and_spacing_regularity[IMG_7502.jpeg]` (regular spacing 70% vs the 75% bar) and `[IMG_7503.jpeg]` (73%).
  - xfail: IMG_7501.
- The Tester's first run failed 3 synthetic tests: illumination gradient (recall 0.24–0.55) and foreshortening (0.85). Those were real detector bugs, not test problems. The blob detector inflates hole size up to 1.7× under uneven light, which broke the spacing/diameter check. I fixed it with the half-depth diameter, and all synthetic tests now pass.
- Overlays: `C:\Users\samst\AppData\Local\Temp\claude\d--ML-Rock-Climbing-Coach-App-ML-AI-Rock-Climbing-Assistant\9ad2a9f4-bb70-4738-8904-72f956d850ff\scratchpad\eval\IMG_750{0..4}_bolts.jpg` (temporary). Regenerate them with `uv run python eval_scale.py ../mobile/ML-Rock-Climbing-App/assets/known_measurements/*.jpeg`.
- Against the slice 2 done-when:

  | Photo | Bolts | Strict regular (Tester's metric) | Regular counting √2/2× | Bolt-detection time |
  |---|---|---|---|---|
  | IMG_7500 | 346 | 90% | 96% | 1.6 s |
  | IMG_7502 | 116 | 66–70% | 91% | 0.7 s |
  | IMG_7503 | 178 | 67–73% | 88% | 0.7 s |
  | IMG_7504 | 211 | 78–81% | 94% | 0.6 s |
  | IMG_7501 | 0 | n/a | n/a | 2.1 s |

  The √2/2× column uses my own scoring script, so its numbers differ slightly from the Tester's.
  - **IMG_7500: met.** A clean grid on all 4 panels with no visible false positives.
  - **IMG_7501: not met.** See Known issues.

#### Decisions made
- Lattice regularity, not size, separates bolts from speckle and grain. Speckle outnumbers bolts 10–20× and hole size changes 10× across photos. (recorded in spec: yes)
- Diameter is measured at half depth, not with the blob detector's size, because the latter is unreliable under gradients. (recorded in spec: yes)
- A 5 px minimum hole diameter. It removes paint-speckle clumps, at the cost of bolts on distant background walls. (recorded in spec: yes)
- I tried a smooth spacing-field fit to reject clumps and reverted it, because it removed real bolts in the dense bottom of IMG_7503.

#### Questions for the human
1. **Regularity metric (Tester's Q1):** the two failing tests count a bolt as regular only if its nearest neighbour is within ±15% of the local median. In 7502 and 7503 the "irregular" bolts are real ones whose diagonal neighbours are hidden by holds, so their nearest neighbour sits at the √2 or 2× grid distance (checked on the overlays). Counting those distances as on-grid gives 88–96%. **I recommend telling the Tester to accept those distances.** I haven't edited the tests. Tester accept this 
2. **IMG_7501:** OK to keep deferring it to slice 5, as the spec plans? OK
3. **Grid assumption:** the spacing ≥ 5× hole diameter prior assumes a grid of about 12 cm or wider. The settings allow 5–50 cm. Should the setting minimum be raised to about 10 cm, or is 5 cm a real case? 10cm
4. **EXIF orientation (existing issue, out of scope):** `/detect` doesn't apply EXIF rotation, and nor does ultralytics for PIL input. A phone photo with orientation 6 (like IMG_7501) is processed sideways relative to how the app shows it, so tap matching and distances could be off. Worth checking what expo-camera uploads. Should I open this as a separate fix? Fix this in the next slice
5. Slice 1 questions still open: empty `bolt_spacing_cm`, the settings button on PhotoPreview, and Prettier on CRLF files. Answered

#### Known issues
- **IMG_7501 finds 0 bolts:**
  - it's a close-up where most holes are metal-filled (grey, not dark)
  - YOLO masks only 12 holds there, so volume texture leaks in as candidates
  - each misaligned panel shows only 3–5 holes, so the line test can't fire
  - This needs the slice 5 fallback (tier B, hole ellipse). With `insufficient_bolts`, the app shows no labels plus the hint.
- Recall is weaker in hold-dense areas (middle of 7502, left of 7504) because holds hide one of a bolt's two lines. Slice 3's lattice fit can predict and verify the hidden positions.
- Bolts on distant background walls (side wall in 7500, back wall in 7503) are partly detected. Slice 5's panel segmentation should exclude them.
- Bolt detection adds 0.6–2.1 s to `/detect` on 12 MP photos, on top of YOLO's 1–2.6 s.
- The tuning comes from 5 photos taken at one gym. Expect to retune on other gyms (brick-effect or painted walls, different hole finishes).

#### Context for the next session
- `bolts._candidates`, `_measure`, `_lattice_filter` and `_line_hits` are private, but `eval_scale.py --candidates` uses `_candidates`.
- `bolts` returns diameter in full-res px and normalized x, y. Slice 3's `fit_lattice` should convert to pixels with `image.size`.
- The lattice is a centred square: nearest neighbours are diagonal at s/√2, and the square side s is at √2·nn. Watch for this in slice 3's fit.
- Scratch scripts used for tuning (`stages.py`, `irreg.py`, `shell.py`, `why.py`) are in the session scratchpad only, not the repo.

#### Next slice
- Slice 3: `fit_lattice` plus a local Jacobian field and segment integration to replace the stub distances, and real wall length. Done when held-out in-panel bolt pairs reach p95 ≤ 7%, and IMG_7500's 6° and 23° panels give consistent scale after correction.

#### Human
- Reviewed: 16/10
- Notes:NA

---

### 2026-10-16 · `wall_size_hold_distance` · Slice 1: walking skeleton

**Agent:** Developer (tests by Tester subagent)
**Status:** Complete. The backend is tested; the on-device check is still to be done by the human.
**Spec:** `docs/features/wall_size_hold_distance.md`

#### What changed
- `backend/scale.py` (new): `compute_scale(detections, image_size)` is the **stub**. It treats the photo height as `STUB_PHOTO_HEIGHT_UNITS = 20` and returns the aspect-corrected Euclidean N×N `distances_units`, rounded to 3 decimals. `select_distances(scale, detections, hold_ids)` returns the sub-matrix in pick order.
- `backend/detection.py`: `select_holds` now returns a flat `[{id, class_name, x, y}]` list in pick order. It used to return a dict grouped by class without ids.
- `backend/main.py`:
  - `/detect` computes the scale from the full-res `image.size`. It caches `detections:{id}` and `scale:{id}` in one pipeline transaction and returns `scale`. A scale error returns 500.
  - `/analysis` takes an optional form field `bolt_spacing_cm`: default 20, valid range [5, 50], anything else (including non-finite values) returns 422 before Redis is touched. It reads both keys with `mget` (either missing returns 410) and enqueues `route` = {holds, distances_units, wall_length_units, bolt_spacing_cm}.
- `backend/worker.py`:
  - `build_route_data(route)` converts units to cm (1 decimal) and builds `distances_cm` as `[{from, to, cm}]`, one entry per unique pair. It also adds `wall_length_cm` and an `accuracy` block.
  - `DISTANCE_MARGIN_PCT = 10` is a placeholder.
  - The system prompt now explains the distances, the wall length and the benefit-of-the-doubt margin.
  - `build_coaching_payload` and `analysis` now take `route`.
- `mobile/.../utils/boltSpacing.ts` (new): the storage key, the default and range constants (kept in sync with main.py), `parseBoltSpacing`, and `formatDistance` (cm below 1 m, otherwise m to 1 decimal).
- `mobile/.../hooks/useBoltSpacing.tsx` (new): bolt spacing persisted in AsyncStorage (`boltSpacingCm`). A missing or corrupt stored value falls back to 20.
- `mobile/.../components/SettingsModal.tsx` (new): a full-screen Modal with a ScrollView and a bolt spacing input that is validated as you type. The form mounts only while the modal is open, so an unsaved draft is dropped when it closes.
- `mobile/.../components/CameraScreen.tsx`: a ⚙ button at the top right opens the settings. CameraScreen owns `boltSpacingCm` and passes it to PhotoPreview.
- `mobile/.../components/PhotoPreview.tsx`: draws yellow SVG lines between consecutive picks, each with a cm/m label at its midpoint. The label is white with a black outline, made from two `SvgText` passes because react-native-svg has no `paintOrder`. The label is recomputed from `boltSpacingCm` and has no label when the distances are null.
- `mobile/.../api/detectHolds.tsx`: new `Scale` type on `DetectHoldsResponse`. `api/climbAnalysis.tsx` sends `bolt_spacing_cm`.
- `mobile/.../package.json`: `@react-native-async-storage/async-storage` 2.2.0, installed with `npx expo install` (approved in the spec).
- Tests (Tester): new `backend/test_scale.py`. `conftest.py` gains a `sample_scale` fixture and seeds the `scale:` key. `test_main.py`, `test_worker.py`, `test_detection.py` and `test_concurrency.py` were rewritten for the new contracts.
- `docs/features/wall_size_hold_distance.md`: slice 1 contracts added under Decisions.

#### Test results
- Command: `cd backend && uv run python -m pytest -q`
- Result: 142 passed, 0 failed. Before the Tester's rewrite it was 19 failed and 61 passed, all failures from old contracts.
- Mobile: `npx tsc --noEmit` is clean. `npx expo lint` shows no new errors. The 2 errors it does show already existed: `useTestPhoto` "hook in callback" in CameraScreen.tsx:53 and ModeSlider.tsx:67 "refs during render".
- Against acceptance criteria:
  - #4 (all-pairs `distances_cm`, N(N-1)/2) is met.
  - #5 (accuracy block and prompt) is met with the placeholder 10%.
  - #6 is met on the backend. The UI is not tested because there is no JS test runner.
  - #1 and #2 are stubs only.
  - #3 needs the on-device check.
  - "Rescale without re-running detection" is met: one `/detect` followed by `/analysis` at 10 cm and at 40 cm gives 4× distances.

#### Decisions made
- `select_holds` returns a flat list in pick order: it keeps the ids, and the LLM sees the same order as the drawn lines. (recorded in spec: yes)
- Scale is stored under a separate `scale:{id}` Redis key in the same transaction, so the `detections:` contract stays as it was. (recorded in spec: yes)
- The `/analysis` → worker contract is in grid units, and cm conversion happens in the worker, following the "backend in grid units" decision. (recorded in spec: yes)

#### Questions for the human
- Should `wall_length_cm` be rounded to 1 decimal, like `distances_cm`? It already is: `_to_cm` rounds both, but the Tester asserts it only approximately. A = round to 1
- Should an empty `bolt_spacing_cm=""` from a client mean "use the default" or return 422? Right now FastAPI decides, and that case is untested. if bolt spacing is empty return 422 with error no bolt spacing provided
- The settings button is only on the camera screen, so the spacing can't be changed from PhotoPreview. Do you want it there too? The labels already rescale live. Add in PhotoPreview
- Prettier reports `PhotoPreview.tsx`, `climbAnalysis.tsx` and `detectHolds.tsx` as unformatted. These existing files use CRLF line endings, so `prettier --write` would rewrite whole files. I left them alone; run `npm run format` yourself if you want it. you make the correct decision here

#### Known issues
- **Stub scale:** the photo height is always 20 grid units (400 cm at the default spacing), so displayed distances are not real yet. Slices 2–3 replace this.
- The stub returns `status: "ok"` with `bolt_count: 0`, which contradicts the spec's meaning of `insufficient_bolts`. The client doesn't branch on either field yet. Slice 2/3 tests will change this.
- Detections cached before this deploy have no `scale:` key, so they return 410 and the user has to retake. The cache TTL is 1 h, so this clears quickly.
- Label font size is a fixed 14 px in image space, so labels grow when zoomed in and can overlap on short segments.
- AsyncStorage is a native module, so a dev client must be rebuilt (Expo Go already includes it).

#### Context for the next session
- `distances_units` rows and columns follow the order of the `detections` array. PhotoPreview maps id → index through `indexById` and doesn't assume id == index.
- `run_detection` thumbnails the image to 1024 px. `/detect` passes the full-res `image.size` to `compute_scale`. In slice 2, `detect_bolt_holes` needs the full-res PIL `image` too, so change the `compute_scale` signature to take the image rather than only its size. The Tester's `test_scale.py` pins `compute_scale(detections, image_size)` and will need updating.
- The `/detect` cache-failure test patches the pipeline class's `execute`. Keep the pipeline write, or tell the Tester.

#### Next slice
- Slice 2: implement a real `detect_bolt_holes` (OpenCV CLAHE + `SimpleBlobDetector` on the full-res image, with blobs inside HOLD/VOLUME polygons dropped) and add a `backend/eval_scale.py` debug overlay. Done when the IMG_7500/7501 overlays show most visible holes with few false positives and the Tester's count and spacing-regularity tests pass. Also check the phone upload resolution, which is an open question in the spec.

#### Human
- Reviewed: 16/10
- Notes: NA

---

### 2026-10-16 · `wall_size_hold_distance` · Slice 0: spec and agent setup

**Agent:** Developer
**Status:** Complete (pending human approval of the spec)
**Spec:** `docs/features/wall_size_hold_distance.md`

#### What changed
- `docs/features/wall_size_hold_distance.md`: filled in the title, the `scale` output shape, measurable targets, reference-data ground truth, slices 0–6, decisions, rejected alternatives, and open questions.
- `.claude/agents/tester.md`: new. The Tester writes tests from the spec only and owns the `backend/test_*.py` files.
- `.claude/agents/reviewer.md`: new. Read-only reviewer that produces a list of concerns.

#### Test results
- Command: none (docs-only slice)
- Result: n/a
- Against acceptance criteria: n/a

#### Decisions made
- OpenCV bolt detection, local Jacobian scale field, grid units on the backend, AsyncStorage, consecutive-pick lines, bolt-grid-only accuracy for now (recorded in spec: yes).
- Lattice nearest neighbours are diagonal at spacing/√2 (recorded in spec: yes).

#### Questions for the human
- Test command: add `npm run pytest`, or correct Agents.MD to `cd backend && uv run python -m pytest`?
- HEIC reference images: declare `pi_heif`, or convert IMG_7502–7504 to JPEG?
- Accept the p90 ≤ 10% in-panel target?
- `.claude/settings.local.json` allows `Bash(git push *)`, which conflicts with Agents.MD's "human only" source control rule. Remove it?

#### Known issues
- None yet. No code has changed.

#### Context for the next session
- `run_detection` thumbnails the image to 1024 px and returns normalized coordinates. Bolt detection must use the full-res image in `/detect`.
- `select_holds` drops hold ids. Slice 1 needs ids kept so the worker can label distances.
- No JS test runner exists, so all distance maths lives in Python.
- `test_worker.py::test_payload_groups_holds_as_xy_objects_in_user_content` will break in slice 1. The Tester rewrites it.

#### Next slice
- Slice 1, the walking skeleton (see spec). Done when tapping 3 holds on a device shows labelled lines, the LLM payload has `distances_cm`, and pytest is green.

#### Human
- Reviewed: 16/10
- Notes: NA