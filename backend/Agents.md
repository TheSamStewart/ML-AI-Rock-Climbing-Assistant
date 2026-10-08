# Backend Testing Plan

Scope: `backend/` — a FastAPI app (`main.py`) with `POST /detect` (YOLO via
`detection.py`, detections cached in Redis) and `POST /analysis` (resolves the
user's selected hold ids against that cache, hands the hold dict to a Celery
task in `worker.py` that calls Claude). `redis_client.py` is the API's own
async client (idempotency keys + detections cache); Celery has its own Redis
connection for broker/result-backend.

## 1–2. Per-file coverage

The per-test breakdown lives in [Docs/testing.md](../Docs/testing.md) — keep
that as the single source of truth instead of duplicating it here. Principles
that apply across files:

- No real infra in pytest: `fakeredis` (with `decode_responses=True`, same as
  the real client), mocked `analysis_task.delay`, mocked Anthropic client,
  stubbed YOLO model (`detection.get_model` patched to return an
  ultralytics-shaped fake result).
- The one real-model test is marked `slow` and skips when `models/best.pt`
  (gitignored) is absent, so CI never runs it.
- Validation order in `/analysis` matters and is tested: bad/too-few
  selections are rejected before any Redis read; unknown detection/hold ids
  are rejected before an idempotency key is reserved.
- Env-var wiring (`REDIS_URL`) is tested via `importlib.reload` under
  `monkeypatch`; those tests run last in their file since they rebind
  module globals.

## 3. Concurrency correctness (the part that matters at 10,000 users)

At load, many requests can arrive for the same `Idempotency-Key` before the
first one finishes reserving it (retries from a flaky mobile connection,
double-taps, etc). The correctness property is: **exactly one Celery task
gets created per key**, no matter how many requests race for it.

`test_concurrency.py` proves this in-process: an `httpx.AsyncClient` against
the app via `ASGITransport`, `fakeredis`'s async client standing in for
Redis, and a few hundred coroutines launched together with
`asyncio.gather` against the *same* key. Assertion: `analysis_task.delay`
was called exactly once; every response is either the 202 winner or a 409/
replay. A second test does the same with distinct keys to confirm normal
concurrent traffic isn't serialized or dropped.

This is deliberately not "spawn 10,000 tasks" — that number doesn't change
what's being proven (SET NX is atomic per-call regardless of concurrency
level); a few hundred concurrent coroutines already exercises every
interleaving that matters. It runs in the normal `pytest` suite, no
external services required.

## 4. Actual load testing (real network, real Redis, real Celery worker)

This needs a running stack, so it's separate from `pytest` by necessity —
correctness tests use fakes and mocks on purpose (fast, deterministic, no
infra); load tests need the real thing.

`load_test/simulate_load.py` is a small `httpx`-async script (no Locust —
Locust pulls in `gevent`, which regularly lags behind brand-new CPython
releases and this project pins `>=3.14`; a dependency-free script avoids
that landmine). It:
- ramps up to a target concurrency of simulated users,
- has each virtual user POST a fake image with a unique idempotency key,
  poll `GET /analysis/{task_id}` until terminal, then repeat for the
  duration,
- reports throughput, error rate, and p50/p95/p99 latency for both
  endpoints.

Run it against `docker-compose up redis api worker` locally, or against a
staging deployment for a real 10,000-user number. **A GitHub-hosted runner
(2 vCPU) cannot honestly produce 10,000 concurrent connections** — the CI
job (`load-test.yml`, manual/scheduled, not on every PR) runs it at a
smoke scale (default 200 concurrent, configurable via workflow input) purely
as a regression signal: did this change measurably worsen latency/error
rate at the scale CI *can* generate. Treat a clean CI load-test run as
"didn't regress," not as "validated for 10,000 users."

### Capacity notes for 10,000 active users (not concurrent — see below)
"10,000 active users" almost certainly means 10,000 people with the app
installed who use it occasionally, not 10,000 simultaneous uploads. Rough
sizing, worth revisiting once there's real usage data:
- Assume a generous burst of 2–5% concurrently active → ~200–500 concurrent
  requests at peak, which is the order of magnitude both the concurrency
  test and the default CI load-test smoke run target.
- `redis.asyncio.Redis.from_url` uses a connection pool; default max size
  should be set explicitly (`max_connections=`) once real concurrency
  numbers exist, instead of relying on the library default.
- `uvicorn` should run with multiple workers (`--workers`) in production;
  `docker-compose.yml` currently runs a single `--reload` dev process.
- Celery worker concurrency/autoscale (`-c`/`--autoscale`) needs to be sized
  to the analysis task's actual runtime once it's more than the current
  stub — right now it's instant, so this can't be sized meaningfully yet.
- None of this is implemented as code changes here — flagging it because
  "account for 10,000 users" is a capacity-planning question as much as a
  testing one, and the honest answer is "the stub task makes real capacity
  numbers meaningless until it does real work."

## 5. CI (`.github/workflows/`)

- `pytest.yml` (existing, extended): now runs the full suite including
  `test_concurrency.py` with coverage (`pytest-cov`), uploads the coverage
  report as a build artifact. No new services needed — everything here
  uses `fakeredis` and mocks.
- `load-test.yml` (new): `workflow_dispatch` (with a `users` input,
  default 200) and a weekly schedule. Brings up `redis`, `api`, `worker`
  via `docker-compose`, waits for health, runs `simulate_load.py` against
  `localhost:8000`, uploads the results as an artifact, tears the stack
  down. Not required on PRs — it's a manual/scheduled signal, not a merge
  gate, until there's a real perf budget to gate on.

## 6. Known limitations / explicitly out of scope

- No test hits a real Redis or a real Celery broker — everything is
  `fakeredis`/mocked in the pytest suite by design (fast, deterministic,
  no infra dependency in CI).
- No test calls the real Claude API, and the real YOLO model only runs in
  the opt-in `slow` smoke test — prompt *quality* and detection *accuracy*
  aren't covered by pytest, only the wiring/contract around them.
- Tap-to-hold matching now happens client-side (`utils/holdMatching.ts` in
  the mobile app), so it has no backend tests; the backend only does the
  id lookup (`detection.select_holds`).
- `load_test/simulate_load.py` still targets the old photo-upload
  `/analysis` contract and needs porting to `/detect` → `/analysis`.
- No auth exists yet (noted in `main.py`'s own comments), so idempotency
  keys are global, not per-user — tests reflect that as-is.
