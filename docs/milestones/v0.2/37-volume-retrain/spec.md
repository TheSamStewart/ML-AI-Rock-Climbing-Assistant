# Volume retrain (#37, branch `feat/37-volume-retrain`)

The plan, steps and pass criteria. Status and the log are in `handover.md`. Holds on volumes (#49) waits on this.

## Why

The field test (2026-11-18, see `wall_size_hold_distance.md`) showed YOLO misses volumes:
- In capture `173933`, the left pyramid is not detected even at 0.01 confidence.
- In capture `174933`, the volume only appears at 0.081 confidence, below our 0.25 floor.

Slice 11 (volume face angles) is no use if the volume isn't found. So we fine-tune the model on more volume photos first, then resume 11.

This is deliberately **not** a slice of the wall size / hold distance feature. Once the new model is in, holds on volumes (#49, was slice 14) can be spotted.

**Correction (2026-11-20):** only spotting that a hold is on a volume (now part of slice 14, which needs a VOLUME polygon) waits for this retrain. Step 2, the volume face angle, takes a volume mask as *input*, so it is being developed and tested against synthetic and hand-drawn masks in parallel with the relabelling. See slice 11 in `docs/features_deprecated/wall_size_hold_distance_handover.md`. The retrain is no longer on 11's critical path.

## Who does what

| Step | Who | Done |
|---|---|---|
| 1. Find and hand over the old training set. The original zip is lost; we use Roboflow `2000_corrections` v1 instead (see Known facts). | Human | ☑ (2026-11-19) |
| 2. Legacy images: drop the old labels; remove copies and trim to 790; have the current model make draft labels in `01_legacy_images/` | Agent | ☑ (2026-11-19) |
| 3. Correct the legacy draft labels in Roboflow and export | Human | ☐ |
| 4. Collect ~100 photos with volumes (plus a few walls without) into `02_new_volume_photos/images/` | Human | ☐ |
| 5. Draft-label the new photos (`tools/prelabel.py`) | Agent | ☐ |
| 6. Correct the new photos' labels in Roboflow and export | Human | ☐ |
| 7. Hold out a test set; merge both corrected exports into one zip with `data.yaml` | Agent | ☐ |
| 8. Write the Colab fine-tune notebook (starts from the current `best.pt`) | Agent | ☐ |
| 9. Train on Colab, return the new `best.pt` | Human | ☐ |
| 10. Evaluate old vs new model | Agent | ☐ |
| 11. If it passes, swap the model into the backend and resume slice 11 | Agent (human approves) | ☐ |

**Where the data lives:** `C:\ML Climbing Project\Datasets\current\2026-11-19_volume_retrain\`. Its `README.md` explains the folders and the Roboflow steps. Older datasets are in `Datasets\archive\`, named `YYYY-MM-DD_<name>` (see `Datasets\README.md`).

## Known facts (so they aren't re-derived)

**Current model**
- YOLO26m-seg, two classes, `0: HOLD`, `1: VOLUME`. Licence is AGPL-3.0.
- Trained on Google Colab GPU: imgsz 1024, batch 1, 100 epochs, about 600 s per epoch.
- Data path in the checkpoint: `/content/dataset_extracted/dataset_3_augmentations/data.yaml`. It was unzipped inside Colab, so the zip is on the human's Google Drive.
- Final mask metrics (both classes together): precision 0.83, recall 0.79. There is no per-class breakdown.
- Backend confidence floors: HOLD 0.15, VOLUME 0.25 (`backend/wall_analysis/detection.py`, `CONFIDENCE_FLOORS`).

**Local datasets** (`C:\ML Climbing Project\Datasets`). None of these is the training set.
- `dataset_3_hopefully`: 49 images, no `data.yaml`, 2181 HOLD and 231 VOLUME labels. It is too small to be the training set.
- The other folders use different class orders. For example, `['Hold', 'Marker', 'Volume']` puts Volume at 2, and `colab_format` has 7 classes. **Don't merge any of them without checking and remapping class ids.**

**Hardware**
- The local GPU (AMD RX 5500 XT) can't train PyTorch on Windows, and the CPU is too slow.
- So training runs on Colab, run by the human.

## Rules for the data

**Photos**
- The human took them, or has permission to use them.
- Variety: volume colours, shapes and sizes; dark-on-dark; slabs and overhangs; different gyms, distances and lighting.
- Add the 15 photos in `backend/field_captures/*/photo.jpg`.
- **Also photograph a slab wall** (a wall leaning back, less steep than vertical), with and without volumes (human, 2026-11-24). The same slab photos, with the wall angle and a few tape distances noted, are the test data for slice 12's slab vs overhang check.

**Labelling**
- **Label every hold and every volume** in each photo. An unlabelled hold teaches the model that holds are background.
- Roboflow export: YOLOv8 segmentation format, **no augmentation**, classes named `HOLD` and `VOLUME`.
- The agent remaps class ids to `0: HOLD, 1: VOLUME` when merging.

**Test set**
- Set aside 15–20 of the new volume photos before merging, plus the field-capture photos.
- These are never trained on, so the before/after comparison is honest.

**Merging**
- Keep the old dataset's train/val split.
- Add the new photos to train and val, roughly 85/15.
- Check that no image is in two splits.

## Pass criteria (step 8)

| Check | Pass if |
|---|---|
| Volume recall on the held-out test set | Clearly higher than the old model's |
| The two field misses (`173933` left pyramid, `174933`) | Found above the 0.25 floor |
| Hold detection | Not worse than the old model's on the old val split |
| Field replay (`backend/accuracy_checks/eval_field.py`, re-created in slice 12) | Distances and angles no worse |

Run the old and new models on exactly the same images.

**Old dataset: the zip `dataset_3_augmentations` is lost.** The best stand-in is Roboflow project `2000_corrections-hubd1`, version 1, exported 2026-11-19 to `C:\Users\samst\Downloads\2000_corrections.v1i.yolov8.zip`.

What's in it:
- 1949 images, all 640×640, no augmentation.
- Split: 1785 train, 140 valid, 24 test.
- Classes are `['Hold', 'Marker', 'Volume']`, so ids must be remapped. Hold 38183, Marker 2424, Volume 2348.
- Mostly product/catalogue photos of single holds and volumes, with fewer real wall photos.

Problems the agent found (the human also says many labels are bad):
- **1491 objects labelled twice with the same class** (overlap above 0.6). It looks like auto-labels and corrections were both kept. This can be fixed by script.
- **56 objects labelled as both Hold and Volume.** These need a human decision.
- Real wall photos have holds left unlabelled.
- Big holds and volumes are labelled inconsistently: some large volumes are marked Hold.
- 552 images have 3 labels or fewer (mostly single-product shots).

Another older export is `C:\Users\samst\Downloads\100_trainig_2.v1i.yolov8.zip` (Roboflow `100_trainig_2` v1, from 2026-06-12). It holds about 70 source photos, each squashed to 640×640 and augmented 10×, with 3 classes and 4271 Volume labels. It's lower quality; use it only if more volume data is needed.

Scratch extract and overlay sheets are at `C:\Users\samst\AppData\Local\Temp\claude\9b2860e22918f817\42e0adec-2063-4034-bdf7-d1fad434972d\scratchpad\ds2000\` (temporary).

