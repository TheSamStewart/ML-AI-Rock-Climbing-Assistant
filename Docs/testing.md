# Testing

## Status

| Automated testing | Workflow | Status |
|-------------------|----------|--------|
| Backend unit tests (pytest) | `pytest.yml` | **Current** (80 tests, 100% line coverage) |
| Load test | `load-test.yml` | **Inactive / OOD** - see [simulate_load.py](#simulate_loadpy) |

## Index

- [Testing](#testing)
  - [Status](#status)
  - [Index](#index)
  - [Backend Testing](#backend-testing)
  - [Directory](#directory)
  - [Running locally](#running-locally)
  - [pytest.yml](#pytestyml)
    - [Summary](#summary)
    - [Fixtures (conftest.py)](#fixtures-conftestpy)
    - [Test Files](#test-files)
      - [test\_main.py](#test_mainpy)
      - [test\_detection.py](#test_detectionpy)
      - [test\_worker.py](#test_workerpy)
      - [test\_concurrency.py](#test_concurrencypy)
      - [test\_redis\_client.py](#test_redis_clientpy)
    - [coverage.xml](#coveragexml)
  - [load-test.yml](#load-testyml)
    - [Summary](#summary-1)
    - [Logs](#logs)
    - [simulate\_load.py](#simulate_loadpy)

## Backend Testing

Nothing in the pytest suite needs real infrastructure: Redis is `fakeredis`,
the Celery task's `.delay()` is mocked, the Claude client is mocked, and the
YOLO model is replaced by a stub that returns an ultralytics-shaped result.
The only exception is one opt-in smoke test that loads the real weights when
they're present.

## Directory
```
├── backend/
│   ├── main.py                       # FastAPI app: POST /detect, POST /analysis, GET /analysis/{task_id}
│   ├── detection.py                  # YOLO loading, run_detection(), select_holds()
│   ├── worker.py                     # Celery app: analysis task builds the coaching prompt + calls Claude
│   ├── redis_client.py               # async Redis client for idempotency keys + detections cache
│   ├── conftest.py                   # shared fixtures (fake redis, mocked Celery task, sample detections)
│   ├── test_main.py                  # API endpoints
│   ├── test_detection.py             # detection.py geometry, filtering, selection (stubbed model)
│   ├── test_worker.py                # prompt payload, Claude call + error mapping, Celery wiring
│   ├── test_concurrency.py           # idempotency race-safety + concurrent /detect
│   ├── test_redis_client.py          # redis_client.py env-var wiring
│   ├── models/best.pt                # YOLO weights - gitignored, only present locally
│   └── load_test/
│       └── simulate_load.py          # async load-test script against a real stack (not part of pytest)
```

## Running locally

From `backend/`:

```
uv run python -m pytest -v --cov --cov-report=term-missing   # full suite
uv run python -m pytest -m "not slow"                         # what CI effectively runs (no best.pt)
uv run python -m pytest -m concurrency                        # just the concurrency tests
```

## pytest.yml

### Summary

Automatic unit testing for the backend. It runs on every PR, on pushes to `main`, and on manual dispatch.

This is the config file/workflow file for GitHub Actions.

On each run, dependencies are installed with `uv sync --all-extras --dev`, pytest runs via `uv run python -m pytest -v --cov --cov-report=term-missing --cov-report=xml`, and the coverage report is uploaded as an artifact to GitHub Actions.

Markers (registered in `pyproject.toml`):

- `concurrency` - many concurrent in-process requests (still fakeredis-backed).
- `slow` - loads the real `models/best.pt`; auto-skipped when it's missing, which is always the case in CI because the weights are gitignored.

### Fixtures (conftest.py)

- `mock_celery_task` (autouse) - patches `main.analysis_task.delay`, returns task id `test-task-id-1234`.
- `mock_redis_client` (autouse) - `fakeredis` async client with `decode_responses=True` (same as the real client, so the `"processing"` sentinel comparison behaves the same).
- `sample_detections` - 4 detections in `run_detection()`'s output shape (3 HOLD, 1 VOLUME).
- `cached_detection_id` - seeds `sample_detections` into fake redis the way `/detect` would, so `/analysis` tests don't need to call `/detect` first.
- `mock_run_detection` - patches `main.detection.run_detection` to return `sample_detections`.
- `jpeg_bytes` - a tiny real JPEG built in-memory with PIL.

### Test Files

#### test_main.py

Tests the FastAPI routes in `main.py`. All tests are async and run through `httpx` + `ASGITransport`, so the fake Redis is awaited on the app's own event loop.

`POST /detect`
- `test_detect_returns_and_caches_detections` - 200 + detections. They're cached under `detections:<id>` with a TTL ≤ `DETECTIONS_TTL_SECONDS`.
- `test_detect_each_call_gets_a_fresh_detection_id`
- `test_detect_non_image_is_422` - non-image bytes return 422, and YOLO is never called.
- `test_detect_truncated_image_is_422` - a valid header with a cut-off body (plain `OSError` from `image.load()`) also returns 422, not 500.
- `test_detect_inference_failure_is_500` - YOLO raising returns 500, and nothing gets cached.
- `test_detect_cache_write_failure_is_503` - a `RedisError` on the cache write returns 503.
- `test_detect_missing_photo_is_422`

`POST /analysis`
- `test_analysis_happy_path_enqueues_selected_holds` - 202. `delay()` gets exactly `select_holds(detections, ids)`, and the idempotency key stores the task id with a TTL.
- `test_analysis_exactly_min_holds_is_accepted` - the `MIN_SELECTED_HOLDS` boundary.
- `test_analysis_bad_selection_is_422_before_touching_redis_or_celery` (parametrized: too few, `[]`, not JSON, not a list, non-int ids) - rejected before any Redis read, task, or key reservation.
- `test_analysis_unknown_detection_id_is_410`
- `test_analysis_unknown_hold_id_is_422_and_reserves_nothing`
- `test_analysis_missing_required_field_is_422` (parametrized over the header and both form fields).
- `test_analysis_key_still_processing_is_409` - real fake-redis state, not mocked `get`/`set`.
- `test_analysis_completed_key_replays_task_id` - no new task created.
- `test_analysis_same_key_twice_sequentially_replays`
- `test_analysis_task_creation_failure_cleans_up_idempotency_key` - if `delay()` raises, the reservation is deleted rather than blocking retries for 24h.

`GET /analysis/{task_id}`
- `test_get_analysis_failure` - returns the error string.
- `test_get_analysis_in_progress_states` (parametrized `PENDING`/`STARTED`/`RETRY`) - only `{task_id, status}` is returned.
- `test_get_analysis_success_returns_steps` - returns the `{steps: [...]}` result as-is.

#### test_detection.py

Tests `detection.py`. `run_detection()` runs against a stubbed model: `detection.get_model` is patched to return a fake whose `predict()` yields `masks.data` / `boxes.cls|conf|xywhn` as torch tensors, plus `orig_shape` and `names`. This means no weights are needed.

- `_polygon_centroid`: unit square; area-weighted (not vertex-mean) centroid; winding-order independence; degenerate inputs (1–2 points, collinear) fall back to the mean; empty input raises.
- `select_holds`: groups by class in selection order; duplicate ids are kept; empty selection gives `{}`; an unknown id raises `UnknownHoldIdError` (a `ValueError`).
- `_mask_to_polygon`: a rectangle mask gives a normalized outline matching its bounds; an empty mask gives `(0, 2)`; with two blobs, only the larger is kept (the "massive line" regression).
- `run_detection`: output is JSON-serializable with the documented keys and `size = sqrt(w*h)`; per-class `CONFIDENCE_FLOORS` apply (unknown classes use the max floor) and ids are re-indexed after filtering; empty masks are skipped without consuming an id; `masks is None` gives `[]`; input is thumbnailed to `MAX_INPUT_SIDE` without mutating the caller's image; `predict()` gets `PREDICT_KWARGS` + `conf=min(floors)`.
- `test_get_model_loads_once_and_caches`
- `test_run_detection_with_real_model` (`slow`) - runs the real `best.pt` on the sample wall photo in `mobile/.../assets/images/` and checks the result is well-formed. It's skipped if the weights or the photo are missing.

#### test_worker.py

Tests `worker.py` with no network. `get_anthropic_client` is patched to a `MagicMock`.

- `build_coaching_payload`: holds become `{x, y}` objects grouped by class in the user message (tuples and Celery's JSON lists give the same result); model / `max_tokens` / system prompt / `output_config.format` are checked; model override works.
- `test_output_schema_matches_mobile_contract` - `steps[].{step_number, instruction, reason}` matches what `getClimbAnalysis.tsx` reads.
- `call_coaching_llm`: success returns the parsed dict (and non-text blocks are skipped); refusal (with/without `stop_details`), `max_tokens` truncation, and invalid/empty JSON each raise `RuntimeError`; every SDK error (missing credentials `TypeError`, 401, 429 with/without `retry-after`, 5xx, connection error) maps to its own `RuntimeError` message with the original as `__cause__`.
- `analysis` task: builds the payload and returns the LLM output. It's registered as `worker.analysis`.
- `test_anthropic_client_is_created_once_and_cached`
- `REDIS_URL` wiring for broker/backend (kept last in the file because it reloads the module).

#### test_concurrency.py

Fires 300 concurrent requests in-process (`httpx` + `ASGITransport`, fake Redis, mocked Celery task).

- `test_concurrent_requests_same_key_create_exactly_one_task` - 300 `/analysis` requests racing the *same* Idempotency-Key still create exactly 1 task. Every response is 202 (same task id) or 409.
- `test_concurrent_requests_distinct_keys_all_create_tasks` - 300 distinct keys all succeed independently.
- `test_concurrent_detects_each_get_their_own_cached_detection_id` - 300 concurrent `/detect` calls give 300 unique, cached detection ids.

#### test_redis_client.py

Tests `redis_client.py`'s environment wiring. It needs no real Redis connection, because `Redis.from_url()` doesn't connect eagerly.

- `test_default_redis_url_when_env_unset` / `test_redis_url_read_from_env`
- `test_client_decode_responses_enabled` - this is what makes the `"processing"` comparison in `main.py` work.
- `test_client_connects_to_configured_host_and_port`

### coverage.xml

Generated by `pytest-cov` (`--cov-report=xml`) and uploaded as a build
artifact. It is not a record of whether tests passed. `coverage.xml`
answers a different question: which lines in `main.py` / `detection.py` /
`worker.py` / `redis_client.py` did the tests actually execute at least once.
100% coverage means no line went untouched.

NOTE: setup threshold in future

## load-test.yml

### Summary

**Out of date:** `simulate_load.py` still POSTs a photo straight to `/analysis`, which the current API rejects (it now expects `detection_id` + `selected_hold_ids` from a prior `/detect`). It needs porting to `/detect` → `/analysis` → poll before its numbers mean anything.

This workflow is manual-only (`workflow_dispatch`). There is no schedule or PR trigger: a 2 vCPU GitHub runner hosting the whole stack mostly measures its own resource contention (see the comment at the top of `load-test.yml`). It simulates N users (default 200) going end to end against a real instance of the app started with docker-compose.

When triggered, the runner installs dependencies, starts the app via `docker compose up -d redis api worker`, waits for the API to be ready, and runs `uv run python load_test/simulate_load.py` with the duration and user-count args. When it finishes, it tears the stack down with `docker compose down -v`.

Once the run completes, the logs are uploaded to GitHub Actions.

### Logs

Logs are saved to GitHub -> Actions -> find the run -> Artifacts. They are kept for 30 days.


### simulate_load.py

Not a pytest file. It has no `test_*` functions; it's a script you
run directly against a live server. Breakdown by function/class:

**`Sample`** - one HTTP call's outcome: which endpoint, how long it took,
the status code, and an error string if the request itself failed
(connection refused, timeout, etc).

**`Results`** - collects every `Sample` from the whole run.
- `summary()` groups samples by endpoint and prints request count, error
  count, and p50/p95/p99/max latency per endpoint.
- `to_csv()` dumps every raw sample to a file (`--csv` flag) for anything
  the printed summary doesn't cover.

**`_percentile()`** - plain linear percentile calc on a
sorted list. No numpy dependency for one function.

**`_timed_request()`** - wraps a single HTTP call. It times the call and turns a
network-level failure (`httpx.HTTPError`) into a `Sample` with
`status_code=0` and an `error` string instead of raising, so one dropped
connection doesn't kill the whole run.

**`virtual_user()`** - one simulated user's behavior, looped until
`stop_at`: POST a fake photo with a fresh Idempotency-Key, then poll
GET until the task leaves `PENDING`/`STARTED`/`RETRY` or 10s passes.
Note: `stop_at` is only checked before starting a *new* POST+poll cycle.
A cycle already in progress can run past it (up to ~10s tail).

**`run()`** - creates one `virtual_user()` task per `--users`, staggering
their start times across `--ramp-up` seconds instead of launching them all
at once, then waits for all of them to finish.

**`main()`** - CLI entrypoint. It parses args, runs `run()`, prints the
summary, optionally writes the CSV, and exits non-zero if the overall
error rate is above 1% (so a CI run of this can fail the job).
