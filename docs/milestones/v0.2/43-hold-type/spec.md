# Hold classification (#43)

Branch `feat/43-hold-type` · Milestone `v0.2` · GitHub issue #43

## Goal
Give every detected hold a type (jug, crimp, sloper, pinch and so on), show it to the user on the photo, and pass the picked holds' types to the coaching prompt.

Milestone criterion (issue #43): *"Each picked hold gets a type from a fixed list, and that type reaches the coaching prompt. Accuracy is measured against holds the human labelled on about 10 captures, with the target set at /start-issue. The coaching eval score doesn't drop."*

Added by the human (2026-11-28): **show the type of every hold in the app**, not only the picked ones, without the cost getting out of hand.

Two approaches are built and compared on the same labelled holds (human, 2026-11-28):
- **Plan 3, a vision-language model:** Claude classifies the crops of every hold, once per photo, in the background.
- **Plan 4b, our own classifier:** trained on public Roboflow hold-type datasets, then on our own labelled holds, and run on the server for free.

**Fallback if both fail:** train on a Roboflow dataset using Roboflow's own training (Roboflow Train), and run that model through their API or download its weights where the plan allows.

## Inputs
- The full-resolution photo (`/detect` already receives it) and its detections: polygon, bounding box, `class_name` (`HOLD` / `VOLUME`), confidence.
- `HOLD` and `VOLUME` detections are both classified, because YOLO mixes up macros and volumes. A `VOLUME` detection comes out as `volume` or `macro`, and a `HOLD` detection can also come out as `macro`.
- For the eval: the 15 field captures in `backend/field_captures/*/` (`photo.jpg` + `capture.json` with `detections`), plus the human's hold-type labels for about 10 of them.
- For Plan 4b: public Roboflow / Kaggle hold-type datasets with a clear licence (see Reference data).

## Outputs
- **Per hold:** `{id, type, type2, confidence, source}`
  - `type`: one of the fixed list, or `null` when unsure (the app shows "?").
  - `type2`: an optional second type (for example a sloping pinch), or `null`.
  - `confidence`: 0–1.
  - `source`: `"vlm"` or `"local"` (which classifier produced it).
- **Fixed list** (human, 2026-11-28; the definitions are in `docs/hold_types.md`): `jug`, `crimp`, `rail`, `sloper`, `pinch`, `pocket`, `macro`, `jib`, `volume`, `other`.
  - Foothold vs handhold depends on the route, not the hold, so it's left to #47. Orientation is #44, incut #45, size #46.
- **Cached in Redis** as `hold_types:{detection_id}`, with the same 1 h TTL as `detections:`.
- **App:** a new endpoint, `GET /hold-types/{detection_id}`, returns the types, or "pending" while the background job runs. The app polls it after `/detect` and shows each hold's type on the photo.
- **Coaching:** the worker adds each picked hold's `type` (and `type2` if set) to the route data and explains them in the prompt. If there are no types (pending, failed, unsure), coaching runs as before.

### Contracts (for the Tester)
To be filled at `/start-slice 1` once the shapes are agreed: the classifier function's signature, the Redis key and value, the endpoint's response, and the worker payload field.

## Acceptance criteria
1. **Every hold gets a type or "unsure".** Each `HOLD` and `VOLUME` detection on a photo gets a result within **5 s** (p90) of `/detect` returning (human, 2026-11-28).
2. **Types reach coaching.** The picked holds' types are in the worker payload and the prompt. `COACHING_OUTPUT_SCHEMA` and `api/getClimbAnalysis.tsx` stay in sync.
3. **Accuracy on the human labels** (`accuracy_checks/eval_hold_type.py`):
   - Report per-class precision and recall, the confusion matrix, macro-F1, and the "unsure" rate.
   - Each configuration is scored on the same labels: Haiku with contact sheets, Haiku with full crops, Sonnet with full crops, and the local classifier(s).
   - **Target: at least 95% of the types shown are correct, excluding "?"** (human, 2026-11-28). Coverage (the share of holds that get a type) is reported alongside it. **Coverage: at least 95% of holds get a type** (human, 2026-11-28).
4. **Cost:** the all-holds pass costs **≤ 0.3p** per photo on average, measured from `usage` (human, 2026-11-28; Haiku is estimated at about 0.2p).
5. **App:** each hold's type shows on the photo, and holds still pending or unsure show nothing or "?". `npx tsc --noEmit` is clean, and lint has no new problems. The wall-angle degree readout stays.
6. **Never breaks the normal flow:** if classification fails, times out or is turned off, `/detect`, `/analysis` and coaching work as before (with no types). `/detect`'s response time doesn't change, because classification runs in the background.
7. **The coaching eval score doesn't drop.** This needs #41. Until #41 exists, the human compares coaching with and without types on 3 captures.
8. The full test suite passes.

## Reference data
- **Eval:** `backend/field_captures/*/` (15 captures with full photos and detections). The human's labels will go in `backend/field_captures/<capture>/hold_types.json`. The format is set in slice 2.
- **Plan 4b training data** (licences to be confirmed in a browser; automated fetches of these pages were refused, 2026-11-28):
  - [Rock climbing, University of Maine](https://universe.roboflow.com/university-of-maine/rock-climbing): Crimp, Edges, Foothold, Jug, Pinch, Pocket, Sloper; MIT according to its image metadata.
  - [Climbing Replica Test](https://universe.roboflow.com/loboflow-go1lj/climbing-replica-test): about 3,100 images, crimp / jug / pinch / pocket / sloper; licence unknown.
  - [ClinbingHoldType](https://universe.roboflow.com/personal-9wu84/clinbingholdtype): 7 classes, including Foothold and Other; licence unknown.
  - [Kaggle hold classification](https://www.kaggle.com/datasets/diegospaziani/indoor-climbing-gym-hold-classification-dataset): Jug, Crimp, Pinch, Slope, Pocket, Volume, with some synthetic images; licence unknown.
  - These are **detection** datasets (boxes labelled with a type). Each box is cropped out to make a classification dataset. Universe *models* can't be downloaded, only run through Roboflow's API, so we train our own.

## Slices
| Slice | Scope | Done when |
|---|---|---|
| 1 | **Plan 3 end to end.** `wall_analysis/hold_type.py`: crop each `HOLD` from the full photo (padded, outline drawn), pack the crops into numbered contact sheets, and make one Claude Haiku call with a structured-output schema. It runs in the background after `/detect`, the result is cached in Redis, `GET /hold-types/{id}` serves it, and the worker passes the picked holds' types to the prompt. Unit tests with a mocked client | A real photo gets types for all its holds, and they appear in the coaching prompt. AC 2, 6 and 8 hold. Token count and cost per photo measured |
| 2 | **The eval set and the eval script.** A labelling helper writes numbered crop sheets per capture for the human to label, plus `accuracy_checks/eval_hold_type.py`. Plan 3 is scored: Haiku with sheets vs full crops, plus Sonnet | Labels exist for about 10 captures (2–3 labelled twice). Baseline numbers for AC 3 and 4. The target is agreed |
| 3 | **Plan 4b: train the local classifier.** A dataset script turns the Roboflow / Kaggle boxes into crops with our label map. A Colab notebook trains the candidates (see Decisions: classifier models). Each is scored by the slice-2 eval | Each candidate's AC 3 numbers on the same labels. Weights stored where the backend can load them (`models/`, gitignored like `best.pt`) |
| 4 | **The local classifier in the backend,** behind the same interface as Plan 3 (a setting chooses `vlm` / `local` / `local+vlm`). Fine-tune on our own labelled holds and on the corrected Plan 3 labels. Choose between them or combine them using the eval | One configuration chosen on AC 1, 3 and 4. Latency on CPU measured |
| 5 | **App:** poll `/hold-types`, and show each hold's type on the photo (a label or icon per hold, "?" when unsure) | AC 5 |
| 6 | **Coaching check and docs.** The coaching comparison (AC 7), then `architecture.md`, `decisions.md` and `testing.md` | AC 7. Issue done |

If slices 3–4 can't beat the target: **fallback** to Roboflow Train on a Roboflow dataset (see Goal). If Plan 3 already meets the target cheaply, slice 4 may be cut to a recorded decision.

## Decisions
- **Detect, then classify: don't retrain YOLO with hold types** (2026-11-24, parked plan): the multi-class YOLO got confused. YOLO keeps finding holds, and a second stage names them from close-up crops.
- **Start before #41** (human, 2026-11-28): accuracy is measured within this issue (slice 2) against the human's labels. The coaching-eval criterion (AC 7) waits for #41, with a manual check until then.
- **Classify every hold, not only the picked ones** (human, 2026-11-28): the app shows types for every hold. Cost is kept down by: classifying once per photo in the background, contact sheets, Haiku first, skipping tiny or low-confidence detections, caching by photo, and a daily spend cap.
- **Build both Plan 3 and Plan 4b and compare them on the same labels** (human, 2026-11-28). Fallback: Roboflow Train.
- **Confirmed by the human (2026-11-28):**
  - All holds, in the background. Haiku first; Sonnet only for the picked holds, if the eval shows it's needed.
  - Latency target: types within **5 s** of `/detect` returning (AC 1).
  - Cost target: **≤ 0.3p per photo** if possible (AC 4).
  - Accuracy target: **at least 95% of shown types correct, excluding "?"** (AC 3).
  - Dependencies approved: `roboflow` (dataset download), `torch.hub` / `timm` (DINOv2, ConvNeXt).
  - A **`macro`** type must exist: a very large hold that is still a hold, gripped directly. (The full list is below.)
- **Label list** (human, 2026-11-28): jug, crimp, rail, sloper, pinch, pocket, macro, jib, volume, other. Rail covers "edge" (a long edge, like a roof's). Crimp stays separate (small, hand-sized).
- **`docs/hold_types.md` is the hold identification table** (human, 2026-11-28). Any change to hold classification updates it in the same change (rule added to `CLAUDE.md`).
- **Classify volumes too, and separate macro from volume** (human, 2026-11-28). Macro face angles and what the coaching AI is told about macros are **#57**, not #43.
- **Accuracy is measured on the shown types only:** ≥ 95% correct, excluding "?" (human, 2026-11-28).
- **Coverage: at least 95% of holds get a type**, so no more than 5% are "?" (human, 2026-11-28).
- **Double labelling** (human, 2026-11-28): the human labels about 10 captures, then 2–3 of them again a few days later without looking. Their agreement with themselves is the most the eval can show. Below 95%, tighten `docs/hold_types.md`, merge types that keep getting confused, or revisit the target.
- **Classifier models for Plan 4b (proposed):**
  - **YOLO-cls** (Ultralytics, already a dependency; ImageNet-pretrained): the simplest to train on Colab and fast on CPU.
  - **DINOv2 ViT-S/14, frozen, plus a linear classifier:** the strongest choice on small datasets and the most robust to a change of gym. Loading it needs `torch.hub` (no new pip package; it downloads code from GitHub) or `timm` (a new dependency): to ask.
  - **Possibly later, a fine-tuned ConvNeXt-Tiny or EfficientNetV2 via `timm`,** if there's enough labelled data (new dependency: to ask).
  - Not recommended: CLIP / SigLIP zero-shot (weak on fine-grained classes), and multi-class YOLO detection (see above).
