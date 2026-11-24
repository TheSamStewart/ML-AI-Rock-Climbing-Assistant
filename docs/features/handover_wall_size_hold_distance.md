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

### 2026-11-20 (later) · `wall_size_hold_distance` · Slice 6b: step 2 continued - synthetic re-run and first real-photo run

**Agent:** `Developer`
**Status:** `Partial` - the volume code is unchanged. Two scoring tools were added, and two problems were found that need a decision before any fix.
**Spec:** `docs/features/wall_size_hold_distance.md`

#### What changed
- `backend/eval_volume_field.py` (new, dev only): `volume.py` on **real** photos. It takes a capture folder (`photo.jpg` + `truth.json`, `capture.json` optional) and runs three paths. **full** is `fit_volume` on YOLO's *raw* mask, re-run because the saved polygon is simplified at 0.005 and drops the corners a box or wedge needs. **oracle** is the right fitter on hand-clicked corners. **depth** is the oracle with the measured depth passed as `height_cm`, which answers the open pyramid question with real data. Gravity comes from the sensor when there is a reading. Otherwise it is solved from the measured wall angle beside the volume, assuming no roll. `--survey` fits every VOLUME detection with no measurements needed. The `truth.json` `volumes` schema is in the module docstring. Overlays (one crop per volume, plus `__ids.jpg` with detection ids) and `results.json` go to `<temp>/eval_volume_field`.
- `backend/draw_volume_corners.py` (new, dev only): an OpenCV clicker. Left-click = base corner, right-click = raised corner. It writes `base_px` / `raised_px` into the folder's `truth.json`. Only smoke-tested headless, not driven by hand yet.
- No change to `volume.py`, the API or any tests.

#### Test results
- `uv run pytest tests/test_volume.py -q` -> 58 passed. `uv run pytest -q` -> **699 passed, 2 xfailed** (641 + the 58 volume tests).
- **Tester's synthetic re-run after fixes 6-9** (`fakewall.py` + `eval_volume.py`, log not kept in the repo):
  - Trusted fits: 73/81 faces, steepness **median 0.1°, p90 1.7°, max 8.3°**, 0 sign flips. Facing bucket 1.00 of the faces scored, **0.90 of all reportable** (the 8 missing are faces that trusted fits did not produce). The go/no-go prints FAIL on that line by a hair.
  - Full ungated: 141/208 faces, median 0.3°, 2 flips. Oracle: 198/208, 0.0°.
  - **Timing: median 87 ms per volume with ridges** (was 535 ms). The crop fix worked.
  - Gate at 0.05 + border: keeps **7 unusable** and rejects 4 usable out of 125. This is worse than the earlier entry's figures, and two of the seven are the dangerous kind (next section).
- **Real photos, `eval_volume_field.py --survey` over all 15 field captures:** 62 VOLUME detections, 60 fitted, **10 trusted - every one a centroid-assumed pyramid.**

#### Findings
1. **The gate trusts outline-apex pyramids that are badly wrong (real data).** Of the 10 trusted real fits, the 7 whose apex came from an outline corner include depths of **55, 72, 73, 92 and 119 cm**, on base edges of 21-115 cm (e.g. `173610` det21: 92 cm deep on a 24 cm base). `171935` det20 is a scooped wedge-like volume read as a 119 cm pyramid at `reprojection_norm` 0.012. Cause: a centroid-anchored pyramid has 2 equations for 1 unknown, so an apex at almost any outline corner is self-consistent, and only `MAX_DEPTH_CM = 120` limits it. The fits whose apex came from **ridges** (`172513` det41, `171935` det4: about 9 cm deep on a 27 cm base) look right on the overlay.
2. **`fit_box_partial` (fix 9) assumes the wrong silhouette.** Experiment 11 shows a two-face box reaches the outline as **2 base + 4 top**, not 4 base + 2 top. As a result, boxes are right in 2/16 cases, and the 2B+4T reading would recover 9 more exactly (ceiling 0.0° error).
3. **The half-cylinder now passes the gate.** It comes back as a `wedge` at `reprojection_norm` 0.022, trusted, with 19.7 cm of height error. Before fix 6 it was a pyramid at 0.142 and suppressed. Fix 6 made curved volumes fit as wedges.
4. Wedges: 9/15 now, 15/15 with perfect corner selection (experiment 11). This confirms the earlier entry's "corner selection is coverage, not accuracy" point.
5. **Real volumes are often not ideal solids.** The `174933` black volumes are long multi-faced blades, and YOLO labels them HOLD (ids 9, 14, 21). No family fits them, and they fall into the gate's "no answer" bucket.
6. **The capture tool is gone.** `backend/field_capture.py` and `/dev/test-capture` were removed on 2026-11-18 and never committed (`git log --all` has no record of them). The previous entry's "capture through the app" cannot be followed as it stands.

#### Decisions made
- **Human, 2026-11-20:** the agent decides the volume internals itself, judged on user experience, app performance and accuracy (accuracy weighs heavily, and there is plenty of development time). The answers to the previous entry's four questions:
  1. Pyramid depth: "figure out a way". Research is under way (see below), not decided yet.
  2. New dev files in `backend/`: yes.
  3. A volume that is not trusted: **say nothing**. The LLM gets nothing about it, and the end user does not see volume angles at all for now.
  4. Curved volumes: rare. Say nothing about them.
- **Fix 1 applied:** `fit_volume` sets `guessed_apex` and never trusts a centroid-assumed pyramid whose apex is an outline corner (also recorded in spec: no)
- **Fix 2 applied:** `fit_box_partial` rewritten for the real 2-base + 4-top silhouette, with a parallelogram check on the hidden base included in `reprojection_px`. Before rewriting it, exact boxes were projected from 20 viewpoints: every outline was 3B+3T, 2B+4T, or the head-on 4T, where height cannot be seen (also recorded in spec: no)
- **Fix 3 not applied, deliberately:** two single-photo curved-volume tests were measured on the synthetic corpus and neither separates cleanly. (a) Outline bulge from the fitted silhouette: half-cylinder p90 0.023-0.029, good fits under 5 px noise up to 0.023. (b) Shading crease, the brightness jump across predicted interior edges divided by the slope beside them: half-cylinder 1.5-1.7, low-contrast wedge 1.9, dark box 2.1. A threshold that tight would fail on real lighting and would also drop good low-contrast volumes. Scratch scripts are not in the repo.

#### Results after fixes 1-2
- `uv run pytest -q` -> **704 passed, 2 xfailed** (the whole suite, after fixes 1-2).
- `uv run pytest tests/test_volume.py -q` -> **63 passed**. The old `test_box_with_only_two_faces_visible_is_still_solvable` fed the impossible 4B+2T outline, so it was **rewritten**: it now takes the outline from the projected hull at 4 viewpoints. Two tests were added: `test_fit_volume_finds_a_two_face_box_from_its_mask` and `test_a_pyramid_whose_apex_is_only_an_outline_corner_is_never_trusted`. **Tester: please review these three, since this file is yours.**
- Synthetic (`eval_volume.py --experiment family gate gonogo`): right family 30 -> **37/66**; boxes 2 -> 8/16, box median steepness 3.1° -> 0.1°; full-path sign flips 2 -> **0**; trusted faces 73 -> **83/91**, p90 1.7° -> 0.9°, bucket 0.91. Still trusted and unusable: 7 of 125 - the half-cylinder, three off-centre or off-axis pyramids (5-10 cm height error, the centroid assumption), and three noise artefacts.
- Real (`eval_volume_field.py --survey`): trusted 10 -> **5/62**, all ridge-apex triangular pyramids, 8-17 cm deep. Every 55-119 cm fit is gone.

#### Pyramid depth: what is being investigated
- A two-photo simulation (scratch, not in the repo) at 300 cm, with the tip at 25 cm and 3 px tip noise. With exact poses, a 40 cm step gives 2.4 cm median error and 60 cm gives 1.7 cm. With each photo's pose estimated **independently** (0.5° rotation error) it gives 8.5 / 4.9 cm. Rotation error dominates, so a two-photo method only works if the two poses are solved **jointly**, from the bolt holes both photos share.
- Two research agents are running: manufacturer volume dimensions (a depth/base prior, and how common curved and blade volumes are), and techniques (shading under gym lighting, surface-normal networks, two-view, phone depth hardware, curved-volume detection).

- **Capture route (human, 2026-11-20):** the phone's normal camera, saved as JPEG, with the measurements written in notes. The agent transcribes the notes into each folder's `truth.json`. Gravity is solved from the wall angle measured beside each volume, assuming the phone is held upright in portrait. Each volume also gets a second photo from about 50 cm-1 m to the side, as real data for the two-photo method.
- **Technique research (agent report):** shading alone cannot recover pyramid height (the generalised bas-relief ambiguity under unknown lighting). The ranked options are: (1) two photos, triangulating the apex, with poses solved jointly from shared bolts; (2) a surface-normal network (DSINE / Metric3D v2 / MoGe-2, MIT/BSD licences, verify) as a single-photo fallback, needing real validation; (3) a curved class in the YOLO retrain to detect curved volumes. Depth networks, cast shadows and phone depth hardware were ruled out as primary routes.

- **Volume-dimensions research (agent report, sources: Nicros 2025 catalogue PDF, Atomik product pages, Anatomic, EP 2025-09 PDF, Walltopia macros PDF, Smog/Samsara/Volx via Oliunid, Rockcandy; Kilter, Volx, Xcult, Teknik and Cheeta could not be fetched):**
  - Pyramid depth ÷ longest base edge: median 0.33, p10-p90 0.25-0.45, deeper for small volumes (about 0.42 under 30 cm).
  - **About half of pyramid products are sold as offset or asymmetric**, with the apex about 15-25% of the base span off centre. Offset designs are shallower (Nicros: 0.25 vs 0.33 on the same footprint).
  - Wood ranges are all flat-faced; fibreglass/ABS "macros" are mostly curved. Long blades are common in big plywood lines (D/E 0.1-0.2).
  - Atomik publishes face angles per product, so its volumes would make good bought-in test pieces.
- **Decision (agent, under the human's rule above): no centroid-assumed pyramid is trusted from one photo, ridge apex or not.** Offsets of 7-12 cm on a 50 cm base become 15 cm or more of height, and the depth prior's spread still leaves about 7° of face error. `fit_volume` adds `centroid_assumed`. `eval_volume.oracle_fit` and `eval_volume_field._finish` apply the same rule. Boxes and wedges are unaffected (also recorded in spec: no).
  - Effect, synthetic: still trusted and unusable 7 -> 4 of 125, and **the only full-path one left is the half-cylinder**; the other three are oracle+noise artefacts. Trusted coverage falls from 83/91 to 35/43 faces, because the corpus is mostly pyramids. Trusted steepness median 0.3°, p90 0.8°.
  - Effect, real: the 5 trusted fits on the field captures were all pyramids, so **no volume in the existing captures is trusted now**. They contain no clean box or wedge.
  - `uv run pytest tests/test_volume.py -q` -> 63 passed.

#### Recommendation for pyramid depth (agent)
1. **Primary: two photos.** When a pyramid is detected, the app asks for a second photo about 50 cm-1 m to the side. Both poses are solved jointly from the shared bolt grid and the apex is triangulated. The human's B photos test this on real volumes before any app change. Prototype next: render a second camera in `fakewall.py` and add joint two-view pose plus apex triangulation.
2. **Fallback: a surface-normal network** (DSINE, MIT - verify), for when there is no second photo. It needs a new dependency and model weights, so ask the human first, and validate it on the measured volumes before trusting it.
3. **Curved volumes:** a "curved" tag in the volume relabelling.

#### Surface-normal network, tried on its own (human approved, 2026-11-20)
- Metric3D v2 ViT-Small (BSD-2) in a **separate** environment; nothing was added to `pyproject.toml`. Setup, the two local patches (no mmcv, CPU) and the scripts are in `backend/experiments/surface_normals/README.md`.
- **CPU time: about 3.3 s per photo**, one pass per photo shared by every volume. That is too slow for production as it stands (`/detect` is already 6.6-15.3 s), so it would need ONNX or quantising.
- **Real walls (15 captures, 641 points): median 8.4°, p90 15°**, and biased - it under-reads overhangs (25.8° read as 8.1°).
- **Synthetic: not usable for judging it.** The network sees the renders' volumes as flat (faces 3° off the wall against a true 45°), while on real photos it clearly separates the faces.
- **Real ridge-apex pyramids (5, no ground truth):** network depth 5-11.5 cm, against 8.4-17.5 cm from the centroid assumption and 8.7-14.3 cm from the catalogue median. It is always at or below the centroid figure, and one hits the 5 cm floor. The wall-ring correction needed is 8-19°.
- **Verdict pending the measured volumes.** If it is not within a few degrees on real faces, drop it and keep the two-photo route.

#### Questions for the human
- None blocking. Later: the app change for the second photo, once the real B photos show it works.

#### Context for the next session
- Score the measured volumes with: `cd backend && uv run python eval_volume_field.py field_captures/<folder> ...`. Run with `--survey` on any new photo first, then read detection ids off `<temp>/eval_volume_field/<folder>__ids.jpg`.
- HEIC is not readable (no `pillow_heif`). Photos must be JPEG.
- `results.json` from the survey run is in `%TEMP%\eval_volume_field\`. It is regenerable.

#### Next slice
- After approval, apply fixes 1-2, re-run `eval_volume.py` and the survey, then score the human's measured volumes. Step 3 (plumbing) still waits on that.

#### Human
- Reviewed: `no`
- Notes:

---

### 2026-11-20 · `wall_size_hold_distance` · Slice 6b: volume face angles, step 2 (feasibility)

**Agent:** `Developer`
**Status:** `Partial` - built, and the gated path passes all three go/no-go bars on synthetic data. **Real measured volumes are the blocker**: nothing here has been scored against a real volume, and only `174933` has a measured face angle.
**Spec:** `docs/features/wall_size_hold_distance.md`

#### The plan this entry sets up

Two tracks run at once, deliberately:

| Track | Who | What |
|---|---|---|
| Relabelling for the volume retrain | Human | `volume_retrain.md` steps 3 and 6, unchanged |
| Slice 6b geometry on synthetic data | Agent | This entry. Needs **no** retrained model, because every method here takes a volume mask as *input* |
| Measured real volumes | Human, next | Section "What to measure" below. The go/no-go cannot be scored without it (only `174933` has a face angle today) |

The serial dependency assumed on 2026-11-19 ("6b is no use until the model finds volumes") only applies to step 1 (spotting a hold on a volume). The face-angle maths can be developed and scored against hand-drawn or synthetic masks first, so it is, and the retrain is no longer on its critical path.

#### What changed

- `backend/volume.py` (new, dev-facing maths only - **no API or payload change yet**, step 3 is still unstarted):
  - `wall_plane(lattice, point, K, spacing_cm)`: the wall as `(n, d)` in cm from `scale.panel_homographies`, promoted from the 2026-11-19 scratch script that read +16.4/+12.5 against the app's 16.1-16.4/12.6. `axis_ratio` (the square grid's two axes, which must come out equal) is kept as a free quality check, and `trusted` gates on it. Unlike `angle.py`'s per-bolt metric this split has **no mirror twin**, so it may also be the fix for the slab/overhang mix-up (still open from 5d).
  - `backproject` / `project` / `point_at_height` / `height_of`: exact pixel <-> cm on a known plane.
  - `fit_box`, `fit_ridge`, `fit_pyramid`: the three shape families. `fit_volume` orchestrates - reduces the outline to its dominant corners, finds the apex from interior ridge lines, tries each family, scores by outline IoU.
  - `ridge_segments` + `converge_point` (idea 2): LSD inside the mask, shrunk first so the outline boundary does not swamp it, then the point most ridge lines pass through. Volumes are matte and single-coloured, so a ridge between two faces is a brightness step even with no texture. No new dependency - LSD is in the cv2 that ultralytics already pulls in.
  - `describe_face`: steepness **and** facing (left/right/out), per the human's 2026-11-19 decision that a sideways face climbs like a sidepull.
  - `hold_face`: which face a hold sits on, and its `standoff_cm`. This is the lever on slice 8 part 1 (`173933`, +19%).
- `backend/tests/test_volume.py` (new, 47 tests, written from the contract rather than the code in the Tester's spec-only style): the exact-geometry guarantees per shape family, the sign conventions against `angle.py`'s, `hold_face`'s standoff, outline reduction and ridge convergence. Two of them assert the *limitation* rather than working around it - `test_outline_cannot_see_how_far_a_volume_stands_off_the_wall` builds two pyramids of very different heights that project to identical outlines, and `test_pyramid_offcentre_apex_is_amplified_and_the_residual_hides_it` pins the amplification and the fact that the residual understates it. Not added to `docs/testing.md` yet (that doc is frozen until End).
- **Bug found and fixed while writing those tests:** a non-finite pixel from a degenerate mask reached `np.linalg.svd` inside `_solve_height` and raised `LinAlgError` out of the fitter instead of returning "no fit". All three fitters now reject non-finite input. This would have surfaced as a 500 from `/detect` once plumbed in, so it was worth the test.
- **Then five more, from the Tester's synthetic evaluation** - see that section below for what each one was. The fixes added `outline_from_mask` and `fit_box_hexagon`, rewrote `ridge_segments`' filter and crop, rewrote `fit_volume`'s wedge and box enumeration, changed its ranking from IoU to normalised reprojection, and made `describe_face` report facing as `"undefined"` near horizontal. `MAX_REPROJECTION_FRACTION`, `VOLUME_SIMPLIFY_EPS` and `FACING_UNDEFINED_STEEPNESS_DEG` are new constants.
- `.gitignore`: `backend/fakewall_out/` (344 MB of regenerable synthetic scenes).

#### The finding that reshapes the slice

**One scalar per volume is not visible in one photo, and it is the one that matters.**

A raised vertex seen at one pixel lies somewhere along one ray; sliding it along that ray does not move its projection. So the outline is *identical* for every height, and so are the interior ridge lines (they join base-corner pixels to the apex pixel whatever the height). Outline IoU therefore cannot rank height at all - only which pixels are base and which are raised.

Each fitter instead pins the height from an **anchor**: a known in-plane point the raised vertex stands over. That is what separates the families, and it is the whole result:

| Family | Anchor | Observed or assumed? | Consequence |
|---|---|---|---|
| Box / riser | the base corner below each top corner | **observed** | solved exactly, 2x4 equations for one unknown |
| Wedge | midpoints of base edges `base[1]-base[2]`, `base[3]-base[0]` | **observed** | solved exactly |
| Pyramid | the base centroid | **assumed** | an apex off-centre by `e` cm gives a height error of about `e / tan(a)` |

`a` is the angle between the apex ray and the wall normal: about 10° near the middle of the frame, so a **6x amplification** there, falling towards 1x at the frame edges. Measured on exact geometry: an apex 5 cm off-centre, near the optical axis, came back 27 cm too tall and its faces 17° out, while the least-squares residual stayed a reassuring 2.6 cm. So `fit_pyramid` reports `offcentre_gain` and the residual must **not** be trusted as the quality gate.

A first attempt pinned the wedge from its ridge being parallel to the base edge below it. That is structurally degenerate - both ridge ends share one height, so the ridge direction is `(d + h)(u2 - u1)` for *any* `h` - `det(A)` came out exactly 0. Removed and replaced with the midpoint anchors above. Recorded so it is not retried.

**What this means for the slice:** boxes and wedges look like production candidates on geometry alone. Single-apex pyramids need one extra cue, and the candidates are (a) the catalogue/aspect prior (standard volume depth as a fraction of base size), (b) the photometric cue - two faces of one volume share their paint, so their brightness ratio is a direct function of the height, which is exactly one constraint for exactly one unknown, (c) the user typing it (friction). Every fitter already takes `height_cm=...` to accept such a cue, so adding one is a small change, not a rewrite. **This needs the human's decision before step 3.**

#### Test results

- Command: `cd backend && uv run pytest tests/test_volume.py -q`
- Result: **47 passed**. Wall back-projection round-trips to 1e-14 cm. All three fitters recover every face normal to **0.00°** and the height exactly, across wall angles -10° to +30° and camera pitch 2° to 15°. `hold_face` returned a 15.0 cm standoff against a true 15.0 cm. `describe_face` reads a known sidepull as `facing: left/right` at 90° with steepness 0, and a face parallel to the wall reports the wall's own angle with `angle.py`'s sign convention.
- Command: `cd backend && uv run pytest -q` (the whole suite, to check nothing regressed)
- Result: **641 passed, 2 xfailed** - unchanged from before this slice. `volume.py` is standalone and imports `scale` lazily, so nothing else moved.
#### Synthetic evaluation (Tester, 2026-11-20)

- `backend/fakewall.py`: renderer plus exact ground truth. 25 scenes, 66 volumes, 208 visible faces, at the field phone's frame and lens, with a real centred-square 25 cm bolt grid, plywood grain, and Lambertian lighting. Covers all four families plus a half-cylinder; apex offsets 0-24 cm; five-position off-axis sweeps; walls -10° to +40°, pitch -5° to +25°, distance 220-400 cm; dark-on-dark, pale and low-contrast; holds occluding base edges; bases clipped by the frame.
- `backend/eval_volume.py`: the evaluation, in `eval_angle.py`'s style.
- Reproduce: `cd backend && uv run python fakewall.py` then `uv run python eval_volume.py` (about 15 s and 4 min). `--experiment <name>` runs one. Output goes to `backend/fakewall_out/` (344 MB, regenerable, now in `.gitignore`).

The Tester measured **two paths**, which is what made the result legible: **full** = `fit_volume` on an outline built exactly as `run_detection` builds one, and **oracle** = the right fitter handed the *true* base and raised pixels. That separates the geometry from the correspondence.

| path | faces matched | steepness median | p90 | facing bucket | sign flips |
|---|---|---|---|---|---|
| full, first run | 96/208 | **11.5°** | 36.7° | 0.33 | 2 |
| full, after fixes 1-5 | 135/208 | **0.3°** | 34.9° | 0.57 | 2 |
| oracle | 198/208 | **0.0°** | 0.0° | 0.95 | 0 |
| **after fixes, gated on `trusted`** | 61/62 | **0.1°** | 1.9° | **0.98** | **0** |

**On the first run the geometry was exact and every route from a real outline into it was broken.** All three bars failed on the full path and passed on the oracle path. The 10 unmatched oracle faces are all the half-cylinder, which has no primitive.

After the five fixes below, the full path's median steepness went **11.5° → 0.3°**, faces produced 96 → 135 of 208, the right shape family 4 → 24 of 66, ridge apexes 0 → 14 of 34, and `fit_volume` 535 → 99 ms. **Restricted to the fits the `trusted` gate accepts, it passes all three go/no-go bars** - the first configuration other than the oracle to do so. Ungated it is limited by *coverage*, not accuracy: of the faces it does produce, 94% are in the right bucket, and both remaining sign flips are on volumes fitted as the wrong family and both are untrusted, so the gate removes them.

Five bugs, found and since fixed (the first four are correspondence, not maths):

1. **`ridge_segments` discarded every real ridge.** It required *both* endpoints of a segment to be inset from the outline, but a volume's ridges run from the apex out to the silhouette corners, so one end is always on the boundary. It never kept more than 2 segments on any of 66 volumes, below the 3 needed, so `converge_point` returned None **100% of the time** - idea 2 was dead on arrival. Fixed: the segment's *midpoint* is tested against `cv2.distanceTransform`.
2. **The wedge enumeration never tried the true split.** A wedge's hexagonal outline *interleaves* base and ridge corners, so its two ridge corners sit opposite each other, three apart; only adjacent pairs were tried. Fixed: the three opposite pairs, both pairings.
3. **`fit_box` was unreachable.** A cuboid has eight vertices but only **six** reach its silhouette - three base, three top - so an eight-corner outline never corresponds to a box, and `fit_box` was never once selected. Fixed with `fit_box_hexagon`, which recovers the hidden fourth base corner as `B_i + B_k - B_j` because the base is a parallelogram.
4. **`detection.POLYGON_SIMPLIFY_EPS` (0.005) drops the sixth corner** of a box and of a wedge, and `dominant_corners` returns None when the outline has fewer points than asked. So even with bug 2 fixed the wedge path died at the simplification step. Fixed with `outline_from_mask`, which takes the fit's own outline at 0.002 rather than inheriting detection's.
5. **`facing_deg` is meaningless near horizontal.** A box's top face on a vertical wall is exactly horizontal, and 1 px of noise swung the reported facing from -90 to +90 while steepness stayed at 89.9 - on its own this put the box family's bucket accuracy at 0.52-0.58 under *any* noise. Fixed: `facing` is `"undefined"` and `facing_deg` is `None` past 85°.

What the evaluation settled, and these are the parts worth keeping:

- **Mask noise is not the limiting factor.** At a realistic 2-5 px of vertex noise the geometry stays inside 1.2° p90 for every family; even 20 px keeps the median under 2.3°. A coherent dilate/erode costs ≤ 0.2°. The rendered outline was faithful to 0.3-0.6 px median even dark-on-dark.
- **`iou` is useless as a quality signal and must not be used as one.** Broken fits scored 0.98-1.01 while being 35 cm out. This is the depth ambiguity confirmed from the data: sliding a vertex along its ray does not move the outline.
- **`reprojection_px` is the gate.** Every one of the 50 broken fits had reprojection ≥ 100 px; 56 of 65 good fits were under 30 px, and those above were themselves genuinely bad. It must be **normalised by volume size**, because px per cm of error varied 1.7-3.3x with frame position. `fit_volume` now ranks on it rather than on IoU and sets `reprojection_norm` and `trusted`.
- **The `offcentre_gain` model holds**, measured/predicted 0.85-0.96 across the off-axis sweep. A 4-8 cm off-centre apex costs 10-20 cm of height and up to 15° on the worst face.
- **A box's face angles are independent of its fitted height** (identical at h = 10/30/60/110 cm): its top face is parallel to the wall and its sides contain the wall normal. So a box depends only on its observed base - the most robust family of the three, 0.0-0.6° median even at 20 px noise.
- **Idea 2 earns its place decisively.** A pyramid's apex projects *inside* its own outline on **29 of 34** volumes (85%), where no outline vertex can ever be it. With a ridge apex: 0.2 cm and 0.1° median. With the best outline vertex: 20.6 cm and 3.2° median, tails to 33°, and 8 more rejected outright. The relaxed filter found 15 of 34 apexes to ≤ 2.4 px - and failed on all four dark/pale/low-contrast pyramids, exactly where it was predicted to.
- **`hold_face` is 8/8 exact given a correct fit** (true standoffs 4.8-27.6 cm, which is the error the current "the hold is on the wall" treatment carries), and 3/8 with errors to 66 cm given a wrong one. It fixes the problem completely or makes it worse; there is no middle, which is why the gate matters.
- **A curved volume fails dangerously, not gracefully.** The half-cylinder came back as a confident `pyramid-4` at **iou 0.972** with h = 89.7 cm against a true 30 cm standoff. Only the reprojection error (857 px) gave it away. Any production gate must be reprojection-based or curved volumes will be reported as plausible pyramids.
- **Timing:** 535 ms per volume with ridges, 27 ms without - ridge detection was 95% of it, because LSD ran over the whole 1776x3840 frame for a mask covering 3-10% of it. Now cropped to the mask's bounding box; the Tester is re-measuring.

#### Focal length: the answer to a question left open in 5d

- **Not a prerequisite for face angles.** At the suspected ~12% error the median steepness error is ~1.2° and the worst face 4-5°, inside the 5° bar on its own - though it eats most of the budget if stacked with anything else.
- **It is a prerequisite for anything in cm.** A 12%-short `f` puts the wall plane ~9% too close and makes every volume height and hold standoff wrong by roughly 7-11%. So slice 8's hold positions in cm and the standoff fix both need it; the face angles do not.
- **`wall_plane`'s `axis_ratio` cannot detect focal error** - it stayed within 1% (0.993-1.006) at ±15% `f`. Do **not** rely on `trusted` as a guard against it. The self-calibration described under "Known issues" is still the way to settle it.

#### The gate, calibrated

A fit counts as unusable if any matched face is more than 5° out, the height is more than 5 cm out, or it failed to produce every visible face.

| `reprojection_norm` threshold | unusable suppressed | usable wrongly dropped |
|---|---|---|
| 0.03 | 50/54 | 4/71 |
| **0.05 (shipped)** | **50/54** | **2/71** |
| 0.10 | 43/54 | 1/71 |
| 0.30 | 36/54 | 1/71 |

**0.05**, because fits that are still usable under a realistic 5 px of mask noise top out at 0.035, so it sits just above that floor, and it is the knee of the curve. The deciding case was the off-centre-apex pyramid: at 0.10 a 4-10 cm apex offset passed as **trusted** while being 9-34 cm out, which would corrupt every hold standoff on that volume. At 0.05 all of those are rejected. The curved volume is suppressed at either threshold (it comes back as a box at 0.142).

**The gate's one blind spot, now closed separately.** Four unusable fits survived any threshold, and only one was dangerous: a volume whose **base is cut off by the frame edge** scored `reprojection_norm` of **0.000** while its height was 14 cm out and its worst face 16° out. Reprojection provably cannot see this - a truncated base is perfectly self-consistent on the corners that remain. So `touches_frame_border` was added and `trusted` now requires it to be false. The other three are benign (two pyramids with correct angles but 6-8 cm of height error, one wedge missing a face).

#### Four more fixes, after the re-run (awaiting the Tester's confirmation)

6. **The wedge base roll.** The opposite-pair fix was right but the base was listed in *increasing index order*, which only lands on `fit_ridge`'s anchoring when the lowest base index happens to follow a ridge corner - true for ridge pairs (0,3) and (2,5), false for (1,4). That one outline phase lost **8 of 15 wedges**, which fitted at reprojection 457 px instead of the 2.1 px the correct roll gives. Now listed in cyclic order with both rolls and both ridge orders tried.
7. **`MAX_REPROJECTION_FRACTION` 0.10 → 0.05**, per the calibration above.
8. **`touches_frame_border`**, per the blind spot above.
9. **`fit_box_partial`, for a box with only two faces visible.** `fit_box_hexagon` needs three visible faces to see three base corners, but a box near a portrait frame's vertical centre line shows its top and one side - the whole base rectangle on the outline and only two top corners. That is 4 base + 2 top, not 3 + 3, and it left **7 of 16 box views** unfitted, falling through to pyramid hypotheses 25-84 cm out (caught by the gate, so the cost was coverage, not wrong answers). All four base corners are observed in that view, so the height is still solved exactly.

**Not done, deliberately, for the human to decide:** five wedges and several boxes fail at the *outline reduction* step rather than in the geometry - three reduce to a 5-point outline even at `VOLUME_SIMPLIFY_EPS = 0.002`, and `dominant_corners` cannot always bisect to exactly 6 points on a 7-8 point outline, or picks six points that are not the six silhouette vertices. Fixing it means a smarter corner selection (longest-edge or dominant-point selection rather than a global tolerance). The Tester is quantifying what it would buy; it is extra complexity for coverage, not accuracy, so it is a judgement call rather than an obvious yes.

#### Current test state

- `cd backend && uv run pytest tests/test_volume.py -q` → **58 passed** (the 47 contract tests plus 11 covering the correspondence layer: every wedge outline phase, the two-face box, the box's height-independence, the frame-border gate, the `undefined` facing, and `outline_from_mask` keeping the corner detection drops).
- `cd backend && uv run pytest -q` → **641 passed, 2 xfailed**, unchanged.

#### Decisions made

- Volume geometry is developed against synthetic and hand-drawn masks, not blocked on the retrain: the methods take a mask as input (also recorded in spec: no - spec not yet updated, awaiting human review of this entry)
- The parallel-ridge constraint for wedges is abandoned as structurally degenerate (also recorded in spec: no)
- Shape families are reported with an `h_source`, so a margin can be set per family rather than one number for all volumes (also recorded in spec: no)
- Idea 3 (the photometric cue) is promoted from "cheap tie-breaker" to the principled fix for the pyramid case, because the unknown count and the constraint count match exactly (also recorded in spec: no)
- **`fit_volume` ranks on normalised reprojection error, not on outline IoU**: IoU provably cannot see the one unknown that matters, and the data confirmed it (0.98-1.01 on fits 35 cm out) (also recorded in spec: no)
- **The fit derives its own outline from the mask** at a finer tolerance than `detection.POLYGON_SIMPLIFY_EPS`, rather than inheriting detection's: at 0.005 a box and a wedge cannot be fitted at all. `run_detection` is left alone, so tap matching is unaffected (also recorded in spec: no)
- **Facing is reported as "undefined" past 85° of steepness** rather than as a confident direction, because the angle is unstable there to a pixel of noise (also recorded in spec: no)

#### Questions for the human

1. **Pyramids need one extra cue** - catalogue prior, photometric, or user input? Boxes and wedges do not. This decides the shape of step 3, and the evidence now says a pyramid without a ridge apex is 20 cm and up to 33° out, so this is the live question.
2. OK that `backend/volume.py`, `backend/fakewall.py` and `backend/eval_volume.py` are new files in `backend/`, following the existing `eval_scale.py` / `eval_angle.py` dev-script convention? The old volume work lived only in a temp scratchpad and was lost between sessions.
3. Is a volume whose face angle cannot be trusted better reported with a wide margin, or **not reported at all**? The evaluation argues strongly for not at all: `hold_face` is exact given a correct fit and up to 66 cm out given a wrong one, and a curved volume produced a confident wrong answer. Recommend gating on `trusted` and staying silent, but it is the human's call.
4. **Curved volumes** (half-cylinders, slopers): report the tangent plane at the hold, or refuse to report a face angle at all? They currently produce confident nonsense that only the gate catches.

#### Known issues

- No API, payload or prompt change yet: step 3 is unstarted on purpose.
- **Curved volumes** are unfittable and are now correctly suppressed by the gate (the half-cylinder scores 0.142), but "the angle" is not well defined for a curved face anyway - the likely answer is the tangent plane at the hold - and that needs a human decision before anything ships.
- **Pyramids depend entirely on the ridge detector**, which finds 14 of 34 apexes overall and **0 of 3** on dark-on-dark, pale and low-contrast volumes. The failure is predictable - too little contrast between adjacent faces to clear `RIDGE_MIN_INLIERS = 3` - and where no apex is found the fallback costs 20 cm and up to 33°, so those volumes are suppressed rather than reported. Every pyramid the full path gets right goes through the ridge apex.
- **Coverage, not accuracy, is the live limitation.** Mask noise now costs coverage: at 5 px of vertex jitter 67% of fits are near-perfect and 33% lose the right hypothesis outright, and `trusted` tracks that split almost exactly. So the gated answer is accurate and the question is what fraction of volumes get an answer at all.
- `MAX_REPROJECTION_FRACTION = 0.05` is calibrated, but on **one synthetic corpus**. The whole production story rests on this gate, so it needs confirming against real captures before it is relied on.
- `fit_volume` enumerates many hypotheses per family, so cost grows with the corner count. `/detect` is already 6.6-15.3 s against a 4-5 s target (slice 7), and at 5-10 volumes a photo the pre-crop ridge detection alone would have added 2.7-5.4 s.
- `f` self-calibration from the bolt grid is **not** needed for face angles but **is** needed for anything in cm (above). One homography of a known square grid over-determines `f` and gives two independent estimates whose disagreement is a free check; degenerate for a fronto-parallel panel. Not built.
- **What the synthetic test cannot settle** (the Tester's list, and the reason real captures are the next step): real YOLO masks, including volumes merged with their holds, split masks and shadow bleed - the "2-5 px on a clean edge" figure is an assumption, not a measurement; real volumes are not ideal polyhedra (chamfered edges, screw-on holds, texture, bases not perfectly flush, a volume straddling a panel seam and so sitting on two wall planes); cast shadows and specular paint, which will make real ridge detection harder and might also help it; lens distortion and roll, absent from a perfect pinhole render; the bolt pipeline, since the evaluation fed `fit_lattice` exact bolt centres rather than detector output; and how often holds really hide a base corner, which drove the 11.5 cm box height error measured for a 72 px displacement.

#### Context for the next session

- **Deleted, deliberately:** every leftover of the 2026-11-19 option-B depth attempt - the temp `scratchpad/vol/` and `depthenv/` dirs, a downloaded thesis PDF, and 95 MB of Depth-Anything-V2-Small weights in `~/.cache/huggingface`. Nothing of it was ever in the repo. The retrain scratch (`scratchpad/ds2000/`, the ORB/embedding files, `pl_fix/`) was left untouched - the human's relabelling depends on it.
- Do not re-try "depth model + wall plane" (2026-11-19) or "wedge from a parallel ridge" (this entry). Both are recorded dead ends.
- The whole approach rests on `scale.panel_homographies` giving a trustworthy wall plane. Where a volume sits on no fitted panel, or `axis_ratio` is off, there is no wall to back-project onto and the volume should be skipped rather than guessed.
- `volume.py` imports `scale` lazily inside `wall_plane` only, so its maths is testable without the lattice machinery.

#### What to measure (human, next step — the blocker)

**This is now the only thing standing between 6b step 2 and a real answer.** The geometry passes on synthetic data; nothing has been checked against a real volume.


Needed to score the go/no-go. Only `174933` has a measured face angle today, and a median over one volume is not a result. Target **15-25 volumes**; if only a few things are possible, items 2, 3 and 4 are the ones that decide the slice.

Per volume, captured **through the app** so the tilt reading and detections are saved the way `backend/field_captures/` does:

1. **Shape family** - triangular pyramid / square pyramid / wedge / box-riser / curved / other.
2. **Each visible face's angle**, phone inclinometer laid flat on the face: degrees from vertical, **+ overhang, - slab**. Per face, not per volume.
3. **How far the apex or top stands off the wall**, in cm (the "depth"). This is the one number a single photo cannot see, so measuring it is what tells us whether the assumption for pyramids is good enough, and it gives the catalogue prior if we go that way.
4. **Where the apex sits over the base** - centred, or offset by roughly how many cm and in which direction. This is the error the 6x gain multiplies, so it directly sizes the pyramid problem.
5. **The wall angle just beside the volume**, so the face angle and the wall angle can be told apart (as `174933` does: face +6, wall -2).
6. **Each face's facing direction** - standing facing the wall, does the face point at you, to your left, or to your right? A rough degree is a bonus.
7. **Base dimensions** - the base edge lengths by tape.
8. **Bolt spacing** for that wall, confirmed rather than assumed (25 cm at the gym used so far).
9. For a few volumes: a **tape distance from a hold on the volume to a hold on the wall**, saying whether it is bolt-to-bolt or centre-to-centre. This is what tests the standoff fix against the +19% error in `173933`.
10. **Whether holds hide a base corner**, and roughly how much of one. A 72 px displacement of one corner cost 11.5 cm of box height in testing, so how often this really happens decides whether it matters.
11. **Note which volumes are curved** (half-cylinder, sloper, rounded) rather than polyhedral. Those are the dangerous-failure class, so what fraction of a real wall they are is worth knowing.

Spread, which matters as much as the count:
- Mixed shapes, and mixed colours including **dark-on-dark** (a black volume on a dark wall) - the ridge detector should be at its worst there.
- On a slab **and** on an overhang.
- **Photograph several volumes twice: once near the middle of the frame, once well off to one side.** The accuracy depends strongly on where in the frame the volume sits (the 6x -> 1x gain above), and this is the cheapest way to measure that on real walls.
- Two gyms if possible; one phone and one gym is what every margin so far rests on.
- A **second photo from a slightly different angle** of each volume is a bonus: it gives tape-free ground truth to check the single-photo answer against.

#### Next slice

- Finish 6b step 2: append the Tester's synthetic results to this entry, get the human's answer on the pyramid cue, then score against real measured volumes.
- Then 6b step 1 (spotting a hold on a volume, which does wait for the retrain) and step 3 (plumbing).
- Order after that is unchanged: 6b -> 8 -> 7 -> End.

#### Human
- Reviewed: `no`
- Notes: `<feedback or changes to the plan>`

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