# Wall measurement close-out (#36)

Branch `feat/36-wall-measurement-closeout` · Milestone V0.2 · GitHub issue #36

## Goal
Finish the wall size / hold distance feature. That means old slice 16, plus slice 12's open data question (do real slabs read as slabs?). The code is done; what's left needs the human.

Feature spec: `docs/features_deprecated/wall_size_hold_distance.md`. History: `docs/features_deprecated/wall_size_hold_distance_handover.md`, the entries "Slice 16: planned with the human" and "Slice 12: wall-angle fixes".

## Inputs
- **Slab photos.** For each one: the wall angle, a few tape distances between holds, and the phone's tilt when the photo was taken.

## Acceptance criteria
1. The bolt-pattern choice in Settings has been checked on a real phone: the three cards, the spacing help text, and the range check after the ×√2 conversion.
2. The slab photos have been added to the reference data. `accuracy_checks.eval_field` and `eval_angle` report on them: slabs read as negative angles within the current margins, or the miss is written up.
3. The human has reviewed slice 16.

## Reference data
- `mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/`, `backend/field_captures/`.

## Slices
| Slice | Scope | Done when |
|---|---|---|
| 1 | Phone check of Settings (human) and any fixes | AC 1 |
| 2 | Slab photos in, replay, write-up | AC 2 |

## Decisions
