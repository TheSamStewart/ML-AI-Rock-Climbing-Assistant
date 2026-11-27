# Volume scan gym trial 1 (2026-11-27)

The human's first gym trial of the volume scan test feature (#38, `docs/milestones/v0.2/38-volume-scan-trial/`). Phone: iPhone 14 (main camera, 26 mm equivalent).

## What's here
- `image_<n>/`: the app screenshot (`*_screenshot.jpg`, converted from PNG) and, for images 1–2, a normal camera photo of the wall (`IMG_*.JPG`). The `.txt` files are the human's notes from the gym, verbatim.
- **The scans themselves** (each with `photo.jpg`, every burst photo, and `scan.json` with the result and per-photo diagnostics) are in `backend/field_captures_scans/<scan_id>/`. That folder is gitignored (80 MB); it exists on the human's PC and laptop only.

## Measuring
Face angles were measured with the iPhone level (Measure app), in degrees **from vertical**, + overhang (a face you pull on) / − slab (a face you can stand on). This is the app's convention; the human confirmed it on 2026-11-27 for image 2. The camera photos (`IMG_*.JPG`) had their GPS EXIF removed before going into git; everything else in their EXIF is kept (26 mm equivalent focal length).

## Results

| Image | Scan | Volume | Face | Actual | App | Error |
|---|---|---|---|---|---|---|
| — | `2026-11-27_103720_5a055561` | small blue volume against the black stripe where two wall panels meet, photo from whole-wall distance | | | ❌ "Couldn't line up enough burst photos" | |
| — | `2026-11-27_103832_cb310826` | pink triangle, bottom of wall | | | ❌ same | |
| 1 | `2026-11-27_104222_ab74269e` | orange pyramid, near-vertical wall (app: 9°) | left | −48° | −52° (app face 2, "left") | 4° |
| | | | right | +7° ¹ | −5° (app face 1, "out") | 12°, sign differs (both near vertical) |
| | | | bottom | +30° | not found | missed |
| 2 | `2026-11-27_110448_f0775720` | long red wedge, wall 30° (app: 27°) | top | −40° | +67° (app face 1) | sign wrong |
| | | | bottom | +53° | −60° (app face 2) | sign wrong |
| 3 | `2026-11-27_111637_0850f4b3`, `2026-11-27_111917_9ec3bb3c` | small blue pentagon | | | ❌ line-up error ×2 ² | |
| 4 | none | pink volumes | | | no volume detected (#37) | |
| 5 | `2026-11-27_113654_afb4dee8` | large pink volume, bottom | | | ❌ line-up error (it was detected: the scan has its outline) | |

App face numbers are the order in each scan's `scan.json` `result.faces`, from 1, as `volume.json` defines. The top/bottom pairing for image 2 is the human's reading of the screenshot.

¹ The note reads "right angle -5 vs 7" under the heading "actual vs yield", but the app showed −5°. So that line is in the reverse order; the human confirmed +7° is the actual (2026-11-27).
² The note says 3 tries all gave the line-up error, and once the volume wasn't detected. Only 2 scans are saved for this volume. The server saves every scan, failed ones included, so a third should exist. It may be on the laptop, or the save may have failed (`main.py` only logs a failed save).

- Burst photos lined up: 2 of 8 (image 1) and 2 of 9 (image 2). The other 5 scans had fewer than 2.
- Outlines don't follow the real faces (images 1–2).
- Depths (11 cm, 26 cm) were measured with the app's bolt spacing at 20 cm. The gym's is 25 cm, so they're 20% short. Angles aren't affected.
