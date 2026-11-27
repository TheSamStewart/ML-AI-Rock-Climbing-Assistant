# Volume scan (test feature, #38, branch `feat/38-volume-scan-trial`)

## Goal
Show the angle of every visible face of a climbing volume, in degrees, in the app. The user takes the normal photo, taps a volume, then holds a button while taking one slow step sideways; the app takes a burst of photos during the step. From the photo plus the burst, the server measures each face's angle and the volume's depth, and the app draws each face's outline with its angle on the photo.

This is a **test feature for gym trials** (human, 2026-11-25). It is not part of the normal flow and does not reach the coaching AI yet. It implements "idea 2" from `docs/features_deprecated/wall_size_hold_distance_handover.md` slice 11: many views from one short sweep, instead of three separate photos (too much to ask) or ARKit/ARCore (not possible in Expo Go). The degree readout is wanted for display even where coaching doesn't need it; see the standing instruction never to remove the angle display.

**After gym trial 1 (2026-11-27): no-go.** At most 2 burst photos lined up in any scan, and 5 of 7 scans failed. Of the 4 faces found, 3 had the wrong sign (one only just: +7° actual, −5° app), and 1 face was missed. The human's decision is to keep working on this feature in this issue until a later trial says go; #50 (face angles in the coaching prompt) stays blocked until then. Users won't step predictably, so the scan must get depth from **any** sideways movement: a big arc, a turn of the phone, a change of height. Trial 1's results are in `backend/field_captures_volumes/scan_trial_2026-11-27/README.md`.

## Inputs
- `photo`: the full-resolution photo already taken (the anchor), and the phone's `gravity` reading at its shutter.
- `frames`: 3–12 photos from the burst, the same camera and picture size as the photo, taken while the phone moves and keeps the volume roughly in frame. The movement can be any amount and shape (decision 2026-11-27). Trial 1 recorded steps of 10–40 cm, walking arcs that ended 45°+ to the side, the phone turned to keep the volume centred, and the phone lowered after the photo.
- `volume_polygon`: the tapped VOLUME detection's outline (normalised x, y on the photo).
- `bolt_spacing_cm`: the user's setting (the depth is in cm).

## Outputs
`POST /dev/volume-scan` returns `200`:
```
{
  scan_id: str,                       // folder name under backend/field_captures_scans/
  faces: [{
    steepness_deg: float,             // degrees from vertical, + overhang / - slab (angle.py's convention)
    facing: "out" | "left" | "right" | "undefined",
    facing_deg: float | null,         // turn about gravity from the wall's own facing, + = climber's right
    outline: [{x, y}],                // normalised, on the photo
    n_points: int                     // 3D points supporting the face
  }],
  depth_cm: float | null,             // furthest point off the wall; null when the photo's bolt-grid
                                      // fit is uneven (axes > 8% apart), since the angles hold but cm don't
  wall_angle_deg: float,              // the wall beside the volume, from the bolt grid + gravity
  frames_used: int, frames_sent: int,
  seconds: float
}
```
`422` with a plain message when the scan can't run: no bolt grid at the volume, fewer than 2 frames posed, unreadable images, or a bad polygon. Every request (inputs and result) is saved under `backend/field_captures_scans/<scan_id>/`, with a `volume.json` truth template to fill by hand.

App: in PhotoPreview, once a VOLUME is among the selected detections, a "Scan volume faces (test)" button opens the scan camera. After the scan, each face's outline is drawn on the photo in its own colour, labelled with the angle (e.g. "+23°") and which way it faces, with the depth below. Errors are shown as text.

### Contracts (for the Tester)
- `volume_scan.scan_volume(photo, frames, volume_polygon, detections, gravity_reading=None, focal_35mm=None, bolt_spacing_cm=25.0) -> dict`. `photo` and `frames` are upright PIL images. It returns the response fields above except `scan_id`, plus `points`, `photo_axis_ratio` and `frame_diagnostics`. It raises `volume_scan.ScanError` (a `ValueError`) with a user-readable message when the scan can't run. Fewer than `volume_scan.MIN_FRAMES` (2) frames always raises; more than `MAX_FRAMES` (12) are thinned evenly.
  - *Added in slice 4:*
    - Each `frame_diagnostics` entry has `frame` (index in the frames as scanned), `wall_matches`, `sharpness` (a float, higher = sharper), `used` (bool) and, when `used` is false, a `reason` string. `wall_inliers` and `baseline_cm` are there when a wall homography was found.
    - `ScanError` has a `diagnostics` attribute: that same list when the scan failed while lining frames up, else `None`.
    - The same inputs give the same result on every call: no run-to-run randomness.
  - *Changed in slice 5 (chained line-up):*
    - `wall_matches` is the number of direct matches between the photo's wall features and that burst photo.
    - `wall_inliers` is the support of the frame's final, refined homography. It can now be **larger** than `wall_matches`, because it also counts matches made after warping the frame into the photo's view, and matches with posed neighbouring burst photos.
    - New fields on lined-up frames:
      - `photo_inliers` (the inliers that come straight from the photo)
      - `wall_ncc` (agreement of the wall, −1..1)
      - `wall_ncc_peak` (how much `wall_ncc` beats the same pose nudged a few px)
      - `linked_from` (None for a frame lined up directly with the photo, else the index of the burst photo it was chained from)
      - `turn_deg` (how far the camera turned from the photo's, degrees, ≥ 0)
    - Every entry also has `source_frame`, its index in the burst as sent (they differ from `frame` only when more than `MAX_FRAMES` were thinned).
    - `reason` can also be "bad pose" (a non-finite pose) or "pose check: …".
    - A frame counts as lined up ("used", spec AC 6) only after the pose check:
      - `wall_inliers` ≥ `MIN_WALL_INLIERS`
      - `photo_inliers` ≥ `MIN_PHOTO_INLIERS`
      - `wall_ncc` ≥ `MIN_WALL_NCC`
      - `wall_ncc_peak` ≥ `MIN_NCC_PEAK`
      - a finite baseline within `MIN_BASELINE_CM`..`MAX_BASELINE_CM` (now 500)
    - The result also has `wall_features`: how many of the photo's features are on the plain wall around the volume, i.e. what the line-up had to work with.
- Synthetic sweeps (slice 5): `synth.sweep_case(scene, n_frames, span_cm, path="step"|"arc"|"height", arc_deg=45, drop_cm=40)`.
  - `arc` walks round the volume at the photo's distance, ending `arc_deg` to the right, the phone turned to keep the volume centred.
  - `height` is the sideways step while lowering the phone by `drop_cm`.
  - The case also returns `frame_baseline_cm` and `frame_turn_deg`, the true camera move of each burst photo from the photo's camera. AC 6's synthetic check compares them with `baseline_cm` and `turn_deg`.
- `POST /dev/volume-scan` on a `ScanError` that carries diagnostics saves them as `frame_diagnostics` in `scan.json` (slice 4). The response is unchanged.
- `accuracy_checks/eval_volume_scan.py` (dev-only replay, slice 4):
  - `pair_faces(truth_faces, app_faces, aspect)` pairs measured faces (with `polygon`, normalised `[x, y]` lists) with app faces (with `outline`) by position. `aspect` is the photo's height / width.
    - It returns one row per measured face, with `app` None when no app face lies mostly on it.
    - *Slice 5:* "mostly" means more than 50% of the app face's outline lies inside the measured face's polygon.
    - Pairs are one-to-one, taken in order of that share, highest first.
    - Rows of paired faces carry `share`.
  - On a failed scan, `scan.json`'s `frame_diagnostics` is at the top level. On a successful one it is in `result.frame_diagnostics`.
  - `lineup_needed(n)` = ceil(0.75 n).
- `POST /dev/volume-scan` (multipart):
  - **Fields:** `photo` (file), `frames` (one or more files), `volume_polygon` (a JSON list of `{x, y}`), optional `gravity` (as for `/detect`) and optional `bolt_spacing_cm` (10–50, default 20).
  - **Saving:** each request is saved in a new folder under `main.SCANS_DIR`, with `photo.jpg`, `frame_NN.jpg`, `scan.json` (inputs, plus `result` or `error`) and a `volume.json` template.
  - **Errors:** a bad polygon, a bad spacing, more than 20 frames, an unreadable image, a `ScanError` or any other failure gives a `422` `{detail, scan_id}`, never a 500.
  - YOLO runs on the photo (`detection.run_detection`); its failure doesn't stop the scan.
- Synthetic test cases: `backend/experiments/two_photo/synth.py`, `sweep_case(scene, n_frames, span_cm)`, with scenes from `synth.scenes()`. It returns `photo`, `frames`, `gravity`, `volume_polygon`, `detections`, `truth_faces` (`angle_deg`, `facing`, visible from the photo) and `depth_cm`. Rendering takes about 15 s per image, so tests using it are `slow`.

## Acceptance criteria
1. On synthetic sweeps (`backend/experiments/two_photo/synth.py`), faces visible from the photo are found and measured within 3° (median) and 6° (each), and the depth is within 5 cm.
2. The endpoint saves every scan's inputs and result, and returns the documented shape or a 422 with a message. It never crashes into a 500 on bad input.
3. The app shows each face's outline and angle on the photo, and the button only appears with a volume selected. `npx tsc --noEmit` is clean, and lint has no new problems.
4. The normal flow (`/detect`, `/analysis`, PhotoPreview selection and submission) is unchanged.
5. ~~Real-world accuracy is not an acceptance criterion.~~ Superseded after trial 1 by criteria 6–7, which are measured on the saved trial-1 scans. Real-world "go" is still decided by a gym trial (slice 8).

Added after trial 1, measured by replaying the saved trial-1 scans on a PC (`accuracy_checks/eval_volume_scan.py`, slice 4), from slice 4 onwards:

6. **Line-up.**
   - **Real scans:** in each of the 7 trial-1 scans, at least 75% of the burst photos line up: 6 of 7, 6 of 8, 7 of 9 (agreed 2026-11-27 as "6 of 8"). The volume is in view in all 7.
   - **What "line up" means:** `frame_diagnostics[].used` is true, *and* the pose passes a check. With that pose, the plain wall around the volume, warped from the photo into the burst photo, must agree with it.
   - **Synthetic sweeps** with known poses, for the movements trial 1 recorded:
     - an arc with the phone turned to keep the volume centred, ending 45° to the side
     - a change of height
     - a straight step

     Every burst photo lines up, within 2 cm and 1° of its true pose (thresholds proposed by the agent, 2026-11-27). In practice the check compares `baseline_cm` and `turn_deg` with the case's `frame_baseline_cm` and `frame_turn_deg`.
7. **Face signs on trial 1:** each measured face whose actual angle is at least 10° from vertical is found and gets the right sign (up-facing −, down-facing +). There are 4 such faces: image 1 left (−48°) and bottom (+30°), image 2 top (−40°) and bottom (+53°). A missed face counts as wrong. Faces within 10° of vertical don't count for the sign, but their error is still reported. The replay reports this at every slice from 4 on; it must hold by the end of slice 7.
   - *Question for the human: the error thresholds for "go" in trial 2. Suggested: the sign is right on ≥ 90% of faces and the median error is ≤ 10°. Not agreed yet.*
8. Criteria 1–4 still hold.

## Reference data
- Synthetic: `backend/experiments/two_photo/synth.py` (scenes with exact face angles).
- Real: `backend/field_captures_volumes/` (5 volumes; photos A/B/edge, not sweeps), and the gym scans as they arrive in `backend/field_captures_scans/`.
- **Trial 1 (2026-11-27):** 7 scans in `backend/field_captures_scans/2026-11-27_*`. These are gitignored (80 MB) and exist only on the human's PC and laptop. Results, measured angles and the scan-to-photo mapping are in `backend/field_captures_volumes/scan_trial_2026-11-27/README.md`. The machine-readable truth for the replay is `truth.json` beside it (slice 4). Angles were measured with the iPhone level from vertical, in the app's sign convention (confirmed by the human 2026-11-27). Phone: iPhone 14, main camera, 26 mm equivalent. Its photos reach the server as 3840×1776 landscape with EXIF rotation, so 1776×3840 upright, with no focal length in the EXIF. All 7 were sent with bolt spacing 20 cm; the gym's is 25 cm, so depths are 20% short.

## Slices
| Slice | Scope | Done when |
|---|---|---|
| 1 | Backend `volume_scan.py` + `POST /dev/volume-scan` + saved scans; synthetic sweep helper; tests | AC 1, 2, 4 (backend) |
| 2 | App: burst camera, scan button, face overlay | AC 3, 4 (app) |
| 3 | Gym trial 1 and write-up | Results table logged (2026-11-27: no-go) |
| 4 | **Replay tool** `accuracy_checks/eval_volume_scan.py`: re-run the saved trial scans on a PC and print, for each burst photo, matches, inliers, sharpness and why it was rejected (failed scans too), plus each face's error against `truth.json`. Test the sign on a synthetic overhanging wall | Baseline numbers for all 7 scans recorded (AC 6, AC 7); sign bug confirmed or ruled out |
| 5 | **Chained line-up:** line each burst photo up with its neighbour, link the steps back to the photo, then re-match against the photo guided by that estimate; a pose check; drop photos that don't pass. Synthetic arc / height / step sweeps with known poses | AC 6 (real and synthetic); AC 1 still holds |
| 6 | **Focal length:** the real focal length of the app's 1776×3840 (upright) photos (from the bolt grid, or a one-off calibration), used when EXIF has none | Replay face errors go down, or the 26 mm guess is shown to be fine |
| 7 | **Face splitting** by 2D edges and shading, if outlines are still wrong after 5–6 | Replay outlines follow the real faces; AC 7 met (if slice 7 isn't needed, AC 7 is checked at the end of slice 6) |
| 7b | **Review fixes** from the slices 3–7 review (list below): the 4 decisions, spec contract updates, code fixes, the Tester's unit tests | Every item in the review-fix list is fixed or has a recorded decision; replay numbers unchanged or explained; AC 1 and AC 7 still hold |
| 7c | **Face outlines:**<br>1. outline each base-edge face by its 3D ridge lines<br>2. drop dense-fit faces overlapping another face<br>3. bring back the visibility test, with a tolerance<br>4. faces that don't meet the wall, from their bounding ridges<br>5. outlines filled across holds | The human's overlay notes (2026-11-27, in the handover) are addressed on all 7 replays; AC 1 and AC 7 still hold |
| 8 | Gym trial 2 (human): also measure the 5 unmeasured trial-1 volumes for `truth.json` | Go / no-go for #50 |

### Slice 7b: review fixes (reviewer, slices 3–7, 2026-11-27)
**For the human to decide at `/start-slice 7b`:**
1. **AC 6 is 6/7, not "each".** The pyramid (104222) lines up 5 of 8 photos and needs 6. Either accept 6/7 and amend AC 6, or mark slice 5 "met except 104222".
2. **Slice 7's done-when isn't met.** It says "outlines follow the real faces", but 5 of 7 overlays are wrong, and what was built is faces from base edges, not splitting by 2D edges and shading. Either mark slice 7 Partial (AC 7 met, outlines moved to 7c) or reword its row.
3. **Two wall-angle readouts.** `/dev/volume-scan` uses a 2884 px focal length and `/detect` uses 2542 px (wedge: 29.0° vs 26.9°). Record this in Decisions and hand it to #36. The readout itself stays.
4. **cm thresholds in the backend**, against the bolt-spacings convention: `MIN_BASE_EDGE_CM`, `MIN_RAISED_CM`, `MIN_INSET_CM`, `BASE_EDGE_MAX_H_CM`, `MAX_BASELINE_CM` (plus slice 1's `bolt_spacing_cm`, `depth_cm`). Either record the exception (spec Decisions now, `decisions.md` at issue close) or convert the thresholds to grid units.

**Docs (spec):**

5. Add a "Changed in slices 6–7" block to Outputs and Contracts:
   - `focal_px`, `focal_check_px`, and each face's `method` and `base`
   - the fields `main.py` already returns: `points`, `wall_features`, `photo_axis_ratio`
   - `linked_from` is a `frame` index, not a `source_frame` index
   - the base-probe pairing rule: `share` is 1.0 or 0.0, which replaces "more than 50% of the outline"

   Also mark the old **Faces** decision (dense plane sweep) as revised by "Faces from base edges".
6. ~~`milestone.md`: change "code slices of its own (4–7)" to 4–7b.~~ Done when 7b was split (now says 4–7c).

**Code:**

7. **Diagnostics mix attempts** (`volume_scan.py` `settle`, and the early return for too few wall inliers). Clear the per-attempt keys before each `update`, or keep the best attempt. When `linked_from` names a frame that wasn't used, record where that frame's own link came from.
8. **Replay crash safety** (`eval_volume_scan.py` `run_one`): put the whole per-scan body inside the `try`. That covers reading `scan.json`, the photo and the frames, plus `pair_faces` and `overlay`.
9. Count base-edge faces toward `MAX_FACES`, not just the dense-fit faces.
10. Reword the "step sideways slowly" error message to match the "depth from any sideways movement" decision.
11. Outward edge direction: test against the mask (a point just outside the edge) instead of the vertex centroid, so concave outlines work.
12. When a base-edge face is found, mark its whole region taken, not just its `support` points, or check duplicates by position. This overlaps 7c item 2; if it needs the outline rework, move it to 7c.
13. Guard `np.linalg.inv(Hs[j])` against a near-singular H.
14. `main.py`: serialise the success response inside the `try`, so a NaN in the result can't cause a 500. This was already there before slices 3–7.

**Tests (Tester, from the updated contract in item 5):**

15. Fast unit tests for:
    - `_focal_px`: 2884 px for 1776×3840 with no EXIF; unchanged for 4:3; the EXIF path still uses `angle.focal_px`
    - `focal_check_px`
    - base-edge faces: the shape of `method` and `base`, the 8° duplicate check, the face cap
    - the `_base_probe` branch of `pair_faces`

    Decide whether AC 1 also covers arc and height sweeps (Tester's question 4). Record in AC 7 that its 4/4 is in-sample (thresholds tuned on those faces) until trial 2.

**Field captures (human, before committing `scan_trial_2026-11-27/`):**

16. Check the images for bystanders and the screenshots' status bars. Decide whether to keep the profanity in the verbatim notes, since the repo is public. Rename `image_1/actual vs yield.txt` to remove the spaces.

Slices 5–7 may be re-ordered once slice 4's numbers are in. Fallbacks if they don't get there: the user taps the volume's corners or picks a shape (pyramid, wedge); video instead of a burst; native AR (a development build instead of Expo Go).

## Decisions
- **A burst of photos, not video** (2026-11-25): the burst frames share the photo's lens and picture size, so their focal length is known. A video's focal length, stabilisation warping, codec and rotation would all be new unknowns. Expo Go only (no native AR).
- **Pose of each frame**: the wall homography between the photo and the frame (RANSAC on SIFT matches over plain wall on the volume's panel), decomposed with the photo's bolt-grid wall plane. On synthetic walls this was exact where PnP failed (slice 11, 2026-11-25).
- **Faces**: a multi-view plane sweep of heights off the wall, then sequential RANSAC planes, each kept only as one compact patch (`COMPACT_FRAC` 0.6). Accurate on synthetic walls (median 0.1°); on three real photos about 50%, which is what this trial re-tests with many frames.
- **SIFT, not ASIFT**: a small sideways step doesn't need affine-invariant matching, and ASIFT takes about 1 minute per photo. *Revisited 2026-11-27:* trial 1's views reached 45°+ to the side. Matching neighbouring burst photos (chaining, slice 5) is tried first, since neighbours stay similar whatever the total movement. ASIFT stays a fallback for the last link back to the photo.
- Dev-only endpoint, no auth (like the rest of the API today). On the Fable-review list to gate or remove before release.
- **Trial 1 is a no-go; keep working in #38** (human, 2026-11-27). #50 stays blocked.
- **Depth from any sideways movement** (human, 2026-11-27): users won't step predictably, so the fix goes in the line-up code, not in stricter instructions. Target: AC 6.
- **Trial scans stay out of git** (human, 2026-11-27).
- **Chained line-up with a peak-NCC pose check** (slice 5, 2026-11-27): neighbours chain the oblique frames, and a frame is trusted only if it beats its own nudged copies on the wall.
- **Focal fallback from the long side** (slice 6): with no EXIF, 26 mm on a full 4:3 sensor's long side. It lives inside `volume_scan` only; `/detect` is unchanged.
- **Faces from base edges** (slice 7): real faces are textureless, so a face meeting the wall is the supporting plane through its base edge, tilted to its ridges. The dense plane fit stays for faces off the wall.
