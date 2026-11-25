---
name: start-slice
description: Plan the next slice of the current feature. Reads the handover status and the spec for that slice, checks git state, and proposes an approach with alternatives. Use at the start of a slice, before any code.
argument-hint: "[slice-number]"
arguments: slice
---

Plan slice $slice. Write no code in this skill.

1. **Read status, by section, not whole files.**
   - `docs/features/handover.md`: "Overview (for the human)", the newest Slice log entry, and any entry whose title mentions slice $slice. Find them with Grep for `^## ` / `^### ` headings, then Read with offset/limit.
   - The feature spec (`docs/features/wall_size_hold_distance.md` unless the Overview points elsewhere): the *Slices* table row for $slice, the *Decisions* that apply to it, and any section titled for slice $slice. Same method: Grep for headings, then read only those ranges.
2. **Check git.** Run `git status` and `git log --oneline -5`. Also `git status -sb` to see if the branch is ahead of its remote.
   - If uncommitted work spans more than one slice, or there are unpushed commits, remind the human to run `/checkpoint` before starting.
3. **Propose, then stop.** Give:
   - The recommended approach, plus 1–2 alternatives, each with its trade-offs.
   - The done-when for the slice (measurable, from the spec where it has one).
   - The tests the Tester should add or change (behaviour from the spec, not from the code).
   - Which accuracy scripts will show no regression (`eval_field.py`, `eval_scale.py --accuracy`, `eval_angle.py`), with the previous entry's numbers to compare against.
   - Any question the spec leaves open.

Then stop and wait for the human's choice. Once they choose, record the decision in the spec's *Decisions* section before building.
