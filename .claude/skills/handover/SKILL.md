---
name: handover
description: Close the current slice. Runs the tests and accuracy checks, has the reviewer subagent review the changes since the last commit, writes the handover entry and updates the Overview. Use at the end of every slice.
---

Close the current slice. Report results faithfully: if something fails, say so with the output.

1. **Tests.** From `backend/`:
   - The test files touched this slice: `uv run python -m pytest <files> -x`.
   - Then the full suite: `uv run python -m pytest`. Record the pass/fail/skip counts.
2. **Accuracy**, only if scale, angle, bolts or detection changed (`wall_analysis/scale.py`, `angle.py`, `bolts.py`, `detection.py`, or what they call): from `backend/`, run `uv run python -m accuracy_checks.eval_field` and `uv run python -m accuracy_checks.eval_scale --accuracy ../mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/*.jp*g` (and `uv run python -m accuracy_checks.eval_angle` with the same photos if angles changed). Compare with the numbers in the previous handover entry and say plainly whether anything got worse.
3. **App**, only if files under `mobile/ML-Rock-Climbing-App/` changed: from that folder run `npx tsc --noEmit` and `npm run lint` (3 lint problems pre-exist; report any beyond those).
4. **Review.** Launch the `reviewer` subagent on the changes since the last commit (`git diff HEAD` plus untracked files), with this slice's file list. List its concerns for the human. Fix one only with the human's OK.
5. **Write the entry** at the **top** of the Slice log in the issue's `handover.md`. The issue comes from the branch: `git branch --show-current` gives `<type>/<n>-<slug>`, and the docs are in `docs/milestones/*/<n>-<slug>/` (or `docs/milestones/*/completed/<n>-<slug>/` once the issue is done).
   - Use the entry template in `docs/milestones/_templates/handover.md`: Status, What changed, Results, Decisions, Questions for the human, Known issues, `**Human:** Reviewed: <yes/no>`.
   - Keep it short and specific: file paths, function names, exact test output.
6. **Update status.**
   - In the issue's `handover.md`: the Status table row for this slice, and "Needs from the human" if it changed.
   - If this was the issue's last slice and its acceptance criteria are met:
     - Bring the held docs up to date from the notes in the issue's handover: `docs/architecture.md`, `docs/testing.md`, `docs/decisions.md`, and `notes/measurements.md` if measurements changed. Project-wide decisions from the spec go into `decisions.md`.
     - Set the issue's row in `milestone.md` to ✅ Done. Update "Needs from you" there, and unblock (⏸ → ☐) any issue that was waiting only on this one.
     - Move the issue's folder into the milestone's `completed/` folder with a plain `mv`, not `git mv`: `docs/milestones/<version>/<n>-<slug>/` → `docs/milestones/<version>/completed/<n>-<slug>/`. Then fix links to it in `milestone.md` and in other issues' docs (Grep for `<n>-<slug>`).
7. **Remind the human** to review and then run `/checkpoint`. After the last slice, also remind them to open a PR to `main` with `Closes #<n>`. Then stop.
