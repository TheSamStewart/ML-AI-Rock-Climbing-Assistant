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

## Roles

The human is the **lead**. They approve plans, choose between alternatives, review all changes, and handle source control. There is no separate leader agent.

### Developer (main session)
- Implements features in thin slices.
- Works from the feature spec and this file.
- Runs the test suite after every change and iterates on failures.
- Does **not** edit tests written by the Tester to make them pass. If a test seems wrong, flag it to the human.

### Tester (subagent)
- Writes tests **from the feature spec and reference data only**.
- Must **not** read the implementation when designing tests, so tests stay independent and don't just confirm the code's own bugs.
- Owns the test files for each feature.
- Reports results against the feature's acceptance criteria.

### Reviewer (subagent, every slice)
- Reviews the changes since the last checkpoint commit (`git diff HEAD` plus untracked files), cross-checked with the slice's *What changed* list in handover.md.
- Focuses on edge cases, error handling, and consistency with *Decisions* and *Conventions*.
- Produces a list of concerns; does not rewrite code.

> In Claude Code, subagent definitions live as Markdown files in `.claude/agents/` (e.g. `tester.md`, `reviewer.md`).

## Feature Specs

Every feature has a spec at `docs/features/<feature-name>.md` before any code is written. Use this template:

```markdown
# <Feature name>

## Goal
<What the feature does and why>

## Inputs
<What goes in>

## Outputs
<What comes out, with units/format>

## Acceptance criteria
<Measurable conditions for "done", e.g. accuracy targets, performance limits>

## Reference data
<Where real-world test data lives, if any>

## Slices
| Slice | Scope | Done when |
|---|---|---|
| 1 | | |

```

## Workflow

1. **Spec first.** If no spec exists, help the human write one. Ask about gaps in goal, inputs, outputs, or acceptance criteria before planning.
2. **Plan, then review.** Start with `/start-slice <n>`. Propose an approach and list alternatives with trade-offs. Wait for the human to choose. Do not write code before a plan is approved.
3. **Record the decision** in the feature spec's *Decisions* section.
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

At the end of each slice, the agent posts in handover.md

## Decisions (project-wide)

Record cross-feature decisions here so later sessions don't relitigate them. Feature-specific decisions go in the feature spec.

- **Architecture:** FastAPI + Redis + Celery backend, Expo React Native app; see docs/architecture.md.
- **Key libraries:** Ultralytics YOLO26-seg, OpenCV, NumPy, Anthropic SDK, TanStack Query, expo-camera, expo-sensors; see docs/decisions.md.
- **Units & conventions:** the backend works in bolt spacings (grid units); only the app and `worker.py` convert to cm. Angles are degrees from vertical, + overhang / − slab, with the same sign in angle.py, volume.py, worker.py and the app.

If an agent believes a decision is wrong, it raises this with the human. It does not silently change course.


## Session Hygiene

- Keep each session focused on one feature slice or stage.
- Start a fresh session when the context gets cluttered.
- Handoffs between agents lose context, so put anything important in this file or the feature spec, not just in chat.

## Guardrails

- Do not refrain from suggesting alternatives which could be better to the user
- Never touch source control beyond read-only commands.
- Don't let agents approve each other's work. Agreement between agents is not a substitute for human review.
- Don't add more agents unless a specific, recurring problem calls for one.
- Don't change units, conventions, libraries, or recorded decisions without human approval.
- Don't install new dependencies without asking.
- When unsure, ask.