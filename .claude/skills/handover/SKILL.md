---
name: handover
description: Close the current slice. Runs the tests and accuracy checks, has the reviewer subagent review the changes since the last commit, writes the handover entry and updates the Overview. Use at the end of every slice.
---

Close the current slice. Report results faithfully: if something fails, say so with the output.

1. **Tests.** From `backend/`:
   - The test files touched this slice: `uv run python -m pytest <files> -x`.
   - Then the full suite: `uv run python -m pytest`. Record the pass/fail/skip counts.
2. **Accuracy**, only if scale, angle, bolts or detection changed (`scale.py`, `angle.py`, `bolts.py`, `detection.py`, or what they call): run `uv run python eval_field.py` and `uv run python eval_scale.py --accuracy` (and `uv run python eval_angle.py` if angles changed). Compare with the numbers in the previous handover entry and say plainly whether anything got worse.
3. **App**, only if files under `mobile/ML-Rock-Climbing-App/` changed: from that folder run `npx tsc --noEmit` and `npm run lint` (3 lint problems pre-exist; report any beyond those).
4. **Review.** Launch the `reviewer` subagent on the changes since the last commit (`git diff HEAD` plus untracked files), with this slice's file list. List its concerns for the human. Fix one only with the human's OK.
5. **Write the entry** at the **top** of the Slice log in `docs/features/handover.md`, using the entry template in that file's "Rules for agents" (Status, What changed, Results, Decisions, Questions for the human, Known issues, `**Human:** Reviewed: <yes/no>`). Keep it short and specific: file paths, function names, exact test output.
6. **Update the Overview** table row for this slice (and "Where we are" / "Needs from you" if they changed).
7. **Remind the human** to review and then run `/checkpoint`. Then stop.
