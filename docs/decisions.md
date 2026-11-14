# Document which outlines different design decisions made and why (for me)

ctrl + k then v to preview in vs code

## Index

**Stack Decisions**
- [Why Async Design](#why-async-design) — Status: Accepted · Date: 2026-07-16
- [React Native](#react-native) — Status: Accepted · Date: 2026-07-16
- [FastAPI RESTAPI](#fastapi-restapi) — Status: Accepted · Date: 2026-07-16
- [Redis](#redis) — Status: Accepted · Date: 2026-07-16
- [Celery](#celery) — Status: Accepted · Date: 2026-07-16
- [Yolo26-seg](#yolo26-seg) — Status: Accepted · Date: 2026-07-16
- [Why expo 54.0.0](#why-expo-5400) — Status: Superseded · Date: 2026-07-28

**Implementation Decisions**
- [Image Storage](#image-storage) — Status: Superseded · Date: 2026-07-16
- [Coordinate Normalization for Hold Taps](#coordinate-normalization-for-hold-taps) — Status: Accepted · Date: 2026-08-25
- [Image Resolution Fix](#image-resolution-fix) — Status: Accepted · Date: 2026-08-25
- [Hold denotion logic](#hold-denotion-logic) — Status: Accepted · Date: 2026-09-29 (uncommitted)
- [best.pt inference settings](#bestpt-inference-settings-detectionpy) — Status: Accepted · Date: 2026-09-29
- [Coaching output as JSON steps](#coaching-output-as-json-steps-workerpy-analysisresulttsx) — Status: Accepted · Date: 2026-10-01
- [Camera mode slider](#camera-mode-slider-modeslidertsx-customcameratsx) — Status: Accepted · Date: 2026-10-09

## Stack Decisions

## Why Async Design

Status: Accepted · Date: 2026-07-16

Asynchronus Design pattern was chosen as the window between the applications request and the backend's reply can exceed 20s. Keeping a synchronous HTTP connection open for this duration risks connection timeouts and client-side disconnections. Instead the application will issue a POST to initiate the task. The API will then issue a 202 accepted and return a TASKID to the application. The Application will then perform polling via GET requests to a status endpoint until the job is complete.

## Brief explanation of each part of the stack and why it was chosen.

### <ins>React Native:</ins>

Status: Accepted · Date: 2026-07-16

Explanation:

React Native allows for development in one language, that through the JavaScript Interface (jsi) allows the JS to call pre-existing native code. The JavaScript Interface utilises C++ wrappers to allow JavaScript to directly call upon native platform APIs (like getBatteryLevel). A wrapper is a C++ function which executes pre-compiled native methods. When our JS engine executes the JS call, this triggers the C++ wrapped which returns our result back in JS.

Why Chosen:

React Native is one of the most popular and modern frameworks for mobile frontends in 2026. I have experience using JavaScript and React so this was a comfortable choice.

### <ins>FastAPI RESTAPI</ins>:

Status: Accepted · Date: 2026-07-16

Explanation:

#### FastAPI

FastAPI is built on Starlette a fast Asynchronous Server Gateway Interface toolkit (ASGI). This allows fastAPI to send, receive and perform small tasks all on one thread. WSGI would perform these together on one thread (one thread = one request).

WSGI (Sequential/Blocking): Request -> Wait for work to be done -> Return payload. (1 thread = 1 active request).

ASGI (Concurrent/Non-Blocking): Request -> While work is being done, take other requests/other work -> Return payload. (1 thread = many concurrent requests).

#### RESTAPI

RESTAPI (Representational State Transfer) is an architecture for API design where the API is stateless. Statelessness means the API does not store any session state, every HTTP request must be self contained - in our case containing the related TASKID.

The frontend makes the request -> API drops the task in redis queue -> API returns the TASKID to the frontend -> moves onto next task.

This combined with the frontend polling GET while the task is being performed keeps our concerns separated and allows the API to process thousands of requests upholding the Async architecture.

Why Chosen:

#### FastAPI

FastAPI has been chosen for this project for two main reasons:

FastAPI is built on an asynchronous architecture (ASGI), which facilitates and supports the high-concurrency design of this application (i.e., managing a high volume of polling requests while offloading tasks to a background worker queue).

FastAPI is also written in Python, a language I am comfortable with through DSA questions.

#### RESTAPI

The REST architecture supports our application's scalability by keeping all HTTP requests stateless. Because the API must immediately terminate the session with the client to avoid disconnections, we cannot rely on persistent server-side sessions. Instead, it is imperative that we track long-running operations statelessly by issuing a unique TASKID to the client, which they must provide in subsequent polling requests to retrieve the task's progress.

### <ins>Redis</ins>

Status: Accepted · Date: 2026-07-16

Explanation:

Redis is an open-source in memory (uses RAM) data-structure, is a key-value store that supports strings, lists, sets. Celery uses Redis's native data-structures (lists) to implement a task-queue

Why Chosen:

By acting as a message-broker (task-queue) Redis facilitates background task execution allowing our Celery workers to process thousands of tasks completely seperate from our API. Redis stores the result from our Celery worker and, due to it's in memory (RAM) key-value architecture allows our API to return the result to the front-end in miliseconds once work is complete.

### <ins>Celery</ins>

Status: Accepted · Date: 2026-07-16

Explanation:

Celery is an open-source tool written in Python that utilises Redis to manage a Task Queue. When a task is added to the Queue using (`my_task.delay(arg)`) Celery serializes the Python args (in our case this would be a Base64 image string) into JSON format so they can travel across the network. Celery also generates a unique TASKID which the frontend uses to poll and retrieve the completed work.

Why Chosen:

Celery abstracts the complexity of the asynchronous processing system by handling task serialization, worker concurrency, and Redis queue management automatically in the background.

### <ins>Yolo26-seg</ins>

Status: Accepted · Date: 2026-07-16

Explanation:

Yolo26 is the most recent model architecture released by Ultralytics. YOLO is used because its eco-system (Ultralytics) make it intuitive to train and run predictions using the model.

Why Chosen:

For the eco-system that make custom-trained ML models achievable to people who are not experts in the Mathematics behind them. Segmentation is used due to the intricate shape or rock climbing holds, simple bounding boxes could lead to confusing annotations where holds overlap.

## Why expo 54.0.0

Status: Superseded · Date: 2026-07-28

- Expo go on app store does not support the latest versions of Expo unless using paid Apple Developer program.

## Implementation Decisions

## Image Storage

Status: Superseded · Date: 2026-07-16

This defines the image journey from user to worker.

1. The frontend will make a POST request in which it will recieve information on where to store the image (URL or something).
2. Frontend will store image at this place.
3. Worker script and frontend are free to access this image as needed.

This is old but at some point will need to sort out storage as production version cannot use redis db


## Coordinate Normalization for Hold Taps

Status: Accepted · Date: 2026-08-25

Explanation:

The user taps the photo preview to mark which holds/areas an LLM should pay attention to. The raw gesture event only gives view-space coordinates - relative to whatever container it's inside, in screen pixels.

The image is rendered with `resizeMode="contain"`, which scales the photo to fit its container while preserving aspect ratio. Unless the photo's aspect ratio happens to exactly match the screen's, this leaves letterboxing (black bars) on one axis. So a naive `x / screenWidth` normalization would be wrong - it measures a fraction of the screen.

The fix: instead of rendering the image full-bleed and inverting the letterbox math after each tap, `PhotoPreview.tsx` now sizes a box to the photo's true aspect ratio up front (via `Image.getSize` for the photo's native pixel dimensions and `useWindowDimensions` for the available space - the same "contain" fit calculation, just done once as layout instead of per-tap as an offset correction), and centers that box in the black background. The `GestureDetector` wraps that box directly, so its bounds *are* the photo's rendered bounds - a tap can't land in a letterbox bar because that area isn't part of the tappable view at all.

Why Chosen:

Because the box's bounds equal the photo's bounds, a tap's `x / box.width` is already a correct, photo-relative fraction the moment it happens - no offset subtraction, no post-tap "was this actually inside the photo" check. `TapPoint` stores that normalized `[0,1]` value directly, so there's no second array to maintain - the same `taps` state that drives the on-screen dots is what gets sent straight through `useClimbAnalysis` to the backend.

## Image Resolution Fix

Status: Accepted · Date: 2026-08-25

Explanation:

The photo preview looked low-resolution. `CustomCamera.tsx` was calling `takePictureAsync()` with no options, and `<CameraView>` had no `pictureSize` prop set. Diagnosed with temporary logging: a captured photo came back as `888x1920` (ratio ~2.16:1), while `getAvailablePictureSizesAsync()` reported the device actually supports `3840x2160`, `1920x1080`, `1280x720`, `640x480`, `352x288` (all 16:9 or 4:3) plus qualitative aliases (`"Photo"`, `"High"`, `"Medium"`, `"Low"`). `888x1920` doesn't match any of those - it's not one of the sensor's real still-capture resolutions at all. Without an explicit `pictureSize`, the capture was instead sized off the on-screen preview surface, i.e. roughly the screen's own resolution, well below what the sensor supports.

Why Chosen:

Fixed by picking the largest real `WxH` entry from `getAvailablePictureSizesAsync()` (filtering out the qualitative aliases, which aren't valid `pictureSize` values) once the camera reports ready via `onCameraReady`, and pinning it to `<CameraView>`'s `pictureSize` prop. This forces capture to use the sensor's max supported still resolution instead of whatever the preview surface happened to be.

## Hold denotion logic (`main.py`, `PhotoPreview.tsx`, `utils/holdMatching.ts`)

Status: Accepted · Date: 2026-09-29 

Implementation:

#### Frontend (`PhotoPreview.tsx`):

When an image has been taken by user we **POST** the image to `main.py/detect` (`POST /detect`) which runs the ML predicitions and then return the `JSON` with prediction coordinates to the frontend. This is done synchronously as the predictions take seconds to run. To denote a hold the user now taps on the screen and `utils/holdMatching.ts` matches the predictions to a user tap. If for example the tap is not near any hold it will be ignored

#### Backend (`main.py`):

`main.py/detect` (`POST /detect`) checks that the upload from the frontend is valid. If valid it will run predicitions and return this for hold denotion in the frontend


## best.pt inference settings (`detection.py`)

Status: Accepted · Date: 2026-09-29

Explanation:

`run_detection` used to call `model.predict(image)` with no arguments. Evaluated against the held-out validation split (49 images, `dataset_3_hopefully`), that left three problems:

- **Duplicates** - YOLO26 defaults to its end-to-end head, which skips NMS entirely (`iou` has no effect), so same-class near-duplicate detections reached the app and broke tap-to-toggle (159 duplicate pairs across 49 images).
- **The "massive line" across volumes** - polygons came from `masks.xyn`, which uses `masks2segments(strategy="all")`: every disconnected blob of a mask gets stitched into one polygon with bridge lines between them. Volumes often split into blobs along shaded faces.
- **Heavy responses** - ~75 points per polygon, ~130 KB per `/detect` response.

Why Chosen:

| setting | value | why |
| :--- | :--- | :--- |
| `end2end` / `iou` | `False` / `0.5` | NMS head removes duplicates; 0.6 and 0.7 kept 4-5x more duplicates for no recall gain |
| `CONFIDENCE_FLOORS` | HOLD `0.15`, VOLUME `0.25` | favours recall; HOLD `0.08` added 1.7 pts recall but doubled duplicates, VOLUME `0.05` added < 2 pts recall for 9 pts precision lost |
| `retina_masks` | `True` | tighter mask outlines |
| `MAX_INPUT_SIDE` | `1024` | model letterboxes to 1024 anyway; without it retina masks on a 4K photo were ~700 MB and 2.3s per request |
| polygon | largest-area contour + `approxPolyDP` (0.005) | drops disconnected fragments instead of bridging them; ~15 points per polygon |
| `imgsz` | `1024` (unchanged) | already inherited from the checkpoint - pinned explicitly for clarity. Test-time augmentation had no effect on this model |

Results (before -> after, same validation split): HOLD recall `0.737 -> 0.818`, HOLD precision `0.815 -> 0.837`, duplicate pairs `159 -> 21`, worst-10% volume outline outside the real volume `24.9% -> 16.6%`, response `132 KB -> 45 KB`, latency unchanged (~1.1s; 0.7s on a 4K photo). Trade-off: VOLUME recall `0.873 -> 0.857`, as NMS merges some overlapping neighbouring volumes.


## Coaching output as JSON steps (`worker.py`, `AnalysisResult.tsx`)

Status: Accepted · Date: 2026-10-01

Explanation:

The coaching LLM used to return free text, which the app could only dump into a single `<Text>`. It now returns `{steps: [{step_number, instruction, reason}]}`, which `AnalysisResult.tsx` maps over to render one entry per move.

Why Chosen:

- **Structured outputs (`output_config.format` + `COACHING_OUTPUT_SCHEMA`)** - the API enforces the schema, so valid JSON doesn't rely on the prompt alone. Truncated (`max_tokens`) or unparseable output fails the task, and the app shows the error like any other failure.
- **Steps with a separate `reason`** - the frontend can style each move and its explanation independently later. Tips go into the relevant step's `reason` instead of a separate list.
- The schema and `ClimbStep`/`ClimbAnalysis` in `getClimbAnalysis.tsx` must be kept in sync by hand.

## Camera mode slider (`ModeSlider.tsx`, `CustomCamera.tsx`)

Status: Accepted · Date: 2026-10-09

Explanation:

Snapchat-style carousel next to the shutter. Mode circles sit to the right of the shutter, swiping right to left slides one into the shutter ring to select it, swiping back returns to plain capture. Only "Static Route Analysis" for now - a placeholder circle with no functionality yet. `onModeChange` fires once the slider settles on a new mode (`null` for plain capture), this is where the mode's functionality will hook in.

Why Chosen:

- Matches the Snapchat camera styling the app already follows - modes can be switched with one thumb without leaving the camera.
- Modes live in one `CAMERA_MODES` array, so adding "Coaching Analysis" etc. is a one-line change.
- Each mode can take an optional `style` in `CAMERA_MODES` (colour, border, opacity etc.) applied on top of the default circle. Size and position stay controlled by the carousel so every icon still centres in the shutter ring.
- The pan uses `activeOffsetX` so a tap on the shutter isn't mistaken for a swipe.
