# Volume scan: handover (#38)

Slice status and the slice log for this issue. The contract is in `spec.md`; the milestone's order and status are in `../milestone.md`.

## Status

| Slice | Scope | Status |
|---|---|---|
| 1 | Backend, endpoint, saved scans | ✅ Done 2026-11-25 |
| 2 | App: burst camera, scan button, face overlay | ✅ Done 2026-11-25 |
| 3 | Gym trial 1 and write-up | ✅ Done 2026-11-27 (trial: no-go) |
| 4 | Replay tool: baseline on the saved scans, sign check | ✅ Done 2026-11-27 (baseline: AC 6 0/7, AC 7 2/4; no sign bug) |
| 5 | Chained line-up, pose check | ✅ Done 2026-11-27 (AC 6: 6/7 real, 3/3 synthetic paths) |
| 6 | Focal length of the app's photos | ✅ Done 2026-11-27 (2884 px; bolt-grid check median 2891) |
| 7 | Faces from base edges (supporting planes) | ✅ Done 2026-11-27 (AC 7: 4/4 signs) |
| 7b | Review fixes from the slices 3–7 review (spec "Slice 7b: review fixes": 4 decisions, docs, code, tests) | ☐ To do |
| 7c | Face outlines: ridge-line outlines, no overlapping faces, visibility test back, faces off the wall, faces under holds (from the human's overlay notes; see "Known issues" in the slices 5–7 entry, which calls this "slice 7b": split into 7b/7c on 2026-11-27) | ☐ To do |
| 8 | Gym trial 2 (also measure the 5 unmeasured trial-1 volumes) | ⏳ Waiting on the human |

**Needs from the human:** review slices 3–7 and `/checkpoint` (the reviewer subagent has reviewed them, 2026-11-27; findings are in spec "Slice 7b: review fixes"). Before committing, check `scan_trial_2026-11-27/` (review fix 16). At `/start-slice 7b`, the 4 decisions in that list; the go thresholds (spec AC 7); then gym trial 2 (bolt spacing 25 cm).

**Trial 1 findings** (from the saved scans, 2026-11-27; details in `backend/field_captures_volumes/scan_trial_2026-11-27/README.md`):
- **Line-up:** only the 2 successful scans have `frame_diagnostics`. In both, only burst photos 0–1 matched the photo; photos 2+ got 10–64 wall matches and were rejected. The 5 failed scans store only the error, because the `ScanError` fires before the diagnostics are returned, so each posed at most 1 photo. The human walked an arc, turned the phone to keep the volume centred, and lowered it after the photo; by photo 5 or so the wall is seen from 45°+ to the side. Some photos are blurred (104222's photos 2 and 5: Laplacian variance 28 at half resolution, vs 92–122 for its rejected photos 3, 6 and 7). But blur doesn't explain the rejections: sharp photos were rejected too. Every photo is matched only against the anchor photo, never against its neighbour.
- **Focal length:** `focal_35mm` is null in every scan. The app's photos are 3840×1776 (cropped to the screen's shape) with no focal-length EXIF, so `angle.focal_px` falls back to 26 mm on that crop's diagonal: 2542 px. If 3840 px is the full sensor width (iPhone 14 main, 26 mm), the real value is 2884 px, 13% more. The camera's own 4032×3024 photos give 3028 px, which is 2884 px scaled to 3840 wide. Unverified: a stabilisation crop would make it larger still. This also affects `/detect`'s wall angle.
- **Wedge (image 2):** both faces came out facing almost straight sideways ("right", `facing_deg` 72° and 95°), with the wrong signs. The second face had only 108 points. Could be a bad pose from 2 photos, the focal guess, or a sign bug on overhanging walls; slice 4 tells which.
- All scans were sent with bolt spacing 20 cm; the gym's is 25 cm. The same mistake happened on 2026-11-18 (`backend/field_captures/2026-11-18_*/NOTE_bolt_spacing.md`), when the app was set to 25. So the setting was changed back or the stored value was lost.

**For other issues:**
- #37: the human wants a rule on "volume vs macro (big hold)" for labelling. Image 4's pink volumes weren't detected. One try on image 3's small blue pentagon also didn't detect it as a volume.
- #36: the bolt spacing setting was back at 20 cm in trial 1 (see above). Worth checking in #36's Settings check that it persists.
- #55 (new, 2026-11-27): the whole-wall switch can be flipped while a submit is in flight, which does nothing. An agent is fixing it on `fix/55-whole-wall-switch` (the human allowed it this once).

**Checklist for trial 2:** bolt spacing set to 25 cm; measure each face from vertical with + / − as in trial 1; note which app face number each measurement belongs to.

**Docs to update when #38 is done:** `decisions.md` (trial-1 no-go and why; the line-up method; how the focal length is handled), `testing.md` (the replay tool and the trial scans as reference data), `architecture.md` if `volume_scan.py`'s pipeline changes.

## Rules for agents
1. At the start of a session, read Status and the newest log entry.
2. At the end of each slice (`/handover`), update Status and add an entry at the **top** of the Slice log using the template below.
3. Don't rewrite past entries. If one was wrong, correct it in the new entry.
4. Be specific: file paths, function names, exact test output. Write what the next session needs, not a diary.

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

## Slice log (newest first)

### 2026-11-27 · Slices 5–7: Chained line-up, focal length, faces from base edges

**Status:** Complete. The human asked for slices 4–7 to run without stopping. The reviewer pass for slices 5–7 **was not run** (to save usage); run it before `/checkpoint`.

**What changed** (all in `backend/wall_analysis/volume_scan.py` unless noted)

*Slice 5: line-up*
- `_line_up`, `_try_frame`, `_refine`, `_gated`, `_rectify`, `_wall_ncc` and `_wall_mask` replace the photo-only `_frame_pose` (whose decomposition is now `_pose_from_h`).
  - Burst photos are anchored to the photo directly, or chained from a neighbour up to 2 away.
  - Each is refined against the photo after being warped into its view (position-gated matches, 80 px then 20 px), jointly with posed neighbours.
- **Pose check:**
  - ≥ 30 inliers, ≥ 8 of them straight from the photo
  - wall NCC ≥ 0.08
  - NCC **peak** ≥ 0.06 over the pose nudged 12 px. A level alone couldn't separate correct oblique poses (0.11–0.24) from wrong frontal ones (up to 0.23).
  - A frame that fails only the NCC check still links a chain.
- `MAX_BASELINE_CM` 300 → 500 (users walked about 3 m).
- Diagnostics: `source_frame`, `photo_inliers`, `wall_ncc`, `wall_ncc_peak`, `linked_from`, `turn_deg`, "bad pose" reason; `wall_inliers` is now kept on rejected anchors. The result has `wall_features`.
- A blur gate was tried and removed (sharp and blurred frames overlap).
- `experiments/two_photo/synth.py`: `burst_positions` with `path` step / arc / height; `frame_baseline_cm` / `frame_turn_deg` returned; render noise seeded with crc32, not `hash()`.

*Slice 6: focal length*
- `_focal_px`: with no EXIF, 26 mm over a full 4:3 sensor's **long side**, giving 2884 px for the app's 1776×3840 photos (was 2542). This is the same as before for 4:3 photos. `angle.focal_px` is untouched, so `/detect` doesn't change (AC 4).
- `_focal_check`: the bolt grid seen at an angle gives a cross-check, returned as `focal_check_px`, plus `focal_px`.

*Slice 7: faces*
- `_base_edge_faces`: for each edge of the simplified outline (it must be on the wall: the band's 25th-percentile height ≤ 8 cm), the face is the supporting plane through that edge.
  - It uses only the raised points nearest that edge in the photo.
  - Tilt: the 95th percentile, then the median of the points within 4°.
- Faces carry `method` ("base_edge" / "surface") and, for base-edge faces, `base` (the edge's two points).
- The dense plane fit still runs on the points left over (it's needed for faces that don't meet the wall, like a box's front), and skips duplicates within 8°.
- There's no "turned away from the camera" test: a matched face is seen.

*Also changed*
- Reviewer slice-4 fixes:
  - inliers kept on rejected frames
  - one-to-one pairing at > 50% share
  - crash-safe replay, with per-scan isolation and null angles
  - model-stamped detection cache, written only under `SCANS_DIR`
  - `needed` counted after thinning
  - non-finite baseline handled
  - hull-area polygon check
  - doc fixes
- `accuracy_checks/eval_volume_scan.py`:
  - base-edge faces pair by a point 10 raster px inside their base edge;
  - measured faces are shrunk 1 px so a shared border isn't counted twice (the Tester's 50/50 case);
  - prints photo inliers, NCC/peak, turn, chain source, focal and its check.
- `truth.json`: the wedge's polygons were redrawn. The first drawing was 0.012 too high and lay mostly over the wall. The pyramid's were checked against the photo and are correct.
- Tests (Tester): the slice-5 contract, synthetic step / arc / height sweeps (AC 6), and stricter pairing tests.

**Results**
- Tests: `uv run python -m pytest` → **921 passed, 2 skipped, 2 xfailed**. Slow synthetic: 23 passed, 1 skipped; AC 1 still met.
- **AC 6:**
  - Real scans: **6/7** (6/7, 8/8, **5/8**, 9/9, 8/9, 9/9, 7/9). The pyramid misses one: 2 blurred frames, and the last 2 too oblique.
  - Synthetic: every frame on all 3 paths, worst errors 0.11 cm / 0.05° (arc to 45°, 191 cm).
- **AC 7: 4/4 signs right.**

  | Face | Actual | Now | Error |
  |---|---|---|---|
  | Pyramid, left | −48° | −37.5° | 10.5° |
  | Pyramid, right | +7° | 0.0° | 7.0° |
  | Pyramid, bottom | +30° | +62.5° | 32.5° |
  | Wedge, top | −40° | −38.4° | 1.6° |
  | Wedge, bottom | +53° | +76.8° | 23.8° |

  Median 10.5°. **Down-facing faces read too steep** (+20–30°).
- Wall angle on the wedge: 29.0° (measured 30°; was 26.9° with the old focal).
- Focal cross-check across scans: 3061, 2593, 3107, 2717, 2891, 2890, 6143. Median 2891 vs 2884 used.
- Accuracy checks: not needed (`angle`, `scale`, `bolts` and `detection` were unchanged). `eval_field` was run before the focal work for reference: angles median 1.2°, p90 3.5°; distances 9/9.

**Decisions** (recorded in spec: yes)
- Chained line-up with a peak-NCC pose check.
- The focal fallback uses the long side, inside `volume_scan` only.
- Faces from base edges. Dense planes can't work on smooth plastic: only ridges match.

**Questions for the human**
1. The go thresholds for trial 2 (AC 7). On trial 1's 5 faces: sign 4/4, median error 10.5°, worst 32.5°.
2. Do the replay overlays (`<temp>/eval_volume_scan/*.jpg`) and `truth.json`'s face outlines look right to you? The pairing depends on them.
3. Is there a 3rd image-3 scan on the laptop?
4. The Tester's spec questions: is `linked_from` a `frame` or `source_frame` index (they're the same unless more than 12 were sent)? Should AC 1 also be tested on arc / height sweeps?

**Known issues / context for the next session**
- Down-facing faces are too steep: the 95th percentile on underside points picks up stray high matches. Try a lower percentile, or a ridge line fit, once trial 2 adds more measured faces.
- The base-edge thresholds were tuned on only 5 measured faces. Trial 2 is the real test.
- The app doesn't show `method` / `base` yet; it ignores the extra keys.
- Before trial 2: set bolt spacing to 25 cm in the app.
- For #36: `/detect`'s `angle.focal_px` has the same 13% focal error on app photos. Its wall angle tested fine (median 1.2°), but it is worth a look.
- **The reviewer hasn't seen slices 5–7.**
- **Human check of the replay overlays (2026-11-27):** the two measured scans' overlays (104222 pyramid, 110448 wedge) are correct. The other 5 (103720, 103832, 111637, 111917, 113654) are **inaccurate**. Those have no measured faces, so their app faces are unscored and AC 7 doesn't see them. Scoring on 2 volumes overstates the method. For trial 2, measure these volumes too (they're still on the wall), so `truth.json` covers all 7.
  - **The human's notes per overlay, with the likely cause in the code:**

    | Scan | What the human saw | Likely cause |
    |---|---|---|
    | 103720 | Pink and blue correct. Yellow overlaps other faces and is in the wrong place. | Yellow is probably a `surface` (dense-fit) face fitted to leftover points. The duplicate check compares normals, not position. |
    | 103832 | Blue semi-accurate but too large; pink too small; much of the volume covered by neither. | Outlines are the hull of each edge's "nearest edge" region. That isn't the real face boundary when the apex is off-centre, and edges that fail the on-wall check leave their part of the volume uncovered. |
    | 111637 | The right number of faces, except the central face is missing. Red almost correct; blue and green blocked by holds. | The central face doesn't meet the wall, so only the dense fit can find it, and that fails on smooth plastic. Hold masks cut points out of the faces. |
    | 111917 | A much worse version of 111637: faces missed, lots of overlapping faces. | Same as 111637, plus overlapping `surface` faces. |
    | 113654 | The right faces, but in the wrong places and sizes. Some faces visible in the burst but not in the photo probably throw it off. | Points from faces hidden in the photo (seen only by the burst photos), and slice 7 dropped the "turned away from the camera" test. |
  - **Next code steps** (a slice 7b, before or alongside trial 2):
    1. Outline each base-edge face by the **ridge lines** (3D ridge points projected into the photo), not by nearest-edge regions.
    2. Drop `surface` faces whose outline mostly overlaps an existing face.
    3. Bring back the visibility test with a tolerance (e.g. allow 15° past edge-on), so hidden faces are dropped without losing the pyramid's bottom.
    4. Faces that don't meet the wall (front faces, like the pentagon's centre): the plane through the 3D ridge lines that bound them.
    5. Hold-covered faces: fill the outline across the hold mask.

**Human:** Reviewed: no · Notes:

### 2026-11-27 · Slice 4: Replay tool, baseline, sign check

**Status:** Complete

**What changed**
- `backend/accuracy_checks/eval_volume_scan.py` (new, dev-only): replays saved scans through `scan_volume`.
  - Prints a per-photo table (matches, inliers, baseline, sharpness, used, reason), the AC 6 line-up verdict, and each measured face paired with an app face (`pair_faces`: by position, using `truth.json`'s face polygons), with error, sign and outline IoU. It ends with an AC 6 / AC 7 summary.
  - Options: `--as-sent` (the app's 20 cm spacing), `--focal-35mm`, `--json`, `--out` (overlays; default `<temp>/eval_volume_scan`).
  - YOLO detections are cached in `<scan>/replay_detections.json`, inside the gitignored scans folder.
- `backend/field_captures_volumes/scan_trial_2026-11-27/truth.json` (new): the measured faces, with approximate face outlines drawn from the photos. The pyramid's apex is at the bolt; the wedge's ridge was read from a brightened crop. Bolt spacing is 25.
- `backend/wall_analysis/volume_scan.py`:
  - `ScanError(message, diagnostics=None)`. The line-up failure now carries the per-photo list.
  - Diagnostics gain `sharpness` and a `reason` (too few wall matches / inliers, baseline too short / long).
  - `_match` uses brute force instead of FLANN (see Decisions). Only the photo's wall features are matched.
  - `_polygon_mask` rejects outlines under `MIN_POLYGON_AREA_PX` (100 px²). The Tester found a collinear polygon gave a 200 with no faces.
- `backend/api/main.py`: a line-up failure's diagnostics are saved in `scan.json` as `frame_diagnostics`.
- Tests (Tester subagent): a "slice 4" section in `backend/tests/test_volume_scan.py`, and the new `backend/tests/test_eval_volume_scan.py` (65 tests for `pair_faces`, `lineup_needed` and `truth.json`).
- `spec.md`: the slice-4 contracts.

**Results**
- Tests: `uv run python -m pytest` → 888 passed, 1 skipped, 2 xfailed. The new files alone: 122 passed, 1 skipped (fast); 14 passed, 1 skipped (slow).
- **Trial-1 faces were noise.** With the old FLANN matcher, the same scan gave different results depending on the C library's `rand()` state. Seeding it 0–5 gave the pyramid's right face as −6.7°, +7.0°, +6.4°, +5.0°, +5.5° (actual +7°). The wedge lined up 1 or 2 photos depending on the seed. The two photos that lined up in each successful scan were about 1 cm apart, so only one real extra viewpoint.
- **Sign check:** the synthetic overhanging scenes (`s_wedge_over35`, `s_box_over20`) pass AC 1 (all faces within 6°, so the signs are right). On real data, with deterministic matching, the "flips" don't hold up: the wedge's +67° face lies mostly on the bottom face (+53°), so the screenshot's top/bottom reading was a guess. **No sign bug found;** the line-up is the cause.
- Baseline (deterministic, 25 cm, `uv run python -m accuracy_checks.eval_volume_scan`):
  - **AC 6: 0/7 scans** (0/7, 1/8, 2/8, 1/9, 1/9, 1/9, 0/9).
  - **AC 7: 2/4 signs right.** Pyramid: left −48° → −39.6°; bottom +30° → +7.2°; right not found. Wedge: scan failed.
  - `--as-sent` (20 cm) gives the same line-up.
- Accuracy checks: not needed. Scale, angle, bolts and detection weren't changed, and `/detect` doesn't use `volume_scan`.

**Decisions** (recorded in spec: yes, the contracts)
- **Brute-force matching, not FLANN:** deterministic, so the replay can compare slices. It's fast enough because only the photo's wall features (a few thousand) are matched: 3–5 s per scan.

**Research for slices 5–7** (prototypes in the session scratchpad, not repo code):
- **Line-up (slice 5).** Prototype:
  1. Link each burst photo to a posed neighbour (homography on all features, up to 3 planes tried).
  2. Warp it into the photo's view.
  3. Re-match the photo's wall features with a position gate (80 px, then 20 px), jointly with the neighbour's wall features mapped into photo coordinates.
  4. Weak direct matches (≥ 12 inliers) are accepted as anchors only if the rectified re-match confirms them.

  Line-up per scan: 7/7, 8/8, **5/8**, 9/9, 9/9, 9/9, 7/9. That's 6 of 7 scans passing AC 6, with walks up to about 3 m.
- **Focal length (slice 6).** From the bolt grid seen at an angle in the lined-up photos, the focal length comes out at about 2700–2900 px. The 26 mm fallback gives 2542 px; 26 mm on a full-width 4:3 sensor gives 2884 px. With 2884 px, the wedge gave +52.5° (actual +53°) and the wall 29.0° (actual 30°, was 26.9°).
- **Faces (slice 7).** The sweep's depth maps show the faces have **no matchable texture** (smooth plastic): only edges and ridges match. Dense plane fitting can't work on real volumes; the synthetic scenes passed because their faces are speckled. Prototype instead: for each edge of the base outline (on the wall, so known in 3D), the face is the *supporting plane* through that edge. Its tilt is the 95th percentile of the angle up to the confident raised 3D points (the ridges). **All 4 counted faces get the right sign** (errors 5.7°, 6.3°, 29.7°, 10.2°, 19.0°).

**Questions for the human**
- None new. The go thresholds (AC 7) are still open.

**Known issues / context for the next session**
- `synth.py` seeds its render noise with Python's `hash()`, which changes per process. That makes `test_synthetic_depth[s_wedge_over35]` skip sometimes (depth null). Fix in slice 5, when `synth.py` gets arc / height sweeps.
- The 3rd image-3 scan is still unaccounted for.

**Human:** Reviewed: no (working through slices 4–7 on the human's go-ahead) · Notes:

### 2026-11-27 · Slice 3: Gym trial 1 and write-up

**Status:** Complete. Trial 1 is a no-go (the human's decision); #38 carries on with slices 4–8.

**What changed**
- `backend/field_captures_volumes/scan_trial_2026-11-27/`:
  - New. The human's screenshots (PNG converted to JPG), two camera photos with GPS EXIF removed, and the gym notes, verbatim.
  - `README.md`: the per-face results table, the scan-to-photo mapping, and app face numbers.
  - Moved here from the untracked `backend/volume_scan_test/`, which was then deleted.
- `backend/field_captures_scans/2026-11-27_*` (7 scans): copied from the laptop by the human. Gitignored, and kept out of git by the human's decision.
- `spec.md`:
  - Goal: the no-go note.
  - Inputs: any movement.
  - AC 5 superseded; new AC 6 (line-up, real and synthetic) and AC 7 (face signs on trial 1).
  - Trial-1 reference data.
  - Slices 3–8.
  - Decisions dated 2026-11-27; the SIFT-not-ASIFT decision revisited.
- `handover.md`: Status for slices 3–8, trial-1 findings, notes for #36, #37 and #55, a checklist for trial 2, and the docs to update at the end.
- `milestone.md`: #38 ▶; "Needs from you" item 3; #55 row; the "why this order" line for #37/#38.
- GitHub: issue #55 opened (the whole-wall switch). At the human's one-off request, the worktree `.claude/worktrees/fix-55-whole-wall-switch` was made on the new branch `fix/55-whole-wall-switch` (from `origin/main`, upstream unset), and an agent is fixing #55 there.

**Results**
- Tests: `uv run python -m pytest` → 799 passed, 1 skipped, 2 xfailed (5 min 38 s). No code changed.
- Against the done-when: the results table is logged. Trial 1: 4 of 5 measured faces found; 3 of those 4 had the wrong sign; at most 2 burst photos lined up per scan; 5 of 7 scans failed at line-up.

**Reviewer** (14 concerns; fixed with the human's standing go-ahead for this issue):
1. GPS EXIF in the two camera photos, in a public repo → removed in place (byte-level, no re-encode; focal EXIF kept).
2. Image 1's right face: the note's order was reversed silently → footnote added; the human confirmed +7°; the sign mismatch is now counted in the spec.
3. Image 5 was detected (the scan has its outline) → the #37 note is limited to image 4 and one image-3 try.
4. AC 6 wasn't measurable → it's now 75% of each scan's photos, a pose check, and synthetic arc / height / step sweeps with known poses.
5. AC 7 conflicted with AC 5 and had no dead-band → AC 5 superseded; 10° dead-band; missed faces count as wrong; checked at every slice.
6. Truth wasn't machine-readable → `truth.json` is part of slice 4; the README now has app face numbers.
7. The line-up and blur claims went beyond the data → reworded (only 2 scans have diagnostics; blur doesn't explain the rejections).
8. The third image-3 try isn't saved → footnote; question for the human below.
9. Stale spec text (Inputs, SIFT decision) → updated.
10. 12% → 13%.
11. Image 0 (103720) description → corrected (panel join, whole-wall distance).
12. The bolt spacing was wrong again → notes for #36 and the trial-2 checklist.
13. Milestone wording → #55 row and the "why this order" line updated.
14. The measurement convention → recorded as confirmed by the human.

**Decisions** (recorded in spec: yes): trial-1 no-go, keep working in #38; depth from any movement; scans stay out of git.

**Questions for the human**
- The "go" thresholds for face angles (AC 7 question).
- Image 3: is a third scan folder on the laptop? If not, a save failed silently (an AC 2 bug).

**Known issues / context for the next session**
- Slice 4 starts from `volume_scan.scan_volume`. Matching is photo-to-frame only (`volume_scan.py` lines 277–295). The `ScanError` at line 296 drops `diagnostics`.

**Human:** Reviewed: no (working through slices 4–7 on the human's go-ahead) · Notes:

### 2026-11-25 · Slices 1–2 (before this doc existed)

The slices 1–2 entry is in `docs/features_deprecated/wall_size_hold_distance_handover.md` under "Volume scan test feature: slices 1–2". Read it before the trial write-up.
