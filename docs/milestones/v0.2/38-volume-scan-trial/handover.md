# Volume scan: handover (#38)

Slice status and the slice log for this issue. The contract is in `spec.md`; the milestone's order and status are in `../milestone.md`.

## Status

| Slice | Scope | Status |
|---|---|---|
| 1 | Backend, endpoint, saved scans | ✅ Done 2026-11-25 |
| 2 | App: burst camera, scan button, face overlay | ✅ Done 2026-11-25 |
| 3 | Gym trial and write-up | ⏳ Waiting on the human |

**Needs from the human:** the gym trial, with tape-measured face angles.

## Rules for agents
1. At the start of a session, read Status and the newest log entry.
2. At the end of each slice (`/handover`), update Status and add an entry at the **top** of the Slice log using the template below.
3. Don't rewrite past entries. If one was wrong, correct it in the new entry.
4. Be specific: file paths, function names, exact test output. Write what the next session needs, not a diary.

<details>
<summary>Entry template</summary>

```markdown
### YYYY-MM-DD · Slice <n>: <title>

**Status:** Complete / Partial / Blocked

**What changed**
- `path/to/file`: what and why

**Results**
- Tests: `<command>` → `<X passed, Y failed>`
- Against the done-when: met / not met, with numbers

**Decisions** (recorded in spec: yes/no)

**Questions for the human**

**Known issues / context for the next session**

**Human:** Reviewed: <yes/no> · Notes:
```
</details>

## Slice log (newest first)

### 2026-11-25 · Slices 1–2 (before this doc existed)

The slices 1–2 entry is in `docs/features_deprecated/wall_size_hold_distance_handover.md` under "Volume scan test feature: slices 1–2". Read it before the trial write-up.
