# CLAUDE.md

@docs/Agents.MD

## Start here
- The workflow is milestone → GitHub issue → slices (`docs/docs.md`). One issue = one branch named `<type>/<n>-<slug>` (e.g. `feat/43-hold-type`). The branch name tells you the active issue; the SessionStart hook prints it.
- Read the issue's docs in `docs/milestones/<version>/<n>-<slug>/`. A finished issue's folder moves to `docs/milestones/<version>/completed/<n>-<slug>/`. In `handover.md`, read Status and the newest Slice log entry; `spec.md` is the contract.
- Read the milestone's order, blockers and needs-from-human in `docs/milestones/<version>/milestone.md`.
- Read by section, not whole files.
- Finished features from before this workflow are in `docs/features_deprecated/`: the `wall_size_hold_distance.md` spec and its archived `*_handover.md`.
- Architecture: `docs/architecture.md`. Why things are the way they are: `docs/decisions.md`.
- Slash commands:
  - `/start-issue`: draft the issue's spec and handover
  - `/start-slice <n>`: plan a slice
  - `/handover`: close a slice
  - `/checkpoint`: commit and push (human only)
- `.claude/hooks/branch_guard.mjs` blocks Edit/Write on `main` or on a branch with no issue number. Don't get round it with Bash. Ask the human to create or rename the branch.

## Commands
From `backend/`:
- Full suite: `uv run python -m pytest`
- One file: `uv run python -m pytest tests/test_scale.py -x`
- Fast only: `uv run python -m pytest -m "not slow"`
- Accuracy (run before and after any change to scale, angle, bolts or detection): `uv run python -m accuracy_checks.eval_field`, `uv run python -m accuracy_checks.eval_scale --accuracy ../mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/*.jp*g`, `uv run python -m accuracy_checks.eval_angle ../mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/*.jp*g`. The scale and angle checks need the photos passed in; the `*.jp*g` glob needs Git Bash (in PowerShell, name the photos)
- Backend layout: `api/` (FastAPI app + Redis client), `coaching/` (Celery worker + coaching prompt), `wall_analysis/` (detection, bolts, scale, angle, volumes), `accuracy_checks/` (dev-only eval scripts and synthetic walls, run with `-m` from `backend/`), `tests/` (pytest; `tests/load/` is the load-test script)

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
- `docs/hold_types.md` is the hold identification table. Any change to hold classification (types, names, identification rules) updates it in the same change.
- Until the current issue is complete, don't edit `docs/architecture.md`, `docs/testing.md`, `docs/decisions.md` or `mobile/ML-Rock-Climbing-App/assets/known_measurements/notes/measurements.md`. Spec edits and per-slice handover entries are fine. Keep notes of what they'll need in the issue's handover, and update them in the issue's last slice (`/handover` does this).
- Remind the human to commit (`/checkpoint`) at the end of each slice, and whenever uncommitted work spans more than one slice.

## Cloud sessions (claude.ai/code)
- `backend/models/best.pt` is deliberately not in the repo, so the YOLO slow tests skip. Don't try to fetch it.
- Work on your own `claude/*` branch and open a pull request. Never merge, never push to `main` or the human's branches.
