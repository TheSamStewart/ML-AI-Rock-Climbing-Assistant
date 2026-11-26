# Fable review (#40)

Branch `chore/40-fable-review` · Milestone V0.2 · GitHub issue #40

## Goal
Old slice 18. Once the wall size / hold distance feature is finished (#36, #39), Fable goes over all the completed work and makes any changes it sees necessary for efficiency, unneeded code, bugs and so on.

Note: `backend/` has since been split into packages (#35), so for example `scale.py` is now `backend/wall_analysis/scale.py` and the eval scripts are in `backend/accuracy_checks/`. The dev-only scripts item was removed from the checklist: #35 settled their place (`accuracy_checks/`).

## Acceptance criteria
Each of Fable's findings is fixed or consciously accepted by the human, the test suite is green, and the accuracy numbers (`accuracy_checks.eval_scale --accuracy`, `--tape`, `accuracy_checks.eval_angle`, the field replay) are unchanged or better.

## Checklist (copied from the old handover, 2026-11-26)

What Fable should check:

**Efficiency**
- Pure-Python loops left in `scale.py`, `bolts.py`, `angle.py`, `volume.py` after slice 13.
- Work done twice per request: the photo decoded, rotated or converted more than once; metrics recomputed per hold rather than once.
- The N×N `distances_units` and `tiers` in the `/detect` response: does the app need all of it?
- YOLO cold start (9.8 s once): is the model warmed when the server starts?
- `volume.fit_volume` tries many shape hypotheses per volume. Is the cost bounded when a photo has 10+ volumes?

**Unneeded code**
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


## Slices
| Slice | Scope | Done when |
|---|---|---|
| 1 | Review and fix, grouped as Fable proposes at /start-slice | AC |

## Decisions
