import importlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

import worker as worker_module
from worker import (
    COACHING_OUTPUT_SCHEMA,
    COACHING_SYSTEM_PROMPT,
    analysis,
    build_coaching_payload,
    call_coaching_llm,
)

# No real Claude calls: get_anthropic_client is patched to a MagicMock whose
# messages.create returns hand-built response objects, or raises real SDK
# exception types.

HOLDS = {"HOLD": [(0.2, 0.9), (0.4, 0.6)], "VOLUME": [(0.5, 0.4)]}

STEPS = {"steps": [{"step_number": 1, "instruction": "Start matched on the low hold.", "reason": "Stable start."}]}


# --- build_coaching_payload ---


def test_payload_groups_holds_as_xy_objects_in_user_content():
    payload = build_coaching_payload(HOLDS)

    [message] = payload["messages"]
    assert message["role"] == "user"
    route_json = message["content"].split("\n", 1)[1]
    assert json.loads(route_json) == {
        "HOLD": [{"x": 0.2, "y": 0.9}, {"x": 0.4, "y": 0.6}],
        "VOLUME": [{"x": 0.5, "y": 0.4}],
    }


def test_payload_accepts_lists_as_celery_delivers_them():
    # Celery's JSON serializer turns the (x, y) tuples into lists in transit.
    as_lists = {k: [list(c) for c in v] for k, v in HOLDS.items()}

    assert build_coaching_payload(as_lists) == build_coaching_payload(HOLDS)


def test_payload_request_settings():
    payload = build_coaching_payload(HOLDS)

    assert payload["model"] == "claude-opus-5"
    assert payload["max_tokens"] == 4096
    assert payload["system"] == COACHING_SYSTEM_PROMPT
    assert payload["output_config"]["format"] == {"type": "json_schema", "schema": COACHING_OUTPUT_SCHEMA}


def test_payload_model_override():
    assert build_coaching_payload(HOLDS, model="claude-sonnet-5-5")["model"] == "claude-sonnet-5-5"


def test_output_schema_matches_mobile_contract():
    # getClimbAnalysis.tsx maps over result.steps[].{step_number, instruction, reason}.
    step = COACHING_OUTPUT_SCHEMA["properties"]["steps"]["items"]
    assert COACHING_OUTPUT_SCHEMA["required"] == ["steps"]
    assert set(step["required"]) == {"step_number", "instruction", "reason"}
    assert step["properties"]["step_number"]["type"] == "integer"


# --- call_coaching_llm ---


def _response(text=None, stop_reason="end_turn", stop_details=None, content=None):
    if content is None:
        content = [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(stop_reason=stop_reason, stop_details=stop_details, content=content)


@pytest.fixture
def mock_client():
    client = MagicMock()
    with patch("worker.get_anthropic_client", return_value=client):
        yield client


def test_call_returns_parsed_steps(mock_client):
    mock_client.messages.create.return_value = _response(json.dumps(STEPS))
    payload = build_coaching_payload(HOLDS)

    assert call_coaching_llm(payload) == STEPS
    mock_client.messages.create.assert_called_once_with(**payload)


def test_call_skips_non_text_blocks(mock_client):
    mock_client.messages.create.return_value = _response(
        content=[SimpleNamespace(type="thinking", thinking="..."), SimpleNamespace(type="text", text=json.dumps(STEPS))]
    )

    assert call_coaching_llm({}) == STEPS


@pytest.mark.parametrize("stop_details, category", [(SimpleNamespace(category="cyber"), "cyber"), (None, "None")])
def test_call_refusal_raises(mock_client, stop_details, category):
    mock_client.messages.create.return_value = _response("", stop_reason="refusal", stop_details=stop_details)

    with pytest.raises(RuntimeError, match=f"declined to respond \\(category: {category}\\)"):
        call_coaching_llm({})


def test_call_truncated_output_raises(mock_client):
    mock_client.messages.create.return_value = _response('{"steps": [', stop_reason="max_tokens")

    with pytest.raises(RuntimeError, match="truncated"):
        call_coaching_llm({})


@pytest.mark.parametrize("content", [[SimpleNamespace(type="text", text="not json")], []])
def test_call_invalid_json_raises(mock_client, content):
    mock_client.messages.create.return_value = _response(content=content)

    with pytest.raises(RuntimeError, match="invalid JSON") as exc_info:
        call_coaching_llm({})

    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status, headers=None):
    return cls(f"{status} error", response=httpx.Response(status, headers=headers, request=_REQUEST), body=None)


@pytest.mark.parametrize(
    "error, message",
    [
        (TypeError("Could not resolve authentication method"), "no credentials configured"),
        (_status_error(anthropic.AuthenticationError, 401), "authentication failed"),
        (_status_error(anthropic.RateLimitError, 429, {"retry-after": "30"}), r"rate limited \(retry after 30s\)"),
        (_status_error(anthropic.RateLimitError, 429), r"rate limited \(retry after unknowns\)"),
        (_status_error(anthropic.InternalServerError, 500), "Anthropic API error 500"),
        (anthropic.APIConnectionError(request=_REQUEST), "network error"),
    ],
)
def test_call_maps_sdk_errors_to_runtime_error(mock_client, error, message):
    mock_client.messages.create.side_effect = error

    with pytest.raises(RuntimeError, match=message) as exc_info:
        call_coaching_llm({})

    assert exc_info.value.__cause__ is error


# --- analysis task ---


def test_analysis_task_builds_payload_and_returns_llm_output():
    with patch("worker.call_coaching_llm", return_value=STEPS) as mock_call:
        result = analysis(HOLDS)

    assert result == STEPS
    mock_call.assert_called_once_with(build_coaching_payload(HOLDS))


def test_analysis_is_registered_as_a_celery_task():
    assert "worker.analysis" in worker_module.app.tasks
    assert analysis.name == "worker.analysis"


# --- get_anthropic_client ---


def test_anthropic_client_is_created_once_and_cached():
    saved = worker_module._anthropic_client
    worker_module._anthropic_client = None
    try:
        with patch("worker.anthropic.Anthropic") as mock_cls:
            first = worker_module.get_anthropic_client()
            second = worker_module.get_anthropic_client()
    finally:
        worker_module._anthropic_client = saved

    mock_cls.assert_called_once_with()
    assert first is second


# --- REDIS_URL wiring (kept last: these reload the module) ---


def _reload_with_env(monkeypatch, env_value):
    if env_value is None:
        monkeypatch.delenv("REDIS_URL", raising=False)
    else:
        monkeypatch.setenv("REDIS_URL", env_value)

    return importlib.reload(worker_module)


def test_default_broker_and_backend_when_env_unset(monkeypatch):
    module = _reload_with_env(monkeypatch, None)

    assert module.app.conf.broker_url == "redis://localhost:6379/0"
    assert module.app.conf.result_backend == "redis://localhost:6379/0"


def test_broker_and_backend_read_from_env(monkeypatch):
    module = _reload_with_env(monkeypatch, "redis://some-host:6380/3")

    assert module.app.conf.broker_url == "redis://some-host:6380/3"
    assert module.app.conf.result_backend == "redis://some-host:6380/3"


def teardown_module(module):
    importlib.reload(worker_module)
