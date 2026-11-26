# Volume scan (test feature, #38, branch `feat/38-volume-scan-trial`)

## Goal
Show the angle of every visible face of a climbing volume, in degrees, in the app. The user takes the normal photo, taps a volume, then holds a button while taking one slow step sideways; the app takes a burst of photos during the step. From the photo plus the burst, the server measures each face's angle and the volume's depth, and the app draws each face's outline with its angle on the photo.

This is a **test feature for gym trials** (human, 2026-11-25). It is not part of the normal flow and does not reach the coaching AI yet. It implements "idea 2" from `docs/features_deprecated/wall_size_hold_distance_handover.md` slice 11: many views from one short sweep, instead of three separate photos (too much to ask) or ARKit/ARCore (not possible in Expo Go). The degree readout is wanted for display even where coaching doesn't need it; see the standing instruction never to remove the angle display.

## Inputs
- `photo`: the full-resolution photo already taken (the anchor), and the phone's `gravity` reading at its shutter.
- `frames`: 3–12 photos from the burst, the same camera and picture size as the photo, taken while the phone moves sideways about 0.3–1 m and keeps the volume in frame.
- `volume_polygon`: the tapped VOLUME detection's outline (normalised x, y on the photo).
- `bolt_spacing_cm`: the user's setting (the depth is in cm).

## Outputs
`POST /dev/volume-scan` returns `200`:
```
{
  scan_id: str,                       // folder name under backend/field_captures_scans/
  faces: [{
    steepness_deg: float,             // degrees from vertical, + overhang / - slab (angle.py's convention)
    facing: "out" | "left" | "right" | "undefined",
    facing_deg: float | null,         // turn about gravity from the wall's own facing, + = climber's right
    outline: [{x, y}],                // normalised, on the photo
    n_points: int                     // 3D points supporting the face
  }],
  depth_cm: float | null,             // furthest point off the wall; null when the photo's bolt-grid
                                      // fit is uneven (axes > 8% apart), since the angles hold but cm don't
  wall_angle_deg: float,              // the wall beside the volume, from the bolt grid + gravity
  frames_used: int, frames_sent: int,
  seconds: float
}
```
`422` with a plain message when the scan can't run: no bolt grid at the volume, fewer than 2 frames posed, unreadable images, or a bad polygon. Every request (inputs and result) is saved under `backend/field_captures_scans/<scan_id>/`, with a `volume.json` truth template to fill by hand.

App: in PhotoPreview, once a VOLUME is among the selected detections, a "Scan volume faces (test)" button opens the scan camera. After the scan, each face's outline is drawn on the photo in its own colour, labelled with the angle (e.g. "+23°") and which way it faces, with the depth below. Errors are shown as text.

### Contracts (for the Tester)
- `volume_scan.scan_volume(photo, frames, volume_polygon, detections, gravity_reading=None, focal_35mm=None, bolt_spacing_cm=25.0) -> dict`. `photo` and `frames` are upright PIL images. It returns the response fields above except `scan_id`, plus `points`, `photo_axis_ratio` and `frame_diagnostics`. It raises `volume_scan.ScanError` (a `ValueError`) with a user-readable message when the scan can't run. Fewer than `volume_scan.MIN_FRAMES` (2) frames always raises; more than `MAX_FRAMES` (12) are thinned evenly.
- `POST /dev/volume-scan` (multipart):
  - **Fields:** `photo` (file), `frames` (one or more files), `volume_polygon` (a JSON list of `{x, y}`), optional `gravity` (as for `/detect`) and optional `bolt_spacing_cm` (10–50, default 20).
  - **Saving:** each request is saved in a new folder under `main.SCANS_DIR`, with `photo.jpg`, `frame_NN.jpg`, `scan.json` (inputs, plus `result` or `error`) and a `volume.json` template.
  - **Errors:** a bad polygon, a bad spacing, more than 20 frames, an unreadable image, a `ScanError` or any other failure gives a `422` `{detail, scan_id}`, never a 500.
  - YOLO runs on the photo (`detection.run_detection`); its failure doesn't stop the scan.
- Synthetic test cases: `backend/experiments/two_photo/synth.py`, `sweep_case(scene, n_frames, span_cm)`, with scenes from `synth.scenes()`. It returns `photo`, `frames`, `gravity`, `volume_polygon`, `detections`, `truth_faces` (`angle_deg`, `facing`, visible from the photo) and `depth_cm`. Rendering takes about 15 s per image, so tests using it are `slow`.

## Acceptance criteria
1. On synthetic sweeps (`backend/experiments/two_photo/synth.py`), faces visible from the photo are found and measured within 3° (median) and 6° (each), and the depth is within 5 cm.
2. The endpoint saves every scan's inputs and result, and returns the documented shape or a 422 with a message. It never crashes into a 500 on bad input.
3. The app shows each face's outline and angle on the photo, and the button only appears with a volume selected. `npx tsc --noEmit` is clean, and lint has no new problems.
4. The normal flow (`/detect`, `/analysis`, PhotoPreview selection and submission) is unchanged.
5. Real-world accuracy is **not** an acceptance criterion: the gym trial measures it. The saved scans plus tape angles are the reference data.

## Reference data
- Synthetic: `backend/experiments/two_photo/synth.py` (scenes with exact face angles).
- Real: `backend/field_captures_volumes/` (5 volumes; photos A/B/edge, not sweeps), and the gym scans as they arrive in `backend/field_captures_scans/`.

## Slices
| Slice | Scope | Done when |
|---|---|---|
| 1 | Backend `volume_scan.py` + `POST /dev/volume-scan` + saved scans; synthetic sweep helper; tests | AC 1, 2, 4 (backend) |
| 2 | App: burst camera, scan button, face overlay | AC 3, 4 (app) |
| 3 | Gym trial and write-up | the human has scanned some volumes with tape angles |

## Decisions
- **A burst of photos, not video** (2026-11-25): the burst frames share the photo's lens and picture size, so their focal length is known. A video's focal length, stabilisation warping, codec and rotation would all be new unknowns. Expo Go only (no native AR).
- **Pose of each frame**: the wall homography between the photo and the frame (RANSAC on SIFT matches over plain wall on the volume's panel), decomposed with the photo's bolt-grid wall plane. On synthetic walls this was exact where PnP failed (slice 11, 2026-11-25).
- **Faces**: a multi-view plane sweep of heights off the wall, then sequential RANSAC planes, each kept only as one compact patch (`COMPACT_FRAC` 0.6). Accurate on synthetic walls (median 0.1°); on three real photos about 50%, which is what this trial re-tests with many frames.
- **SIFT, not ASIFT**: a small sideways step doesn't need affine-invariant matching, and ASIFT takes about 1 minute per photo.
- Dev-only endpoint, no auth (like the rest of the API today). On the Fable-review list to gate or remove before release.
