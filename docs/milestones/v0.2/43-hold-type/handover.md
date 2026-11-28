# Hold classification: handover (#43)

Slice status and the slice log for this issue. The contract is in `spec.md`; the milestone's order and status are in `../milestone.md`.

## Status

| Slice | Scope | Status |
|---|---|---|
| 1 | Plan 3 end to end: Haiku classifies every hold in the background; types reach the prompt | ☐ To do |
| 2 | The eval set (human labels) and `eval_hold_type.py`; Plan 3 baseline | ☐ To do |
| 3 | Plan 4b: Roboflow/Kaggle crops, train YOLO-cls and a DINOv2 linear classifier on Colab | ☐ To do |
| 4 | Local classifier in the backend; fine-tune on our labels; choose or combine | ☐ To do |
| 5 | App: show each hold's type | ☐ To do |
| 6 | Coaching check (AC 7) and docs | ☐ To do |

**Needs from the human:**
1. Approve the spec, and confirm the "proposed" decisions in spec Decisions.
2. Before slice 2: label the hold types on about 10 captures (sheets generated for you), and 2–3 of them twice, a few days apart.
3. Before slice 3: check the Roboflow/Kaggle licences in a browser, and choose: download the datasets yourself, or let the agent add the `roboflow` package (a new dependency).
4. Before slice 3: approve `torch.hub` (or `timm`) for DINOv2.

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

*(No slices yet. Issue started 2026-11-28. Research and plan choice are in spec Goal and Decisions.)*

**Docs to update when #43 is done:**
- `architecture.md`: the hold-type stage and the `/hold-types` endpoint.
- `decisions.md`: detect then classify; the VLM vs local choice and the eval numbers; the cost controls.
- `testing.md`: `eval_hold_type.py` and the labelled captures.
