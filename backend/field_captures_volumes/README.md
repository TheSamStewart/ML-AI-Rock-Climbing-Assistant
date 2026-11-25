# Field captures: volumes

Written by the app's dev-only "Save A / Save B / Save edge" buttons
(`POST /dev/volume-capture`, `backend/volume_capture.py`). TEMPORARY.

One folder per volume: `V01`, `V02`, ... "Save A" starts a new folder; "Save B"
and "Save edge" add to the newest one. A repeat of the same role gets a suffix
(`photo_B_2.jpg`); nothing is ever overwritten.

## Files in each folder
- `photo_<role>.<ext>`: the photo exactly as the phone uploaded it (EXIF
  intact, NOT rotated). Apply `ImageOps.exif_transpose` before using any
  coordinate in capture.json, as /detect does.
  - A: phone upright in portrait, whole volume in frame with bolts around it.
  - B: same volume after one big step (0.5-1 m) to the side.
  - edge: the volume near the edge of the frame (only for some volumes).
- `capture.json`: `{"photos": [...]}`, one entry per saved photo:
  - `file`, `role`, `saved_at`, `phone_filename` (the app's file name).
  - `photo`: raw size, upright size (after EXIF rotation), EXIF orientation,
    `focal_35mm` (null = 26 mm assumed by /detect).
  - `sensor`: `gravity_sent` (smoothed accelerometer at the shutter, in G,
    device frame x right / y up the screen / z out of the screen),
    `accepted`, `pitch_deg` (positive = camera pointing up), `roll_deg`
    (0 = upright portrait).
  - `client`: platform, OS version, capture time, bolt spacing set in the app.
  - `detect`: the cached /detect result for this photo (`detection_id`,
    `scale`, `detections`), or null if detection hadn't finished / failed.
  - `bolts`: bolt holes re-detected on the same upright pixels (normalized
    x, y; diameter in full-res px), or null.
- `volume.json`: ground truth, filled BY HAND. Template written on the
  first save. Only its `photos` key is updated by later saves.

## Conventions
- Angles: degrees, positive = overhang, negative = slab.
- Lengths: cm.
- null = not recorded, not zero.

## Bolt spacing
The gym's real spacing is **25 cm**. V01 was saved with the app at its default 20 cm
(`client.bolt_spacing_cm` = 20 in its capture.json). capture.json keeps distances in grid units only,
so nothing is wrong in the data: always use cm = units x 25. Check `client.bolt_spacing_cm` on later volumes.
