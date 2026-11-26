---
name: start-slice
description: Plan the next slice of the current issue. Finds the issue from the branch name, reads its handover status and spec for that slice, checks git state, and proposes an approach with alternatives. Use at the start of a slice, before any code.
argument-hint: "[slice-number]"
arguments: slice
---

Plan slice $slice. Write no code in this skill.

1. **Find the issue.** Run `git branch --show-current`. It must match `<type>/<n>-<slug>`, and the issue's docs are in `docs/milestones/*/<n>-<slug>/` (or `docs/milestones/*/completed/<n>-<slug>/` once the issue is done).
   - If the branch doesn't match, stop and ask the human to rename it.
   - If the folder has no `spec.md`, stop and suggest `/start-issue`.
2. **Read status, by section, not whole files.** Find sections with Grep for `^## ` / `^### `, then Read with offset/limit.
   - The issue's `handover.md`: Status, the newest Slice log entry, and any entry whose title mentions slice $slice.
   - The issue's `spec.md`: the *Slices* row for $slice, the *Acceptance criteria*, and the *Decisions* that apply.
   - `milestone.md` in the same version folder: this issue's row, cross-issue *Decisions*, and any parked plan for this issue.
3. **Check git.** Run `git status`, `git log --oneline -5` and `git status -sb`. If uncommitted work spans more than one slice, or there are unpushed commits, remind the human to run `/checkpoint` before starting.
4. **Propose, then stop.** Give:
   - The recommended approach, plus 1–2 alternatives, each with its trade-offs.
   - The done-when for the slice: measurable, taken from the spec where it has one.
   - The tests the Tester should add or change: behaviour from the spec, not from the code.
   - Which checks will show no regression, with the previous entry's numbers to compare against:
     - `accuracy_checks.eval_field`, `accuracy_checks.eval_scale --accuracy`, `accuracy_checks.eval_angle`
     - the coaching eval, once #41 exists, for any change to the coaching prompt or payload
   - Any question the spec leaves open.

Then stop and wait for the human's choice. Once they choose, record the decision in the issue's `spec.md` *Decisions* section before building.
