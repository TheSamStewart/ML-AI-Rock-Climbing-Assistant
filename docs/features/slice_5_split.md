# Slice 5 split: plan

Feature: `wall_size_hold_distance` (spec: `docs/features/wall_size_hold_distance.md`)
Status: **approved by the human 2026-10-19**; 5a done, 5b done (pending human review), 5c next

## Why split

The slice 5 row in the spec covers four large pieces of work:

1. the √2 fix (made a must-fix by the human on 2026-10-19)
2. panel segmentation with one homography per panel, and cross-seam distances
3. the fallback ladder (tiers A/B/C) for photos like IMG_7501
4. per-tier margins

Each of these is about the size of an earlier slice. Doing all four in one session would give a very large diff to review, and Agents.MD asks for thin slices that each leave the feature working end to end. So slice 5 becomes 5a, 5b and 5c.

## What "√2" means here

√2 ("square root of 2") ≈ **1.41**. It is the ratio between a square's diagonal and its side. A 20 cm square has a corner-to-corner diagonal of 20 × 1.41 ≈ 28 cm.

Your walls have a bolt at each corner of a 20 cm square **and one in the middle**. The closest bolt to any bolt is therefore the middle one, about 14 cm away (half the diagonal). The app uses that 14 cm closest-bolt distance as its ruler.

The problem: if holds cover all the **middle** bolts in an area, the closest bolts left are the corners, 20 cm apart. Locally that pattern looks exactly like a normal wall with middle bolts, just zoomed in by 1.41×. The app then reads 20 cm as 14 cm, and every distance in that area comes out about 30% short. Read the other way round, the true value is 41% bigger than what the app reports, which is the "about 40% off" from the slice 4 question.

Today the app fixes small patches like this by asking each bolt's neighbours to vote. It fails when the patch is big (about 6×8 squares or more) or runs along the wall's edge, because the bolts deep inside the patch only have neighbours that are wrong too.

**Approved fix (boundary rule, 2026-10-19):** group the bolts that agree on scale. Where two touching groups disagree by exactly that 1.41× factor, with the same shape, the coarser group is the one misreading corners as middle bolts, so it is re-read on the finer grid. This doesn't depend on how big the patch is. The remaining limit: if a photo has **no** middle bolts visible anywhere, there's nothing to compare against, and it stays ambiguous.

## Proposed slices

| Slice | Scope | Done when |
|---|---|---|
| **5a** | √2 fix (boundary rule) in `scale.fit_lattice`. IMG_7504 outlines added to panels.json (done) and scored. Tester turns the √2 xfail tests into must-pass and adds a whole-photo "edge strip" case. Margin re-derived. Spec records the slice 7 latency target of 4–5 s. | Large interior (6×8 squares) and edge-strip centre-less regions pass at p95 ≤ 7% on synthetic walls. Reference photos don't regress (in-panel reach-range p95 per photo within 0.5 points of the baseline below). pytest green apart from the known IMG_7502/7503 same-patch tests. |
| **5b** | Panel segmentation from the bolt lattice (bolt groups split where the fitted grid changes direction or scale), then one homography per panel instead of interpolated Jacobians. Cross-seam distances go through the seam. Aimed at IMG_7502's 12.6%. panels.json is the ground truth for the segmentation. | Segmented panels match panels.json (most bolts land in the right panel). In-panel p95 ≤ 7% on every reference photo, including IMG_7502. Cross-seam bolt pairs are within the margin. |
| **5c** | Fallback ladder: tier A = lattice, tier B = metal-filled or few-hole panels (hole ellipse), tier C = scale borrowed from a neighbouring panel. `scale.tiers` is filled in, there is a margin per tier, and the worker passes the tier to the LLM. | IMG_7501 gives a scale for every panel. Every distance has a tier. The worker test checks per-tier margins. |

Slice numbers 6 (tape-measured calibration) and 7 (performance, target 4–5 s per photo, faster if it costs little) stay as they are.

### Alternatives considered for the √2 fix

- **Hole-size prior** (compare hole diameter to grid spacing): rejected. IMG_7500's holes are 1.4× larger relative to the spacing than those in 7502–7504, which is about the same size as the √2 gap itself, so this check would misfire. (Within **one** photo hole size is consistent, and it was used as an offline check of the rule's re-reads, not inside the rule. See the 5a log.)
- **Wider neighbour vote:** rejected. It only moves the size limit, so a bigger hidden patch still fails, and it makes the fit slower.

## Baseline before 5a (2026-10-19, IMG_7504 outlines now included)

`cd backend && uv run python eval_scale.py ../mobile/ML-Rock-Climbing-App/assets/known_measurements/IMG_750?.jpeg --accuracy`, in-panel reach-range p95:

| Photo | p95 |
|---|---|
| IMG_7500 | 1.2% |
| IMG_7502 | 12.6% |
| IMG_7503 | 2.7% |
| IMG_7504 | **4.6%** (n=680, previously 5.9% on same-patch pairs) |
| Pooled | 5.2% (margin stays 6%) |

## Notes

- IMG_7504's outlines are on `IMG_7504.heic`, not the `.jpeg`. The `.jpeg` stays clean because the app's "Use Test Photo" button loads it.
- IMG_7504's 13° section is yellow (confirmed by the human 2026-10-19; measurements.md corrected from "black").
- **Handover:** progress for 5a, 5b and 5c is logged in this file, one section per sub-slice. **Once all of slice 5 is complete, the full slice 5 implementation (every sub-slice's changes, results, decisions and open issues) must be written up as one entry in `docs/features/handover_wall_size_hold_distance.md`** (requested by the human 2026-10-19).

---

## 5a log (2026-10-19)

**Agent:** Developer (tests by Tester subagent)
**Status:** Complete, pending review. The √2 must-fix is met. 5 non-legacy test failures are explained below; 4 are pre-existing and 1 is a scoring artefact.

### What changed
- `backend/scale.py`: the √2 boundary rule, run in `_fit_lattice_once` right after the per-bolt vote (`_choose`).
  - `_groups`: links each bolt to its 12 nearest bolts whose metric agrees within 20%; the connected pieces are "groups".
  - `_resolve_sqrt2`: a group is re-read on the finer grid (`J @ LATTICE_BASIS`, metric ×2) when all three hold against a touching group:
    1. most links show the other group's metric at 2× its own (±15%)
    2. the other group has at least 7 bolts (`SQRT2_MIN_REFERENCE`)
    3. at least 80% of its bolts within 3 squares of the border sit on the other group's grid (`_continues_lattice`)
  - Repeated up to 10 rounds. New constants: `SQRT2_NEIGHBOURS`, `SQRT2_GROUP_TOLERANCE`, `SQRT2_RATIO_TOLERANCE`, `SQRT2_REACH_UNITS`, `SQRT2_ALIGN_FRACTION`, `SQRT2_MIN_REFERENCE`, `SQRT2_MAX_ROUNDS`.
- `known_measurements/panels.json`: IMG_7504 outlines (red 23°, yellow 13°), digitised from `IMG_7504.heic` with the slice 4 extractor.
- `known_measurements/measurements.md`: IMG_7504 section 2 "black" → "yellow".
- Spec (`wall_size_hold_distance.md`): slice 5 row split into 5a/5b/5c; √2 decision with both guards; slice 7 target 4–5 s; Reference data mentions IMG_7504's outlines.
- Tests (Tester):
  - `backend/test_scale.py`:
    - the √2 xfail becomes must-pass and is widened to 48 cases: interior 6×8, left and bottom edge strips, two corners, and a region over 70% of the wall, × 4 transforms × 0 / 30% extra hiding
    - new guard tests: neighbouring panels at a genuinely different scale must not be re-read, and a centre-less block inside a panel at a different depth is re-read against its own panel
    - new slow test: per-photo regression guard (baseline + 0.5 points, pooled over 8 fold seeds)
  - `backend/test_panels_reference.py`: IMG_7504 angles.

### How the fix was checked
- **Synthetic:** before the fix, centre-less strips, corners, half-walls and large interior patches all came out ~29% short. After it, the worst p95 over 48 scratch cases is 1.5%. With 1 px jitter, ≤ 1.1%.
- **Two guards were added after real failures:**
  - Without the grid-continuity check, a genuine panel 1.35–1.5× closer was wrongly re-read: p95 8% → 41%.
  - Without the minimum group size, on IMG_7503 one stray bolt re-read the whole yellow panel √2 wrong. Hole sizes proved it wrong: implied hole 1.40 cm, against 0.97 cm before and 1.09 cm on the red panel.
  - With both guards, every genuine-scale scratch case gives exactly the same numbers as with the rule switched off.
- **Reference photos:** only 2 bolts are re-read (IMG_7503). Their implied hole size moves from 0.78 to 1.10 cm, against a photo median of 1.03 cm, so the re-read agrees with the hole-size evidence. Nothing is re-read on 7500, 7502 or 7504.

### Accuracy after 5a
In-panel reach-range p95. "Tester guard" is the Tester's slow test, pooled over 8 fold draws, which makes it the steadier number.

| Photo | Baseline | eval_scale (one draw) | Tester guard |
|---|---|---|---|
| IMG_7500 | 1.2% | 1.2% | 1.20% |
| IMG_7502 | 12.6% | 12.6% | n/a (too noisy, see below) |
| IMG_7503 | 2.7% | 3.4% (n 254 → 437) | 3.38% (see below) |
| IMG_7504 | 4.6% | 3.1% | 3.02% |
| Pooled | 5.2% | 4.7% | |

- **IMG_7503 is better, though the guard number rose.** Once its 2 re-read bolts are corrected, more of the wall links into one lattice patch, so the guard (and eval_scale) now score extra, harder pairs they couldn't score before. Scored on **identical** pairs (same panel, same ground truth in both fits, 8 fold seeds, n = 2209), p95 goes from **3.07% with the rule off to 2.65% with it on**. (The Tester's 2.66% was measured on an intermediate version of the rule.)
- **Margin kept at 6%.** The re-derived pooled p95 is 4.7%, which would round up to 5%. However, one photo's p95 moves by 1 point or more between fold draws and runs (YOLO also gave 142 vs 143 holds on IMG_7504 across runs, so bolt counts differ run to run). Lowering the margin on that evidence isn't justified while IMG_7502 is at 12.6%. Re-derive after 5b.

### Test results
- Command: `cd backend && uv run python -m pytest -q`
- Result: **6 failed, 382 passed, 1 xfailed** (the xfail is the existing IMG_7501 one in `test_bolts.py`).
  - `test_reference_photo_held_out_bolt_pairs_p95[IMG_7502]`: the known, accepted same-patch failure. The IMG_7503 one now **passes**.
  - 4 × `test_adjacent_panels_at_different_scale_are_not_reread_as_sqrt2[*_rotated_20-*]`: these fail identically with the rule switched off, so they are pre-existing (see Known issues).
  - `test_reference_photo_in_panel_reach_range_p95_does_not_regress[IMG_7503]`: 3.38% against a 3.2% bar. This is a scoring artefact; on identical pairs the rule improves the photo (see Accuracy above). With the rule off, the guard passes.
- All 48 √2 cases pass (previously xfail), as do the non-rotated guard tests and `test_panels_reference.py` (9/9).
- Against the 5a done-when:
  - **centre-less regions of any size at p95 ≤ 7%:** met (48/48)
  - **no reference regression:** met on 7500 and 7504, and on 7503 when scored like-for-like; IMG_7502 can't be measured at 0.5-point precision
  - **pytest green apart from known tests:** not met as written, for the 5 tests explained above

### Known issues / open
- **Rotated + rescaled neighbouring panels (4 Tester guard tests fail):** `test_adjacent_panels_at_different_scale_are_not_reread_as_sqrt2[further_0.8_rotated_20 / closer_1.2_rotated_20, 0% / 30%]`.
  - These fail identically with the √2 rule switched off, so they are **pre-existing**. Where two panels differ in both scale and grid rotation, each bolt's fit near the seam pools neighbour vectors from both panels, and the error leaks more than 1 square into each panel.
  - The Tester's report of a "2× re-read" came from an intermediate version of the rule, before the two guards. On the final code, the rule changes nothing in these cases.
  - This is 5b's job (one fit per panel), so these tests become part of 5b's done-when.
- **IMG_7502 can't be held to a 0.5-point bar:** with about 130 pairs, its p95 swings from 9.8% to 17.7% depending only on the fold draw (Tester's finding). The Tester left it out of the regression guard.
- A photo with no centre bolts visible anywhere stays ambiguous (documented limit).

### Questions for the human
1. The 4 rotated-panel guard tests fail before and after 5a. Should the Tester mark them xfail with the reason "slice 5b: per-panel fit", or leave them failing as 5b's target? leave failed for 5b
2. IMG_7502's regression bar: drop it from 5a's done-when (recommended: it's 5b's target anyway, and 5b's done-when is ≤ 7%), or use a looser bar? ok
3. The IMG_7503 regression guard scores whatever pairs each fit happens to link into one patch, so a fix that links more of the wall can "fail" it while improving every shared pair (3.07% → 2.65%). Recommended: ask the Tester to score pairs on a fixed ground truth (for example, only pairs linked in both the baseline and the new fit, or a frozen baseline bolt index) or to re-baseline 7503. OK to send that to the Tester? yes ask tester 

**Human answers (2026-10-20):** Q1 leave the 4 rotated-panel tests failing as 5b's target. Q2 OK, IMG_7502 dropped from 5a's regression bar. Q3 yes, sent to the Tester in 5b (below).

---

## 5b log (2026-10-20)

**Agent:** Developer (tests by Tester subagent)
**Status:** Complete, pending review. Every 5b done-when item is met on the reference photos; the segmentation bars are the Tester's proposal (question 1). 5c next.

### What changed
- `backend/scale.py`: panel segmentation and one homography per panel.
  - `Lattice` gains `panel` (N,) and `grid` (N, 2), filled by `fit_lattice` → `segment_panels`. New `Lattice.take(mask)` subsets every per-bolt field. Measuring a lattice whose `panel`/`grid` don't match its bolts raises `ValueError`, so a stale subset can't silently mix panels.
  - `segment_panels`: competing local homographies (seeds from each bolt's 12 nearest), each bolt assigned over a window of its 7 nearest bolts, refit, merge, 8 rounds; then split into connected pieces (≥ 8 bolts), then merge again with an offset search. Guards: scale must agree with the bolts' own metric; one bolt per site; merges need the joint RMS ≤ 1.5× the parts'; and parts must be ≤ 6 spacings apart. Constants `PANEL_*`.
  - `panel_homographies(lattice)`: fitted from the lattice's own bolts each time it's measured, so leave-out evaluation stays honest.
  - `metric_at`: panel homography metric for points whose nearest in-panel bolts belong to a panel; the interpolated field otherwise, and as a guard when the homography is extrapolated too far. `segment_lengths` (and so cross-seam distances and the wall length) use it unchanged.
  - `index_lattice` (the evaluation ground truth): panel sites instead of the step-by-step walk; panels whose grid continues across a seam share a frame (`_panel_link`, tried both ways). The old walk is `_bfs_index`, still used for bolts in no panel and for seeds.
- `backend/eval_scale.py`: `--accuracy` also prints segmentation purity / coverage / panels per outline vs panels.json, cross-seam error, and the field-only error on the same pairs; uses `Lattice.take`.
- **Tests moved to `backend/tests/`** (your request): all `test_*.py` and `conftest.py`. `pyproject.toml` gains `testpaths = ["tests"]` and `pythonpath = ["."]`; coverage omits `tests/*`. Four `__file__`-relative paths in `test_bolts.py`, `test_detection.py` and `test_panels_reference.py` were moved up one level (mechanical, no test logic touched). `docs/testing.md`, `docs/architecture.md` and `.claude/agents/tester.md` updated. The test command is unchanged. I used plain moves, not `git mv`, so git will show deletes plus new files until you stage them.
- Spec: Reference data (ground truth), new "Accuracy results (slice 5b)", Decisions → "Slice 5b panels + homography per panel".

### Findings that changed the plan
- **Most of IMG_7502's 12.6% was the ground truth, not the fit.** The step-by-step lattice walk slipped by one site on 7 of 83 bolts (two different bolts were both labelled "-0.5, 7.5"). Scored on panel sites, the unchanged field method gives 3.1–3.9% and homographies 1.9–2.3%. On the old ground truth the homographies score *worse* (16%), because they disagree with the slipped labels.
- **Region growing creeps over folds** (one region took 4 panels on IMG_7500): about 1 random point in 5 is within tolerance of some lattice site. Hence the competing-models design.
- **Degenerate homographies:** without the metric guard, a too-fine or near-singular homography fits every bolt and swallowed whole photos (p95 > 1000%).

### Accuracy (cached detections, `fit_lattice` on the same bolts, 8 fold seeds like the Tester's guard)
In-panel reach-range p95, panel-site ground truth:

| Photo | 5b (homographies) | Field only (5a method), same pairs | Panels vs outlines |
|---|---|---|---|
| IMG_7500 | 1.03% | 1.13% | 173 blue · 89 red · 18+36 green/yellow (merged, 3° apart) |
| IMG_7502 | 2.28% | 3.10% | 34° panel as 2 (top 13, bottom 34) · red 15 · right wall 18 |
| IMG_7503 | 2.40% | 2.39% | red 41 · yellow 37 + 17 · two side walls |
| IMG_7504 | 2.95% | 3.17% | red 44 + 39 · yellow 42 · right wall 15 + 10 |

`eval_scale.py --accuracy` (fresh YOLO run, one fold draw) gave pooled p95 2.5%, worst photo 2.9%, purity 94–100%, coverage 91–97%, cross-seam p95 0.9% (IMG_7500, n=129) and 2.2% (IMG_7502, n=8). IMG_7503 (grids turned 45°) and IMG_7504 (grids offset at the seam) have no shared frame, so no cross-seam ground truth exists there until slice 6's tape measurements.

Final numbers are in the spec's "Accuracy results (slice 5b)" table (fresh run: 1.0 / 1.7 / 2.7 / 2.9%, pooled 2.2%).

### Tests (Tester)
- `tests/test_scale.py`:
  - `_subset` uses `Lattice.take`.
  - `_two_panels` fixed: its rotated right panel used to swing across the seam into the left panel (35/160 and 63/160 left bolts inside the right panel's footprint, confirmed independently by the Tester). New self-check `test_two_panel_geometry_keeps_the_seam_clear`. The 4 rotated cases you asked to leave failing for 5b now pass.
  - Regression guard (your 5a Q3): rebuilt on a **frozen bolt index**, `tests/data/reference_bolt_index.json`, from the 5b fit. Live bolts are matched to it by position, so the pairs scored are the same every run. IMG_7502 is back in (its spread is now 1.6–3.1%, was 9.8–17.7%). Re-freeze with `uv run python tests/freeze_reference_index.py`, only when you approve a ground-truth change.
- New `tests/test_scale_panels.py` (54 tests):
  - contract: fields, `take`, the `ValueError`, panel-less lattices
  - synthetic folds at 15°/25° with a continuous grid (in-panel ≤ 7%; cross-seam ≤ 6% against the along-surface distance)
  - offset seams, coplanar and turned
  - a bolt-free strip through one panel
  - a background wall at another depth
  - stray / too-fine / degenerate points
  - reference-photo segmentation, in-panel and cross-seam checks

### Test results
- Command: `cd backend && uv run python -m pytest -q`
- Result: **446 passed, 0 failed, 3 xfailed** (5 min; Developer's own run on the final code, matching the Tester's).
  - The xfails are the existing IMG_7501 one and the 2 cases of question 2.
  - The known IMG_7502/7503 same-patch failures from slices 3–5a now pass: 2.0% and 3.0%.
- Against 5b's done-when:
  - **Segmented panels match panels.json:** met under the Tester's proposed bars (purity ≥ 90%, coverage ≥ 85%). Measured purity 94–100%, coverage 91–97%.
  - **In-panel p95 ≤ 7% on every reference photo incl. IMG_7502:** met, 1.03 / 2.28 / 2.40 / 2.95% (Tester, 8 draws).
  - **Cross-seam bolt pairs within margin (6%):** met where they exist. IMG_7500 1.05%, IMG_7502 3.67%. The evidence is thin (see Known issues).
  - **The rotated-panel tests from 5a:** pass.

### Decisions made (recorded in spec: yes)
- **Competing homographies, not region growing:** growing creeps over folds.
- **The ground truth changes to panel sites:** the step-by-step walk slipped on IMG_7502. This changes what every accuracy number means from 5b on, so please check it.
- **Parts more than 6 spacings apart never merge:** a homography can absorb a grid offset across a long gap. The cost is that IMG_7502's 34° panel stays two panels.
- **Bolts in no panel don't vote on which panel a point is measured on.** They're the bolts whose fit is contaminated across a seam.
- **The margin stays at 6%:** see question 4.

### Questions for the human
1. **Segmentation bars** (Tester): the spec says "most bolts land in the right panel". The Tester proposes purity ≥ 90% and coverage ≥ 85%; measured 94–100% and 91–97%. OK? ok
2. **√2 limit found by the Tester** (non-strict xfail): 4 false detections that complete one √2-finer cell around a centre bolt give 9 bolts on the finer grid, over the 7-bolt guard from 5a. That re-reads the whole wall √2 wrong (p95 41%). This is in the 5a per-bolt stage, not 5b. Such points only just pass slice 2's spacing filter (0.707 vs 0.7). Make it must-pass (a 5a follow-up, e.g. requiring the finer reference group to hold more than one cell), or accept it as a limit? you make the optimal decision
3. **Frozen-index regression guard** (Tester): is the approach and the 21 KB data file OK? IMG_7504 moved +0.77 points in 1 of 8 simulated detection changes, so it could trip the 0.5-point bar on a real detection change. Keep 0.5, or loosen 7504's bar? you make the decision
4. **Margin:** the pooled p95 is now 2.2%, so the slice 4 rule (round up) gives 3%. I recommend **keeping 6% until 5c**, which adds per-tier margins:
   - the ground truth changed in this slice
   - strict refit still swings (IMG_7503 28.7% on one bad fold)
   - cross-seam evidence is thin
   - all photos are from one gym

   Halving the LLM's benefit of the doubt on that basis seems early. Lower it now instead? 6% until 5c is fine

### Known issues
- **Cross-seam evidence is thin:**
  - IMG_7500's pairs cross a 3° fold measured as one panel.
  - IMG_7502's are 3 boundary bolts (n=70 over 8 draws; one draw was 15.7%).
  - 7503 and 7504 have no shared grid frame, so there is no ground truth.
  - Real cross-seam checks need slice 6's tape measurements.
- **Strict k-fold refit** on IMG_7503 is 28.7% (all-pairs) from one bad fold. It's identical without homographies, so it's pre-existing lattice-choice fragility on fewer bolts.
- **Run-to-run detection variance** remains (IMG_7504 has given 202 and 211 bolts).
- `/detect` is about 0.3–0.45 s slower: `compute_scale` was 1.8–3.3 s and is now 2.2–3.7 s. Slice 7 must absorb this.
- **Wall length on IMG_7502** moves from 22.8 to 21.1 units. There is no ground truth to say which is right.
- **IMG_7501** is still 0 bolts (5c).

### Measurements needed (human, requested 2026-10-20)
The human will measure a different type of climbing wall (still with bolt holes). These measurements serve four purposes:
- the first real cross-seam check (currently the thinnest evidence)
- the first wall-length ground truth
- a second wall type, to show the panel detection isn't tuned to one gym
- a start on slice 6's hold measurements

Everything is in cm, measured **along the wall surface**: let the tape follow the wall and bend over the seam, rather than going through the air.

**1. About the wall** (write these down first)
- **Bolt pattern.** Is it a square with a bolt in the middle of each square, like your current walls? Or a plain square grid, or something else? A close-up photo of a few bolts is enough. **The app assumes the square-with-centre pattern, so if this wall is different, tell me before anything else.**
- **Bolt spacing.** The side of one square, centre to centre. Measure across 5 squares and divide by 5, which is more accurate than measuring one square.
- **Surface and holes.** The surface (plywood, painted, textured, ...), and whether the holes are dark and open or metal-filled.
- **Each panel's angle**, as in measurements.md.
- **Each seam:** does a row of bolts carry on straight across it, or jump?

**2. Photos**
- Use the phone camera at full resolution, with no zoom, crop or edits. Get the whole wall in frame, from roughly where a climber would stand.
- Make two copies of each photo:
  - **clean**, untouched
  - **marked**: in Paint, draw the panel outlines in different colours as before, plus a numbered dot on every point you measured
- If you can, take 2–3 photos from different positions (front-on, from the side, from low down). The same measurements are reused for each photo.

**3. Measurements, most needed first.** Measure from bolt-hole centre to bolt-hole centre, not from holds: hole centres are exact. Pick holes that are clearly visible in the photo.
1. **Across seams:** 6–10 pairs of bolts, one on each side of a seam, between about 30 and 250 cm apart. Include at least one fold (where the angle changes), and a seam where the grid jumps if the wall has one.
2. **Wall length:** from the top edge of the wall to the bottom edge, in one vertical line, plus the top-most and bottom-most bolt in that line. Note which line you used (for example "line through dot 5").
3. **Within one panel:** 4–6 bolt pairs. At least 2 of them should span an area where holds or volumes hide the bolts, like the middle of IMG_7502.
4. **Optional, for slice 6:** 5–10 hold-to-hold distances between holds a climber would move between, centre to centre, noting the hold type (crimp, jug, volume, ...).
5. **Optional:** for 2–3 of the cross-seam pairs, also the straight-line distance through the air. This needs a second person. It tells us whether reach should be judged along the surface (what the spec does now) or in a straight line.

**4. Where to put them**
- Put the photos in `mobile/ML-Rock-Climbing-App/assets/known_measurements/` as `IMG_XXXX.jpeg` (clean) and `IMG_XXXX_marked.jpeg` (marked). HEIC is fine.
- Add a section to `measurements.md` in the same style as the existing ones:
  ```
  ## Image_XXXX  (wall: <type>, bolt pattern: <square with centre bolt / ...>, spacing: <cm>)
  Section 1 - red outline - 15 degrees
  Section 2 - yellow outline - 30 degrees
  Seams: red/yellow - grid continues | grid jumps

  | From | To | cm | Notes |
  | 1 | 2 | 143 | across red/yellow seam |
  | 3 | 4 | 88 | in red, across a big volume |
  | top edge | bottom edge | 410 | wall length, line through dot 5 |
  ```

**What happens next:** I'll check bolt detection works on the new surface, add the outlines to panels.json and the measured points to a new reference file, and compare the app's distances with your tape. That will be the first accuracy check that doesn't rely on the bolt grid. It also decides whether the 6% margin (question 4) can come down.

### Context for the next session
- Scratch tools are in this session's scratchpad, not the repo:
  - `ev.py`: harness on cached detections, pooled 8 seeds like the Tester's guard
  - `run3.py`: homography vs field vs old ground truth
  - `draw.py`: panel overlays
  - cached bolts in `ref/*.json`
- Panel overlays: `C:\Users\samst\AppData\Local\Temp\claude\d--ML-Rock-Climbing-Coach-App-ML-AI-Rock-Climbing-Assistant\662442d1-8a06-4059-b528-62d1e003b777\scratchpad\IMG_750{0,2,3,4}_panels_5b.jpg` (temporary).
- 5c's tier C ("scale borrowed from a neighbouring panel") can use the panel homographies: a panel with too few bolts can borrow a neighbour's homography metric. `metric_at` already falls back panel → field.
- A panel needs ≥ 8 bolts for a homography (`PANEL_MIN_BOLTS`). IMG_7501's panels (3–5 visible holes each) won't segment; that's what tier B is for.

### Next
- 5c: fallback ladder (A lattice / B hole ellipse / C borrowed). `tiers` gets filled, margins are per tier, and the worker passes the tier to the LLM. Done when IMG_7501 gives a scale for every panel, every distance has a tier, and the worker test checks per-tier margins.

---

## 5b follow-up (2026-11-04)

**Human answers to the 5b questions:** Q1 segmentation bars OK (purity ≥ 90%, coverage ≥ 85%). Q2 Developer's decision. Q3 Developer's decision. Q4 margin stays 6% until 5c.

**Decisions (Developer):**
- **√2 limit (Q2): fixed, not accepted.** The human called a 40% error unacceptable (2026-10-19), so a hole in the rule that re-reads a whole wall (p95 41%) can't stay as a "known limit". `scale._resolve_sqrt2` now also requires the finer reference group to reach `SQRT2_MIN_REFERENCE_RADIUS = 1.5` grid units from its centre (`_radius_units`). Four false points completing one finer cell give 9 bolts within half a unit, so they no longer count as a reference.
  - Result: `four_strays_completing_one_finer_cell-homography` now **XPASSes** (the Tester should drop its xfail). The `-foreshortened_rotated` case still fails at p95 10.4% (bar 7%), **identically with the √2 rule switched off**, so it is a separate effect (4 false points disturbing the per-bolt fit), not a re-read. Left as a known issue.
  - Reference photos unchanged: in-panel p95 1.0 / 1.7 / 2.7 / 2.9%, pooled 2.2% (same as the 5b final run).
- **Frozen-index guard (Q3): keep the approach and the 21 KB file; keep the 0.5-point bar for 7500, 7502 and 7503, loosen IMG_7504's to 1.0 point.** It moved +0.77 in 1 of 8 simulated detection changes, so 0.5 would trip on noise rather than a real regression. **To do (Tester):** apply the 7504 bar; remove the xfail on the homography stray case.

**IMG_7552 (new, 2026-11-04):** see `plan_after_5b.md`. Tape check says about 22.6 cm per grid unit; the spacing is unresolved.

## 5c log (2026-11-04)

**Agent:** Developer. **Status:** Partial: tiers A/C and per-tier margins are built; tier B is not (decision needed). Tests for the new contract are not written yet (Tester).

### What changed
- `backend/scale.py`: `segment_support`, `TIER_A_MAX_SUPPORT`, `_tier_rows`, `select_tiers`; `compute_scale` fills `tiers` (rows of "A"/"C").
- `backend/main.py`: `/analysis` passes `route["tiers"]`.
- `backend/worker.py`: `DISTANCE_MARGIN_PCT_BY_TIER = {"A": 6, "C": 14}`; `distances_cm` entries gain `tier`; `accuracy.margin_pct_by_tier`; the prompt and guidance explain the tiers. `DISTANCE_MARGIN_PCT` stays 6 (wall length).
- `mobile/.../api/detectHolds.tsx`: `Scale.tiers` is `string[] | null`. `npx tsc --noEmit` clean. No UI change.
- Spec: new "Slice 5c: confidence tiers" section with the derivation; Outputs updated.

### Test results
- `uv run python -m pytest -q tests/test_main.py tests/test_worker.py tests/test_concurrency.py tests/test_detection.py tests/test_redis_client.py`: **158 passed, 13 failed.** All 13 pin the old contract (`tiers is None`; exact `distances_cm` keys; `margin_cm` at 6% for every pair; exact `accuracy` keys; prompt wording). They are the Tester's to rewrite from the spec section; none shows a logic error.
- The slow reference tests (`test_scale*.py`) were not re-run after the tier code, which only adds a read-only output.

### Needs the human
1. **Tier B:** drop it (recommended, evidence in the spec), or invest in it with no ground truth to validate against?
2. **Tester:** rewrite those 13 tests and add: tier A for a short line on a full lattice; tier C across a bolt-free block; `select_tiers` ordering; worker margins per tier; an old cached scale without `tiers` is treated as A.
3. **UI:** show tier C distances differently (for example "~" before the label)? Not done; the spec doesn't ask for it.
