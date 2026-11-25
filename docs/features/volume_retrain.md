# Volume retrain (side task, parked until the human has gathered the data; slice 14 needs it)

Handover doc between sessions. Read this first, then update **Status** and the **Log** at the end of every session.

## Why

The field test (2026-11-18, see `wall_size_hold_distance.md`) showed YOLO misses volumes:
- In capture `173933`, the left pyramid is not detected even at 0.01 confidence.
- In capture `174933`, the volume only appears at 0.081 confidence, below our 0.25 floor.

Slice 11 (volume face angles) is no use if the volume isn't found. So we fine-tune the model on more volume photos first, then resume 11.

This is deliberately **not** a slice in `wall_size_hold_distance.md`. Once the new model is in, slice 14 (volumes, finish) can spot holds on volumes. Slice order lives in `handover.md`.

**Correction (2026-11-20):** only spotting that a hold is on a volume (now part of slice 14, which needs a VOLUME polygon) waits for this retrain. Step 2, the volume face angle, takes a volume mask as *input*, so it is being developed and tested against synthetic and hand-drawn masks in parallel with the relabelling. See slice 11 in `handover.md`. The retrain is no longer on 11's critical path.

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
- Backend confidence floors: HOLD 0.15, VOLUME 0.25 (`backend/detection.py`, `CONFIDENCE_FLOORS`).

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
| Field replay (`backend/eval_field.py`, re-created in slice 12) | Distances and angles no worse |

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

## Status

**2026-11-19:**
- Decision: "medium" cleanup. The legacy set's old labels are dropped; the current model makes fresh draft labels, and the human corrects them in Roboflow.
- Step 2 done: `01_legacy_images/` has 790 images with draft labels, ready for the human to upload and correct (step 3).
- Steps 4 and 5 done (final; the human has no more photos for now): 55 photos in `02_new_volume_photos/` with draft labels (2837 holds, 353 volumes).
  - 26 are the human's own gym photos, converted from HEIC; 29 are web images.
  - Originals, set-aside duplicates and one full-size original (shrunk to 4032 px for use) are in `originals/`.
- Both sets (790 + 55 = 845 images, 27,576 outlines) passed a format check, ready for Roboflow.
- Next: the human corrects both sets in Roboflow (steps 3 and 6).

## Open questions

- None right now.

## Log

- **2026-11-20:**
  - Slice 11 (volume face angle) restarted on a new approach: the wall plane from the bolt grid plus the volume's base back-projected onto it. Built as `backend/volume.py`, exact on synthetic geometry. Details are in `handover.md`, slice 11.
  - 11 step 2 no longer waits for this retrain (see the correction under "Why"). Relabelling and the geometry work run in parallel.
  - Every leftover of the abandoned depth-model attempt was deleted: the temp `scratchpad/vol/` and `depthenv/` dirs, a downloaded PDF, and 95 MB of Depth-Anything-V2-Small weights in `~/.cache/huggingface`. **The retrain scratch was left untouched** - `scratchpad/ds2000/`, `emb_legacy.npz`, `emb_test.npz`, `orb_pairs.pkl`, `S_centered.npy`, `old_drafts/`, `pl_fix/`, `pl_test/`, `heic_test/` and the sheet JPEGs are all still there.
  - Next for the human on this doc: unchanged, steps 3 and 6 (correct both label sets in Roboflow).

- **2026-11-19:**
  - Plan agreed with the human.
  - Confirmed `dataset_3_hopefully` is not the training set.
  - The B2 surface-normal test (slice 11) is paused until the new model is in. Running it also needs the human's OK to download and run model code from GitHub (Metric3D v2 or DSINE).
  - Found the legacy set (`2000_corrections` v1) and audited its labels.
  - Human chose medium cleanup: fresh draft labels from the model, corrected by the human.
  - Reorganised `C:\ML Climbing Project\Datasets` into `archive/` and `current/` with dated names. Nothing was deleted.
  - Created `current/2026-11-19_volume_retrain/` and `tools/prelabel.py`. VOLUME is drafted at 0.10 confidence, below the app's 0.25, so misses show up.
  - Started draft labelling of the legacy images.
  - Found the legacy images were already augmented before upload: the 1949 contain only 1104 different photos.
    - Model fingerprints (`embed.py`) can't tell copies apart on their own; unrelated wall photos look as alike as copies.
    - So copies were found by matching distinctive points (ORB) between each image and its 30 nearest fingerprints, at 60 or more matching points (`find_copies.py`, giving `copies.csv`).
  - Human chose to trim to 600–800. Kept 790 (`select_legacy.py`, `selection.csv`): 490 with a volume, 223 wall photos and 77 catalogue shots. The other 1159 were moved to `00_legacy_excluded/`.
  - Bug found and fixed in `prelabel.py`: ultralytics 8.4 `masks.xy` joins a mask's separate pieces with straight lines across the image, and some outlines came out as rectangles. The script now extracts the outline itself (largest piece only) and drops box-shaped and tiny outlines. All 790 were re-drafted.
  - New volume photos: 43 supplied.
    - The 26 iPhone HEIC photos were converted to JPG with Windows' built-in decoder (PowerShell, `System.Windows.Media.Imaging`), so no `pillow-heif` install was needed. WebP and AVIF were converted with Pillow.
    - One duplicate web image was dropped, leaving 42, which were draft-labelled.
    - Drafts show the volume problem clearly: many volumes come out as HOLD (large triangles and slabs), so correcting the class is the main job in Roboflow.
  - Scratch harness for B2 (fake wall plus scorer) is at `C:\Users\samst\AppData\Local\Temp\claude\9b2860e22918f817\42e0adec-2063-4034-bdf7-d1fad434972d\scratchpad\vol\`. It is temporary and may be cleared on reboot. If it's gone, it can be rewritten from the description in `wall_size_hold_distance.md`, slice 11.
