# Wall size and hold distance

## Goal
This feature will implement 3 main things:

1. Implement a system which uses the TNUT bolt holes distance in climbing walls to figure out the size of the wall
2. Implement a system in which we figure out the distance between all holds
3. Implement a settings button inside CameraScreen.tsx which allows the user to input the distance between the bolt holes in their gym for more accurate results

## Inputs
The picture of the climbing holds from the user, for the purpose of development I have provided images in D:\ML-Rock-Climbing-Coach-App\ML-AI-Rock-Climbing-Assistant\mobile\ML-Rock-Climbing-App\assets\images with known measurements

- `bolt_spacing_cm`: side length of the bolt grid square, set by the user in the CameraScreen settings panel. Default 20, allowed range 10–50 (raised from 5 on 2026-10-16: bolt detection assumes a grid of roughly 12 cm or wider, see Decisions). Stored on device (AsyncStorage key `boltSpacingCm`).

## Outputs
We know the size of the wall and distance between all holds selected by the user in PhotoPreview.tsx

- `POST /detect` response gains a `scale` object, in **grid units** (1 unit = one `bolt_spacing_cm`):
  ```
  scale: {
    status: "ok" | "insufficient_bolts",
    bolt_count: int,
    wall_length_units: float | null,      // along the wall surface, top bolt to bottom bolt + half a pitch each end
    distances_units: float[][] | null,    // N×N, indexed in the same order as `detections`
    tiers: string[] | null               // N rows of N chars, "A" or "C" per distance (slice 5c; "B" is not produced, see Decisions)
  }
  ```
- PhotoPreview: a line and label (cm below 1 m, else m to 1 decimal) between each consecutively selected hold. Distance in cm = `distances_units × bolt_spacing_cm`.
- LLM payload (worker.py): holds with ids, `distances_cm` for every selected pair, `wall_length_cm`, and an `accuracy` block that explains the margin to apply.
  ```
  distances_cm: [{from: id, to: id, cm: float, tier: "A"|"C", margin_cm: float}]   // margin_cm = cm × margin_pct_by_tier[tier]/100 + centroid_allowance_cm, 1 decimal, from the already-rounded cm
  accuracy: {
    margin_pct: 6,                 // relative margin, derived in slice 4 (see Accuracy results)
    centroid_allowance_cm: 5,      // hold centres are estimates; added to every hold-to-hold distance, not to wall_length_cm
    applies_to: str,
    guidance: str                  // plain-language rule stating both numbers
  }
  ```

## Acceptance criteria
1. we derive the distance from the top to bottom of the wall using TNUT bolt holes
2. we derive the distance between holds on the wall 
3. we display the distance between each hold that the user selects in PhotoPreview.tsx
4. in the JSON payload for the LLM in worker.py, we send the distance from each hold to each hold so the LLM can have a better picture of what holds are reachable from each hold
5. edit the coaching payload so that the LLM understands the accuracy of this and if a hold seems unreachable by 10% to give them the benfit of the doubt due to accuracy restrictions (this is an example you will derive the accuracy values)
6. A settings button will exist on CameraScreen.tsx which is scrollable but for will only include bolt hole distance where the user can input their own bolt hole value.
7. At the end of the feature (the "End" row in Slices), update architecture.md, testing.md and decisions.md with high-level human readable non-jargon overview of changes made in this feature

Measurable targets (agreed with human 2026-10-16):
- Held-out bolt pairs within one panel: p95 relative error ≤ 7%.
- Changing `bolt_spacing_cm` rescales the displayed distances without re-running detection.
- `insufficient_bolts` only when the whole photo has no usable bolt.

## Reference data
D:\ML-Rock-Climbing-Coach-App\ML-AI-Rock-Climbing-Assistant\mobile\ML-Rock-Climbing-App\assets\known_measurements

Inside know measurements you have measured photos

Folder layout (tidied 2026-11-18):
- `reference/`: everything the tests and eval scripts read. The full-res photos (`IMG_7500–7504.jpeg`, `IMG_7552.jpeg`, `epic_wall.jpg`, `epic_wall_2.jpg`) plus `panels.json` and `pairs.json`. "Use Test Photo" loads `reference/IMG_7504.jpeg`.
- `originals/`: the HEIC originals (git-ignored). `IMG_7504.heic` is also the source of IMG_7504's panel outlines. The HEICs keep the iPhone's tilt reading in their metadata; the `.jpeg` copies of 7502–7504 and 7552 lost it.
- `notes/`: the human's raw notes (`measurements.md`, `epic_wall_2_measured.txt`).
- `gym_sessions/<date>/`: on-device app tests. `2026-11-17/` holds three PhotoPreview screenshots (IMG_7899, 7900, 7902; 1170×2532 with overlays, so not usable as reference photos) and their tape and angle notes.

- Ground truth for now is the bolt grid itself: two bolts whose lattice offset is (i, j) squares are `bolt_spacing_cm × |(i, j)|` apart. Bolt pairs are held out of the fit and the predicted distance is compared to this.
  - The offsets come from `scale.index_lattice`. Since slice 5b that is each bolt's site in its segmented panel's lattice (rounded through the panel homography), with panels whose grid continues across a seam sharing one frame. Bolts in no panel still use the step-by-step walk (BFS). The walk alone slipped by one site on IMG_7502 (7 of 83 bolts), which is what its 12.6% mostly was (see Accuracy results, slice 5b).
- Tape-measured hold-to-hold distances: `known_measurements/reference/pairs.json` holds IMG_7552 (5 pairs, 4 edges), `epic_wall` (6 pairs, 2 lines, iPhone measuring app) and `epic_wall_2` (real tape, 2026-11-13; see "Slice 6"); `eval_scale.py --tape <spacing_cm>` compares them. See "Accuracy results (epic_wall)". Slice 6 uses them.
- `epic_wall_2.jpg` is the same photo as `epic_wall.jpg` (pixel-identical under the drawings), with the tape pairs labelled by small red digits beside each end's bolt hole instead of panel outlines. Same wall, holds and panel angles. Raw notes: `notes/epic_wall_2_measured.txt`.
- `epic_wall.jpg` (2420×3294, a second gym wall): ten panels (P7–P16, 14–31°) outlined in red and numbered in green **on the photo itself**; outlines are in `panels.json` under `epic_wall`. The bolt square side is **25 cm** (human, 2026-11-13; it was first read as 26 cm from "5 holes across a row = 1.04 m", see "Slice 6"), not 20.
- Panel outlines: `known_measurements/reference/panels.json`, digitised (2026-10-19) from the coloured lines drawn on IMG_7500, 7502, 7503 and 7504, with angles from measurements.md. Normalized x, y on the EXIF-upright photo. IMG_7504's outlines are drawn on `originals/IMG_7504.heic` (red 23°, yellow 13°); `IMG_7504.jpeg` stays clean for the app's "Use Test Photo". IMG_7501 has no outlines drawn.

## Accuracy results (slice 4, 2026-10-19)
`cd backend && uv run python eval_scale.py ../mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/IMG_750?.jpeg --accuracy`. Leave-own-J-out held-out bolt pairs. "Reach range" = true distance 1.5–12.5 grid units (30–250 cm at 20 cm), the distances the LLM margin is for. In-panel = both bolts inside the same outline in panels.json.

| Photo | All same-patch p95 | In-panel p95 | In-panel p95, reach range | In-panel strict refit p95 |
|---|---|---|---|---|
| IMG_7500 | 4.0% | 1.4% | **1.2%** (n=3593) | 1.6% |
| IMG_7502 | 12.0% | 15.6% | **12.6%** (n=132) | 14.8% |
| IMG_7503 | 8.2% | 3.5% | **2.7%** (n=254) | 17.6% |
| IMG_7504 (no outlines, same-patch) | 6.1% | n/a | **5.9%** (n=1054) | 7.5% (all) |
| IMG_7501 | 0 bolts | n/a | n/a | n/a |

- Pooled reach range, each photo weighted equally: p50 0.7%, **p95 5.2%**. Worst photo: 12.6% (IMG_7502).
- Error falls with distance. Pairs under 1.5 units have p95 4.5–60% (IMG_7502's 60% is 19 pairs), which the fixed centroid allowance absorbs at those lengths. 8–12.5 units is ≤ 2.1% in-panel everywhere.
- The in-panel target (p95 ≤ 7%) is met on 7500, 7503 and 7504, and missed on 7502 (sparse plywood, one big 34° panel). Accepted by the human for slice 4 (2026-10-19).

## Accuracy results (slice 5b, 2026-10-20)
Same command and pairs as above (leave-own-J-out, reach range 1.5–12.5 u, in-panel by panels.json), with the slice 5b ground truth (panel sites, see Reference data). "Field only" is the slice 3–5a method (no homographies) scored on the same pairs and ground truth. Cross-seam = pairs in two different outlines whose grids share one frame.

| Photo | In-panel p95 | Field only | Cross-seam p95 | Segmentation purity / coverage | Segmented panels per outline |
|---|---|---|---|---|---|
| IMG_7500 | **1.0%** (n=3483) | 1.1% | 0.9% (n=129) | 94% / 97% | 1, 1, 1, 1 (green 17° and yellow 14° are one panel) |
| IMG_7502 | **1.7%** (n=117) | 3.9% | 2.2% (n=8, see below) | 95% / 96% | 3 (34° top, 34° bottom, 3 boundary bolts on the red panel), 1 |
| IMG_7503 | **2.7%** (n=278) | 2.3% | n/a (grids turned 45°, no shared frame) | 100% / 95% | 1, 2 |
| IMG_7504 | **2.9%** (n=436) | 2.9% | n/a (grids offset at the seam) | 100% / 91% | 3, 1 |

- Final run 2026-10-20 (fresh YOLO + bolt detection, one fold draw). Pooled (equal weight): p50 0.5%, **p95 2.2%**. Worst photo 2.9%. The in-panel target (p95 ≤ 7%) is met on every reference photo, including IMG_7502. The Tester's guard, pooled over 8 fold draws on a frozen bolt index, gives 1.03 / 2.28 / 2.40 / 2.95%.
- **Where IMG_7502's 12.6% went:** mostly the ground truth. Scored on the corrected sites, the old field method gives 3.9% on the same pairs; panel homographies take it to 1.7%. On 7500, 7503 and 7504 the homographies match the field to within half a point.
- Purity = of bolts in both a segmented panel and an outline, the share whose segmented panel's majority outline is their own. A physical panel can be split where one homography doesn't fit all of it (IMG_7504's 23° panel), which keeps distances right; two panels a few degrees apart can be one (IMG_7500 green/yellow). IMG_7502's 34° panel is two segmented panels, top and bottom, because no bolts are detected in its middle (see Decisions, merge guard 4).
- **Cross-seam evidence is thin.** On IMG_7500 the pairs come from the green/yellow seam (merged into one panel, so this tests a 3° fold measured as flat). On IMG_7502 they are 3 yellow-outline bolts at the boundary that the red panel claims, not a real two-panel seam; the Tester's 8-draw figure there is 3.67% (n=70, one draw 15.7%). Synthetic folds (15°, 25°) and coplanar offset seams are ≤ 6% in the Tester's tests. Real cross-seam checks need slice 6's tape measurements.
- Strict k-fold refit: 1.2 / 8.3 / 6.2 / 5.3% in-panel, but IMG_7503's all-pairs strict is 28.7%, from one of five folds where the lattice fit itself goes wrong on the reduced bolt set, identically with or without homographies (29.1% field only, earlier run). Pre-existing; the lattice choice flips on a few bolts (see Image resolution).

## Image resolution needed (measured 2026-10-19)
Reference photos (3024×4032) were resized to each height with Lanczos and run through YOLO, `detect_bolt_holes`, `fit_lattice` and `eval_scale.accuracy`. "Hole" is the median bolt-hole diameter. "NN" is the median nearest-bolt distance, which is the diagonal, i.e. 0.71 × bolt spacing. p95 is held-out reach-range error, in-panel where outlines exist. Full-res wall lengths are the reference.

| Photo | Height px | Bolts | Hole px | NN px | Wall (units) | p95 |
|---|---|---|---|---|---|---|
| IMG_7500 | 2400 / 2800 / 3200 / 3600 / 4032 | 321 / 351 / 362 / 357 / 346 | 6.1 → 10.0 | 66 → 110 | 25.3 / 26.2 / 26.1 / 25.8 / 26.1 | 6.0 / 1.4 / 1.3 / 7.7 / 1.2% |
| IMG_7502 | same | 27 / 65 / 79 / 85 / 116 | 6.7 → 8.0 | 91 → 123 | 4.6 / 20.5 / 20.0 / 19.3 / 22.8 | 4.1 / 4.4 / 7.0 / 4.4 / 12.6% |
| IMG_7503 | same | 92 / 125 / 161 / 172 / 178 | 6.0 → 8.3 | 83 → 127 | 9.8 / 13.8 / 20.6 / 20.9 / 19.3 | 2.9 / 3.3 / 3.0 / 3.8 / 2.7% |
| IMG_7504 | same | 97 / 214 / 201 / 162 / 211 | 6.1 → 8.4 | 89 → 128 | 8.6 / 18.8 / 19.7 / 18.8 / 19.4 | 8.5 / 37.6 / 8.4 / 5.3 / 5.9% |

At 1500 px, 7500 and 7504 find 0 bolts. At 2000 px they find 106 and 43, and the wall length comes out about half the true value.

- **Requirement:** about **6 px per cm of wall** or more. That means a bolt hole at least 7 px across and neighbouring bolts at least 90 px apart (≈ 110 px at the default 20 cm spacing). For a photo framing a whole wall, this is about **3200 px on the long side**. Below it, bolts drop out unevenly, so the lattice covers only part of the wall and the wall length collapses: 7503 gives 9.8 u at 2400 px against 19.3 u at full res.
- **Use the native camera resolution** (12 MP, 4032 px). Never resize or recompress uploads in the app. `CustomCamera.tsx` already pins the largest `pictureSize`. Resolutions above 12 MP are untested; they should be no worse, because `bolts.MAX_SIDE` shrinks anything over 4096 px.
- **More pixels isn't always more accurate above 3200 px.** p95 jumps around between neighbouring sizes (7500 is 7.7% at 3600 px, 7504 is 37.6% at 2800 px) because the lattice choice flips on a few bolts. That's fit robustness, not resolution. It belongs with the IMG_7502 accuracy work (slice 5), and slice 7 should keep resolution in mind.
- A photo taken further away has the same problem as a resized one: fewer pixels per cm. The px/cm rule is the real limit, not the image size.
- The 640×640 dataset test photo (about 1 px per cm) finds no bolts, which is expected. "Use Test Photo" now loads the full-res IMG_7504.jpeg.

## Slices
| Slice | Scope | Done when |
|---|---|---|
| 0 | Spec filled in, Tester/Reviewer agent files created, test command agreed. | Human approves the spec. |
| 1 | Walking skeleton: settings modal + AsyncStorage; `/detect` returns a stub `scale` (photo height = 20 grid units, aspect-corrected Euclidean); PhotoPreview lines + labels; `bolt_spacing_cm` on `/analysis`; worker payload with ids, `distances_cm`, placeholder 10% margin. | Tap 3 holds on device → labelled lines; LLM payload contains `distances_cm`; pytest green. |
| 2 | Real `detect_bolt_holes` (OpenCV blobs on full-res image, masked by HOLD/VOLUME polygons) + `eval_scale.py` debug overlay. | IMG_7500/7501 overlays show most visible holes and few false positives; Tester's count/spacing-regularity tests pass. |
| 3 | `fit_lattice` + local Jacobian field + segment integration replace the stub; wall length. | Held-out in-panel bolt pairs p95 ≤ 7%; IMG_7500's 6° and 23° panels give consistent scale after correction. |
| 4 | Accuracy evaluation; derived margin replaces the placeholder in the prompt. | `eval_scale.py` numbers recorded below; worker test checks the margin text. |
| 5 | Split into 5a/5b/5c on 2026-10-19 (approved; see `docs/features/slice_5_split.md`). | See 5a–5c. |
| 5a | √2 fix (boundary rule, see Decisions); IMG_7504 outlines scored; margin re-derived; slice 7 target recorded. | Centre-less regions of any size (interior 6×8 squares, a 3-square strip along the wall edge) measure at p95 ≤ 7% on synthetic walls; reference photos don't regress (in-panel reach-range p95 within 0.5 points of the 2026-10-19 baseline); pytest green apart from the known IMG_7502/7503 same-patch tests. |
| 5b | Panel segmentation from the bolt lattice + homography per panel; cross-seam distances. | Segmented panels match panels.json; in-panel p95 ≤ 7% on every reference photo incl. IMG_7502; cross-seam bolt pairs within margin. |
| 5c | Confidence tiers (A lattice / C borrowed); `tiers` filled; per-tier margins in the worker. **Tier B (hole ellipse) dropped, approved by the human 2026-11-09.** | Every distance has a tier; worker test checks per-tier margins. IMG_7501 stays `insufficient_bolts` (no distances, existing hint), which replaces the original "IMG_7501 gives a scale for every panel". |
| 5d | **Panel angle (added 2026-11-09, plan below, not yet approved).** Estimate the wall angle under each selected hold from the photo and send it to the LLM. Step 1 is a feasibility measurement, step 2 the plumbing. | Step 1: angle estimates compared with measurements.md on all six reference walls, go/no-go agreed with the human. Step 2: each selected hold carries `wall_angle_deg` and the prompt explains how to use it; worker test checks the payload. |
| 6 | Tape-measured hold pairs re-calibrate the centroid allowance. **2026-11-13: done, 5 cm confirmed by data (see "Slice 6"); bad measurements deleted.** | Human measurements exist in measurements.md (now `pairs.json` / `epic_wall_2_measured.txt`); the allowance is replaced or confirmed and the spec says which. |
| 5e | **Approved by the human 2026-11-13; after slice 6, before slice 7.** Wall-angle improvements from the 5d handover. (1) Group bolts by their own wall direction before assigning holds (fixes the smooth-seam miss, epic_wall P14). (2) A confidence per hold: no angle when the evidence is thin or the two mirror answers are equally supported. Plus a synthetic-wall test of the vote. (3) **Added 2026-11-19:** `backend/eval_field.py`, a dev script that replays the 15 field captures (photo + recorded gravity) through the current pipeline and scores them against each `truth.json`, as the regression check for 5e, 6b, 8 and 7. The real-phone angle check is done (2026-11-18, see "Field test"). | P14 within 10° without regressing the other 18 panels in `eval_angle.py`; the confidence rule is tested; the field replay shows no hold angle or distance getting worse than its baseline in "Field test" (volume holds excepted, they are 6b's). |
| 6b | **Volumes (added 2026-11-19, plan in "Slice 6b: volumes").** Spot holds that sit on a volume, and estimate the volume face's own angle by a separate method from the wall's (the bolt grid gives the wall behind the volume, not the face). | Every picked hold has an on-volume yes/no; the volume face angle meets a bar agreed with the human after the step 1 feasibility check (or is left out, with the hold flagged); the LLM gets the wall angle and the volume face angle separately; worker test checks the payload. |
| 8 | **Volume fixes and more coaching information (added 2026-11-19, plan in "Slice 8").** Part 1: fix the remaining volume problems, first the distance error for holds that stand off the wall (field capture `173933`: +19%). Part 2: send the LLM (1) hold positions in cm on the wall and each move's up/across parts, (3) an on-volume flag plus the volume's size, (4) a note when a move crosses a change of wall angle, (5) the climber's height and ape index from settings, (6) hold colour, used to suggest the route's holds and nearby footholds. Item 2 of the 2026-11-19 list (hold size) is not in scope. | Part 1: `173933`'s pair is inside its tier's 6%/14% part of the margin (not only the 5 cm allowance), with no other field capture worse. Part 2: each item reaches the LLM payload and the prompt explains it; worker tests check each; architecture.md section 5 rows ticked. |
| 7 | Performance: vectorise the pure-Python loops in `scale.fit_lattice` and `bolts`, and shrink the N×N `distances_units` payload (about 300 KB for 200 holds). Planned on 2026-10-19, after the human deferred optimisation. | `/detect` latency target met on a 12 MP photo (target **4–5 s**, agreed 2026-10-19 — faster if it costs little; it is about 7–8 s today); accuracy numbers unchanged. |
| End | Wrap-up, run once the last slice is done. **Order agreed 2026-11-19: 5e → 6b → 8 → 7 → End**, so slice 7 times the final pipeline. Update `docs/architecture.md` and `docs/testing.md` for the whole feature, plus the handover entry and `decisions.md` (acceptance criterion 7). Agreed with the human 2026-11-09: no docs other than this spec are edited before this step. | `architecture.md` and `testing.md` describe the finished feature in plain language, and the human has reviewed them. |

## Decisions
- Approach:
  - **Bolt detection:** classical OpenCV (CLAHE + `SimpleBlobDetector`) on the full-resolution upload, not the 1024 px detection thumbnail. Blobs inside HOLD/VOLUME polygons are dropped.
  - **Lattice:** square grid of side `bolt_spacing_cm` with a centre bolt, so nearest neighbours are diagonal at `bolt_spacing_cm / √2`. The fit must use this lattice.
  - **Scale:** local 2×2 Jacobian field (pixels → grid units) from each bolt's neighbour vectors; distances integrate the field along the segment (≈16 samples). Since slice 5b, inside a segmented flat panel the metric comes from that panel's homography instead (see "Slice 5b panels").
  - **Units:** the backend works in grid units; client and worker multiply by `bolt_spacing_cm`.
  - **Distances computed on the backend only** (N×N matrix in the `/detect` response), because there is no JS test runner.
  - **Wall size** = length along the wall surface, not vertical height.
  - **Odd sections (IMG_7501):** a misaligned seam breaks shared lattice coordinates, not scale. Each panel keeps its own scale; tiers B/C cover panels with few or no visible bolts.
  - **Accuracy margin** = p95 relative error from held-out bolt pairs + a centroid allowance (starting at 5 cm, revisit in slice 6), per tier.
  - **Settings storage:** `@react-native-async-storage/async-storage` (new dependency, approved).
  - **Display:** lines between consecutive picks only.
- Alternatives rejected (with reason):
  - Retrain YOLO with a BOLT_HOLE class: hundreds of tiny holes to label before slice 1 can run.
  - Manual tap calibration: adds friction and gives one scale only, which fails on angled sections.
  - One global scale per photo: wrong across panels at different angles and with perspective.
  - All-pairs lines in PhotoPreview: 8 holds = 28 lines, unreadable.
  - Client-side distance maths: no JS test runner; keep one tested implementation in Python.

  - **Test command:** `cd backend && uv run python -m pytest` (Agents.MD corrected).
  - **Slice 1 contracts (2026-10-16):**
    - `select_holds` returns a flat list `[{id, class_name, x, y}]` in pick order, not grouped by class. This keeps ids, and pick order matches the PhotoPreview lines.
    - The scale is cached under its own `scale:{detection_id}` key, written in the same Redis transaction as `detections:{id}`. If either key is missing, `/analysis` returns 410.
    - `/analysis` passes the worker a `route` dict in grid units: `holds`, `distances_units` (sub-matrix in pick order), `wall_length_units` and `bolt_spacing_cm`. The worker converts these to cm in `build_route_data`.
    - The LLM gets `distances_cm` as `[{from, to, cm}]`, one entry per unordered pair of distinct ids.
  - **Slice 2 bolt detection (2026-10-16), `backend/bolts.py`:**
    - **Candidates:** SimpleBlobDetector on CLAHE grey at pyramid levels ×1, ×2 and ×4 (threshold step 20), de-duplicated. Each candidate must lie outside every HOLD/VOLUME polygon, its local contrast on raw grey, (ring median − core mean) / ring median, must be ≥ 0.3, and its diameter must be ≥ 5 px.
    - **Diameter** is measured at half depth: the area darker than midway between core and ring, converted to an equal-area circle. The blob detector's own size runs up to 1.7× too large under uneven lighting, which broke the size checks.
    - **Speckle and distant walls:** the 5 px floor removes paint speckle clumps. It also drops bolts on distant background walls, which aren't the wall being measured.
    - **Lattice support:** a candidate is kept only if it sits in an evenly spaced line of similar-sized blobs (size ratio ≤ 1.5) along ≥ 2 directions. Candidates that line up with accepted bolts are then re-admitted, along 2 directions or along 1 direction on the anchor's own grid step.
    - **Spacing filters:** a bolt is dropped if its nearest-neighbour distance is under 0.7× the local median, or under 5× the hole diameter. The diameter rule is a physical prior that assumes a grid of roughly 12 cm or wider.
    - **Why not plain SimpleBlobDetector:** paint speckle (IMG_7500) and wood grain (7502–7504) outnumber bolts by 10–20×. Lattice regularity is what separates them, and it doesn't depend on photo scale.
    - **Inputs:** runs on the same un-rotated pixels YOLO sees. Images larger than 4096 px are shrunk first.
    - **Output:** `detect_bolt_holes(image, detections) -> [{x, y, diameter}]`, with normalized x, y and diameter in full-res px.
    - **Scale:** `compute_scale(detections, image_size, bolts)`. No bolts gives `insufficient_bolts` (null distances and wall length), otherwise `bolt_count = len(bolts)`. Distances stay on the stub until slice 3.
    - **Dev tool:** `backend/eval_scale.py` is a dev-only overlay that writes to the system temp dir by default.
  - **Slice 3 lattice + distances (2026-10-16), `backend/scale.py`:**
    - **Per-bolt J (px per grid unit):** fitted from the neighbour vectors pooled over the bolt's 5 nearest bolts. Each pair of distinct short directions is tried as the two diagonals, and the fit is refined by least squares over the vectors within 0.25 nearest-neighbour lengths (px) of an integer lattice offset.
    - **Ambiguity:** locally, three wrong readings fit the neighbours about as well as the right one:
      - a sheared basis
      - the √2 "diagonal vs square side" reading, where centre bolts are hidden
      - a finer lattice that explains a false detection between bolts
    - **Candidates:**
      - Basis candidates are the shortest vector per direction plus the most frequent direction/length clusters.
      - Every fit and its √2 variants (J·E, J·E⁻¹) is scored on its own inliers. Variants with at least 65% of the best count are kept.
      - Candidates are ordered by nearest-neighbour-site occupancy (sparse, i.e. finer lattices, go last), then squareness.
      - Each bolt then takes the candidate whose metric best matches the median of its 12 nearest bolts, over 8 rounds.
    - **Off-lattice pass:** after a first fit, points that most of their 6 nearest fitted bolts place off-lattice are removed, and the fit is rerun without them.
    - **Outlier drop:** bolts whose metric deviates more than 35% from the local median are dropped.
    - **Metric:** M = AᵀA with A = J⁻¹, interpolated by inverse-square weights over the 6 nearest fitted bolts. M is invariant to the lattice's 8 symmetries, so no consistent labelling is needed to measure. It also doesn't care that IMG_7503's two panels have grids rotated 45° to each other.
    - **Distance:** the straight image segment between two hold centroids, integrating √(dpᵀ M dp) at 16 midpoints. This is the stub's replacement.
    - **Wall length:** top bolt to bottom bolt within a ±4 nearest-neighbour band around the median bolt x, integrated the same way, plus 0.5 units at each end.
    - **Status:** `insufficient_bolts` when no bolt gets a valid fit.
    - **Accuracy measure:** `eval_scale.py --accuracy`. Ground truth is `index_lattice` (BFS integer coordinates per connected patch).
      - The headline is "leave-own-J-out": fit on all bolts, then drop the held-out bolts' own J, which mirrors measuring between holds.
      - Strict 5-fold refit is reported alongside. It's harsher on sparse walls, because removing 20% of bolts also degrades their neighbours' fits.
      - Patches stand in for panels until slice 5.
  - **EXIF orientation:** `/detect` applies `ImageOps.exif_transpose` before YOLO and bolt detection, so every coordinate matches the photo as the app displays it.
  - **Slice 4 margin (2026-10-19), `backend/worker.py`:**
    - `DISTANCE_MARGIN_PCT = 6`: the pooled reach-range in-panel p95 (5.2%, each photo weighted equally) rounded up to a whole percent. Re-derive it with `eval_scale.py --accuracy` (the `SUMMARY` block) whenever the fit changes.
    - `CENTROID_ALLOWANCE_CM = 5`: the starting value from the original decision, for hold centres sitting off the wall surface and away from where a climber grips. Slice 6 re-calibrates it.
    - Hold-to-hold margin = `cm × 6% + 5 cm`. The wall length gets 6% only, because it is measured bolt to bolt.
    - Each `distances_cm` entry carries a precomputed `margin_cm`, so the LLM doesn't do the arithmetic.
    - **Pooled, not worst photo:** the worst photo (IMG_7502) is 12.6%. Using that would make every wall twice as lenient to cover one sparse wall. Per-photo and per-tier margins are slice 5's job.
    - **Reach range only:** pairs under 30 cm are dominated by the fixed 5 cm allowance, and pairs over 250 cm aren't single moves.
  - **Panel outlines for evaluation:** digitised automatically from the Paint-coloured lines (thin-line colour mask, blob-shaped holds of the same colour removed, enclosed regions filled), then checked against the photos. One region on IMG_7500, the red volume enclosed by the green and yellow lines, was dropped because it isn't a panel.
  - **√2 fix, boundary rule (slice 5a, approved 2026-10-19):** where holds hide every centre bolt across a region, the remaining corners form a plain square grid that locally reads as the normal lattice 1.41× (√2) coarser, so distances there come out ~30% short. The per-bolt neighbour vote only fixes small regions. After the vote, bolts are grouped by scale agreement; where two touching groups' metrics differ by a uniform factor of 2 (√2 in length) with the same shape, the **coarser** group is re-read on the finer (×2 metric) variant — the coarse reading is always the misread one, since a real panel next door at exactly √2 the scale would need a √2 depth jump. Repeated until stable. Size-independent; a photo with no centre bolts anywhere stays ambiguous (no group to compare against).
    - **Two guards, both needed on real data (2026-10-19):** (1) the misread group's bolts must continue the finer group's lattice (≥ 80% of its bolts within 3 grid units of the border land on it); a separate panel at a different depth drifts off within a few squares, even where it lines up by chance right at the seam. (2) The finer group must have ≥ 7 bolts: on IMG_7503 a single stray bolt fitted on a too-fine lattice otherwise re-read the whole 78-bolt yellow panel √2 wrong (hole size in that panel confirmed the original reading). Constants `SQRT2_*` in `scale.py`.
    - Checked on the references with within-photo hole size (holes are one physical size per photo, so hole px ÷ local grid px should agree across the photo): only 2 bolts are re-read (IMG_7503), and their implied hole size moves from 0.78 to 1.10 cm against a photo median of 1.03, i.e. towards agreement. Nothing is re-read on 7500/7502/7504.
    - Rejected: hole-size prior (IMG_7500's hole/spacing ratio is 1.4× the other photos', the same size as the gap being detected); a wider vote (only moves the size limit, slower).
  - **Slice 5b panels + homography per panel (2026-10-20), `backend/scale.py`:**
    - **Contract:** `Lattice` gains `panel` (N,) int (-1 = in no panel) and `grid` (N, 2), the bolt's lattice site in its panel's frame, both filled by `fit_lattice` via `segment_panels`. `Lattice.take(mask)` subsets every per-bolt field; a subset made any other way must subset `panel` and `grid` too, or measuring raises `ValueError`. A `Lattice` built without them (None) measures on the field only, as before. `panel_homographies(lattice)` fits each panel's homography (grid units → px) from that lattice's own bolts, so a subset measures only from the bolts it keeps (leave-own-J-out stays honest). No change to the `/detect` response.
    - **Segmentation, competing homographies:** a local homography is fitted to each bolt's 12 nearest bolts (seeds). Each bolt joins the panel whose lattice it and its 6 nearest bolts sit closest to (distance to the nearest site, in nearest-neighbour spacings), if its own distance is ≤ 0.15; every panel is refitted, and panels one homography fits are merged, 8 rounds. Then each panel is split into connected pieces (steps ≤ 2.6 spacings), pieces under 8 bolts are dropped, and the pieces are merged again, now also searching lattice offsets (two best-matching lattice symmetries, offsets within 1.6 units) across gaps with no bolts.
    - **Guards, all needed on the reference photos:** (1) a homography whose scale disagrees with its bolts' own metrics (`MAX_METRIC_DEVIATION`) can't win them, and is dropped if < 80% agree. Without this, a degenerate or too-fine homography puts every bolt near *some* site and swallowed whole photos (p95 > 1000%). (2) No two bolts on one site. (3) A merge must keep each side's bolts within 0.12 spacings (90%) and its RMS within 1.5× the separate fits' (floor 0.03). Without the RMS rule IMG_7502's 34° panel merged with doubled residuals and in-panel p95 went from 2.1% to 4.7%. (4) Only parts within 6 spacings of each other merge: across a long bolt-free gap a homography bends just enough to absorb a grid offset, so two coplanar patches drilled out of line (the Tester's `test_index_lattice_separates_distant_patches`, 30 units apart, offset 0.3) merged into one frame. The cost: IMG_7502's 34° panel stays two panels, top and bottom.
    - **Why not region growing** (tried first): grown from one seed, a panel creeps over folds, because about 1 random point in 5 sits within tolerance of some site of an extrapolated lattice, and each refit bends the homography further. On IMG_7500 one region swallowed 4 panels.
    - **Measuring:** a point is measured on the panel most of its in-panel nearest bolts (of 6) belong to, the nearest breaking ties, with the metric of that panel's homography. Bolts in no panel don't vote: they failed every panel's checks, usually because their own fit pooled neighbours across a seam, so the field near them is the least reliable. The field is used only when none of the 6 nearest bolts is in a panel, or when the homography there is behind the camera or strays > 50% from the field (extrapolated too far). Distances still integrate 16 samples along the image segment, so a cross-seam distance runs through the seam, each part on its own panel's metric.
    - **Ground truth (`index_lattice`):** panel sites, not the step-by-step walk, where there are panels (see Reference data). Two panels share a frame when ≥ 80% (and ≥ 3) of one side's bolts within 1.6 spacings of the other land on a single site of its extended lattice under one symmetry and offset, tried in both directions. That frame is the unfolded wall, so a cross-seam true distance is along the surface.
    - **Time:** `segment_panels` takes 0.1–0.4 s on the reference photos (first version 0.8–2.3 s; the offset search was narrowed). Whole `compute_scale` goes from 1.8–3.3 s to 2.2–3.7 s (+0.3–0.45 s); slice 7 has to absorb this.
    - **Wall length** changes with the panels too (it integrates the same metric): IMG_7502 22.8 → 21.1 units, the others within 1%. There is no wall-length ground truth; on 7502 the old value came from interpolating straight across the 34° panel's bolt-free middle.
    - **Alternatives considered:** keep the interpolated field (no homographies): simpler, and nearly as good once the ground truth is fixed (3.9% vs 1.9% on IMG_7502, equal elsewhere), but it smears scale across folds and has nothing to extrapolate with across bolt-free gaps. Unfolded straight-line cross-seam distances (map both holds into one shared frame): exact where grids share a frame, but most seams here don't (7503, 7504), so the along-the-image-line integration is used everywhere.
  - **HEIC references:** converted to JPEG (`IMG_7502–7504.jpeg`, EXIF orientation applied, quality 95). No `pi_heif` dependency. The original `.heic` files are kept.

## Open questions
- `test_worker.py::test_payload_groups_holds_as_xy_objects_in_user_content` pins the old payload shape and will break in slice 1. The Tester rewrites it from this spec.
- ~~Confirm the phone upload isn't compressed below the resolution needed to see bolt holes.~~ Resolved 2026-10-19: `CustomCamera.tsx` pins the largest available `pictureSize`, and `takePictureAsync` uses full quality. The "Use Test Photo" image is a 640×640 dataset export where the holes are a few px and low-contrast: 22 of 86 candidates pass the contrast check and none form lattice lines, so `insufficient_bolts` is the correct result there.

## Slice 5c: confidence tiers (2026-11-04)
- **Tier A / C, per distance (`scale.segment_support`, `TIER_A_MAX_SUPPORT = 1.5`).** A distance is **A** when every one of its 16 sample points is within 1.5 nearest-bolt spacings (about 1 grid unit) of a fitted bolt, i.e. it is measured on bolt evidence all along; **C** otherwise, because part of its scale is borrowed from further away (holds or volumes hide the bolts). `scale.tiers` is N rows of N characters (`"AACA"`), not an N×N list, to keep `/detect` small. `/analysis` passes the picked sub-matrix to the worker as `route["tiers"]` (`scale.select_tiers`); a missing `tiers` (a scale cached before this change) is treated as A.
- **Margins (`worker.DISTANCE_MARGIN_PCT_BY_TIER`): A 6%, C 14%**, plus the 5 cm centroid allowance on both; the wall length keeps 6%. Each `distances_cm` entry gains `tier`, and `accuracy` gains `margin_pct_by_tier`. The prompt explains the tiers.
- **How C's 14% was derived:** random discs of 1.5–6 spacings were cut out of each reference photo's fitted bolts (40 per photo: IMG_7500, 7502, 7503, 7504, 7552). The held-out bolt pairs inside each disc were measured from the remaining bolts and compared with the panel-site ground truth (reach range 1.5–12.5 u). p95 by photo: 3% (7500), 30% (7502), 9% (7503), 10% (7504), 2% (7552); pooled, equal weight per photo, **13.4%**, rounded up to 14%. Pairs with support under 1.5 spacings are rare in that test (n=100, p95 10.8%, 7502 skewing it), so tier A's 6% rests on the slice 5b held-out numbers (pooled 2.2%) instead. The script (`gaps.py`) is in the session scratchpad, not the repo.
- **Tier B (hole ellipse) is not built, and I recommend dropping it.** On IMG_7501 a circle detector finds about 10 holes outside the holds, but their apparent diameters span 21–39 px (nearly 2×), because the wall mixes open holes, flush screws and washers. Hole size is not a ruler, so a scale from it would be ±30% or worse, with no tape measurement on that photo to check it. Partial-lattice fitting from 3–5 holes per panel is ambiguous (a short vector could be 0.7, 1 or 1.4 units). IMG_7501 therefore stays `insufficient_bolts` (no distances, the app's existing hint). **Needs the human's decision**, since it changes the approved 5c done-when ("IMG_7501 gives a scale for every panel").
- **Decision (human, 2026-11-09): tier B is dropped.** IMG_7501 stays `insufficient_bolts`. Revisit only if a wall with tape measurements and few visible bolts turns up.
- **Tier C as "borrowed from a neighbouring panel" is the existing field fallback in `metric_at`** (nearest bolts, whichever panel), now labelled and given its own margin, rather than a separate mechanism.

## Accuracy results (epic_wall, 2026-11-09)
`cd backend && uv run python eval_scale.py ../mobile/ML-Rock-Climbing-App/assets/known_measurements/reference/epic_wall.jpg --accuracy` (and `--tape 26`). 295 bolts found, 290 fitted, 4 patches, wall length 18.96 units (about 4.9 m at 26 cm).

- **Bolt grid:** in-panel reach-range p95 **1.8%** (n=592); cross-seam p95 **0.9%** (n=1652); all held-out pairs 1.3%. As good as the earlier photos.
- **Panel segmentation:** 3 panels segmented against the 10 drawn, purity 45% (bar from 5b: 90%), coverage 97%. The plywood grid runs straight across the seams, so panels at 25° and 31° read as one surface. Distances are unaffected here (field-only gives the same 1.9%). Accepted as a known limit; no fix planned.
- **Tape check at 26 cm/unit (measured with an iPhone measuring app, not a tape, so treat as ±10%).** Superseded: the spacing is 25 cm (2026-11-13); see "Slice 6" for the same pairs at 25 cm.

| Item | Tape | App | Error |
|---|---|---|---|
| 1 yellow–yellow (bolt) | 38 cm | 35.5 | −7% |
| 3 black–black (hand) | 66 | 61.6 | −7% |
| 5 purple crimp–pink (bolt) | 94 | 98.6 | +5% |
| 4 purple–black (bolt) | 141 | 155.9 | +11% |
| horizontal line (top edge) | 302 | 302.4 | 0% |
| 2 big yellow–pink (bolt) | 72 | 93.8 | +30% |
| 6 purple jug–crimp (hand) | 47 | 72.3 | +54% |
| vertical line | 322 | 473.0 | +47% |

- **Outliers judged measurement error (human, 2026-11-09):** pair 2 (both bolts sit under the labels, 760 px apart, which is about 100 cm at the photo's 7.6 px/cm), pair 6 (hand to hand against hold centres) and the vertical line (3,145 px tall, so about 410 cm or more at the same scale).
- Pairs 1, 3 and 5 sit inside the 6% + 5 cm margin; pair 4 (+11%) is about 1.4 cm outside it (error 14.9 cm against a margin of 141 × 6% + 5 = 13.5 cm; inside the 14% tier C margin if that pair is tier C).
- Endpoints are the centres of the green number labels, snapped to the nearest detected hold, so the pairs are approximate (±3 cm).

## Slice 5d: panel angle (planned 2026-11-09, awaiting approval)

**Why:** today no angle reaches the LLM (worker.py notes it as a later step). A 30° overhang and a 10° wall give different move difficulty for the same hold distances. The angle only affects distances indirectly now, through the compressed bolt grid.

**What to send (recommended):** a `wall_angle_deg` on each selected hold (degrees from vertical, positive = overhanging, 0 = vertical, negative = slab), plus a `wall_angle_margin_deg`. Per hold, not per panel: the app often cannot tell panels apart (epic_wall: 3 found of 10 drawn), but every hold has a local bolt grid. The prompt tells the LLM it is an estimate and to use the margin, and that the angle of a move is the angles of its two holds.

**How to estimate (to be proven in step 1):** the bolt grid is a known square, so its local shape in the photo gives the tilt of the wall relative to the camera. Turning that into an angle from vertical needs two more things:
1. **Camera tilt.** The photo alone cannot say how the phone was pitched. Options: assume it was held roughly level (error = pitch, perhaps 10–20°); or have the app send the phone's tilt at capture (a new `expo-sensors` dependency, which needs approval); or use a vertical reference in the photo.
2. **Overhang or slab.** One photo cannot tell a wall leaning towards the camera from one leaning away. Proposed prior: overhang, with the sign set by the phone's tilt if we get it.

**Alternatives:**
- User types each panel's angle: accurate, but too much friction, and the app cannot tell the user where panels are.
- One angle for the whole wall in settings: easy, but wrong on walls like epic_wall (14–31°) and IMG_7500 (6–23°).
- Per panel instead of per hold: needs segmentation to work, which it does not on smooth seams (see epic_wall).

**Step 1: feasibility (no payload change).** Estimate the angle at the centre of every outlined panel on IMG_7500, 7502, 7503, 7504 and epic_wall (and the whole-wall range 5–10° on 7552), compare with measurements.md. Report the error with the camera-level assumption and with the true camera tilt (back-solved) to show how much the tilt matters. Proposed go/no-go (human to agree): median error ≤ 5° and 90% of panels within 10°. If it fails, step 2 is replaced by the app sending phone tilt (needs a dependency decision) or by dropping the slice.

**Step 2: plumbing.** `/detect` returns per-hold angle in `scale`; `/analysis` passes the picked holds' angles; `worker.build_route_data` adds `wall_angle_deg` and a margin to each hold; the prompt explains them; tests per the Tester's spec-only approach.

**Decisions and research (2026-11-09):**
- **Show the angle in PhotoPreview too** (human), alongside what goes to the LLM.
- **expo-sensors research** (the app is on Expo SDK ~58, React Native 0.88):
  - `expo-sensors` ships with the SDK (`DeviceMotion`, `Accelerometer`) and works on Android and iOS and in Expo Go. `DeviceMotion` gives the gravity direction directly, which is what we need for camera pitch.
  - **It does not raise the phone floor.** The OS minimum comes from Expo itself: SDK 57 lists Android 7+ and iOS 16.4+ (SDK 58's row was not found, check it before the install). Android 7 covers 2016-era phones that were updated. iPhones from 2017 (iPhone 8) work; the 2016 iPhone 7 stops at iOS 15, but that is Expo's limit and is already the case today.
  - **Speed and size:** one gravity reading at capture time. No network, no extra upload, negligible latency. If the sensor is missing or errors, fall back to the photo-only estimate with a wider margin (`Accelerometer.isAvailableAsync()`).
  - **Accuracy:** a 2020 study of phones against a reference device found mean tilt errors of up to about 2° (pitch) and 6.6° (roll), varying by model. Camera pitch is what we need, so about 2° is expected. This is a published study, not a test on our phones.
  - **Gotchas:** iOS may need a motion-usage description string (config plugin `motionPermission`), which means a new dev build. Photos from "Use Test Photo" or the gallery carry no tilt, so they use the fallback. Read the sensor at the moment of the shot, with the phone held still.
- **Go/no-go for adding expo-sensors (proposed): GO.** It adds no OS floor, is built into the SDK, costs nothing noticeable in speed, has a fallback, and the sensor error (about 2°) is well inside the 5° bar. **It needs the human's OK before it is installed** (project rule: no new dependencies without asking).
- **Go/no-go for the angle estimate (step 1, unchanged):** median error ≤ 5° and 90% of panels within 10° against measurements.md, scored with the true camera tilt back-solved from each photo. A second check with real sensor readings needs a few new photos taken through the app (the reference photos carry no tilt), and a dev build.
- **No tape measurements are needed for 5d.** Its ground truth is the panel angles already in measurements.md (about 25 panels over six walls). Tape-measured hold pairs matter for slice 6 only.

**Open questions for the human:**
1. OK to install `expo-sensors` (`npx expo install expo-sensors`) when step 2 starts?
2. A few photos taken in the app with the tilt logged, on walls whose angle you know, are needed to validate the sensor path. Can you take 3–5?

## Slice 5d results and contracts (2026-11-09)

**Status:** built (backend `angle.py` + plumbing, mobile capture and display). Sensor path not yet checked on a real phone against a known-angle wall (the human is doing this).

### Step 1: feasibility (`backend/eval_angle.py`)
`uv run python eval_angle.py <photos...> [--pitch N]`. For each outlined panel, the median of the per-bolt estimates against the angle in measurements.md. Estimates use the camera tilt shown ("back-solved" = the pitch that fits that photo best, i.e. what a perfect sensor would give; "assumed 12" = the no-sensor fallback).

| Photo | Panels measured → estimated, back-solved pitch | Assumed 12° pitch |
|---|---|---|
| IMG_7500 (best pitch 11°) | 23→24, 17→23, 14→13, 6→2 | 23→25, 17→24, 14→14, 6→3 |
| IMG_7502 (best −9°) | 34→10, 9→10 | 34→31, 9→31 |
| IMG_7503 (best 11°) | 14→14, −26→26 | 14→15, −26→27 |
| IMG_7504 (best 13°) | 23→22, 13→13 | 23→21, 13→12 |
| epic_wall (best 14°) | 25→24, 25→24, 29→26, 31→28, 30→27, 29→29, **14→27**, 14→14, 14→14 | 25→22, 25→22, 29→24, 31→26, 30→25, 29→27, **14→25**, 14→12, 14→12 |
| IMG_7552 (whole wall, no outlines) | top 10 → 9.1, bottom 5 → 9.0 (assumed 12°) | |

- **Result against the proposed bar (median ≤ 5°, 90% of panels within 10°):** median error **1°** (19 panels, back-solved pitch), **3°** at the assumed 12° pitch. Within 10°: **16 of 19 (84%)**, so the 90% bar is narrowly missed. The three misses are explained:
  1. **IMG_7503's −26° slab** reads +26°: one photo cannot tell a slab from an overhang (mirror solution), and the estimator assumes overhang. A known limit, stated in the prompt.
  2. **IMG_7502's 34° panel** (24° off with the true tilt, but 3° off at 12°): sparse bolts and a back-solved pitch pulled by the 9° panel; the 9° panel is merged into the big one by the segmenter and reads 31°.
  3. **epic_wall panel P14 (14°) reads 25–27°:** a smooth seam, so the majority of bolts nearby belong to the steeper panels beside it.
- **Camera tilt matters a lot:** with a level camera (pitch 0) the median error is 11–15°. Every photo's best-fit pitch was 11–14° (people point the phone up at a wall), so the no-sensor fallback assumes 12° (`angle.DEFAULT_PITCH_DEG`).
- **Method (angle.py):** the local grid metric at each bolt (from `scale.metric_at`) is matched to a flat plane seen through a pinhole camera (focal length from EXIF 35 mm-equivalent, default 26 mm, principal point at the centre). That gives two mirror-image wall normals per bolt. The true normal is shared by all bolts on a flat panel while the mirror one moves with position, so the normal that most of the 50 nearest bolts agree on (within 5°) wins; ties go to the overhanging one. Angle = `asin(normal · down)`, where down is gravity in the camera frame. Synthetic check: exact with no noise, under 0.5° with 2% metric noise.
- **Margins set from this:** `MARGIN_SENSOR_DEG = 8` (most panels within ~7° with a true tilt; the three misses above are not covered), `MARGIN_ASSUMED_DEG = 15` (adds the spread in how people hold a phone, not measured on other people).

### Contracts (for the Tester; written from the spec, not the code)
- **`POST /detect`** gains an optional form field `gravity`: the phone accelerometer reading `[x, y, z]` (JSON list, or `x,y,z`) in the device frame: x right, y up the screen, z out of the screen, back camera along −z. Phone held upright (portrait). A missing, empty or malformed value is ignored (no error) and the assumed tilt is used. A reading whose y axis is more than 60° from vertical (|y|/|g| < 0.5) is not used. Android reports the reaction to gravity (y ≈ +1 upright) and iOS native reports gravity (y ≈ −1); both must give the same angles. The photo's EXIF 35 mm-equivalent focal length is used when present, else 26 mm.
- **`scale` gains** `angles_deg` (one number or null per detection, same order as `detections`, 1 decimal, degrees from vertical, positive = overhanging), `angle_source` (`"sensor"` or `"assumed"`) and `angle_margin_deg` (8 for sensor, 15 for assumed). With `status: "insufficient_bolts"` all three are null. A failure inside the angle code never fails `/detect`: the three fields come back null and distances are unaffected.
- **`select_angles(scale, detections, hold_ids)`** returns the angles for `hold_ids` in that order, None when the scale has none.
- **`/analysis`** passes `angles_deg` (picked holds, pick order), `angle_source`, `angle_margin_deg` in `route`.
- **Worker payload:** each hold gains `wall_angle_deg` when it has an angle (the key is absent when it has none); a top-level `wall_angle` block `{margin_deg, source, guidance}` is present only when at least one picked hold has an angle. A route without angle fields (an older cached scale) produces exactly the pre-5d payload. The system prompt explains wall angle (positive = overhang, margin, estimate, slab caveat).
- **Pure maths (`angle.py`):** `gravity_from_pitch(deg)` (unit down vector in the camera frame, camera looking `deg` above horizontal); `gravity_from_sensor(reading)` → `(down, pitch_deg)` or None; `focal_px(size, focal_35mm)`; `plane_normals(metric, point, size, f)` → the two mirror unit normals facing the camera; `wall_angle_deg(normals, down)`. A synthetic plane at a known angle, seen at a known camera tilt, must be recovered to < 1° from its exact metric, at any point in the frame.
- **Mobile:** `useGravityReading` (low-passed accelerometer, `expo-sensors` 58), passed from the camera with the photo to `/detect`; PhotoPreview shows `≈N°` above each selected hold. Not unit-tested (no JS test runner); `npx tsc --noEmit` is clean.

### Open
- The sensor path needs a check on a real phone against a wall of known angle (human, in progress). Android and iOS sign conventions are handled by assumption (`up.y < 0` means gravity convention); this is exactly what that check must confirm.
- Slabs read as overhangs (see above). Fixing it needs another cue; not planned.
- Margins are from five photos taken by one person on one phone: revisit after the real-phone check.

## Slice 6: centroid allowance (2026-11-13)

**Bolt spacing (human, 2026-11-13): 25 cm on epic_wall / epic_wall_2 and on IMG_7552** (measurements.md: "25 by 25"). This replaces the 26 cm read from epic_wall's "5 bolts across = 1.04 m" and the 20 cm used for IMG_7552's first tape check. With 25 cm, the epic_wall photos' bolt-to-bolt errors drop from about +6% to +1–2%, which shows the spacing was the cause of the earlier "+6%".

**Data:** `epic_wall_2` (real tape): pairs 3–6 (207, 161, 67, 167 cm) and the red vertical line (457 cm), drawn on `epic_wall_2.jpg` (runs down the right-hand column, x ≈ 0.65). Pairs 3–6 are bolt to bolt, at the bolt hole beside each red label. Pair 5 runs between two bare wall bolt holes, so it has no hold and tests the bolt-grid scale alone. The horizontal line (301 cm) is left out (human unsure of it); the epic_wall top edge already checks it (302 cm tape, 291 app at 25 cm, −4%).

**Deleted as measurement errors (human, 2026-11-13):** epic_wall_2 pairs 1 (94 cm) and 2 (67 cm), labelled in black on the same holds as epic_wall pairs 3 (66 cm) and 1 (38 cm). The bolt grid, counted by eye, puts them at about 64 and 40 cm, matching the app (63.6, 39.4) and the earlier measurements, so they were 30–40% off. Also deleted: epic_wall pairs 2 and 6 and the 322 cm vertical line, judged measurement errors on 2026-11-09. The raw notes (`epic_wall_2_measured.txt`) still list pairs 1 and 2.

**Tool:** `eval_scale.py --tape` now measures every pair twice: **points** (between the recorded points, so the error is the scale alone) and **holds** (between the nearest detected hold centroids, which is what the LLM gets), with the pair's tier, the worker's `margin_cm` and inside/outside. "Centroid shift" = holds − points, i.e. how far the centroid-to-centroid distance moves from the bolt-to-bolt one. `"snap": false` in pairs.json marks a pair with no holds.

**Results** (`uv run python eval_scale.py <photo> --tape 25`, all three photos at 25 cm):

| Photo · pair | Tape | Points (scale only) | Holds (app) | Tier · margin | Inside? | Centroid shift |
|---|---|---|---|---|---|---|
| epic_wall_2 · 3 | 207 | 211.4 (+2%) | 207.1 | A · 17.4 | yes | −4.3 |
| epic_wall_2 · 4 | 161 | 164.2 (+2%) | 163.7 | A · 14.8 | yes | −0.5 |
| epic_wall_2 · 5 (bare bolts) | 67 | 68.2 (+2%) | n/a | n/a | n/a | n/a |
| epic_wall_2 · 6 | 167 | 158.2 (−5%) | 168.5 | A · 15.1 | yes | **+10.3** (big black hold) |
| epic_wall_2 · red vertical line | 457 | 460.8 (+1%) | | wall margin 6% | yes | |
| epic_wall · 1 | 38 | 38.7 (+2%) | 34.2 | A · 7.1 | yes | −4.5 |
| epic_wall · 3 (hand) | 66 | 66.9 (+1%) | 68.1 | A · 9.1 | yes | +1.2 |
| epic_wall · 4 | 141 | 147.0 (+4%) | 149.9 | C · 26.0 | yes | +2.9 |
| epic_wall · 5 | 94 | 96.0 (+2%) | 94.9 | A · 10.7 | yes | −1.1 |
| IMG_7552 · top green | 20 | 18.6 (−7%) | 20.5 | A · 6.2 | yes | +1.9 |
| IMG_7552 · top white | 14 | 16.5 (+18%) | 16.6 | A · 6.0 | yes | +0.1 |
| IMG_7552 · bottom blue | 66 | 70.3 (+6%) | 69.7 | A · 9.2 | yes | −0.6 |
| IMG_7552 · bottom green | 50 | 56.6 (+13%) | 55.8 | A · 8.3 | yes | −0.8 |
| IMG_7552 · bottom white | 37 | 40.1 (+8%) | 44.3 | A · 7.7 | yes | +4.2 |

IMG_7552's four edges at 25 cm read −6% to +19%; their endpoints are corners read by eye from a drawn quadrilateral (±10%), so they are not used.

**Findings:**
1. **The allowance is confirmed at 5 cm; no change to `worker.py`.** All 12 trusted hold pairs on three walls fall inside their `margin_cm`. The centroid shift has a median of about 1.5 cm; 11 of the 12 are within 5 cm. The 12th is +10.3 cm, on the largest hold (a big black jug whose centroid is about 79 px from its bolt), and that pair still lands within 1.5 cm of the tape because its scale error (−5%) cancelled. The most any pair needs beyond the 6% part of the margin is 4.6 cm (IMG_7552 bottom white, whose endpoints are approximate), so 5 cm covers every trusted pair. 12 pairs is thin, so per the slice rule the allowance is not tightened.
2. **Tier A's 6% holds on real tape.** The bolt-to-bolt (points) errors on the epic_wall photos are +1% to +4%, with one at −5% (n = 9 including the vertical line). Every one is inside 6%. IMG_7552's pairs spread wider (−7% to +18%), but they are short (14–66 cm) with endpoints read by eye (about ±3 cm, i.e. ±20% on the 14 cm pair), so that spread is mostly the endpoints.
3. **Big holds can exceed the allowance on their own** (+10.3 cm). This is one case, so there is no change now. If more data shows the same, the fix would be an allowance scaled by hold size (for example, a fraction of the hold's radius) rather than a flat 5 cm.

**Open:** none for slice 6.

## Field test (2026-11-18, real phone)

**Data:** `backend/field_captures/` (15 captures, one gym, one iPhone on iOS 26.6.1, each through the app with the phone's tilt recorded). Ground truth is each folder's `truth.json`. The app's bolt spacing was 20 cm for the first 11 captures; every cm below is recomputed at the wall's real 25 cm (see the folder's README).

**Distances** (tape is bolt to bolt; the app measures hold centre to hold centre):

| Capture | Tape | App | Error | Tier · margin | Inside? |
|---|---|---|---|---|---|
| `174106` / `174142` / `174346` / `174447` (same pair, stepping back) | 76 | 79.8 / 78.4 / 75.8 / 78.2 | +5 / +3 / 0 / +3% | A · 9.5–9.8 | yes |
| `173610` across a seam | 155 | 154.7 | 0% | C · 26.7 | yes |
| `174933` slab, lower hold on a volume | 162 | 168.6 | +4% | C · 28.6 | yes |
| `172816` across a fold, 21° → 54° | 135 | 125.2 | −7% | C · 22.5 | yes |
| `171333` 1° wall | ~180 (tester: "about") | 195.4 | +9% | C · 32.4 | yes |
| `173933` **both holds on volumes** | ~80 (tester: "about") | 95.4 | **+19%** | C · 18.4 | yes, by 3 cm |

- All 9 independent pairs are inside their `margin_cm`. `174741` is left out: its tape value was taken from the app.
- Repeatability: one pair photographed at 16°, 21° and 26° phone tilt (`173154`, `173256`, `173344`) reads 69.6, 69.3, 69.6 cm.
- The margins are **not** changed: one gym, one phone, 9 pairs.

**Angles:** 29 hold angles against the tester's values (the hold on a volume left out): median error about **1.2°**, worst **5.2°**, all inside the 8° sensor margin. Includes a 54° overhang read as 54.5°, and phone tilt from −2° to 26°. The iOS sensor path is confirmed. Not yet tested: Android, a real slab (only −2° and 0° here, so the slab/overhang mix-up is still open), a second gym.

**Problems found:**
1. **Holds on volumes.** A hold on a volume stands 20–30 cm off the wall. Its distance is measured as if it were on the wall (`173933`, +19%), and its angle is the wall behind the volume, not the volume face (`174933`: face +6°, app −2.9°). → slices 6b and 8.
2. **Speed:** `/detect` took 6.6–15.3 s from the phone (about 11 s typical) against the 4–5 s target. → slice 7.
3. **Photo size:** the phone sends 1776×3840 (6.8 MP, cropped to the screen's shape) with no EXIF, so the focal length falls back to 26 mm on a cropped frame (probably about 12% short). Angles are still good. To check in slice 7 or 6b; the "Image resolution" section assumes 12 MP.
4. **`wall_length_cm` is the wall in the photo, not the wall:** the same wall gave 10.7 to 20.5 grid units as the tester stepped back. Acceptance criterion 1 needs a decision before End.

## Slice 6b: volumes (planned 2026-11-19, awaiting approval of details)

**Why:** field captures `173933` and `174933` (see "Field test"). The wall angle under a hold on a volume is not the angle the climber pulls on, and the human wants the volume face's angle too, derived a separate way.

**Step 1: spot holds on volumes.** YOLO already returns `VOLUME` polygons. A picked hold whose outline sits mostly inside a volume's outline is "on a volume". Ground truth: the field overlays (holds on volumes in `173933`, `174933`).

**Step 2: volume face angle, feasibility first (no payload change).** Candidate methods, to be compared and agreed with the human before any is built:
- bolt holes on the volume face, where it has its own, fitted with the existing lattice code;
- the volume's outline shape (its edges and corners as a known solid against the wall plane);
- volume angle typed in by the user (fallback; friction).

Proposed go/no-go like 5d: median error ≤ 5° on the volume faces with known angles. **Needs data:** a few captures of volumes with each face's angle measured (only `174933` has one today; `173933`'s 12°/20° needs confirming as volume face or wall).

**Step 3: plumbing.** Each hold gets `on_volume`, and `volume_angle_deg` with its own margin when the method passes; the prompt explains the difference from `wall_angle_deg`.

**Feasibility, option B first try (2026-11-19, scratch scripts, field capture `173933`):**
- **Depth model:** Depth Anything V2 Small (Apache-2.0), CPU, 0.4–0.65 s per volume cut-out, about 1 s for the whole photo.
- **Wall plane from the bolt grid works:** each panel's homography split into the wall's exact position (focal length known) gives +16.4° and +12.5°, against the app's 16.1–16.4° and 12.6°, with the grid's two axes equal within 0.2% and the wall about 3.1 m away. Unlike the current per-bolt method, this split has no mirror twin, so it may also help the slab/overhang mix-up (to check in 5e).
- **The model sees volumes clearly** (faces and ridges visible in its depth map), but **its scale cannot be set from the wall:** fitted on the wall around a volume, the volume comes out 2–3 cm deep (real: 20 cm or more); fitted on the whole photo, the wall fit is off by 7–12 cm and volumes land behind the wall. So "depth model + wall" gives no usable face angle here.
- **YOLO misses volumes:** `173933`'s left pyramid is not a VOLUME detection, and `174933` has none, so "hold on a volume" by polygon would miss both field-test volume holds. Any 6b method needs better volume detection (lower `VOLUME` confidence floor, retraining, or raised regions in a depth map).
- Next options: a surface-normal model (gives face direction directly, no scale needed; corrected by the known wall direction), or option A (second photo). Human to choose.

**Decision (human, 2026-11-19):** a volume face is described by its steepness **and** the direction it faces (left / right / up / down), not steepness alone, because a sideways face climbs like a sidepull. Both come from the same face direction the method computes, so this adds no infrastructure.

## Slice 8: volume fixes and more coaching information (planned 2026-11-19)

**Part 1, volume fixes.** Start with the distance between holds that stand off the wall (`173933`, +19%), then anything left open by 6b. Approach to be proposed after 6b, using what 6b learns about the volume's geometry.

**Part 2, more information for the LLM** (numbering from the 2026-11-19 list; item 2, hold size, is out of scope):
1. **Hold positions in cm on the wall** (height above the lowest bolts, sideways offset), from the panel homographies and the gravity reading, plus each move's up/across parts. Today the LLM gets photo fractions, and the photo is 2.16× taller than wide.
3. **On a volume** (from 6b) and the volume's size in cm.
4. **Angle change along a move**, e.g. "from 21° onto 54°" (`172816`).
5. **Climber height and ape index**, entered in the settings panel (new user input, approved by the human 2026-11-19).
6. **Hold colour**, from the photo's pixels inside each hold's outline: suggest the route's other holds when picking, and send nearby footholds of the route's colour.

Each item is its own step with a worker test; the order inside the slice is proposed when it starts.

**Note (human, 2026-11-19): plan a slice 9 with the human to cut down `/detect` times**, once slice 8 is done. The field test measured 6.6–15.3 s from the phone (see "Field test"), and 6b and 8 add work per photo. Slice 9 is planned together with the human, not drafted alone; how it splits from slice 7 (speed) is decided then.

**Decisions (human, 2026-11-19):** volume work is a new slice 6b (slice 6 is taken); slice 8 includes items 1, 3, 4, 5 and 6; order 5e → 6b → 8 → 7 → End. **architecture.md gets a new section 5 now** ("What the coaching AI is told", a checklist table), an exception to the 2026-11-09 rule that no doc other than this spec changes before End. The human fills in its not-yet-built rows; it is the plan for the rest of the branch, and each slice ticks its rows.
