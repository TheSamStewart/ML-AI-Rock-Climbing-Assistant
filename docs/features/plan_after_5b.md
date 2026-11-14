# Plan after slice 5b (written 2026-11-04)

Feature: `wall_size_hold_distance` (spec: `docs/features/wall_size_hold_distance.md`).
Context: slices 0–5b are done. 5b is still pending human review. The human has added a new photo, `IMG_7552.jpeg`, with tape measurements that change a few assumptions. This plan says what to do next and in what order. It supersedes only the "Next" lines of the 5b log, not the slice definitions.

## What IMG_7552 is

A different wall from IMG_7500–7504 (flat plywood sheets, one large panel area, angle +5° at the bottom to +10° at the top). Its measurements are the first **real tape data** for this feature, so it moves slice 6 (tape-measured calibration) forward.

| Measurement | Value | Use |
|---|---|---|
| Wall edges: bottom 2.67 m, top 2.00 m, left 3.58 m, right 3.52 m | | wall-length ground truth (first one); left/right are the vertical lengths |
| Green holds (bottom), line colour green | 50 cm, bolt to bolt | hold-pair |
| Blue holds (bottom), line colour brown/dark red | 66 cm | hold-pair |
| White holds (bottom), line colour yellow | 37 cm | hold-pair |
| Green holds (top), line colour red | 20 cm | hold-pair |
| White holds (top), line colour "black" in measurements.md | 14 cm | hold-pair (see Q2) |

### Baseline run on IMG_7552 (2026-11-04, current code, no changes)
`uv run python eval_scale.py <IMG_7552.jpeg> --accuracy`:
- 237 bolts found, 233 fitted, 4 patches (largest 185). 68 holds. Median nearest-bolt spacing 158 px.
- Held-out bolt pairs: p95 **1.0%** (n=3503). Reach-range p95 0.9%. That is better than every earlier photo, so bolt detection and the fit work on this wall as they are.
- **Wall length: 17.81 grid units.**
- Timing: YOLO 9.8 s, bolts 1.8 s (the 4–5 s slice 7 target is far off, though YOLO was cold here).

### The important finding: spacing
measurements.md says the bolt holes in this photo are "25 by 25 - means incorrect original assumption" (the original assumption was 20 cm).

- The fit only gives units. Real length = units × `bolt_spacing_cm`.
- Wall length 17.81 u × 20 cm = **3.56 m**, which matches the tape (left 3.58 m, right 3.52 m) within about 1%.
- Wall length 17.81 u × 25 cm = **4.45 m**, about 25% too long.

So the evidence says this wall's square side, as the app defines it, is about **20 cm**, not 25. The most likely explanations:
1. "25 by 25" is a different thing from the app's "side of the square that has a bolt in its middle" (for example, a different count of squares, or a grid pitch measured another way).
2. The pattern is a plain square grid (no centre bolt) at 25 cm pitch. Then the app's centre-bolt assumption would read it as s = 35 cm and the wall would come out about 6.3 m. That doesn't match the tape, so it's unlikely.
3. The tape or the 25 is wrong.

This needs to be settled before any 7552 distance is used as ground truth. It is a human measurement (Q1).

## Order of work

### Step 0: decisions and data from the human (blocks everything else)
Q1–Q4 below, plus the open 5b questions (segmentation bars, √2 xfail, frozen-index guard, margin). No code.

### Step 1: record IMG_7552 as reference data (Developer; small)
- Fix `known_measurements/measurements.md`: heading level, colour typo (Q2), confirmed spacing, tape table.
- New `known_measurements/pairs.json`: for each tape pair, the two endpoints in normalised photo coordinates (from the drawn lines, on the EXIF-upright photo) and the tape cm, plus the four wall edges. A real format for tape data, shared with slice 6.
- Keep a clean copy of the photo for tests. The `.jpeg` has the lines drawn on it. Bolt detection still works (237 bolts), but the app's "Use Test Photo" stays on IMG_7504.
- Spec: Reference data section gets IMG_7552 and `pairs.json`; wall-length ground truth stops being "none".
- Done when: the files exist, and `measurements.md` agrees with the spec.

### Step 2: first tape check (Developer; Tester writes the test from the spec)
- A dev command in `eval_scale.py` (`--tape`): run `/detect`-equivalent on IMG_7552, snap each tape endpoint to the nearest detected hold, and compare the app's cm (at the confirmed spacing) with the tape. Also compare `wall_length_cm` with the left/right edges.
- Report: error per pair, and whether the 6% + 5 cm margin would have covered it.
- Done when: the table is in the spec ("Accuracy results (tape, IMG_7552)"). This is the first accuracy figure that doesn't depend on the bolt grid.
- Tester test: pairs.json is valid; the wall length is within 5% of the tape edges at the confirmed spacing (slow test, same pattern as the existing reference-photo tests).
- Risk: the pairs are bolt-to-bolt or centroid-to-centroid? "Bolt to bolt" is only stated for the first. If the human measured the holds' own bolts, the app's hold centroids will be off by a few cm. Note it per pair rather than hide it (Q3).

### Step 3: gate on the spacing answer
- **If the true side is 20 cm:** nothing in code changes. Document that "25 by 25" meant something else, and the user sets 20 in the settings.
- **If the true side is 25 cm centre-bolt:** the wall length is 25% off, which is a bug to investigate before 5c. Likely suspects: √2 misreading over a large region (the 5a rule), or `wall_length_units` taking the wrong band.
- **If it is a plain grid:** add a bolt-pattern option to settings and the backend (`bolt_pattern: "centred" | "plain"`; plain pitch p equals a centred side of p√2). That is a new small slice (5b.1) with its own spec change, since the lattice fit already handles both but the unit conversion doesn't.

### Step 4: slice 5c: fallback ladder (as planned, unchanged)
- Tier A lattice, tier B hole ellipse for panels with few or metal-filled holes (IMG_7501), tier C borrowed from a neighbouring panel (use `metric_at`'s panel → field fallback and the panel homographies).
- `scale.tiers` filled in, per-tier margins in `worker.py`, tier passed to the LLM.
- Done when (from the spec): IMG_7501 gives a scale for every panel, every distance has a tier, and the worker test checks per-tier margins.
- Per-tier margin starting points use the 5b numbers (A: from the pooled p95, B and C: wider; derive from data, don't guess). IMG_7552's tape errors from step 2 feed tier A.

### Step 5: slice 6: calibrate the centroid allowance
- Use IMG_7552's five pairs (and the other gym's data when the human has it, per the 5b "Measurements needed" list).
- Done when the 5 cm allowance is replaced or confirmed by data, and the spec says which. Five pairs on one wall is thin: say so, and don't tighten the margin on it alone.

### Step 6: slice 7: performance
Unchanged (target 4–5 s per 12 MP photo). New data point: YOLO took 9.8 s in the 7552 run, so profile YOLO as well as the pure-Python fit.

### Step 7: write-up
- One full "slice 5" entry in `handover_wall_size_hold_distance.md`, once 5c is complete (requested 2026-10-19). Include IMG_7552 and the spacing outcome.
- Update `architecture.md` and `decisions.md` in plain language (acceptance criterion 7, still open).

## Questions for the human

1. **Spacing (blocks step 3).** Please measure bolt-hole centre to centre across 5 squares along a straight row in IMG_7552's wall and divide by 5. Also say whether a bolt sits in the middle of each square on this wall. Our current numbers say the app's "square side" is about 20 cm, not 25 (see above).
2. **Line colours.** In measurements.md "Top white 14 cm" is "black", but I see no black line. The top white holds (right edge) have a yellow line, and the bottom white holds have another yellow one. Is the top 14 cm the yellow line near the top right, and the bottom 37 cm the yellow line at the bottom right? And "Bottom blue 66 cm - brown" the dark red line, "Top green 20 cm - red"?
3. **What the tape touched.** Were the five hold distances measured between the holds' own bolt holes, or between the middles of the holds? It changes how much error is the app's and how much is the measuring point.
4. **Outlines.** IMG_7552 has no panel outlines in panels.json. Do you want to draw them (as for the earlier photos), or is it fine to treat the photo as one wall for now? The wall angle goes from +5° to +10°, so I'd guess two panels.

## Not in this plan
- No code has been changed by writing this plan. Nothing has been committed.
- The unanswered 5b questions (segmentation bars, √2 xfail, frozen-index guard, margin) still stand; I'd answer them before step 4.

## Update 2026-11-04 (after the human's answers)

Answers: Q1 can't measure (not at the wall), centre bolt in every square except where a plywood sheet ends; Q2 colours confirmed (top white 14 cm is yellow); Q3 pairs measured bolt to bolt; Q4 the blue quadrilateral on IMG_7552 is how the wall edges were measured (top 2.00, right 3.52, bottom 2.67, left 3.58 m).

Done (not committed): `known_measurements/pairs.json` (5 pairs + 4 edges, points read by eye so about ±3 cm), and `eval_scale.py --tape <spacing_cm>`.

First tape check, `uv run python eval_scale.py <IMG_7552.jpeg> --tape 20`: the tape implies a median **22.6 cm per grid unit** (pairs 20.9–24.3, edges 21.0–26.6; the bottom edge is the least reliable, it runs along the floor). At 20 cm the app is 4–18% short; at 25 cm it would be 2–20% long. Neither matches. The spacing isn't needed from the human right now: a bolt-to-bolt tape across several squares, or the gym's wall spec, would settle it later. Until then the app's units on this wall are about 11% below the tape at 20 cm.

Follow-up (human, 2026-11-04): no individual panels were measured on IMG_7552; the wall goes from +5° at the bottom to +10° at the top, so it has no panel outlines and is scored as one wall. The drawn lines mark which holds were measured and are not accurate positions, so `pairs.json` endpoints and the quadrilateral edges are approximate. Treat the tape check as a rough guide (about ±10%) until exact endpoints or a bolt-to-bolt tape exist.
