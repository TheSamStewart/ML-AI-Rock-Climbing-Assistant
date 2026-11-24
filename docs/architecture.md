# Architecture

ctrl + k then v to preview in vs code

This doc answers *what the system is and how the pieces fit together*.
For *why* a given technology/pattern was chosen, see [decisions.md](decisions.md).

## 1. System Overview

Currently:

- 1 - Mobile app compiles formData and POSTs to API/detect to get hold detections from ML predictions.
- 2 - Mobile app allows user to denote holds in PhotoPreview which are previewed to user.
- 3 - Mobile app compiles formData and POSTs to API/analysis. LLM runs inference on the hold denotions and returns a JSON list of climbing steps.
- 4 - Mobile app polls the API/GET/analysis/{task_id} for the completed analysis.
- 5 - Mobile app maps over the returned steps and displays them to the user.

## 2. Request / Data Flow

1. User captures a photo in `CustomCamera.tsx` (picks the sensor's best real `pictureSize`), shown by `CameraScreen.tsx`.
2. As soon as the photo is captured, `PhotoPreview.tsx` automatically fires `useDetectHolds` (no user action needed), which builds formData with the image and `POST`s to `/detect`. (this is synchronous as only takes seconds to run predictions on one image)
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
| `photo` | multipart file | required |

Responses: `422` `Upload file isnt readable` if non image/corrupt upload. If YOLO inference fails `500` `Hold detection failed`. Redis cache write failure `503` `couldnt save detection results`. Valid photo returns 200 with detections.  


### `POST /analysis`
| Field | Where | Notes |
| :--- | :--- | :--- |
| `Idempotency-Key` | header | required, scoped globally (no auth yet) |
| `detection_id` | form field | required, from a prior `/detect` response |
| `selected_hold_ids` | form field | required, JSON array of ints - hold ids from that `/detect` response the user selected |

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
│   └── load-test.yml                 # manual/weekly: runs load_test/simulate_load.py against a real stack
├── docs/
│   ├── architecture.md               # what the system is, how it fits together
│   ├── decisions.md                  # why each tech/pattern was chosen
│   ├── localhost.md                  # running the full stack locally
│   ├── contributing.md
│   └── testing.md
├── backend/
│   ├── Dockerfile
│   ├── main.py                       # FastAPI app: POST /detect, POST /analysis, GET /analysis/{task_id}
│   ├── detection.py                  # YOLO model loading; run_detection() (id'd detections); select_holds() lookup
│   ├── worker.py                     # Celery app: analysis task builds the coaching prompt + calls Claude, returns JSON steps
│   ├── redis_client.py               # async Redis client for idempotency-key + detections-cache reservations
│   ├── bolts.py                      # bolt-hole detection on the full-res photo
│   ├── scale.py                      # bolt lattice fit, panel homographies, hold distances, wall length
│   ├── eval_scale.py                 # dev-only overlay + accuracy report (not used by the API)
│   ├── tests/                        # every pytest file; run from backend/ (testpaths in pyproject.toml)
│   │   ├── conftest.py               # fakeredis + mocked Celery task fixtures, autouse
│   │   ├── test_main.py              # pytest for the API endpoints
│   │   ├── test_redis_client.py      # pytest for redis_client.py's env-var wiring
│   │   ├── test_worker.py            # pytest for the Celery task + broker/backend wiring
│   │   ├── test_concurrency.py       # pytest: idempotency race-safety under concurrent requests
│   │   └── test_detection.py, test_bolts.py, test_scale.py, test_panels_reference.py
│   ├── load_test/
│   │   └── simulate_load.py          # async load-test script against a real stack (not part of pytest)
│   └── models/
│       ├── best.pt                   # trained YOLO weights (expected filename)
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
    │   ├── PhotoPreview.tsx           # fires /detect on capture, tap-to-toggle hold selection rendered as real polygons, submits to /analysis
    │   └── AnalysisResult.tsx         # renders polling status/error/timeout text, or the coaching steps list on success
    ├── hooks/
    │   ├── useDetectHolds.tsx         # useMutation wrapper around detectHolds (POST /detect)
    │   ├── useClimbAnalysis.tsx       # useMutation wrapper around climbAnalysis (POST /analysis)
    │   └── useGetClimbAnalysis.tsx    # useQuery wrapper around getClimbAnalysis; polls every
    │                                  # 2s while PENDING/STARTED/RETRY, gives up after 30s
    ├── api/
    │   ├── detectHolds.tsx            # builds multipart FormData (photo), POSTs /detect; exports the Detection type
    │   ├── climbAnalysis.tsx          # POSTs detection_id + selected_hold_ids to /analysis
    │   └── getClimbAnalysis.tsx       # GETs /analysis/{task_id}, typed by status union; exports ClimbStep/ClimbAnalysis types
    ├── utils/
    │   └── holdMatching.ts            # client-side tap -> detection resolution (point-in-polygon + nearest-centroid)
    └── assets/images/
        └── ...                        # camera preview / dev test-photo assets
```

## 5. What the coaching AI is told

Everything the coaching AI (the LLM) receives when it writes the climbing steps. ☑ = built and sent today, ☐ = planned. Tick a row when it ships.

| Done | Information | In plain words |
| :---: | :--- | :--- |
| ☑ | Picked holds | The holds the climber tapped, in the order they tapped them, each marked as a hold or a volume. |
| ☑ | Where each hold is | How far across and how far down the photo the hold sits, as a fraction of the photo (not in cm). |
| ☑ | Distance between holds | The distance between every pair of picked holds in cm, measured along the wall. Worked out from the wall's grid of bolt holes and the bolt spacing set in Settings. |
| ☑ | How sure each distance is | "A" when the bolt holes are visible the whole way between the two holds, "C" when holds or volumes hide some of them. |
| ☑ | Room for error on distances | How far off each distance could be (a few cm, more for "C"). The AI is told to treat a move as reachable if it is short by no more than this. |
| ☑ | Wall length | Top to bottom of the wall that is in the photo, in cm. This is only the part in the photo, not the whole wall. |
| ☑ | Wall steepness at each hold | Degrees from upright: positive means the wall leans out over the climber, negative means it leans back. Uses the phone's tilt when the photo was taken. |
| ☑ | Room for error on steepness | About 8° when the phone's tilt was recorded, 15° when it wasn't, plus a warning that a wall leaning back can be mistaken for one leaning out. |
| ☑ | How to coach | Be a friendly coach; give the start position, then one move per step with a short reason; use plain language; describe holds by where they are, not their number; never invent holds. |
| ☐ | | |
| ☐ | | |
| ☐ | | |
