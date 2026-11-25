# CLAUDE.md

@docs/Agents.MD

## Start here
- Status lives in `docs/features/handover.md`: read "Overview (for the human)" and the newest Slice log entry. Don't read the whole file (~65 KB); read by section. The same goes for the spec `docs/features/wall_size_hold_distance.md`.
- Architecture: `docs/architecture.md`. Why things are the way they are: `docs/decisions.md`.
- Slash commands: `/start-slice <n>` to plan a slice, `/handover` to close it, `/checkpoint` (human only) to commit and push.

## Commands
From `backend/`:
- Full suite: `uv run python -m pytest`
- One file: `uv run python -m pytest tests/test_scale.py -x`
- Fast only: `uv run python -m pytest -m "not slow"`
- Accuracy (run before and after any change to scale, angle, bolts or detection): `uv run python eval_field.py`, `uv run python eval_scale.py --accuracy`, `uv run python eval_angle.py`

From `mobile/ML-Rock-Climbing-App/`:
- `npx tsc --noEmit`
- `npm run lint` (3 lint problems pre-exist)

## Conventions
- The backend works in bolt spacings (grid units). Only the app and `worker.py` convert to cm.
- Angles are degrees from vertical, + overhang / − slab, with the same sign in `angle.py`, `volume.py`, `worker.py` and the app.
- Photos reach `/detect` at full resolution (bolt detection needs ~3200 px).
- Backend and app types are kept in sync by hand: `COACHING_OUTPUT_SCHEMA` (`worker.py`) <-> `ClimbStep`/`ClimbAnalysis` in `api/getClimbAnalysis.tsx`; limits in `utils/boltSpacing.ts` and `utils/climberStats.ts` <-> `main.py`.

## Product rules
- Never remove the wall-angle degree readout in the app. If a change would, remind the human.
- Until the current feature is complete, don't edit `docs/architecture.md`, `docs/testing.md`, `docs/decisions.md` or `mobile/ML-Rock-Climbing-App/assets/known_measurements/notes/measurements.md`. Spec edits and per-slice handover entries are fine.
- Remind the human to commit (`/checkpoint`) at the end of each slice, and whenever uncommitted work spans more than one slice.

## Cloud sessions (claude.ai/code)
- `backend/models/best.pt` is deliberately not in the repo, so the YOLO slow tests skip. Don't try to fetch it.
- Work on your own `claude/*` branch and open a pull request. Never merge, never push to `main` or the human's branches.
