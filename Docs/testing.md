# Testing

## Backend Testing

## Directory
```
├── backend/
│   ├── main.py                       # FastAPI app: POST /analysis, GET /analysis/{task_id}
│   ├── worker.py                     # Celery app (currently a stub)
│   ├── redis_client.py               # async Redis client for idempotency-key reservations
│   ├── conftest.py                   # configures fake application for testing (fake redis, mocked Celery task)
│   ├── test_main.py                  # pytest for the API endpoints
│   ├── test_redis_client.py          # pytest for redis_client.py's env-var wiring
│   ├── test_worker.py                # pytest for the Celery task + broker/backend wiring
│   ├── test_concurrency.py           # pytest: idempotency race-safety under concurrent requests
│   └── load_test/
│       └── simulate_load.py          # async load-test script against a real stack (not part of pytest)

```

## pytest.yml

### Summary

Automatic unit testing for the backend, automatically runs upon PR.

This is the config file/workflow file for GitHub Action.

Upon PR the: dependencies are install via `uv sync --all-extras --dev`, pytest is ran via `uv run python -m pytest -v --cov --cov-report=term-missing --cov-report=xml`, the coverage report is uploaded as an artifact to Github Actions.

### Test Files

#### test_main.py

Tests the FastAPI routes in `main.py` - `POST /analysis` and
`GET /analysis/{task_id}` - against fake Redis + a mocked Celery task.

- `test_post_already_processing` - a key mid-reservation returns 409.
- `test_post_image` - happy path: valid upload returns 202 + a task_id.
- `test_get_analysis_failure` - `FAILURE` state returns the error string.
- `test_get_analysis_pending` - `PENDING` state, no `result`/`error` keys.
- `test_post_missing_idempotency_key_header_is_422` - the header is
  required; omitting it fails FastAPI's own validation.
- `test_post_replays_task_id_for_completed_key` - a key already holding a
  finished task_id replays it instead of creating a new task.
- `test_post_invalid_taps_json_defaults_to_empty_list` - malformed `taps`
  JSON is swallowed, not a 500.
- `test_post_valid_taps_json_is_parsed_and_forwarded` - valid `taps` JSON
  is parsed and passed through to the Celery task unchanged.
- `test_post_no_taps_field_defaults_to_empty_list` - omitting `taps`
  entirely behaves the same as invalid JSON.
- `test_post_forwards_filename_and_content_type` - the uploaded file's
  name/content-type reach the task as-is.
- `test_post_sets_idempotency_reservation_with_ttl` - the reservation key
  is written with a TTL, not left to live forever.
- `test_post_task_creation_failure_cleans_up_idempotency_key` - if
  `delay()` raises, the reservation is deleted rather than blocking retries
  for the full 24h TTL.
- `test_get_analysis_success_returns_result` - terminal success state
  returns the task's `result`.
- `test_get_analysis_in_progress_states` (parametrized `STARTED`/`RETRY`)
  - both in-progress states behave like `PENDING`.

#### test_redis_client.py

Tests `redis_client.py`'s environment wiring - no real Redis connection,
since `Redis.from_url()` doesn't connect eagerly.

- `test_default_redis_url_when_env_unset` - falls back to
  `redis://localhost:6379/0` when `REDIS_URL` isn't set.
- `test_redis_url_read_from_env` - a custom `REDIS_URL` is picked up.
- `test_client_decode_responses_enabled` - `decode_responses=True` is set,
  which is what makes the `"processing"` string comparisons in `main.py`
  work at all.
- `test_client_connects_to_configured_host_and_port` - the URL is parsed
  into the right host/port/db on the client's connection pool.

#### test_worker.py

Tests the Celery `analysis` task in `worker.py`, called directly as a
plain function (no running worker needed), plus the same env-var wiring
as `redis_client.py`.

- `test_analysis_concatenates_filename_and_content_type` - the stub's
  actual (only) behavior: returns `filename + content_type`.
- `test_analysis_default_taps_is_none_and_unused` - calling without
  `taps` doesn't error.
- `test_analysis_accepts_taps_without_using_them` - passing `taps`
  doesn't change the result (unused by the current stub).
- `test_analysis_handles_empty_strings` / `test_analysis_handles_unicode_filename`
  - basic input-shape edge cases.
- `test_analysis_is_registered_as_a_celery_task` - the `@app.task`
  decorator actually registered it in `app.tasks`.
- `test_analysis_task_name_matches_module_path` - it's registered under
  the expected name, `worker.analysis`.
- `test_default_broker_and_backend_when_env_unset` /
  `test_broker_and_backend_read_from_env` - same `REDIS_URL` wiring check
  as `redis_client.py`, since both must agree.

#### test_concurrency.py

Fires 300 concurrent requests in-process (`httpx` + `ASGITransport`, fake
Redis, mocked Celery task) to prove the idempotency guard actually holds
under real concurrency, not just sequential calls.

- `test_concurrent_requests_same_key_create_exactly_one_task` - 300
  requests racing the *same* Idempotency-Key still create exactly 1 task.
- `test_concurrent_requests_distinct_keys_all_create_tasks` - 300
  requests with distinct keys all succeed independently (nothing gets
  serialized or dropped).

### coverage.xml

Generated by `pytest-cov` (`--cov-report=xml`) and uploaded as a build
artifact. Not a record of whether tests passed. `coverage.xml`
answers a different question: which lines in `main.py` / `worker.py` /
`redis_client.py` did the tests actually execute at least once. 100%
coverage means no line went untouched.

NOTE: setup threshold in future

## load-test.yml

### Summary

This test runs every Monday at 6am and tests 200 real users using the system end to end (POST -> poll GET) against a real instantiation of our application via docker-compose.

This is the config/worflow file for Github Actions. This file runs automatically but can also be triggered manually (see `worflow_dispatch`). 

At 6am on Monday the VM will: install dependencies, instantiate our0 application via `docker-compose up -d redis api worker`, wait for the API to be ready, run the tests via `uv run python load_test/simulate_load.py` passing in our args like max test duration and amount of users to the `simulate_load.py` script. Upon completion we tear down the application stack with `docker compose down -v`.

Once the testing is completed the logs are upladed to Github actions.

### Logs 

Logs are saved to Github -> Actions  -> find the run -> Artifacts, they are held for 30 days.


### simulate_load.py

Not a pytest file - there's no `test_*` functions here, it's a script you
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

**`_timed_request()`** - wraps a single HTTP call: times it, and turns a
network-level failure (`httpx.HTTPError`) into a `Sample` with
`status_code=0` and an `error` string instead of raising - so one dropped
connection doesn't kill the whole run.

**`virtual_user()`** - one simulated user's behavior, looped until
`stop_at`: POST a fake photo with a fresh Idempotency-Key, then poll
GET until the task leaves `PENDING`/`STARTED`/`RETRY` or 10s passes.
Note: `stop_at` is only checked before starting a *new* POST+poll cycle -
a cycle already in progress can run past it (up to ~10s tail).

**`run()`** - creates one `virtual_user()` task per `--users`, staggering
their start times across `--ramp-up` seconds instead of launching them all
at once, then waits for all of them to finish.

**`main()`** - CLI entrypoint: parses args, runs `run()`, prints the
summary, optionally writes the CSV, and exits non-zero if the overall
error rate is above 1% (so a CI run of this can fail the job).
