---
name: start-issue
description: Start work on a GitHub issue. Finds the issue from the branch name, drafts its spec.md and handover.md from the templates, the GitHub issue and the milestone, and stops for the human's approval. Use once per issue, before /start-slice 1.
---

Start the issue for the current branch. Write no code in this skill.

1. **Find the issue.** Run `git branch --show-current`. It must match `<type>/<n>-<slug>` (type: feat, fix, refactor, docs, chore, test). If it doesn't, stop and ask the human to create or rename the branch (`git branch -m <type>/<n>-<slug>`). Never create or switch branches yourself.
2. **Read the issue and its milestone.**
   - `gh issue view <n> --json title,body,milestone,labels`
   - In `docs/milestones/*/milestone.md`, find the row for `#<n>`. Read the Goal, that row, "Needs from you", and any parked plan for this issue (Grep for `#<n>`).
3. **Create the docs** in `docs/milestones/<version>/<n>-<slug>/`, where the folder name is the branch without its type.
   - If `spec.md` / `handover.md` already exist, read them and skip to step 4. Don't overwrite.
   - If the folder is already in `docs/milestones/<version>/completed/<n>-<slug>/`, the issue is done. Stop and ask the human whether they meant to reopen it.
   - Otherwise, copy `docs/milestones/_templates/spec.md` and `handover.md`.
   - Fill `spec.md` from the issue's done-when and the milestone criterion: goal, inputs, outputs, measurable acceptance criteria and a first cut of slices (thin slices: slice 1 runs end to end, even if stubbed).
   - Where a criterion isn't measurable yet, write it as a question rather than inventing a number.
   - Fill `handover.md`'s Status table from the slices.
4. **Update `milestone.md`:** set this issue's status to ▶ In progress.
5. **Check git:** `git status -sb`. If uncommitted work belongs to another issue, remind the human to `/checkpoint` first.
6. **Stop and present.** Give the drafted acceptance criteria and slices, the open questions, and anything the human must supply (data, labels, approvals). Wait for approval before `/start-slice 1`.
