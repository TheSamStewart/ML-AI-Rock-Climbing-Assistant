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
    CENTROID_ALLOWANCE_CM,
    COACHING_SYSTEM_PROMPT,
    DISTANCE_MARGIN_PCT,
    DISTANCE_MARGIN_PCT_BY_TIER,
    analysis,
    build_coaching_payload,
    build_route_data,
    call_coaching_llm,
)

# No real Claude calls: get_anthropic_client is patched to a MagicMock whose
# messages.create returns hand-built response objects, or raises real SDK
# exception types.

# Route as main.py hands it to analysis_task.delay(): flat holds in pick
# order, the matching N x N grid-unit sub-matrix, wall length in grid units,
# and the user's bolt spacing. Ids are deliberately not 0..N-1 so a test
# that confuses ids with positions fails.
HOLD_LIST = [
    {"id": 7, "class_name": "HOLD", "x": 0.2, "y": 0.9},
    {"id": 3, "class_name": "HOLD", "x": 0.4, "y": 0.6},
    {"id": 5, "class_name": "VOLUME", "x": 0.5, "y": 0.4},
]

ROUTE = {
    "holds": HOLD_LIST,
    "distances_units": [
        [0.0, 1.5, 2.25],
        [1.5, 0.0, 1.23456],
        [2.25, 1.23456, 0.0],
    ],
    # Slice 8: picked sub-matrix of tiers, N strings of N chars, pick order.
    # Pairs: (7,3) A, (7,5) C, (3,5) A.
    "tiers": ["AAC", "AAA", "CAA"],
    "wall_length_units": 20.0,
    "bolt_spacing_cm": 20.0,
}

STEPS = {"steps": [{"step_number": 1, "instruction": "Start matched on the low hold.", "reason": "Stable start."}]}


def _route(**overrides):
    route = json.loads(json.dumps(ROUTE))
    route.update(overrides)
    return route


PCT_BY_TIER = {"A": 6, "C": 14}


def _margin(cm, tier="A"):
    # Spec (Outputs, slice 8): margin_cm = cm x margin_pct_by_tier[tier]/100
    # + centroid_allowance_cm (5), 1 decimal, from the already-rounded cm.
    return round(cm * PCT_BY_TIER[tier] / 100 + 5, 1)


def _route_of_size(n, bolt_spacing_cm=20.0):
    holds = [{"id": 100 + i, "class_name": "HOLD", "x": i / 10, "y": 0.5} for i in range(n)]
    d = [[abs(i - j) * 0.5 for j in range(n)] for i in range(n)]
    return {"holds": holds, "distances_units": d, "wall_length_units": 20.0, "bolt_spacing_cm": bolt_spacing_cm}


# --- build_route_data ---


def test_route_data_top_level_shape():
    data = build_route_data(_route())

    assert set(data) == {"holds", "distances_cm", "wall_length_cm", "accuracy"}
    assert data["holds"] == HOLD_LIST
    json.dumps(data)


def test_route_data_distances_cm_every_pair_in_pick_order_with_ids():
    data = build_route_data(_route())

    # cm = units * 20, rounded to 1 decimal: 1.23456 * 20 = 24.6912 -> 24.7
    # margin_cm = cm * pct_by_tier[tier] + 5 cm, 1 decimal:
    # 30 A -> 6.8, 45 C -> 6.3 + 5 = 11.3, 24.7 A -> 6.482 -> 6.5
    assert data["distances_cm"] == [
        {"from": 7, "to": 3, "cm": 30.0, "tier": "A", "margin_cm": 6.8},
        {"from": 7, "to": 5, "cm": 45.0, "tier": "C", "margin_cm": 11.3},
        {"from": 3, "to": 5, "cm": 24.7, "tier": "A", "margin_cm": 6.5},
    ]


@pytest.mark.parametrize("n", [2, 3, 4, 5, 8])
def test_route_data_pair_count_is_n_choose_2(n):
    data = build_route_data(_route_of_size(n))

    assert len(data["distances_cm"]) == n * (n - 1) // 2
    pairs = {frozenset((e["from"], e["to"])) for e in data["distances_cm"]}
    assert len(pairs) == n * (n - 1) // 2
    assert all(e["from"] != e["to"] for e in data["distances_cm"])


def test_route_data_repeated_id_is_paired_only_at_first_occurrence():
    holds = [
        {"id": 7, "class_name": "HOLD", "x": 0.2, "y": 0.9},
        {"id": 3, "class_name": "HOLD", "x": 0.4, "y": 0.6},
        {"id": 7, "class_name": "HOLD", "x": 0.2, "y": 0.9},
        {"id": 5, "class_name": "VOLUME", "x": 0.5, "y": 0.4},
    ]
    d = [
        [0.0, 1.0, 0.0, 2.0],
        [1.0, 0.0, 1.0, 3.0],
        [0.0, 1.0, 0.0, 2.0],
        [2.0, 3.0, 2.0, 0.0],
    ]

    # Tier of each kept pair read at the first occurrence: (7,3) = [0][1] C,
    # (7,5) = [0][3] A, (3,5) = [1][3] C. The duplicate row/column is consistent.
    tiers = ["ACAA", "CACC", "ACAA", "ACAA"]

    data = build_route_data({"holds": holds, "distances_units": d, "tiers": tiers, "wall_length_units": 20.0, "bolt_spacing_cm": 10.0})

    assert data["holds"] == holds
    assert data["distances_cm"] == [
        {"from": 7, "to": 3, "cm": 10.0, "tier": "C", "margin_cm": 6.4},
        {"from": 7, "to": 5, "cm": 20.0, "tier": "A", "margin_cm": 6.2},
        {"from": 3, "to": 5, "cm": 30.0, "tier": "C", "margin_cm": 9.2},
    ]


@pytest.mark.parametrize("bolt_spacing_cm", [10.0, 12.5, 20.0, 50.0])
def test_route_data_cm_is_units_times_bolt_spacing(bolt_spacing_cm):
    data = build_route_data(_route(bolt_spacing_cm=bolt_spacing_cm))

    units = {(7, 3): 1.5, (7, 5): 2.25, (3, 5): 1.23456}
    for e in data["distances_cm"]:
        assert e["cm"] == round(units[(e["from"], e["to"])] * bolt_spacing_cm, 1)
    assert data["wall_length_cm"] == round(20.0 * bolt_spacing_cm, 1)


@pytest.mark.parametrize(
    "wall_length_units, bolt_spacing_cm, expected",
    [
        (20.0, 12.34, 246.8),     # float product 246.79999... -> 246.8
        (20.0, 20.0, 400.0),
        (13.37, 20.0, 267.4),     # 267.4000...
        (12.345, 10.0, 123.5),    # 123.45000... -> 123.5
        (7.777, 33.3, 259.0),     # 258.9741 -> 259.0
        (1.23456, 20.0, 24.7),    # 24.6912 -> 24.7, same rule as distances_cm
    ],
)
def test_route_data_wall_length_cm_rounded_to_one_decimal(wall_length_units, bolt_spacing_cm, expected):
    # Human decision (handover, slice 2 Q): wall_length_cm = round(units * spacing, 1),
    # the same rule as distances_cm.
    data = build_route_data(_route(wall_length_units=wall_length_units, bolt_spacing_cm=bolt_spacing_cm))

    assert data["wall_length_cm"] == round(wall_length_units * bolt_spacing_cm, 1)
    assert data["wall_length_cm"] == expected
    assert isinstance(data["wall_length_cm"], float)


def test_route_data_changing_bolt_spacing_rescales_distances():
    small = build_route_data(_route(bolt_spacing_cm=10.0))
    large = build_route_data(_route(bolt_spacing_cm=40.0))

    for a, b in zip(small["distances_cm"], large["distances_cm"]):
        assert (a["from"], a["to"]) == (b["from"], b["to"])
        assert b["cm"] == pytest.approx(4 * a["cm"], abs=0.25)  # each value rounded to 0.1
        assert a["tier"] == b["tier"]
        # Only the percentage part scales; the 5 cm centroid allowance is fixed.
        assert b["margin_cm"] - 5 == pytest.approx(4 * (a["margin_cm"] - 5), abs=0.45)
        assert b["margin_cm"] == pytest.approx(_margin(b["cm"], b["tier"]), abs=0.1)
    assert small["wall_length_cm"] == 200.0
    assert large["wall_length_cm"] == 800.0


def test_route_data_distances_none_when_units_none():
    data = build_route_data(_route(distances_units=None))

    assert data["distances_cm"] is None
    assert data["holds"] == HOLD_LIST


def test_route_data_wall_length_none_when_units_none():
    data = build_route_data(_route(wall_length_units=None))

    assert data["wall_length_cm"] is None
    assert data["distances_cm"] is not None


def test_derived_margin_constants():
    # Spec, Decisions -> Slice 5 margin: pooled reach-range p95 5.2% rounded up to 6
    # (the wall length keeps it); centroid allowance starts at 5 cm.
    # Slice 8: per-tier margins A 6%, C 14%.
    assert DISTANCE_MARGIN_PCT == 6
    assert CENTROID_ALLOWANCE_CM == 5
    assert DISTANCE_MARGIN_PCT_BY_TIER == {"A": 6, "C": 14}


def test_route_data_accuracy_block():
    accuracy = build_route_data(_route())["accuracy"]

    assert set(accuracy) == {"margin_pct", "margin_pct_by_tier", "centroid_allowance_cm", "applies_to", "guidance"}
    assert accuracy["margin_pct"] == 6
    assert accuracy["margin_pct_by_tier"] == {"A": 6, "C": 14}
    assert accuracy["centroid_allowance_cm"] == 5
    assert isinstance(accuracy["applies_to"], str) and accuracy["applies_to"].strip()
    assert isinstance(accuracy["guidance"], str) and accuracy["guidance"].strip()


def test_route_data_accuracy_guidance_states_both_numbers_and_rule():
    guidance = build_route_data(_route())["accuracy"]["guidance"]
    lower = guidance.lower()

    assert "6%" in guidance
    assert "14%" in guidance
    assert "5 cm" in guidance
    assert "margin_cm" in guidance
    assert "tier" in lower
    assert "benefit of the doubt" in lower or "reachable" in lower


def test_route_data_accuracy_applies_to_mentions_wall_length_percentage_only():
    applies_to = build_route_data(_route())["accuracy"]["applies_to"].lower()

    assert "wall" in applies_to and "length" in applies_to
    assert "%" in applies_to or "percent" in applies_to


@pytest.mark.parametrize("tier", ["A", "C"])
@pytest.mark.parametrize(
    "units, bolt_spacing_cm",
    [(1.5, 20.0), (2.25, 20.0), (1.23456, 20.0), (7.777, 33.3), (12.5, 20.0), (0.3, 10.0), (0.0, 20.0)],
)
def test_route_data_margin_cm_formula(units, bolt_spacing_cm, tier):
    d = [[0.0, units], [units, 0.0]]
    holds = HOLD_LIST[:2]
    tiers = ["A" + tier, tier + "A"]
    data = build_route_data({"holds": holds, "distances_units": d, "tiers": tiers, "wall_length_units": 20.0, "bolt_spacing_cm": bolt_spacing_cm})

    [entry] = data["distances_cm"]
    assert set(entry) == {"from", "to", "cm", "tier", "margin_cm"}
    assert entry["tier"] == tier
    assert entry["cm"] == round(units * bolt_spacing_cm, 1)
    # Spec: margin comes from the already-rounded cm.
    assert entry["margin_cm"] == pytest.approx(_margin(entry["cm"], tier), abs=0.1)
    assert isinstance(entry["margin_cm"], float)
    assert entry["margin_cm"] == round(entry["margin_cm"], 1)
    assert entry["margin_cm"] >= 5


def test_route_data_tier_c_margin_is_wider_than_tier_a_for_same_distance():
    def one(tier):
        r = {"holds": HOLD_LIST[:2], "distances_units": [[0.0, 10.0], [10.0, 0.0]], "tiers": ["A" + tier, tier + "A"],
             "wall_length_units": 20.0, "bolt_spacing_cm": 20.0}
        return build_route_data(r)["distances_cm"][0]

    a, c = one("A"), one("C")
    assert a["cm"] == c["cm"] == 200.0
    assert a["margin_cm"] == 17.0   # 200 x 6% + 5
    assert c["margin_cm"] == 33.0   # 200 x 14% + 5


@pytest.mark.parametrize("tiers", [None, "missing"])
def test_route_data_route_without_tiers_is_treated_as_tier_a(tiers):
    # A scale cached before slice 8 has no tiers.
    route = _route()
    if tiers is None:
        route["tiers"] = None
    else:
        del route["tiers"]

    data = build_route_data(route)

    assert [e["tier"] for e in data["distances_cm"]] == ["A", "A", "A"]
    assert [e["margin_cm"] for e in data["distances_cm"]] == [6.8, 7.7, 6.5]
    assert data["accuracy"]["margin_pct_by_tier"] == {"A": 6, "C": 14}
    json.dumps(data)


def test_route_data_wall_length_margin_stays_6_percent_whatever_the_tiers():
    all_c = build_route_data(_route(tiers=["ACC", "CAC", "CCA"]))
    all_a = build_route_data(_route(tiers=["AAA", "AAA", "AAA"]))

    assert all_c["wall_length_cm"] == all_a["wall_length_cm"] == 400.0
    assert all_c["accuracy"]["margin_pct"] == all_a["accuracy"]["margin_pct"] == 6
    assert all_c["accuracy"]["centroid_allowance_cm"] == 5


def test_route_data_every_pair_has_margin_cm():
    data = build_route_data(_route_of_size(6, bolt_spacing_cm=25.0))

    for e in data["distances_cm"]:
        assert e["tier"] == "A"  # no tiers on this route
        assert e["margin_cm"] == pytest.approx(_margin(e["cm"]), abs=0.1)


def test_route_data_wall_length_has_no_centroid_allowance():
    # wall_length_cm is a plain number; the 5 cm allowance is for hold-to-hold distances only.
    data = build_route_data(_route(wall_length_units=20.0, bolt_spacing_cm=20.0))

    assert data["wall_length_cm"] == 400.0


def test_route_data_accuracy_block_present_without_distances():
    data = build_route_data(_route(distances_units=None, wall_length_units=None))

    assert data["distances_cm"] is None  # no entries, so no margin_cm either
    assert data["wall_length_cm"] is None
    accuracy = data["accuracy"]
    assert accuracy["margin_pct"] == DISTANCE_MARGIN_PCT == 6
    assert accuracy["centroid_allowance_cm"] == CENTROID_ALLOWANCE_CM == 5
    assert accuracy["margin_pct_by_tier"] == {"A": 6, "C": 14}
    assert "6%" in accuracy["guidance"] and "14%" in accuracy["guidance"] and "5 cm" in accuracy["guidance"]
    json.dumps(data)


# --- COACHING_SYSTEM_PROMPT ---


def test_system_prompt_explains_distances_and_margin():
    prompt = COACHING_SYSTEM_PROMPT.lower()

    assert "distances_cm" in prompt
    assert "wall_length_cm" in prompt
    assert "margin" in prompt
    assert "tier" in prompt  # slice 8: the prompt explains the confidence tiers
    assert "reachable" in prompt


def test_system_prompt_uses_margin_cm_as_benefit_of_doubt_threshold():
    prompt = COACHING_SYSTEM_PROMPT.lower()

    assert "margin_cm" in prompt
    assert "benefit of the doubt" in prompt
    assert "10%" not in prompt  # the slice 2 placeholder is gone


# --- wall angle (slice 9) ---

PRE_5D_KEYS = {"holds", "distances_cm", "wall_length_cm", "accuracy"}


def test_route_without_angle_fields_gives_exactly_the_pre_5d_payload():
    data = build_route_data(_route())

    assert set(data) == PRE_5D_KEYS
    assert data["holds"] == HOLD_LIST
    assert all("wall_angle_deg" not in h for h in data["holds"])
    assert "wall_angle" not in data


@pytest.mark.parametrize(
    "extra",
    [
        {"angles_deg": None, "angle_source": None, "angle_margin_deg": None},
        {"angles_deg": [None, None, None], "angle_source": "assumed", "angle_margin_deg": 15},
        {"angles_deg": [], "angle_source": "sensor", "angle_margin_deg": 8},
    ],
)
def test_route_with_no_usable_angle_gives_the_pre_5d_payload(extra):
    data = build_route_data(_route(**extra))

    assert data == build_route_data(_route())
    assert "wall_angle" not in data


def test_route_data_wall_angle_deg_per_hold_in_pick_order_and_block():
    data = build_route_data(_route(angles_deg=[24.5, 12.0, 30.1], angle_source="sensor", angle_margin_deg=8))

    assert [h["wall_angle_deg"] for h in data["holds"]] == [24.5, 12.0, 30.1]
    # Everything else about each hold is unchanged.
    for h, original in zip(data["holds"], HOLD_LIST):
        assert {k: v for k, v in h.items() if k != "wall_angle_deg"} == original
    block = data["wall_angle"]
    assert set(block) == {"margin_deg", "source", "guidance"}
    assert block["margin_deg"] == 8
    assert block["source"] == "sensor"
    assert isinstance(block["guidance"], str) and block["guidance"].strip()
    json.dumps(data)


def test_route_data_wall_angle_deg_absent_only_where_hold_has_none():
    data = build_route_data(_route(angles_deg=[24.5, None, 0.0], angle_source="assumed", angle_margin_deg=15))

    h0, h1, h2 = data["holds"]
    assert h0["wall_angle_deg"] == 24.5
    assert "wall_angle_deg" not in h1
    assert h2["wall_angle_deg"] == 0.0  # zero (vertical) is an angle, not "none"
    assert data["wall_angle"]["margin_deg"] == 15
    assert data["wall_angle"]["source"] == "assumed"


def test_route_data_negative_angle_is_kept_as_slab():
    data = build_route_data(_route(angles_deg=[-5.0, None, None], angle_source="sensor", angle_margin_deg=8))

    assert data["holds"][0]["wall_angle_deg"] == -5.0
    assert "wall_angle" in data


def test_route_data_angles_do_not_change_distances_or_accuracy():
    plain = build_route_data(_route())
    with_angles = build_route_data(_route(angles_deg=[1.0, 2.0, 3.0], angle_source="sensor", angle_margin_deg=8))

    for key in ("distances_cm", "wall_length_cm", "accuracy"):
        assert with_angles[key] == plain[key]


def test_route_data_does_not_mutate_input_route_holds():
    route = _route(angles_deg=[24.5, 12.0, 30.1], angle_source="sensor", angle_margin_deg=8)
    before = json.dumps(route)

    build_route_data(route)

    assert json.dumps(route) == before


def test_route_data_wall_angle_block_with_angles_but_no_distances():
    data = build_route_data(_route(distances_units=None, wall_length_units=None, angles_deg=[1.0, 2.0, 3.0], angle_source="sensor", angle_margin_deg=8))

    assert data["distances_cm"] is None
    assert data["wall_angle"]["margin_deg"] == 8


def test_system_prompt_explains_wall_angle():
    prompt = COACHING_SYSTEM_PROMPT.lower()

    assert "wall_angle_deg" in prompt
    assert "wall_angle" in prompt
    assert "overhang" in prompt
    assert "margin" in prompt
    assert "estimate" in prompt
    assert "slab" in prompt


def test_payload_includes_wall_angle_when_present():
    route = _route(angles_deg=[24.5, 12.0, 30.1], angle_source="sensor", angle_margin_deg=8)
    content = build_coaching_payload(route)["messages"][0]["content"]

    assert content.endswith(json.dumps(build_route_data(route)))
    assert "wall_angle_deg" in content


# --- build_coaching_payload ---


def test_payload_user_content_is_prefix_then_route_data_json():
    route = _route()
    payload = build_coaching_payload(route)

    [message] = payload["messages"]
    assert message["role"] == "user"
    route_json = json.dumps(build_route_data(route))
    assert message["content"].endswith(route_json)
    prefix = message["content"][: -len(route_json)]
    assert prefix.strip(), "expected a text prefix before the route JSON"


def test_payload_route_json_contains_distances_for_every_selected_pair():
    route = _route_of_size(4, bolt_spacing_cm=25.0)
    content = build_coaching_payload(route)["messages"][0]["content"]

    route_json = json.dumps(build_route_data(route))
    data = json.loads(content[content.index(route_json):])
    assert len(data["distances_cm"]) == 6
    assert data["wall_length_cm"] == 500.0
    assert data["accuracy"]["margin_pct"] == 6
    assert data["accuracy"]["margin_pct_by_tier"] == {"A": 6, "C": 14}
    assert data["accuracy"]["centroid_allowance_cm"] == 5
    assert all(e["margin_cm"] == pytest.approx(_margin(e["cm"], e["tier"]), abs=0.1) for e in data["distances_cm"])


def test_payload_accepts_route_after_celery_json_round_trip():
    route = _route()

    assert build_coaching_payload(json.loads(json.dumps(route))) == build_coaching_payload(route)


def test_payload_request_settings():
    payload = build_coaching_payload(_route())

    assert payload["model"] == "claude-opus-5"
    assert payload["max_tokens"] == 4096
    assert payload["system"] == COACHING_SYSTEM_PROMPT
    assert payload["output_config"]["format"] == {"type": "json_schema", "schema": COACHING_OUTPUT_SCHEMA}


def test_payload_model_override():
    assert build_coaching_payload(_route(), model="claude-sonnet-5-5")["model"] == "claude-sonnet-5-5"


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
    payload = build_coaching_payload(_route())

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
        result = analysis(_route())

    assert result == STEPS
    mock_call.assert_called_once_with(build_coaching_payload(_route()))


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
