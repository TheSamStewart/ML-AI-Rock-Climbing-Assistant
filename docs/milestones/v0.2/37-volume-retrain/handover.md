# Volume retrain: handover (#37)

Status and log. The plan, steps and pass criteria are in `spec.md`. New log entries go at the top of the Log, newest first.

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
  - Slice 11 (volume face angle) restarted on a new approach: the wall plane from the bolt grid plus the volume's base back-projected onto it. Built as `backend/wall_analysis/volume.py`, exact on synthetic geometry. Details are in `docs/features_deprecated/wall_size_hold_distance_handover.md`, slice 11.
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
