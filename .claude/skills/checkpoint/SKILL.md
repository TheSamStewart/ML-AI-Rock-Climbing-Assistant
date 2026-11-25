---
name: checkpoint
description: Commit the reviewed slice and push the current branch. Human-triggered only.
disable-model-invocation: true
---

The human has asked to commit the reviewed slice and push it. This is the one case where an agent commits; never run it on your own initiative.

1. **Branch.** Run `git branch --show-current`. If it is `main` (or `master`), refuse and stop: say the human should switch to the feature branch first.
2. **Show the state.** Run `git status` and `git diff --stat HEAD`, and list what will be committed.
3. **Stage carefully.** Stage files by name (`git add <paths>`), never `git add -A` or `git add .`. Never stage:
   - `.env` or `.env.*` (except `.env.example`)
   - `.claude/settings.local.json`
   - `backend/models/*.pt`
   - scratch output such as `backend/final.txt`, `backend/fakewall_out/`, `backend/field_captures_scans/`
   - anything that looks like a secret or a large binary not already tracked. If unsure about a file, leave it out and say so.
4. **Commit.** Subject: the newest Slice log entry's title in `docs/features/handover.md` (the text after `### `). Body: that entry's *What changed* bullets. End the message with a blank line and:
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
   Use a heredoc so the formatting survives.
5. **Push** the current branch: `git push -u origin <branch>`. No force, ever. If the push is rejected, stop and report; don't pull, rebase or force.
6. **Report** the commit hash (`git log --oneline -1`), the files committed, anything left unstaged and why, and the push result.
