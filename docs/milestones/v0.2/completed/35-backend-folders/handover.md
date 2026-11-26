# Backend folder layout: handover (#35)

Slice status and the slice log for this issue. The contract is in `spec.md`; the milestone's order and status are in `../milestone.md`.

## Status

| Slice | Scope | Status |
|---|---|---|
| 1 | Move files, fix imports, Docker, CI, docs paths | ✅ Done 2026-11-26 |

**Needs from the human:** `/checkpoint`, then a PR to `main` with `Closes #35`.

## Rules for agents
1. At the start of a session, read Status and the newest log entry.
2. At the end of each slice (`/handover`), update Status and add an entry at the **top** of the Slice log, using the template in `docs/milestones/_templates/handover.md`.
3. Don't rewrite past entries. If one was wrong, correct it in the new entry.
4. Be specific: file paths, function names, exact test output.

## Slice log (newest first)

### 2026-11-26 · Slice 1: backend folder layout + milestone docs workflow

**Status:** Complete. AC1–3 are met, and the human has decided on every review concern (see "Review concerns: resolved" below).

**What changed**
- **Backend move** (git sees renames):
  - `backend/{main,redis_client}.py` → `backend/api/`
  - `worker.py` → `backend/coaching/`
  - `{angle,bolts,detection,scale,volume,volume_scan}.py` → `backend/wall_analysis/`
  - `eval_*.py`, `fakewall.py`, `draw_volume_corners.py` → `backend/accuracy_checks/`
  - `load_test/simulate_load.py` → `backend/tests/load/`
  - new `__init__.py` in `api/`, `coaching/`, `wall_analysis/`, `accuracy_checks/`
- **Imports and callers:**
  - every `backend/tests/test_*.py`, `tests/conftest.py`, `tests/freeze_reference_index.py`
  - `experiments/two_photo/{synth.py,README.md}`
  - `backend/TESTING_PLAN.md`
- **Run config:**
  - `backend/Dockerfile` (`uvicorn api.main:app`)
  - `docker-compose.yml` (`celery -A coaching.worker.app`)
  - `.github/workflows/load-test.yml` (`tests/load/simulate_load.py`)
  - `backend/pyproject.toml` (coverage sources, comment), `backend/uv.lock`, `.gitignore`
- **Path comments only:** `mobile/ML-Rock-Climbing-App/{api/detectHolds,api/getClimbAnalysis,api/volumeScan,components/PhotoPreview,hooks/useGravityReading}.tsx` and `utils/{boltSpacing,climberStats,holdMatching}.ts`.
- **Docs:** `docs/architecture.md`, `docs/testing.md`, `docs/localhost.md` (paths to the new layout).
- **Not pure moves** (made before this doc existed; flagged by the reviewer):
  - `coaching/worker.py:421`: `@app.task(name="worker.analysis")`. This keeps the Celery task name the API sends, so it's needed for the move.
  - `wall_analysis/angle.py`: `angles_at()` deleted. It had no callers.
  - `pyproject.toml`: dev deps `httpx2` and `mock` removed, `readme` removed, `description` rewritten.
- **Milestone docs workflow (this session):**
  - new `docs/docs.md`, `docs/milestones/` (templates, `v0.2/milestone.md`, issue folders 35–40, `completed/` convention)
  - `docs/features/*` moved to `docs/milestones/v0.2/37-*`, `38-*` and `docs/features_deprecated/wall_size_hold_distance_handover.md`
  - new `.claude/skills/start-issue/`; edited `start-slice`, `handover`, `checkpoint`
  - `.claude/agents/{reviewer,tester}.md`
  - new `.claude/hooks/branch_guard.mjs`; edited `tester_guard.mjs` (blocks handover.md)
  - `.claude/settings.json` (PreToolUse and SessionStart hooks), `CLAUDE.md`, `docs/Agents.MD`
  - GitHub issues #35–#53 and labels created.

**Results**
- **Full suite:** `uv run python -m pytest` → `798 passed, 1 skipped, 2 xfailed` (5:35, slow tests included). The reviewer separately ran `-m "not slow"` → `763 passed, 1 skipped, 36 deselected, 1 xfailed`.
- **AC2 (accuracy), unchanged:**
  - `accuracy_checks.eval_field`: angles n=29, median 1.2, p90 3.5, max 5.2, the same before and after; distances 9/9 inside their margins.
  - `accuracy_checks.eval_scale --accuracy`: per-photo p95 1.0 / 1.7 / 2.7 / 2.9% on IMG_7500 / 7502 / 7503 / 7504, identical to slice 7 of the old handover. Pooled (7 photos) p95 2.0%; worst photo 2.9%.
  - `accuracy_checks.eval_angle`: per-panel readings as before (IMG_7503 26→26, IMG_7504 13→13 back-solved; IMG_7502's 9° panel still merged into 31°).
- **AC3:**
  - `docker compose config -q` → OK.
  - The Dockerfile CMD and compose commands use the new module paths.
  - `python tests/load/simulate_load.py --help` works, the way CI calls it.
  - The reviewer checked: `celery -A coaching.worker.app` registers `worker.analysis`, `uv lock --check` passes, and every `python -m accuracy_checks.*` entry point runs.
  - Not run: a real `docker compose up` or the CI workflow.
- **App:** `npx tsc --noEmit` clean; `npm run lint` shows the 3 problems that were already there.

**Decisions** (recorded in spec: yes)
- The Celery task keeps the name `worker.analysis` after the move, so queued tasks and a mixed-version API and worker still match.
- The deletion of `angles_at()` and the removal of the `httpx2` and `mock` dev deps are approved (human, 2026-11-26).
- The stale links in `architecture.md` and `decisions.md` are left for #39.

**Review concerns: resolved** (human, 2026-11-26)
1. **Kept all three non-move edits.**
   - Tester: `test_api_enqueues_under_the_same_task_name_as_the_worker` added to `tests/test_worker.py`. It asserts `api.main.analysis_task.name == analysis.name == "worker.analysis"`.
   - The worker side was already pinned by `test_analysis_is_registered_as_a_celery_task`.
2. **Fixed the Grep gap.** In `tester_guard.mjs`, a Grep over a folder that contains an implementation folder (`backend/tests` ⊃ `backend/tests/load`) is now blocked unless `glob` is `test_*` or `conftest*`. The block message says so.
3. **Fixed `/d/...` paths.** `norm()` in both hooks maps Git Bash `/d/...` to `d:/...` on win32. Tested: `/d/.../backend/api/main.py` is blocked for the Tester, and `/d/.../CLAUDE.md` is blocked on `main` by the branch guard.
4. **Fixed the stale links:**
   - comments in `.gitignore`, `api/main.py`, `coaching/worker.py`, `experiments/two_photo/synth.py`, `wall_analysis/{angle,bolts,scale,volume_scan}.py`, and `mobile/.../{api/volumeScan.tsx, components/PhotoPreview.tsx, components/VolumeScanCamera.tsx}`
   - Tester-owned comments in `tests/{test_scale,test_scale_panels,test_volume_scan}.py`
5. **`architecture.md` and `decisions.md` links:** left for #39, whose spec already lists them. No held docs were changed in #35.
6. **#40 spec:** removed the dev-scripts bullet.
7. **`CLAUDE.md:39`:** restored the bullet and the backticks.

**Questions for the human** (as originally raised by the reviewer)
1. **Non-move edits:** keep or revert the deletion of `angles_at()` and the removal of the `httpx2` and `mock` dev deps? Dependency changes need your OK. Add a test that pins `analysis.name == "worker.analysis"`?
2. **Tester guard gap:** `Grep(path="backend/tests")` now also searches `tests/load/simulate_load.py`, which counts as implementation. Fix: block Grep when an implementation folder lies under the given path.
3. **`/d/...` path bypass:** both hooks treat Git Bash-style paths (`/d/ML-...`) as outside the repo, so they allow them. Fix: map `^/x/` to `x:/` in `norm()`.
4. **Stale `docs/features/` links:**
   - In code comments: `api/main.py:356`, `wall_analysis/volume_scan.py:3,21`, `experiments/two_photo/synth.py:4`, `.gitignore:33`, `mobile/.../volumeScan.tsx:4`, `PhotoPreview.tsx:260`, `VolumeScanCamera.tsx:7`, `tests/test_volume_scan.py:1` (Tester-owned).
   - Older links to `wall_size_hold_distance.md` in `worker.py`, `angle.py`, `bolts.py`, `scale.py` and `test_scale*.py`.
   - Fix: one grep-and-replace.
5. **Held docs:**
   - `docs/architecture.md:86-89,190` and `docs/decisions.md:25,249` still show `docs/features/`.
   - #35 has one slice, so the rule says to update them now.
   - #39 also lists these, so: update now under #35, or leave them for #39?
6. **#40's spec** still asks whether to move the dev scripts to a `tools/` folder. #35 already moved them to `accuracy_checks/`. Update that bullet?
7. **`CLAUDE.md:39`** lost its `- ` bullet and the backticks around file names.

**Known issues / context for the next session**
- Hook failure modes:
  - Missing node or git makes `branch_guard` allow edits (fail-open).
  - Mid-rebase, the branch reads as `""`, which counts as a detached HEAD, so edits are blocked.
  - An Edit on `refactor/backend-folders` was confirmed blocked live (2026-11-26), so the `args` form works.
- Closed 2026-11-26: #35 set to ✅ in `milestone.md`, and this folder moved to `docs/milestones/v0.2/completed/35-backend-folders/`.
- Not run: a real `docker compose up`, or the CI load-test workflow. The PR's CI is the first real run.

**Human:** Reviewed: · Notes:

### 2026-11-26 · Docs moved to the milestone workflow

**Status:** Note, not a slice.

**What changed**
- This issue's docs were created when the project moved to milestone → issue → slice docs (`docs/docs.md`).
- The same working tree also holds that docs change: `docs/milestones/`, `docs/docs.md`, `CLAUDE.md`, `docs/Agents.MD`, `.claude/skills/*`, `.claude/agents/*`, `.claude/hooks/branch_guard.mjs` and `.claude/settings.json`.
- The folder move itself was done before this doc existed. `git status` shows it.

**Human:** Reviewed: · Notes:
