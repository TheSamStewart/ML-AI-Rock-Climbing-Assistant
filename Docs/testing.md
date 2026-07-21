# Testing the API

## Tools
- `pytest` (installed as a dev dependency, run via `uv run pytest`)
- `fastapi.testclient.TestClient` (wraps `httpx`, no running server needed) — add `httpx` as a dev dependency if it isn't already pulled in transitively

## Approach
Endpoints like `/add` call `add.delay(...)` to enqueue a Celery task. Tests should not depend on a live Redis/worker, so mock the Celery call at the boundary:

```python
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_add_numbers():
    with patch("main.add.delay") as mock_delay:
        mock_delay.return_value.id = "fake-task-id"
        response = client.get("/add", params={"x": 2, "y": 3})

        assert response.status_code == 200
        assert response.json()["task_id"] == "fake-task-id"
        mock_delay.assert_called_once_with(2, 3)
```

## What to cover
- **Happy path** — valid params return 200 and a `task_id`.
- **Validation** — invalid/missing query params return 422 (FastAPI handles this automatically via type hints).
- **Celery call shape** — `delay()` is called with the right args (catches wiring bugs without needing Redis).

## Integration testing (optional, separate tier)
To verify Celery/Redis actually process a task end-to-end, run a real Redis (e.g. via `docker compose up redis`) and a worker, then assert on task state (`task.get(timeout=...)`) instead of mocking `delay`. Keep these in a separate test file/marker so they can be skipped when Redis isn't available.

## Running tests
```bash
uv run pytest
```
