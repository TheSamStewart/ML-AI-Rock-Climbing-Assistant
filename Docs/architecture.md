# Architecture

ctrl + k then v to preview in vs code

This doc answers *what the system is and how the pieces fit together*.
For *why* a given technology/pattern was chosen, see [decisions.md](decisions.md).

## 1. System Overview

Currently:

- 1 - Mobile app compiles formData and POSTs to API/analysis.
- 2 - FastAPI adds the analysis task to the redis queue and returns the taskid.
- 3 - Mobile app polls the API/GET/analysis/{task_id} for the completed analysis.
- 4 - Mobile app displays the completed analysis to the user.

## 2. Request / Data Flow

1. User captures a photo in `CustomCamera.tsx` (picks the sensor's best real `pictureSize`), shown by `CameraScreen.tsx`.
2. User taps holds on `PhotoPreview.tsx`; taps are normalized to `[0,1]` coordinates relative to the photo.
3. `PhotoPreview.tsx` submits via `useClimbAnalysis` (wraps `climbAnalysis.tsx`), which builds multipart `FormData` (photo + taps) and `POST`s to `/analysis` with a caller-generated `Idempotency-Key` header.
4. `main.py` reserves the idempotency key in Redis (`SET NX`, 24h TTL), enqueues `analysis_task.delay(...)` on Celery, stores the resulting `task_id` against that key, and returns `202 {task_id}`.
5. `CameraScreen.tsx` swaps in `AnalysisResult.tsx`, which polls `GET /analysis/{task_id}` via `useGetClimbAnalysis` (every 2s while in progress, gives up after 30s).
6. The Celery worker (`worker.py`) picks up the job and runs `analysis(filename, content_type, taps)` — currently a stub; eventually YOLO26-seg + LLM reasoning.
7. The task's result/state is written back through Celery's Redis result backend.
8. The next poll's `GET /analysis/{task_id}` reads that state/result and returns it; `AnalysisResult.tsx` renders the status, error, timeout, or final result text.

## 3. API Contract

### `POST /analysis`
| Field | Where | Notes |
| :--- | :--- | :--- |
| `photo` | multipart file | required |
| `Idempotency-Key` | header | required, scoped globally (no auth yet) |
| `taps` | form field | optional, JSON string of `{x, y}` normalized [0,1] points |

Responses: `202` `{task_id}` on success · `409` if a request with this key is already
being processed · replay of the original `{task_id}` if the key already completed.

### `GET /analysis/{task_id}`
| Status | Response body |
| :--- | :--- |
| `PENDING` / `STARTED` / `RETRY` | `{task_id, status}` |
| `FAILURE` | `{task_id, status, error}` |
| other (complete) | `{task_id, status, result}` |

## 4. Directory Map

```
ML-AI-Rock-Climbing-Assistant/
├── README.md                         # stack table, learning goals, current focus
├── docker-compose.yml                # redis + api + worker + frontend services
├── .github/workflows/
│   └── pytest.yml                    # CI: runs backend/test_main.py
├── Docs/
│   ├── architecture.md               # what the system is, how it fits together
│   ├── decisions.md                  # why each tech/pattern was chosen
│   ├── docker.md
│   ├── contributing.md
│   ├── testing.md
│   ├── TS.md
│   ├── react-expo.md
│   └── tanstack.md
├── backend/
│   ├── Dockerfile
│   ├── main.py                       # FastAPI app: POST /analysis, GET /analysis/{task_id}
│   ├── worker.py                     # Celery app (currently a stub)
│   ├── redis_client.py               # async Redis client for idempotency-key reservations
│   └── test_main.py                  # pytest for API
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
    │   ├── PhotoPreview.tsx           # tap to mark holds, normalized 0 -> 1. Submits request to API
    │   └── AnalysisResult.tsx         # renders polling status/result/error/timeout text, will eventually render the coaching feedback
    ├── hooks/
    │   ├── useClimbAnalysis.tsx       # useMutation wrapper around climbAnalysis (POST)
    │   └── useGetClimbAnalysis.tsx    # useQuery wrapper around getClimbAnalysis; polls every
    │                                  # 2s while PENDING/STARTED/RETRY, gives up after 30s
    ├── api/
    │   ├── climbAnalysis.tsx          # builds multipart FormData (photo+taps), POSTs /analysis
    │   └── getClimbAnalysis.tsx       # GETs /analysis/{task_id}, typed by status union
    └── assets/images/
        └── flipoutline_110902.png     # camera flip icon
```

