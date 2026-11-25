# Field captures (wall angle / hold distance testing)

> The capture tool (button and `/dev/test-capture`) was removed on 2026-11-18 after the field test. These files are the finished dataset.

Written by the app's dev-only "Save image to pc for testing" button
(`POST /dev/test-capture`, `backend/field_capture.py`). One folder per photo,
named `<date>_<time>_<first 8 chars of detection_id>`.

## Files in each folder
- `photo.<ext>`: the photo exactly as the phone uploaded it (original bytes,
  EXIF intact, NOT rotated). Rotate with EXIF (`ImageOps.exif_transpose`)
  before using any coordinate below, as /detect does.
- `capture.json`: written once, on the first save.
  - `photo`: raw (stored) size, upright size (after EXIF rotation, the frame
    every coordinate uses), EXIF orientation, `focal_35mm` (what /detect used;
    null = 26 mm assumed), selected EXIF tags.
  - `sensor`: `gravity_sent` (low-passed accelerometer at the shutter, what
    /detect received), `gravity_raw` (single unsmoothed sample at the shutter,
    from the app), `accepted` (whether angle.gravity_from_sensor accepted it),
    `pitch_deg` (camera pitch it implies, positive = pointing up),
    `roll_deg` (phone roll in portrait, 0 = upright). Device frame: x right,
    y up the screen, z out of the screen, in G.
  - `client`: what the app sent: platform, OS version, device name, photo
    source (`camera` / `test_photo`), capture time, the photo's EXIF as
    expo-camera returned it, and /detect round-trip time.
  - `scale`: the exact `/detect` scale response for this photo (distances in
    grid units, tiers, `angles_deg` per detection, `angle_source`,
    `angle_margin_deg`, `wall_length_units`).
  - `detections`: the exact `/detect` detections (normalized coords, upright frame).
  - `bolts`: bolt holes re-detected at save time by `bolts.detect_bolt_holes`
    on the same upright pixels and detections (deterministic, so the same set
    /detect used). Normalized x, y; diameter in full-res px.
- `saves.json`: one entry per button press: selected hold ids (pick order),
  bolt spacing set in the app, the tester's note, and for each consecutive
  pair (`legs`) the units, cm, tier and margin_cm exactly as the LLM would get
  them, plus each picked hold's angle.
- `overlay_<n>.jpg`: the photo (upright) with every hold's id, the bolts
  (cyan dots), each hold's estimated angle, and save n's picked holds and
  legs (yellow, with cm). Use it to find hold ids when filling truth.json.
- `truth.json`: ground truth, filled in BY HAND after the session (template
  written on the first save; never overwritten).

## Root files
- `index.csv`: one row per save across all folders (quick overview).

## Conventions
- Angles: degrees from vertical, positive = overhanging, negative = slab.
- Distances: cm along the wall surface. Grid units x bolt_spacing_cm = cm.
- An empty `notes` / null truth value means "not recorded", not zero.

## Known issue: bolt spacing wrong in early captures (2026-11-18)
The app's bolt spacing was left at the default 20 cm for every capture up to and including
`2026-11-18_174142_ac2132d6` (11 folders, 17:13-17:41). The wall's real spacing is 25 cm, set
correctly from the next capture on; later captures are accurate. In the affected folders every cm
value in `saves.json` (and `index.csv`'s `leg_cm` / `wall_length_cm`) is 1.25x too short:
recompute as `units x 25`. Grid units, tiers, angles and bolts are not affected. Each affected
folder has a `NOTE_bolt_spacing.md` (corrected legs) and the note in `truth.json`.

Affected folders (app at 20 cm; corrected cm = units x 25):

| Folder | Holds picked | Legs: app cm → corrected cm | Note |
|---|---|---|---|
| `2026-11-18_171333_455a14e2` (save 1) | 2 | 11→3: 156.3 → 195.4 | Sensor sanity on 1 degree wall actual distance bolt to bolt is about 180cm |
| `2026-11-18_171935_d09906ce` (save 1) | 2 | 9→2: 138.9 → 173.6 | Known overhang bottom hold 31 top 25 |
| `2026-11-18_172513_a23e8649` (save 1) | 2 | 3→27: 144.5 → 180.6 | Phone held at roughly 20degrees  wall angle 25 |
| `2026-11-18_172816_cd704be3` (save 1) | 2 | 6→11: 100.1 → 125.2 | Wall angles, 21 for bottom 54 for top distance 135 bolt to bolt |
| `2026-11-18_173154_e5fa8472` (save 1) | 2 | 13→11: 55.7 → 69.6 | White hold 17 green hold 18 |
| `2026-11-18_173256_39de9e4b` (save 1) | 2 | 8→9: 55.5 → 69.3 | Same as photo before, but phone tilted at about 30 degrees |
| `2026-11-18_173344_9ee79fae` (save 1) | 2 | 8→12: 55.7 → 69.6 | Angles same as last but phone at 70 degrees ish this time n |
| `2026-11-18_173610_3c85ab53` (save 1) | 2 | 30→8: 123.7 → 154.7 | Cross seam pink is 20 purple is 1, distance 155cm |
| `2026-11-18_173933_109f12fb` (save 1) | 2 | 28→35: 76.3 → 95.4 | Testing bolt holes hidden behind a volume left  distance bolt to bolt about 80angle is12 right is 20 |
| `2026-11-18_174106_63d2f8c2` (save 1) | 2 | 3→4: 63.8 → 79.8 | Actual distance 76cm actual angle 24 |
| `2026-11-18_174142_ac2132d6` (save 1) | 2 | 27→12: 62.7 → 78.4 | Same but further |

Captures after `2026-11-18_174142_ac2132d6` were taken at 25 cm and are accurate as saved.

## Tester's standing rules (2026-11-18)
- Every tape distance in these captures is **bolt hole to bolt hole**, unless a note says otherwise.
- The phone's **sensor pitch/roll in `capture.json` is the true camera tilt**; the tilt the tester typed in a note is only a rough estimate.
- Bolt spacing on this wall is a **known 25 cm** (not taped in the session).
- `truth.json` was filled from the in-app notes by an agent; every assumption was then confirmed by the tester. One value is approximate: `173610` purple hold is about 14 deg (the note's "1" was a typo).
