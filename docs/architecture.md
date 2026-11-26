# Architecture

ctrl + k then v to preview in vs code

This doc answers *what the system is and how the pieces fit together*.
For *why* a given technology/pattern was chosen, see [decisions.md](decisions.md).

## 1. System Overview

Currently:

- 1 - Mobile app compiles formData (photo + the phone's tilt) and POSTs to API/detect. The backend finds the holds (YOLO), finds the wall's bolt holes, and uses the bolt grid as a ruler to work out distances between holds, the wall's length and its steepness under each hold.
- 2 - Mobile app allows user to denote holds in PhotoPreview, which shows the distance between consecutive picks and the wall angle at each hold.
- 3 - Mobile app compiles formData and POSTs to API/analysis. LLM runs inference on the hold denotions and returns a JSON list of climbing steps.
- 4 - Mobile app polls the API/GET/analysis/{task_id} for the completed analysis.
- 5 - Mobile app maps over the returned steps and displays them to the user.

## 2. Request / Data Flow

1. User captures a photo in `CustomCamera.tsx` (picks the sensor's best real `pictureSize`), shown by `CameraScreen.tsx`.
2. As soon as the photo is captured, `PhotoPreview.tsx` automatically fires `useDetectHolds` (no user action needed), which builds formData with the image and the phone's tilt at the shutter (`useGravityReading`) and `POST`s to `/detect`. This is synchronous; it takes 7–15 s today (target 4–5 s, slice 13). Inside `/detect`, in order:
   1. **YOLO** (`detection.py`) finds holds and volumes on a 1024 px copy of the photo.
   2. **Bolt holes** (`bolts.py`) are found on the **full-resolution** photo. They are about 10 px across, so shrinking the photo loses them.
   3. **Scale** (`scale.py`) fits the bolt grid, splits the wall into flat panels, and measures every hold-to-hold distance in grid units (1 unit = one bolt spacing), with a confidence tier (A or C) for each.
   4. **Angle** (`angle.py`) works out the wall's steepness at each hold from the grid's shape plus the phone's tilt. If it fails, the angles come back empty and the distances are unaffected.
3. `PhotoPreview.tsx` receives the JSON object containing detections and disables tapping until it arrives (shows a "Detecting holds…" indicator). Once ready, each tap resolves to the nearest/containing detection via `utils/holdMatching.ts` and toggles that hold's selection (tap again to deselect); selected holds render as their real detected polygon shape, not a generic marker.
4. `PhotoPreview.tsx` submits via `useClimbAnalysis` (wraps `climbAnalysis.tsx`), which `POST`s `detection_id` + `selected_hold_ids` to `/analysis` with a caller-generated `Idempotency-Key` header — no photo is re-uploaded, the backend already has the detections cached from step 3.
5. `main.py` validates the selection (minimum hold count; every id must exist in the cached detections, else `422`; a missing/expired `detection_id` returns `410`), resolves it into a `master_hold_dict`, reserves the idempotency key in Redis (`SET NX`, 24h TTL), enqueues `analysis_task.delay(master_hold_dict)` on Celery, stores the resulting `task_id` against that key, and returns `202 {task_id}`.
6. `CameraScreen.tsx` swaps in `AnalysisResult.tsx`, which polls `GET /analysis/{task_id}` via `useGetClimbAnalysis` (every 2s while in progress, gives up after 30s).
7. The Celery worker (`worker.py`) picks up the job and runs `analysis(master_hold_dict)` — builds the coaching prompt and calls the Claude Messages API with structured outputs (`output_config.format` + `COACHING_OUTPUT_SCHEMA`), so the beta comes back as JSON `{steps: [{step_number, instruction, reason}]}`. The task parses it and returns it as a dict; truncated or unparseable output fails the task.
8. The task's result/state is written back through Celery's Redis result backend.
9. The next poll's `GET /analysis/{task_id}` reads that state/result and returns it; `AnalysisResult.tsx` renders the status, error, or timeout text, or on success maps over `result.steps` into a scrollable list of steps.

## 3. API Contract

### `POST /detect`

| Field | Where | Notes |
| :--- | :--- | :--- |
| `photo` | multipart file | required. Full camera resolution; never resize it (bolt detection needs about 3200 px on the long side) |
| `gravity` | form field | optional. The phone's accelerometer reading `[x, y, z]`. Missing or bad values are ignored and a 12° camera tilt is assumed |

Responses: `422` `Upload file isnt readable` if non image/corrupt upload. If YOLO inference fails `500` `Hold detection failed`; if bolts or scale fail `500` `Wall scale estimation failed`. Redis cache write failure `503` `couldnt save detection results`. Valid photo returns 200 with `{detection_id, detections, scale}`.

`scale` holds `status` (`ok` / `insufficient_bolts`), `bolt_count`, `wall_length_units`, `distances_units` (N×N, same order as `detections`), `tiers` (N strings of `A`/`C`), `angles_deg` (one per detection, + overhang / − slab), `angle_source` (`sensor` / `assumed`), `angle_margin_deg` and `wall_axes` (per detection, the photo directions of "down the wall" and "across", used to split moves into up/across; absent when no bolts were found). Units are bolt spacings; the app and the worker multiply by the user's bolt spacing.


### `POST /analysis`
| Field | Where | Notes |
| :--- | :--- | :--- |
| `Idempotency-Key` | header | required, scoped globally (no auth yet) |
| `detection_id` | form field | required, from a prior `/detect` response |
| `selected_hold_ids` | form field | required, JSON array of ints - hold ids from that `/detect` response the user selected |
| `bolt_spacing_cm` | form field | optional, default 20, range 10–50. Empty returns `422` "No bolt spacing provided." |
| `climber_height_cm`, `climber_arm_span_cm` | form fields | optional (absent or empty = not set), ranges 100–230 and 90–250. Anything else returns `422` |

Responses: `202` `{task_id}` on success · `422` if fewer than the minimum hold count is
selected or a selected id isn't in the cached detections · `410` if `detection_id` is
missing/expired · `409` if a request with this key is already being processed · replay
of the original `{task_id}` if the key already completed.

### `GET /analysis/{task_id}`
| Status | Response body |
| :--- | :--- |
| `PENDING` / `STARTED` / `RETRY` | `{task_id, status}` |
| `FAILURE` | `{task_id, status, error}` |
| other (complete) | `{task_id, status, result}` - `result` is `{steps: [{step_number, instruction, reason}]}` |

## 4. Directory Map

```
ML-AI-Rock-Climbing-Assistant/
├── README.md                         # stack table, learning goals, current focus
├── docker-compose.yml                # redis + api + worker + frontend services
├── scripts/
│   └── refresh-lan-ip.ps1            # re-detects the host's LAN IP for the frontend container, see localhost.md
├── .github/workflows/
│   ├── pytest.yml                    # CI: runs the full backend pytest suite with coverage
│   └── load-test.yml                 # manual/weekly: runs tests/load/simulate_load.py against a real stack
├── docs/
│   ├── architecture.md               # what the system is, how it fits together
│   ├── decisions.md                  # why each tech/pattern was chosen
│   ├── localhost.md                  # running the full stack locally
│   ├── contributing.md
│   ├── testing.md
│   ├── features/
│   │   ├── handover.md               # slice status, plan, per-slice log (start here)
│   │   ├── volume_scan.md            # spec: volume scan test feature
│   │   └── volume_retrain.md         # side task: retraining YOLO to find volumes (parked)
│   └── features_deprecated/
│       └── wall_size_hold_distance.md # finished feature's spec: contracts, decisions, accuracy tables
├── backend/                          # run everything from here (uvicorn api.main:app, celery -A coaching.worker.app)
│   ├── Dockerfile
│   ├── TESTING_PLAN.md               # test strategy, concurrency and load-test reasoning
│   ├── api/                          # the web server the app talks to
│   │   ├── main.py                   # FastAPI app: POST /detect, POST /analysis, GET /analysis/{task_id}, POST /dev/volume-scan
│   │   └── redis_client.py           # async Redis client for idempotency-key + detections-cache reservations
│   ├── coaching/                     # the background job that writes the climbing steps
│   │   └── worker.py                 # Celery app: analysis task builds the coaching prompt + calls Claude, returns JSON steps
│   ├── wall_analysis/                # reading the photo: holds, bolt grid, distances, angles
│   │   ├── detection.py              # YOLO model loading; run_detection() (id'd detections); select_holds() lookup
│   │   ├── bolts.py                  # bolt-hole detection on the full-res photo
│   │   ├── scale.py                  # bolt grid fit, panels, hold distances + confidence tiers, wall length
│   │   ├── angle.py                  # wall steepness at each hold, from the bolt grid + phone tilt
│   │   ├── volume.py                 # volume face geometry (not wired into /analysis yet, slice 14)
│   │   └── volume_scan.py            # volume scan test feature: photo + sideways burst -> face angles
│   ├── accuracy_checks/              # dev-only scripts, run as `uv run python -m accuracy_checks.<name>`
│   │   ├── eval_field.py             # replays the real-phone field captures; run before/after any change
│   │   ├── eval_scale.py, eval_angle.py # accuracy reports against the reference photos
│   │   ├── eval_volume.py, fakewall.py  # synthetic walls with volumes, and their scoring
│   │   ├── eval_volume_field.py      # volume fits on the real field photos
│   │   └── draw_volume_corners.py    # click volume corners to record ground truth
│   ├── experiments/two_photo/        # parked two-photo volume experiment; synth.py also feeds test_volume_scan's slow tests
│   ├── field_captures/               # 15 real-phone captures (photo + tilt + truth.json), 2026-11-18
│   ├── field_captures_volumes/       # measured volumes (photo A/B/edge + tape), 2026-11-25
│   ├── tests/                        # every pytest file; run from backend/ (testpaths in pyproject.toml)
│   │   ├── conftest.py               # fakeredis + mocked Celery task fixtures, autouse
│   │   ├── test_main.py              # pytest for the API endpoints
│   │   ├── test_redis_client.py      # pytest for redis_client.py's env-var wiring
│   │   ├── test_worker.py            # pytest for the Celery task + broker/backend wiring
│   │   ├── test_concurrency.py       # pytest: idempotency race-safety under concurrent requests
│   │   ├── test_detection.py, test_bolts.py, test_scale.py, test_scale_panels.py, test_angle.py,
│   │   │   test_main_angle.py, test_volume.py, test_volume_scan.py, test_panels_reference.py
│   │   ├── freeze_reference_index.py # re-freezes data/reference_bolt_index.json (human approval only)
│   │   ├── data/                     # frozen reference bolt index for the regression guard
│   │   └── load/
│   │       └── simulate_load.py      # async load-test script against a real stack (not part of pytest)
│   └── models/
│       ├── best.pt                   # trained YOLO weights (expected filename, gitignored)
│       └── README.md
└── mobile/ML-Rock-Climbing-App/
    ├── README.md
    ├── Dockerfile
    ├── app/
    │   ├── _layout.tsx                # root layout to wrap app in global providers
    │   └── index.tsx                  # entry route, renders CameraScreen
    ├── components/
    │   ├── CameraScreen.tsx           # composes gate -> camera -> preview -> analysis result, holds image uri and taskid state
    │   ├── CameraPermissionGate.tsx   # camera permission request/settings UI, gates children
    │   ├── CustomCamera.tsx           # deals with any camera function(flipping, retake), also calculates best resolution to display image at
    │   ├── PhotoPreview.tsx           # fires /detect on capture, tap-to-toggle hold selection rendered as real polygons,
    │   │                              # distance labels between picks and ≈N° wall angle per hold, submits to /analysis
    │   ├── ModeSlider.tsx             # swipeable camera-mode carousel next to the shutter
    │   ├── SettingsButton.tsx         # ⚙ button over the camera and PhotoPreview
    │   ├── SettingsModal.tsx          # settings screen: bolt pattern + spacing, climber height + arm span (validated as you type)
    │   ├── BoltPatternGraphic.tsx     # small drawing of each bolt pattern, with the distance to measure
    │   └── AnalysisResult.tsx         # renders polling status/error/timeout text, or the coaching steps list on success
    ├── hooks/
    │   ├── useDetectHolds.tsx         # useMutation wrapper around detectHolds (POST /detect)
    │   ├── useClimbAnalysis.tsx       # useMutation wrapper around climbAnalysis (POST /analysis)
    │   ├── useGetClimbAnalysis.tsx    # useQuery wrapper around getClimbAnalysis; polls every
    │   │                              # 2s while PENDING/STARTED/RETRY, gives up after 30s
    │   ├── useBoltSpacing.tsx         # bolt spacing saved on the phone (AsyncStorage), default 20 cm
    │   ├── useClimberStats.tsx        # climber height + arm span saved on the phone, both optional
    │   └── useGravityReading.tsx      # smoothed accelerometer reading, taken at the shutter
    ├── api/
    │   ├── detectHolds.tsx            # builds multipart FormData (photo), POSTs /detect; exports the Detection type
    │   ├── climbAnalysis.tsx          # POSTs detection_id + selected_hold_ids to /analysis
    │   └── getClimbAnalysis.tsx       # GETs /analysis/{task_id}, typed by status union; exports ClimbStep/ClimbAnalysis types
    ├── utils/
    │   ├── holdMatching.ts            # client-side tap -> detection resolution (point-in-polygon + nearest-centroid)
    │   ├── boltSpacing.ts             # bolt spacing limits (kept in sync with main.py) + cm/m formatting
    │   ├── boltPattern.ts             # the three bolt patterns and their conversion to the backend's square side
    │   └── climberStats.ts            # climber height/arm span limits (kept in sync with main.py) + parsing
    └── assets/
        ├── images/                    # camera preview assets
        └── known_measurements/        # reference photos + tape/angle ground truth used by tests and eval scripts
            ├── reference/             # full-res photos, panels.json, pairs.json ("Use Test Photo" = IMG_7504)
            ├── notes/                 # raw measurement notes
            └── gym_sessions/          # on-device test screenshots and notes
```

## 5. What the coaching AI is told

Everything the coaching AI (the LLM) receives when it writes the climbing steps. ☑ = built and sent today, ☐ = planned. Tick a row when it ships.

| Done | Information | In plain words |
| :---: | :--- | :--- |
| ☑ | Picked holds | The holds the climber tapped, in the order they tapped them, each marked as a hold or a volume. |
| ☑ | Where each hold is | How far across and how far down the photo the hold sits, as a fraction of the photo (not in cm). |
| ☑ | Distance between holds with confidence and margin for error | The distance between every pair of picked holds in cm, measured along the wall. Worked out from the wall's grid of bolt holes and the bolt spacing set in Settings. |
| ☑ | Wall length | Top to bottom of the wall that is in the photo, in cm. This is only the part in the photo, not the whole wall. |
| ☑ | Wall steepness at each hold with margin for error | Degrees from upright: positive means the wall leans out over the climber, negative means it leans back. Uses the phone's tilt when the photo was taken. |
| ☑ | How to coach | Be a friendly coach; give the start position, then one move per step with a short reason; use plain language; describe holds by where they are, not their number; never invent holds. |
| ☑ | Each move, split into up and across | For each move in pick order: its length, how much of it is up (or down) the wall and how much is sideways, in cm along the wall. Also where each hold is from the first picked hold. Slice 15. |
| ☑ | Wall angle change during a move | The steepness at both ends of each move, and a note when the wall gets clearly steeper or less steep (e.g. "steeper: 20 to 54.5 degrees"). Slice 15. |
| ☑ | The climber's height and arm span | Optional, entered in Settings, with the ape index worked out (arm span minus height). Slice 15. |
| ☐ | Whether a hold is on a volume, and the volume's size | Waits on slice 14 (needs the volume retrain). |
| ☐ | Where a hold is located on a volume | Helps when a hold on a volume is used to mount or as a foot for example. |
| ☐ | Hold type | What kind of hold each one is: whether it's a foothold or a handhold, and its type (crimp, jug, sloper, pinch, pocket, edge, etc.). Not built yet; plan in `docs/features/handover.md` → "Parked plans". |
