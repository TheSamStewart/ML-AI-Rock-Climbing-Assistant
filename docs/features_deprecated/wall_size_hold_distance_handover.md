# Handover: wall size and hold distance

> **Archived 2026-11-26.** The project moved to milestone → issue → slice docs (`docs/docs.md`). Open work from this file is now in GitHub issues #36–#40, #49 and #50, with docs in `docs/milestones/v0.2/`. The parked hold-type plan moved to `docs/milestones/v0.2/milestone.md`. This file is history: don't add to it.

The one place for slice status, open questions and what happened in each slice. The spec (`wall_size_hold_distance.md`) holds the contracts, decisions and accuracy tables. The volume retrain side task has its own doc (`volume_retrain.md`).

Compiled on 2026-11-24 from four older files (`handover_wall_size_hold_distance.md`, `slice_5_split.md`, `plan_after_5b.md`, and the logs in the spec). Their full text is in git history (commit `Wall size / hold distance: slices 1-11 snapshot`).

---

## Overview (for the human)

**What the feature does.** It uses the grid of bolt holes on a climbing wall as a ruler. From one photo it measures the distance between holds, the wall's length and the steepness under each hold. It sends all of that, with honest error margins, to the coaching AI.

**Where we are.** Slices 1–10, 12, 13 and 15 part 2 are done and work end to end. Slices 11 and 14 (volumes) and 15 part 1 wait on data. **Next is slice 16, planned with you.**

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
| 11 | 6b steps 1–2 | Volumes: can we measure a volume face's angle? | ⏸ Parked 2026-11-25: one-photo no-go; two-photo sound on synthetic walls but not on real photos, and 3 photos is too much to ask |
| 12 | 5e | Wall-angle fixes, field replay script, slab check | ✅ Done (two data questions for you, below) |
| 13 | 7 | Speed: server time halved; a 4× smaller upload awaits your OK | ✅ Done |
| 14 | 6b step 3 | Volumes, finish: holds on volumes (face angles dropped 2026-11-25, see slice 11) | ⏸ Blocked: needs the volume retrain only |
| 15 | 8 | More coaching info: move up/across in cm, angle change, height + arm span ✅; volume items blocked on 14 | ✅ Part 2 done |
| **16** | 9 | **Planned with you:** reference angles fixed ✅, smaller photos ✅, wall-length message ✅, wall-length fix ✅, bolt pattern setting ✅ | **▶ In progress** |
| 17 | End | Final docs write-up | To do |
| 18 | new | **Fable review** of all the work (see below) | To do |
| — | new | **Volume scan test feature** (`volume_scan.md`): photo + sideways burst → every face's angle on screen | ▶ Built 2026-11-25, awaiting the gym trial |

**Order:** 16 → (14 and 15 part 1 when the volume data exists) → 17 → 18. 12, 13 and 15 part 2 done 2026-11-24.
- 12 goes before 13 because both rewrite `scale.py` and `angle.py`. Speeding up code that is about to change wastes the work.
- 12 also rebuilds the field replay script, which every later slice uses to prove nothing got worse.
- 16 exists because 14 and 15 add work to each photo after 13 has made it fast.

**Needs from you:**
1. **Slab photos** (coming). For each: the wall angle, a few tape distances, and the phone's tilt when the photo was taken (you're capturing on your laptop). More detail under slice 12.
2. **Measured volumes: ON HOLD** (volume face angles parked 2026-11-25; don't collect unless that changes). 5 arrived 2026-11-25 (`backend/field_captures_volumes/`). About 10–20 more are still wanted, including a slab and an overhang wall, 2–3 tape distances per volume from a hold on the volume to a hold on the plain wall, and bolt holes visible around the volume in photo B. The full list is in the 2026-11-25 slice 11 entry.
3. **Volume retrain data:** unblocks slice 14 (`volume_retrain.md`).

**Answered 2026-11-24:** epic_wall P14 is about 29° and IMG_7503's lower panel is a +26° overhang (reference data corrected); smaller photos approved if no worse (tested and done, slice 16).

---

## Parked plans (read before starting the matching work)

### Hold type: foothold or handhold, crimp / jug / sloper etc. (discussed 2026-11-24)

**Why not retrain YOLO:** the human tried hold types as YOLO classes originally, and the model got easily confused (it has to find holds *and* sort them at once). YOLO already finds the holds, so naming them is a separate, easier job for a vision model.

**Option A (recommended first):** give the existing coaching call the photo, with the picked holds numbered on it (like `field_captures/*/overlay_1.jpg`), plus close-up crops of each picked hold from the full-resolution photo. The prompt asks the coaching model to work out each hold's type.
- No new pipeline step, and under 1p per analysis for the extra image.
- Best context: foothold vs handhold depends on the route and the climber, not the hold alone, and the coaching model already has the route, distances and angles.
- Downside: the types live only inside the coaching answer, so the app can't show them and we can't measure them.

**Option B (if types are wanted in the app or measured):** a separate classifier call before coaching, on Claude Haiku 5.5 ($0.10 / $0.50 per million tokens; about 0.1p per photo, Sonnet 5.5 about 2p).
- One request per photo, with the numbered image plus crops.
- Structured outputs (`output_config.format`, JSON schema) with the type as a fixed list: crimp, jug, sloper, pinch, pocket, edge, volume, other; plus a size.
- The result goes into the worker payload like the other fields.

**Needed either way:**
- **The server doesn't keep the photo** after `/detect` (only detections and scale are cached in Redis), so cache it, or a downscaled copy plus crops, for the same 1 hour, or have the app send it again.
- **Small holds:** in a full-wall image shrunk to about 1,500 px a small crimp is 20–30 px, so send crops of the picked holds.
- **An eval before trusting it:** the human labels the hold types on about 10 field captures; compare Haiku and Sonnet on them (and option A's answers), and only pick Haiku if it holds up.
- Read the `claude-api` skill before writing the calls (current model ids, structured outputs, image inputs).

**Status:** not started; waiting on the human's go-ahead and the labelled captures. Belongs with slice 15 (more coaching information).

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
- **Borderline bolts** (slice 16): on hold-covered walls about 15% of bolts flip in or out with tiny pixel changes. The wall-length rule is fixed; check whether anything else (panel segmentation, tiers) amplifies those flips.
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

**Walls that break the bolt-pattern assumption** (human, 2026-11-24). Fable derives a solution for the patterns the Settings choice doesn't cover. Research and sources are in the slice 16 entry.
- **Rectangular staggered grids** (rows closer than the spacing along a row, e.g. 6" with 3" offsets): today they read as perspective, which skews distances in one direction and the wall angle. Can the fit take a rectangle's aspect ratio, from a setting or estimated?
- **Hexagonal or triangular patterns:** a different lattice altogether.
- **Mixed density:** extra holes between the grid, or 10 cm next to 20 cm panels. The finer-lattice and √2 guards could misread a denser panel. Spacing per panel?
- **Different spacing on different panels in one photo:** one spacing per wall today.
- **Sparse or 3D textured panels with few t-nuts:** what to do when there are too few bolts.
- **Random drilling** fails safely ("no bolt holes found"). Is there any other ruler, e.g. hold size or a user-tapped reference?
- For each: say how a user would select or confirm it, test on synthetic walls (as `fakewall.py` / `test_scale.py` do), and don't regress the current patterns (field replay, reference accuracy).

**The coaching prompt** (`worker.COACHING_SYSTEM_PROMPT` and the user content built in `build_coaching_payload` / `build_route_data`). Fable reviews it and makes any changes that give better coaching output:
- Clarity and order: does the prompt explain each payload field (distances and margins, tiers, wall angle, moves and positions, climber) once, in plain words, without contradictions or leftovers from earlier slices?
- Field names and units in the payload read naturally to the model, and nothing it doesn't need is sent (e.g. photo coordinates now that positions in cm exist).
- Output quality: run the prompt on a few real routes (the field captures make good inputs), and judge the beta for correctness, use of reach and wall angle, and plain language. Compare before and after any change.
- Prompting practice: current Claude prompting guidance (read the `claude-api` skill or docs first, not from memory), the model id and `effort` setting, and the structured-output schema (`COACHING_OUTPUT_SCHEMA`), kept in sync with the app's `ClimbStep` type.
- Changes to the prompt keep the worker tests' contract, or update them with the Tester.

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

### 2026-11-25 (late) · Branch merged to main

**Status:** Complete

**What changed**
- `docs/changes/2026-11-25_wall-size-hold-distance.md` (new): a short human summary of the branch, also used as the PR description.
- At the human's request, Claude committed the branch and merged it into main by PR. This was a one-off, as on 2026-11-24.

**Results**
- The pyramid's slow tests (`-m slow -k s_pyr4_wall0`) gave `3 passed` on the code below, so CI has no known failure.

**Known issues / context for the next session**
- `backend/field_captures_volumes/` is now tracked (43.5 MB, human's choice). `backend/final.txt` is scratch output and left untracked.

**Human:** Reviewed: <yes/no> · Notes:

### 2026-11-25 (night) · Volume scan test feature: slices 1–2 (spec `volume_scan.md`)

**Status:** Built and ready for a gym trial. Slice 3 (the trial) is the human's. Volume face angles were reopened by the human: the degrees are wanted on screen, as a selling point. Standing instruction: never remove the angle display.

**Why this design:**
- The human picked "idea 2", many views from one sweep.
- ARKit/ARCore is out: the app runs in Expo Go, which can't load native AR code.
- Video is out: unknown field of view, stabilisation warp, codec and rotation, and lower resolution.
- So the sweep is a **burst of stills**, taken with the same lens and picture size as the photo.
- **Human idea for later:** make the whole capture one "hold and step" gesture, like a short video, where the first still is the main photo. Not built; the current flow is photo, tap the volume, then "Scan volume faces (test)".

**What changed**
- `docs/features/volume_scan.md` (new spec).
- `backend/volume_scan.py` (new): `scan_volume`.
  - the photo's pose from the bolt grid
  - each burst frame's pose from the photo-to-frame wall homography, decomposed (SIFT + FLANN)
  - a multi-view plane sweep 0–90 cm
  - faces as RANSAC planes, each one compact patch, with outlines
  - depth only when the photo's grid fit is even (axes within 8%), because an uneven fit keeps the angles right but the cm wrong
- `backend/main.py`: `POST /dev/volume-scan` (dev only, no auth, on the Fable list). Every request, failures included, is saved to `backend/field_captures_scans/<scan_id>/`: photo, frames, `scan.json`, and a `volume.json` template for tape angles.
- `backend/experiments/two_photo/synth.py`: `sweep_case()` renders a synthetic photo plus burst with exact truth.
- `backend/tests/test_volume_scan.py` (Tester, 49 tests).
- App (Expo Go, no new dependencies):
  - `components/VolumeScanCamera.tsx` (hold-to-scan burst, 3–12 photos, at most 6 s)
  - `api/volumeScan.tsx`, `hooks/useVolumeScan.tsx`
  - `utils/pictureSize.ts`, shared with `CustomCamera.tsx` (behaviour unchanged)
  - `PhotoPreview.tsx`: the button appears in `__DEV__` once a VOLUME is selected; each face is drawn in its own colour with "+23° ←"; the summary shows the depth, wall angle and scan id
  - Each selected HOLD sitting on a scanned face gets "≈5° · face +23° ←" (wall angle, then the face it's on); `utils/holdMatching.isPointInPolygon` is now exported for this

**Results**
- Synthetic sweeps (6 frames over 60 cm): every frame posed with its spacing exact (10–60 cm).
  - Wedge on a 35° overhang: 3/3 faces within 0.4°, depth exact.
  - Box on a 20° overhang: 2/2 within 0.4°, depth exact.
  - 4-sided pyramid: all 4 faces within 0.8° (+43.3/+43.2, −37.6/−38.3, +0.1/0, +0.3/0), depth 26 vs 30 cm. The down-facing face was missed at first; fixed (see below).
- Time: **about 4 s per scan** on the server (was 9–70 s, see the fixes below).
- Tests: `tests/test_volume_scan.py` gives `48 passed, 1 skipped` (fast and slow). Whole fast suite (before the fixes below, which touch only `volume_scan.py`): `763 passed, 1 skipped, 36 deselected, 1 xfailed`.

**Fixes after the Tester's report** (human chose "fix", 2026-11-25)
- Input-check 422s (bad polygon, bad spacing, more than 20 frames) now save their scan folder, like every other request.
- **The missed pyramid face was a lighting effect.** The down-facing face is the darkest (mean grey 61 against 85–90), so its texture is fewer grey levels, and only 27% of its windows cleared `MIN_STD` = 4. `MIN_STD` is now 2.0. The real guard against noise is `MIN_NCC`/`MIN_GAP`, since noise doesn't correlate between photos. Real undersides will be darker too.
- **Speed.** That gives about 3× more points (100k), which exposed two costs:
  - plane scoring on every point: RANSAC now scores on a 4,000-point sample, then takes the winner's inliers from all points
  - `np.linalg.svd` with full matrices, which built an N×N matrix: now thin SVD
  - Together: 70 s → 4.2 s, with identical faces.
- `.gitignore` now ignores `backend/field_captures_scans/` (human, 2026-11-25).

**Cleanup** (human, 2026-11-25: "delete them"). The earlier entries below still name some of these; they no longer exist.
- Deleted, superseded by `volume_scan.py`: `backend/experiments/two_photo/two_view.py`, `wallfix.py` and `sweep2.py`. These were never committed, so they're gone for good.
- Deleted: the dropped surface-normal route, `backend/experiments/surface_normals/` (5 of its 6 files are in git history; `vol_eval.py` was not committed).
- Deleted: the Metric3D environment and weights (about 2 GB) from an older session's temp folder, and this session's scratch.
- `experiments/two_photo/` now holds only `synth.py` (trimmed to `scenes()` + `sweep_case()`, used by the scan tests) and a new README.
- Kept for the Fable review to decide: the one-photo tools (`eval_volume.py`, `eval_volume_field.py`, `draw_volume_corners.py`, `volume.py`'s fitters and `test_volume.py`). `fakewall.py` is kept because `synth.py` uses it.
- Tests after the cleanup: `tests/test_volume_scan.py` gives `48 passed, 1 skipped`.
- `npx tsc --noEmit` is clean; lint shows only the 3 problems that were there before.

**Decisions** (spec: yes)
- A burst, not video or AR.
- Frame poses by homography decomposition.
- SIFT, not ASIFT.
- Save every request.

**Questions for the human**
- None open. Both earlier questions were answered: the pyramid face is fixed, and the scans are git-ignored.
- FYI: the slow synthetic tests run in CI too (no model needed), adding about 2 minutes.

**Gym trial: how to**
1. The backend and app run as usual; the endpoint is live, with no rebuild needed.
2. Take the photo front-on, as normal, with the volume near the middle and plain wall all round.
3. Tap the volume so it's selected, then tap "Scan volume faces (test)".
4. Stand where you took the photo, hold "Hold to scan", and take one slow step sideways (about 0.5 m). Keep the volume and the wall around it in frame.
5. Wait up to a minute; the faces appear on the photo.
6. Note the scan id shown, and tape-measure the faces whose numbers you want to check. Each scan's `volume.json` in `backend/field_captures_scans/<scan_id>/` is the place for those numbers; face numbers follow the order in `scan.json`.

**Known issues / context for the next session**
- **Real accuracy is unknown:** this trial is the experiment. The three-photo version was about 50% on real volumes; the bet is that many close frames remove that noise.
- Nearly edge-on faces (thin tops) can be missed. Faces turned away from the photo can't be measured at all.
- `uvicorn` has one process, so a scan (up to a minute) holds a worker thread; fine for one tester.

**Human:** Reviewed: · Notes:

### 2026-11-25 (late) · Slice 11: single-photo surface-normal network on the measured volumes

**Status:** Tested with ViT-Small and ViT-Large; neither is usable. Volume face angles are closed for now.

**What changed**
- `backend/experiments/surface_normals/vol_eval.py` (new, dev only); README updated with the results.
- Cleanup: about 7.6 GB of temp caches and renders deleted (all can be regenerated), plus this session's scratch copies of the two-photo scripts (the repo copies are the masters). Older sessions' scratch folders (retrain data, the normals environment) were left alone.

**Results** (Metric3D v2 ViT-Small, one photo, per-face direction clusters; details in the README): all photos 42% within 5°, median 6.7°, 6 sign flips, 15 extra faces. The clean photos alone (B, edge) are about 52% within 5°. Some faces fail the same way from every viewpoint (V03's +19° face reads −8 to −10°). The wall correction makes it worse.

**Where volume face angles stand:**
- One photo cannot measure them geometrically.
- Two or three photos: accurate on synthetic walls, about 50% on real ones.
- A learned single-photo model: about 50%.
- None has a trust signal.

**ViT-Large tried the same evening (human's go-ahead): no better.** All photos: 34/46 faces found, median 8.0°, 38% within 5° (ViT-Small 42%), 6 sign flips, 11 extra faces. The same faces fail in every photo (V03's +19° face reads −18 to −27°), so the errors are systematic, not model size. It is also 6× slower (22 s per photo on CPU). `predict.py` now takes `METRIC3D_MODEL`. The 1.65 GB of weights sit in the older session's `normals/torch_home`.

**Verdict: volume face angles are closed for now.** Every route lands at about 40–50% on real volumes, with no trust signal. **Next for volumes is the retrain plus the on-volume flag (slice 14).**

The only remaining option seen is the iPhone LiDAR depth sensor (Pro models, native code); fine-tuning a model on climbing volumes would need a lot of labelled data.

**Human:** Reviewed: · Notes:

### 2026-11-25 (evening) · Slice 11: synthetic test of the two-photo method; volume face angles parked

**Status:** Parked (human and agent, 2026-11-25). The method is sound on synthetic walls but does not carry over to the real photos, and three photos per volume is too much to ask of a user. **Volume face angles are not pursued. Slice 14 becomes just the on-volume flag** (needs the retrain, no extra photos). Measured-volume photo collection is on hold.

**What changed** (all dev only, in `backend/experiments/two_photo/`)
- `synth.py` (new): a small ray-cast renderer of three-photo scenes. Textures are fixed to the wall and faces, using `fakewall`'s shapes. It writes the `field_captures_volumes` layout, so `sweep2.py` runs on it unchanged. This deviates from the agreed plan: a separate renderer instead of modifying `fakewall.py`, because fakewall's texture is screen noise. `fakewall.py` is untouched.
- `two_view.py`: the other photo's pose now comes from decomposing the wall homography between the two photos with the anchor's wall plane (`POSE=homog`, the default); PnP remains as `POSE=pnp`. `TWO_PHOTO_ROOT` points the scripts at another data folder.
- `sweep2.py`: faces come from sequential RANSAC planes on the 3D points (`FACES=planes`, the default; `FACES=regions` is the shading split). A plane counts only if 60% of its inliers form one patch in the photo (`COMPACT_FRAC`). Depth comes from faces holding at least 3% of the points. Added an `ANCHORS` filter and an "extra faces" count.

**Results, synthetic** (15 scenes: pyramids, wedges, boxes on 0°, −15° and +20/35° walls, 50–120 cm steps; photo A as photo 1)
- Faces reported are accurate: **median 0.1°, p90 0.6°, depth median 2 cm**. 30 of 44 faces found; 2 extra faces; 1 sign flip.
- With `COMPACT_FRAC` 0.4: 34/44 found, median 0.2°, 4 extra faces.
- Stress variants (12): focal length 13% off still works (median 1.7° across all variants; one face 27° off). Plain or untextured pyramids and wedges still work, carried by the edges between differently lit faces. An untextured flat box front fails.
- Bugs it found and fixed: PnP put photo 2's camera 229 cm off on a 35° overhang (decomposition gets 80.0 cm exactly), and the shading split merged faces (21/44 found).

**Results, real V01–V05** (same final version): 4–9 of 17 faces found, median error 14–20°, depth error 28 cm. That is worse than the earlier shading-split version (47% within 5°). **The synthetic-to-real gap is large.** Real volumes give 3D points too noisy for plane fitting. The drawn A photos explain part of this, not all.

**Decision (human, 2026-11-25): three photos per volume is too much to ask of a user.** The options discussed:
1. On-volume flag only (chosen to ship).
2. One extra photo only when a picked hold is on a volume.
3. A short sideways video.
4. LiDAR on Pro iPhones.

2–4 stay as possible future upgrades; none is planned.

**Questions for the human:** none open.

**Human:** Reviewed: · Notes:

### 2026-11-25 (later) · Slice 11: two-photo method, designed and tested

**Status:** Partial. It works on some faces, but **its accuracy is not known**. Five volumes (15 scored faces with photo A as photo 1), drawn-on A photos and run-to-run spread make the numbers too thin to trust. It waits for clean photos of more volumes (list below).

**What changed**
- `backend/experiments/two_photo/` (new, dev only, README inside): `two_view.py` (poses, sparse version), `wallfix.py` (exact wall alignment), `sweep2.py` (the method). Caches and outputs go to the system temp folder. No API, `volume.py` or test changes.

**The method** (details in the README): photo 1's camera from its bolt grid; the other photos' cameras from ASIFT matches on plain wall plus PnP (no bolts needed in them); exact wall alignment by a local RANSAC homography; a plane sweep of heights 0–90 cm averaged over the other photos; faces as regions of uniform shading, each with a RANSAC plane.

**Results** (`uv run python experiments/two_photo/sweep2.py`)
- **Placing the second camera works.** Its distance from the wall agrees with its own bolt grid to within a few percent (217 vs 215 cm, 298 vs 295, 197 vs 215). That fixes V05-B's 0 bolts.
- **Exact wall alignment is essential.** Without it, 3–58% of plain-wall pixels sweep to height 0; with it, 80–100%.
- **With photo A as photo 1:** 15 of 17 faces found, 47% within 5°, median error 11°, worst tenth 48° or more off, 2 sign flips, depth error median 19 cm. Using all photos as photo 1 is worse (40% within 10°), so photo 1 must be the front-on photo.
- **Good on large, well-lit flat faces:** V04's hexagon front 2.6–2.7° and upper left 1.3–3.3°; V05's sides 0.2–2.1°; V01's top and lower faces 1.7–4.3° on the best run.
- **Bad on:** V04's top (a thin face at a grazing angle, 14–29° off), V03's left face (sign flips every run; its photo A has black drawn lines on the edges), V02 (curved, as expected).
- **Unstable:** V04's upper right read 5.4° off in one run and 15.5° in another with the same code.

**Dead ends (don't retry)**
- Plain SIFT across the side views: mostly wrong matches at 50–60°. ASIFT fixes it.
- Triangulating sparse feature matches on the volume: volumes are plain apart from identical bolt holes, so depths came out 2–3× too large.
- Pose-only plane homographies with no wall alignment: the wall itself did not line up.
- Masking a wide band around the tester's drawn lines: it removed the edges the method relies on.

**Decisions** (recorded in spec: no)
- Photo 1 is the front-on photo; the others only give parallax.
- The drawn-on A photos make this data unfair to the method; the next test uses clean photos.

**Data needed (human, agreed 2026-11-25):** the same as V01–V05, but keep the photos clean and draw face numbers on a **copy**. Three photos per volume: front-on (A), a step left (B), a step right (the "edge" slot), each under about 30–40° from front-on, with plain wall and bolts visible all round the volume. Measure the face angles (check the underside sign), depth and wall angle beside; edge lengths optional. Aim for 10–20 volumes, mostly flat-faced, including a slab and an overhang wall.

**Open (when the data comes)**
- Re-run `sweep2.py` on the new volumes; if large faces hold at about 5°, decide the trust rule (which faces to report) with the human.
- Then: speed (about 1.5 min per volume; ASIFT dominates), YOLO missing V04-A and V05-A, and run-to-run stability (fixed seeds, more RANSAC iterations).

**Human:** Reviewed: · Notes:

### 2026-11-25 · Slice 11: first real measured volumes, one-photo method scored

**Status:** Partial. The done-when ("scored against real measured volumes") is met, and the answer is **no-go for the one-photo method**. The two-photo design (plan step 4) waits for the human's call.

**What changed**
- `backend/field_captures_volumes/V01–V05/volume.json`: filled from the tester's `.txt` notes and the face numbers drawn on `photo_A.jpg`. Added fields: per-face `number` / `edges_cm`, `"score": false` on V03 face 3, and `detection_ids` (the measured volume's id in each photo's saved `/detect`, picked by eye). V01's wall angle is 0 (tester: "same as the rest"). V02 face 1 (iPhone Measure read −92) is left empty at the tester's request.
- `backend/eval_volume_field.py` (dev only): reads the new folder layout. `load_volume_folder` turns a folder with `volume.json` into one capture per photo (A / B / edge). `run()` takes an already-loaded capture, and `_facing_from_points` maps "points" onto the matcher's out / left / right, leaving mixed directions unset. The old one-photo folders are unchanged (a `--survey` of `173933` still gives 4 fitted, 0 trusted). No test imports the script, and no API or `volume.py` code changed.

**Results** (`uv run python eval_volume_field.py field_captures_volumes/V0*`)
- **0 of 11 fits trusted.** On the untrusted fits, the face steepness error is median 15.7°, p90 33°, with 4 sign flips; only 20 of 32 measured faces were produced at all. Against the bar (median ≤ 5° on trusted faces), there is nothing to pass.
- Almost every volume is fitted as a pyramid with an assumed tip, so it can never be trusted. The real shapes (a faceted wedge, a curve, a hexagonal box, a long faceted bar) are outside the box / wedge / pyramid library. The one good number: V04's tilted hexagon front reads 52° and 50° against 48°.
- Depth error median 3.6 cm, but that comes from fits that are wrong in other ways. Not a result.
- **Wall plane:** the wall angle beside each volume reads −4° to +8° against 0 / 11°. But `wall_plane` is UNTRUSTED (axis ratio about 0.46–0.48) on V02-B, V03-B and V04-B, all side-step photos. A ratio near 0.5 looks like the grid's diagonal misread as its side when seen obliquely. **This matters for the two-photo method**, which needs photo B's wall plane.
- **Bolts on photo B:** re-run today, the counts match the day's (V05 edge now finds 16, where on the day its detection never finished). **V05 B still finds 0**: the side step was so big that the grid fails the bolt detector's regularity check. So a B photo must stay fairly square-on.
- **YOLO on the target volume:** missed in V04-A (hexagon) and V05-A (long black bar), both the clean front-on shots. V01 is found only as its yellow top face, not the wood-coloured wedge. V02-B is merged with the big wood volume next to it. **Add these photos to the retrain's held-out test set; never train on them.**

**Data checks done**
- V03's tape numbers can't all be right. Tip edges of 42 and 42 cm with a 25 cm depth allow a bottom edge of at most 67.5 cm, not 82 (the photo says about 71). And face 3, the underside facing down, must be a large overhang, not −20. Face 3 is excluded from scoring; faces 1 and 2 are used.
- V04 is consistent: the front face (26 cm tall at 48°) plus the top (23 cm at −80°) matches the 23 cm depth.

**Decisions** (recorded in spec: no, spec waits for slice 17)
- The one-photo method is not adopted for real volumes. Volumes keep saying nothing, which is already the agreed behaviour for untrusted fits.
- Hold-on-volume (slice 14 step 1) is **not** started early (human, 2026-11-25).

**Questions for the human**
- Plan step 4: write the two-photo design now, or wait? The human said "come back to me when needed". The scores say it is needed, if volume face angles are still wanted.

**Data still wanted** (human's next session): about 10–20 more volumes, including a slab and an overhang wall and a dark volume on a dark wall. For each: the same measurements as V01–V05, with the faces drawn on a **copy** of photo A; 2–3 tape distances from a hold on the volume to a hold on the plain wall; and photo B taken from a smaller side step, with the bolts around the volume in view.

**Known issues / context for the next session**
- Overlays and `results.json` from this run are in this session's scratchpad (`.../scratchpad/evf/`), not the repo. Re-run the command to regenerate them.
- `field_captures_volumes/README.md` refers to `backend/volume_capture.py` and `POST /dev/volume-capture`, which are not in the repo. The folder is untracked.

**Human:** Reviewed: · Notes:

### 2026-11-24 · Slice 16: planned with the human (in progress)

**Status:** Reference angles, photo quality, the wall-length message and fix, and the bolt pattern setting are done. Hold colour was dropped (human, 2026-11-24: not every gym sets routes in one colour).

**Reference angles corrected** (human, 2026-11-24). epic_wall P14 is 14 → 29 and IMG_7503's yellow panel is −26 → +26 (an overhang), in `panels.json`, `test_panels_reference.py` and `notes/measurements.md` (the original value is kept with the correction beside it).
- With the true camera tilt, **18 of 19 reference panels are now within 10°** (was 16). IMG_7503 reads 26° (error 0.2°); P14 reads 27° (error 2°).
- The one miss left is IMG_7502's 9° panel, which the segmenter merges with its 34° neighbour.

**Smaller photos: done.** `CustomCamera.tsx` now calls `takePictureAsync({ quality: 0.85 })`, and the spec's rule now reads "never resize uploads; quality 0.85 is fine". The test that justified it ("no worse"), on the 15 field captures plus 6 reference photos:
- **YOLO:** finds 99.5% of the same holds. Every hold that changed sat at the confidence cutoff (holds 0.15–0.21 against a 0.15 floor; two volumes 0.29/0.31 against 0.25), and about as many appeared as disappeared.
- **Full pipeline on the field captures** (fresh YOLO, bolts and scale on the re-saved photo): angles median 1.2° / max 5.1°, 9/9 tape pairs inside their margins. The same as the original.
- **Reference photos' bolt grid:** pooled p95 2.2% → 2.3%. But a near-lossless re-save (quality 100) moves it as much (to 1.9%), so this is within the noise of *any* re-save, not caused by compression.
- How it works: the phone encodes the JPEG with a bit more compression, and the server decodes it into pixels exactly as before. The detail JPEG drops is gone for good, not restored, but the tests show none of it was needed.

**New finding: the bolt-grid fit is fragile to tiny pixel changes** on the sparse reference walls. A near-lossless re-save changed IMG_7502's wall length from 21.1 to 22.6 units, and a quality-92 save collapsed it to 8.2 units. The distances held (p95 stays 2–3%), but which lattice wins can flip on a few bolts, as the 2026-10-19 resolution tests also saw. Added to the Fable checklist.

**Wall length: what it is, and options.** Today `wall_length_cm` = from the highest to the lowest bolt **visible in the photo**, in a band down the middle, measured along the wall surface, plus half a bolt square at each end. So it is "how much wall is in the shot", not the wall's real height: the same wall read 10.7 to 20.5 grid units (2.7–5.1 m) as the tester stepped back, because more wall came into frame. Acceptance criterion 1 says "distance from the top to the bottom of the wall".
- **Decision (human, 2026-11-24): ask the user.** The camera now shows "Fit the whole wall in the shot, floor to top". PhotoPreview has a "Whole wall in the photo" switch, off by default, which is sent as `whole_wall_in_photo`. The AI gets `wall_length_is`: either the full height or "only the part of the wall in the photo". It only appears when the app sends the answer. This counts as AC1 met (the human: whether it's the full height "is trivial").

**The fragility, in detail** (IMG_7502, same YOLO holds for every version, so only the bolt side changes):

| Version | Bolts found (same as original) | Column used for the wall length | Wall |
|---|---|---|---|
| original | 116 | x=1622, top bolt y=508 | 21.1 u |
| quality 100 (mean pixel change 0.2/255) | 119 (100) | x=1480, top bolt y=140 | 22.6 u |
| quality 92 | 118 (82) | x=1892, top bolt y=2706 | **8.2 u** |
| quality 85 | 147 (90) | x=1528, top bolt y=140 | 22.0 u |

- **Bolt detection:** on this wall most bolts are hidden by holds, and many of the visible ones sit right at the detector's limits (5 px wide, contrast 0.3, lining up with neighbours). A change too small to see flips about 15% of them in or out, whatever the cause: compression, re-saving, or a slightly different shot.
- **The scale is stable:** cm per pixel down the wall is the same in every version (0.41, 0.45, 0.56–0.58, 0.64–0.66, 0.74–0.76 units per 100 px), which is why hold distances stay accurate.
- **The wall-length rule amplifies the flips.** It takes one vertical strip of bolts at the *median* bolt x, then that strip's highest and lowest bolt. A few bolts on the right coming or going move the median x, the strip slides onto a part of the wall with no top bolts, and the length collapses (8.2 u).
- **Fixed (slice 16, human-approved).** `scale.wall_length_units` now measures along 5 fixed vertical lines (at the 20/35/50/65/80th percentile of bolt x) and averages them. Each line takes its top and bottom from the bolts within ±8 spacings (`WALL_WINDOW_SPACINGS`), so a distant side patch is still ignored (the Tester's test passes).
- **Spread across the four versions** (original, quality 100/92/85), old → new: IMG_7502 **67% → 7.6%**, IMG_7503 9.4% → 4.2%, IMG_7504 4.5% → 3.9%, IMG_7500 1.1% → 0.9%, IMG_7552 1.6% → 0.3%, epic_wall 0.0% → 0.1%. Windows of 6, 8, 10 spacings and unlimited were tried; 8 was chosen.
- **What's left:** on IMG_7502 the lines cross a long stretch with no visible bolts, so part of the scale is borrowed (like a tier C distance). ±3.8% around the middle is inside the 6% margin the AI gets for wall length.
- Tests: 721 fast + 26 slow pass; field replay unchanged (hold distances and angles don't use this rule).

**Bolt pattern research (2026-11-24, gym walls; boards excluded by the human).** No wall maker publishes its gym t-nut layout, so this comes from build guides, one Walltopia brochure and builder forums.
- **Fit our model:** an "8 inch grid, alternate rows shifted 4 inches" is exactly our pattern at 20.3 cm. Walltopia's "standard 10 × 10 cm diamond grid" is our pattern turned 45°, but users may type the wrong number.
- **Break it:**
  - a plain square grid (home walls; speed walls use 125 mm squares): about 41% too long, with no warning
  - rectangular staggered grids (e.g. 6", shifted 3")
  - hexagonal patterns
  - random drilling (fails safely: "no bolt holes found")
  - panels with extra holes, or mixed 10 cm / 20 cm density
  - textured or 3D panels with few t-nuts
- Sources: [Walltopia training-boards brochure](https://cdn.walltopia.com/wp-content/uploads/20231027223324/Walltopia-Training-Boards-Brochure.pdf), [Walltopia Climbing Walls in Detail](https://walltopia.com/images/downloads/Walltopia_ClimbingWallsInDetail.pdf), [Rockwerx spec](https://specguy.com/site/wp-content/uploads/Rockwerx-SECTION-11-66-00.02-CLIMBING-WALLS-GymRock.pdf), [Element Climbing](https://elementclimbing.com/pages/how-to-build-a-wall), [ClimbingShed](https://climbingshed.com/blogs/resources/how-many-t-nuts-do-you-need), [Mountain Project: offset grid](https://www.mountainproject.com/forum/message/118355502), [Mountain Project: t-nut placements](https://www.mountainproject.com/forum/topic/106646080/t-nut-placements), [UKClimbing: grid pattern](https://www.ukclimbing.com/forums/walls+training/grid_pattern_for_home_board-729439), [Wikipedia: speed climbing wall](https://en.wikipedia.org/wiki/Speed_climbing_wall).

**Bolt pattern choice in Settings: done** (human, 2026-11-24).
- Three cards, each with a small drawing (`BoltPatternGraphic.tsx`): "Squares with a centre hole", "Plain square grid", "Diamond grid". Each shows the holes, a faint outline of their shape, and the distance to measure in orange; the spacing help text changes to match.
- **The backend is unchanged:** plain and diamond are our pattern turned 45°, so the app sends side = measured spacing × √2 (`utils/boltPattern.ts`). `boltSpacingCm` keeps its meaning and storage key; the pattern is stored separately, and existing users default to "Squares with a centre hole".
- The spacing range check applies after conversion (10–50 cm side), and the error message shows the range in the units being typed.
- Test (`test_scale.py`, Developer-written): a synthetic plain grid at 0°, 45° (diamond) and 12°, fitted for real and converted ×√2, measures known distances within 1%. `tsc` is clean; lint shows only the three problems that were there before. **Not yet checked on a phone: please look at the Settings screen.**

**Human:** Reviewed: · Notes:

### 2026-11-24 · Slice 15 part 2: more coaching information (old 8)

**Status:** Items 1, 4 and 5 complete. Item 3 (on a volume) is slice 14's and blocked. Item 6 (hold colour) was dropped (human, 2026-11-24: not every gym sets routes in one colour). Part 1 (the volume distance fix) is blocked on slice 14.

**What changed**
- **Item 1, positions and move parts in cm.**
  - `angle.wall_axes`: at each hold, the photo directions of "down the wall" (gravity with its part along the wall normal removed) and "across to the right", from the same wall direction the angle vote finds.
  - `scale` returns them per detection as `wall_axes`; `/analysis` passes the picked holds' axes as `route["wall_axes"]` (`scale.select_axes`).
  - The worker splits each move into `up_cm` / `across_cm`. The *proportions* come from the axes at both ends; the *length* is the existing along-the-wall distance, so the parts always add up to `distances_cm`, folds included.
  - Each hold gets `position_from_start_cm` (up/across from the first picked hold). That replaces "height above the lowest bolts" from the plan, because the lowest bolt in the photo isn't the floor or the start.
- **Item 4, angle change along a move.** Each move carries `from_wall_angle_deg` / `to_wall_angle_deg`, and `wall_angle_change` (e.g. "steeper: 20 to 54.5 degrees") when the change is bigger than the angle margin.
- **Item 5, climber height and arm span.**
  - Optional fields in Settings, saved on the phone (`useClimberStats`, `utils/climberStats.ts`), sent as `climber_height_cm` / `climber_arm_span_cm`.
  - `/analysis` checks them (100–230 cm and 90–250 cm; absent or empty = not set; anything else is a 422).
  - The worker adds a `climber` block with the ape index (arm span minus height).
- **Prompt:** two new short sections, "Moves and positions" and "Climber".
- **Backward compatible:** `moves`, `position_from_start_cm` and `climber` only appear when there's data. An older cached scale or an older app gives exactly the previous payload.

**Results**
- Sanity check on the field captures: every move's up/across matches the photo, and **the same 76 cm pair photographed from four spots splits consistently**: up −24/+27/−24/−33 cm and across 76/−74/72/71 cm (one pair was picked in the opposite order).
- Tests: 715 fast pass. Field replay unchanged. `npx tsc --noEmit` is clean; `expo lint` shows only the three problems that were there before.
- New tests: `wall_axes` geometry (checked by projecting real 3D points), moves and positions, angle-change flag, the old payload when there are no axes, the climber block and `/analysis` validation. **These were written by the Developer, not the Tester; please have the Tester review them.** Two Tester-owned key lists (`test_scale._KEYS`, `test_main` line 140) gained `wall_axes`, as the contract now includes it.

**Decisions** (spec not yet updated; slice 17)
- Up/across is a proportion of the measured distance, not a separate measurement, so the two can never disagree.
- Positions are relative to the first picked hold.
- Arm span is stored rather than the ape index: it's what people can measure, and the ape index follows from it.


**Human:** Reviewed: · Notes:

### 2026-11-24 · Slice 13: speed (old 7)

**Status:** Complete for the server. The biggest remaining win is an app change that needs your OK (question 3 in the Overview).

**Where the time went (measured, warm server).** On your phone's photos the server took 2.5–3.9 s, against 6.6–15.3 s measured on the phone. So most of the wait was **uploading a 3.8–4.4 MB photo**, not computing. Of the server time, the scale step (fitting the bolt grid and measuring every hold pair) was the largest part, then YOLO, then bolt detection.

**What changed.** Every change keeps the outputs **identical**: checked on 21 photos (6 reference + 15 field captures) against outputs saved before any change. The field replay and the 26 slow accuracy tests also pass unchanged.
- `backend/scale.py`:
  - The grid fit's second pass reuses first-pass fits for bolts whose neighbourhood didn't change, keyed on the exact input bytes.
  - 2×2 maths in the per-bolt loop is done directly instead of through `np.linalg`, with plain floats in the clustering loops.
  - Hold-pair distances and tiers share one neighbour search (`_lengths_and_support`).
  - `metric_at` accepts a precomputed search.
- `backend/bolts.py`:
  - `knn` copies OpenCV's results out in bulk.
  - New `find_candidates(image)`: the blob search, which needs only the photo. `detect_bolt_holes(image, detections, candidates=None)` takes its result; the contract the tests check is unchanged.
- `backend/main.py`:
  - YOLO and the bolt blob search run side by side.
  - Responses are gzipped (`GZipMiddleware`, over 1 KB): `/detect` is 3–4× smaller (429 KB → 116 KB for 183 holds), and phones unpack it automatically.
  - The model is warmed in a background thread at startup (`detection.warm_up`), so the first photo after a restart doesn't pay the ~5 s load.
  - Each `/detect` logs its upload size and per-stage times.

**Results (server time per photo, warm)**

| Photo | Before | After |
|---|---|---|
| Phone capture, 20 holds (6.8 MP) | 2.49 s | **≈1.3 s** |
| Phone capture, 83 holds | 3.94 s | **≈2.0 s** |
| epic_wall (8 MP, 77 holds) | 5.49 s | **≈2.9 s** |
| IMG_7500 (12 MP, 183 holds) | 8.55 s | **≈5.1 s** |

- Scale step alone over all 21 photos: 47.0 s → 21.0 s.
- Tests: 697 fast tests pass in 2.5 min (was 5 min); 26 slow pass. Field replay unchanged.
- **Done-when:** "4–5 s on a 12 MP photo". Met on typical photos; the busiest reference photo is 5.1 s. Your phone sends 6.8 MP, where the server now takes 1.3–2.0 s.

**Finding: the photo can be 4× smaller with no loss (needs your OK).** Re-saving the 15 field photos at lower JPEG quality and rerunning bolt detection and the scale step:

| JPEG quality | Size | Bolts found | Angle error (median / max) | Tape pairs inside margin |
|---|---|---|---|---|
| original (app today, quality 1.0) | 3.76 MB | 2861 | 1.2° / 5.2° | 9/9 |
| 92 | 1.20 MB | +0.8% | 1.1° / 5.4° | 9/9 |
| **85** | **0.86 MB** | −0.0% | 1.2° / 5.1° | 9/9 |
| 60 | 0.48 MB | −0.6% | 1.2° / 5.6° | 9/9 |

The spec says "never resize or recompress uploads", from the 2026-10-19 *resolution* tests, which still stand; JPEG *quality* was never tested. The change is one line in `CustomCamera.tsx`: `takePictureAsync({ quality: 0.85 })` (it passes no options today). It's not made, because it changes a recorded decision.

**Not done**
- YOLO via ONNX/OpenVINO needs a new dependency (not installed without asking). YOLO is now 0.6 s on phone photos, so the likely gain is 0.2–0.3 s. Not recommended for now.
- OpenCV's blob detector is 1 s on 12 MP photos, but changing its settings would change which bolts are found.
- Tried and rejected: a pure-numpy neighbour search (3× slower at 266k points) and OpenCV FLANN (exact but 2.5× slower).

**Context:** `eval_field.py`, plus the golden-output and timing scripts in this session's scratchpad (not the repo), are how to check a speed change.

**Human:** Reviewed: · Notes:

### 2026-11-24 · Slice 12: wall-angle fixes (old 5e)

**Status:** Complete in code and tests. The P14 done-when is not met, because the evidence says P14's recorded angle is wrong, not the code (question 2 in the Overview).

**What changed**
- `backend/eval_field.py` (new, dev only): the field replay. It re-runs the 15 field captures through the current `scale.compute_scale`, using the detections, bolts and phone tilt saved on the day (no YOLO, about 30 s). It prints truth / the day's value / now for every measured angle and tape distance, flags anything worse than the day, and gives a summary. Holds on a volume, and 174741's tape value (read off the app), are listed but not scored. **Run it before and after any change to `scale.py`, `angle.py` or `bolts.py`.**
- `backend/angle.py`: confidence rule in `consensus_normals`. No angle when fewer than `MIN_SUPPORT = 10` bolts back the winner, or when a genuinely different wall direction (over `MIRROR_MIN_SEP_DEG = 10°` away) is backed at least `TIE_RATIO = 0.85` as well. A "no angle" goes through the existing path (NaN → the hold's `wall_angle_deg` key is absent), so the API and payload are unchanged.
- `backend/tests/test_angle.py`: 5 new tests of the vote, the first it has had. A flat wall at −20°, 0°, 14°, 31° and 45° under three camera tilts is recovered within 1° everywhere in the frame (**slabs included**); two panels across a fold stay apart; a true tie and thin evidence give no angle; a near-tie between almost identical directions still gives one. **Written by the Developer, not the spec-only Tester, because no Tester subagent was available. Please have the Tester review them.**

**Results**
- `uv run pytest tests/test_angle.py -q` → 128 passed.
- Field replay: angles n=29, median 1.2°, p90 3.5°, max 5.2°, none lost; 9/9 tape distances inside their margins. Identical to the day.
- `eval_angle.py` on the reference panels: identical to slice 9.

**Findings**
1. **P14 is probably mislabelled.** The bolts inside P14's outline read 26–27° whatever method is used: today's vote, smaller neighbourhoods, grouping bolts by direction, each bolt's own fit without the panel homography, or the panel homography itself. The top-right 14° panel reads 13.9°. On the left column the same fold shows at the same height, from 14° to 29°. Walls fold along horizontal lines, so P14 is most likely about 29°. Item 1 of the scope ("group bolts by wall direction") was built and tested in scratch and **not kept**: it changed nothing on P14 and nothing elsewhere.
2. **IMG_7503's "−26 slab" may be a sign slip.** The vote reads +26 with a lead of 47 to 6, which is not a near-tie. The synthetic tests show the vote recovers real slabs, and the field test's −2° and 0° walls read −3.1° and −1.1°. The slab photos will settle it.
3. **The panel homography (`volume.wall_plane`) is not a slab fix.** It has no mirror twin in exact maths, but its slab-vs-overhang information sits in the weak perspective terms. It also read IMG_7503 as +29°. It is better on two panels (IMG_7502's 9° panel: 9 against the vote's 31; IMG_7500's 17°: 14 against 24) and worse wherever panels were merged (epic_wall's 29–31° panels: 23°). Not adopted.
4. **Weak votes are not wrong votes.** Six field holds had their rival at 70–78% of the winner's backing and were still within 3–6° of the truth. That's why the confidence rule only catches true ties.

**Decisions** (spec Decisions not yet updated; that's slice 17's job)
- Confidence only blanks true ties and sparse bolts. Blanking weak votes would have dropped 6 of 29 correct field angles.
- No change to how bolts are grouped (finding 1).

**Known issues / context for the next session**
- IMG_7502's 9° panel still reads 31° (merged with its 34° neighbour by the segmenter). The homography reads it right; a per-panel blend is possible later, but only once merged panels can be detected.
- Scratch experiments (`exp1`–`exp4`, `p14.py`) are in this session's scratchpad, not the repo.

**Human:** Reviewed: · Notes:

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
