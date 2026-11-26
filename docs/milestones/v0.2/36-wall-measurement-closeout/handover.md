# Wall measurement close-out: handover (#36)

Slice status and the slice log for this issue. The contract is in `spec.md`; the milestone's order and status are in `../milestone.md`.

## Status

| Slice | Scope | Status |
|---|---|---|
| 1 | Phone check of Settings | ⏳ Waiting on the human |
| 2 | Slab photos, replay, write-up | ⏳ Waiting on the human |

**Needs from the human:** check the bolt-pattern Settings screen on a phone; take the slab photos (wall angle, tape distances, phone tilt).

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
