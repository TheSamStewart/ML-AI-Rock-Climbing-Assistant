# AGENTS.md

Guidance for AI coding agents working on this repository. Read this file in full before planning or writing code. It applies to every feature.

## Project

| Item | Definition |
|---|---|
| Project | AI rock climbing coach/route analysis |
| Platform | IOS/Android |
| Test command | cd backend && uv run python -m pytest |
| App check | cd mobile/ML-Rock-Climbing-App && npx tsc --noEmit && npm run lint |

> Agents must not guess values marked `<placeholder>`. Ask the human instead.

## Source Control: Human Only

The human handles **all** source control. Agents must never:

- commit, amend, rebase, merge, or push
- create, switch, or delete branches
- open, update, or comment on pull requests
- tag releases or change remote settings

Agents may run read-only commands such as `git status`, `git diff`, and `git log` to understand the current state.

At the end of each slice, the agent stops and hands over a summary for the human to review (see *Handover*). Each reviewed slice ends with the human running `/checkpoint`, which commits the slice and pushes the feature branch. Agents never commit on their own initiative.

Cloud sessions (claude.ai/code) may push only their own `claude/*` branch and open a pull request. They never merge and never push to main or the human's branches. The human reviews and merges.

**Branches and issues.**
- Each GitHub issue gets one branch, named `<type>/<issue#>-<slug>`. The human creates it.
- `.claude/hooks/branch_guard.mjs` blocks agents from editing files on `main` or on a branch with no issue number.
- Agents create or edit GitHub issues only when the human asks.

## Roles

The human is the **lead**. They approve plans, choose between alternatives, review all changes, and handle source control. There is no separate leader agent.

### Developer (main session)
- Implements features in thin slices.
- Works from the issue spec and this file.
- Runs the test suite after every change and iterates on failures.
- Does **not** edit tests written by the Tester to make them pass. If a test seems wrong, flag it to the human.

### Tester (subagent)
- Writes tests **from the issue spec and reference data only**.
- Must **not** read the implementation when designing tests, so tests stay independent and don't just confirm the code's own bugs.
- Owns the test files for each feature.
- Reports results against the feature's acceptance criteria.

### Reviewer (subagent, every slice)
- Reviews the changes since the last checkpoint commit (`git diff HEAD` plus untracked files), cross-checked with the slice's *What changed* list in handover.md.
- Focuses on edge cases, error handling, and consistency with *Decisions* and *Conventions*.
- Produces a list of concerns; does not rewrite code.

> In Claude Code, subagent definitions live as Markdown files in `.claude/agents/` (e.g. `tester.md`, `reviewer.md`).

## Milestones, issues and specs

Work is split into a milestone, then GitHub issues (one per success criterion, one branch each), then slices. The human-facing overview is `docs/docs.md`.

- `docs/milestones/<version>/milestone.md` holds the criteria, the issue table (status, order, dependencies), cross-issue decisions and needs-from-human.
- `docs/milestones/<version>/<n>-<slug>/spec.md` is the issue's contract. It must exist before any code is written. `/start-issue` creates it from `docs/milestones/_templates/spec.md` (goal, inputs, outputs, acceptance criteria, reference data, slices, decisions).
- `docs/milestones/<version>/<n>-<slug>/handover.md` holds the issue's slice status and slice log. The Tester never reads it.
- When an issue is done, `/handover` moves its folder to `docs/milestones/<version>/completed/<n>-<slug>/`.

## Workflow

1. **Spec first.** On a new issue branch, run `/start-issue`. Ask about gaps in goal, inputs, outputs, or acceptance criteria before planning.
2. **Plan, then review.** Start with `/start-slice <n>`. Propose an approach and list alternatives with trade-offs. Wait for the human to choose. Do not write code before a plan is approved.
3. **Record the decision** in the issue spec's *Decisions* section.
4. **Build in thin slices** (see below).
5. **Test** after every change, against the acceptance criteria.
6. **Hand over** at the end of each slice with `/handover` and stop. The human then reviews and runs `/checkpoint`.

## Thin Slices

Build a crude version of every stage first so input goes in and output comes out end to end. Then improve one stage at a time.

- Slice 1 may hardcode or stub anything, as long as the whole path runs.
- Each later slice replaces one stub or improves one stage.
- Each slice must leave the feature working end to end.
- One slice per session where possible.
- Stop at the end of each slice so the human can review and work can continue.

## Handover

At the end of each slice, the agent runs `/handover`, which posts the entry in the issue's `handover.md`. On an issue's last slice, it also marks the issue done in `milestone.md`.

## Decisions (project-wide)

Record cross-feature decisions here so later sessions don't relitigate them. Issue-specific decisions go in the issue spec; cross-issue ones in `milestone.md`.

- **Architecture:** FastAPI + Redis + Celery backend, Expo React Native app; see docs/architecture.md.
- **Key libraries:** Ultralytics YOLO26-seg, OpenCV, NumPy, Anthropic SDK, TanStack Query, expo-camera, expo-sensors; see docs/decisions.md.
- **Units & conventions:** the backend works in bolt spacings (grid units); only the app and `worker.py` convert to cm. Angles are degrees from vertical, + overhang / − slab, with the same sign in angle.py, volume.py, worker.py and the app.

If an agent believes a decision is wrong, it raises this with the human. It does not silently change course.


## Session Hygiene

- Keep each session focused on one feature slice or stage.
- Start a fresh session when the context gets cluttered.
- Handoffs between agents lose context, so put anything important in this file or the issue spec, not just in chat.

## Guardrails

- Do not refrain from suggesting alternatives which could be better to the user
- Never touch source control beyond read-only commands.
- Don't let agents approve each other's work. Agreement between agents is not a substitute for human review.
- Don't add more agents unless a specific, recurring problem calls for one.
- Don't change units, conventions, libraries, or recorded decisions without human approval.
- Don't install new dependencies without asking.
- When unsure, ask.