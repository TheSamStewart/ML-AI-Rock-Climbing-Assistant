# Wall measurement docs write-up (#39)

Branch `docs/39-wall-measurement-docs` · Milestone V0.2 · GitHub issue #39

## Goal
Old slice 17. Some docs are held back until the wall size / hold distance feature is complete (product rule in `CLAUDE.md`). Once #36 is done, bring them up to date.

## Acceptance criteria
1. These four docs match the code:
   - `docs/architecture.md`
   - `docs/testing.md`
   - `docs/decisions.md`
   - `mobile/ML-Rock-Climbing-App/assets/known_measurements/notes/measurements.md`
2. No doc still points at `docs/features/...`. Those files now live in `docs/features_deprecated/` (finished feature) or `docs/milestones/v0.2/` (open issues). Known stale links:
   - `architecture.md` (the docs tree and the hold-type row)
   - `decisions.md` (the feature spec links)
   - `docs/changes/2026-11-25_wall-size-hold-distance.md`
3. `architecture.md` shows the new backend layout (#35) and the `docs/milestones/` layout.

## Slices
| Slice | Scope | Done when |
|---|---|---|
| 1 | Update the four docs and fix stale paths | AC 1–3 |

## Decisions
