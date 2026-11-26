# Backend folder layout (#35)

Branch `refactor/35-backend-folders` · Milestone V0.2 · GitHub issue #35

## Goal
Move the flat `backend/` into packages so each part of the system has one home:
- `api/`: the FastAPI app and the Redis client
- `coaching/`: the Celery worker and the coaching prompt
- `wall_analysis/`: detection, bolts, scale, angle and volumes
- `accuracy_checks/`: the dev-only eval scripts and synthetic walls, run with `-m` from `backend/`
- `tests/load/`: the load-test script

No behaviour changes.

## Acceptance criteria
1. Full suite green: `uv run python -m pytest`.
2. `accuracy_checks.eval_field`, `eval_scale --accuracy` and `eval_angle` give the same numbers as before the move.
3. The Dockerfile, docker-compose, both CI workflows and the load test run from the new paths.

## Slices
| Slice | Scope | Done when |
|---|---|---|
| 1 | Move the files, fix imports, entry points, Docker, CI and docs paths | AC 1–3 |

## Decisions
- 2026-11-26 (human): the Celery task keeps the name `worker.analysis` after `worker.py` moved to `coaching/worker.py`. The API sends tasks by that name, so queued tasks and a mixed-version API and worker keep working. A test pins `coaching.worker.analysis.name == "worker.analysis"`.
- 2026-11-26 (human): `wall_analysis.angle.angles_at()` deleted (no callers). The dev dependencies `httpx2` and `mock` removed from `pyproject.toml` (the suite passes without them).
- 2026-11-26 (human): the stale `docs/features/` links in `architecture.md` and `decisions.md` are left for #39.
