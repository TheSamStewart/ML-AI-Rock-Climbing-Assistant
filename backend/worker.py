import json
import logging
import os
from celery import Celery
import anthropic

logger = logging.getLogger(__name__)

#Defaults to localhost for running outside Docker; docker-compose sets REDIS_URL to the redis service
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery("Tasks", broker=redis_url, backend=redis_url)

#Loaded lazily and cached on first use, not at import time: would fuck with testing.
#Anthropic() resolves credentials from the environment (ANTHROPIC_API_KEY) by default.
_anthropic_client = None

def get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client

#System prompt for the coaching LLM call - persona, task, and output-format rules.
#Wall angle, climber physical stats are NOT here yet - get added to the user content (as extra route/climber context) in a later step.

COACHING_SYSTEM_PROMPT = """You are an expert, encouraging rock climbing coach.

You will be given the normalized coordinates of every hold and volume a climber
has selected for their route on a bouldering wall, detected by a computer vision
model from a photo of the wall.

Coordinate convention: each hold is given as normalized (x, y) values between 0
and 1, relative to the photographed wall. x=0 is the left edge, x=1 is the right
edge. y=0 is the TOP of the photo, y=1 is the BOTTOM - so a LOWER y value means a
hold is HIGHER on the wall.

Your job: produce a clear, accessible, step-by-step climbing sequence ("beta")
that a climber of any experience level can follow, as a list of steps:

- Step 1 is the starting position - which hands and feet go on which holds.
- Each subsequent step is a single move, in order - which limb moves to which
  hold ("instruction"), and a brief reason why ("reason"), e.g. body
  positioning, weight shift, technique used.
- Put any practical tips into the relevant step's reason, in plain language -
  avoid unexplained jargon, so the output is just as usable for a first-time
  climber as an experienced one.

Only reference holds present in the data you are given - never invent holds or
coordinates. Keep instructions concise, one instruction per step."""

#JSON schema the API enforces on the response (structured outputs) - the
#mobile app maps over result.steps, so keep this in sync with getClimbAnalysis.tsx.

COACHING_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_number": {"type": "integer"},
                    "instruction": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["step_number", "instruction", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["steps"],
    "additionalProperties": False,
}


def build_coaching_payload(
    master_hold_dict: dict[str, list[tuple[float, float]]],
    model: str = "claude-opus-5",
) -> dict:
    """Compile the master hold dict + coaching system prompt into a Claude
    Messages API request payload - i.e. the kwargs for client.messages.create(**payload).

    Only builds the request payload; call_coaching_llm() below sends it. Wall
    angle / climber physical stats (ape index etc.) still need to be added to
    the user content once that data is available.
    """
    route_data = {
        class_name: [{"x": x, "y": y} for x, y in coords]
        for class_name, coords in master_hold_dict.items()
    }

    user_content = (
        "Here is the detected route data (normalized image coordinates, "
        "grouped by hold type):\n" + json.dumps(route_data)
    )

    return {
        "model": model,
        "max_tokens": 4096,
        "system": COACHING_SYSTEM_PROMPT,
        "output_config": {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": COACHING_OUTPUT_SCHEMA},
        },
        "messages": [
            {"role": "user", "content": user_content},
        ],
    }

#Sends the built payload to the Claude Messages API and returns the parsed {"steps": [...]} coaching output

def call_coaching_llm(payload: dict) -> dict:
    """Call the Claude Messages API with a payload from build_coaching_payload()
    and return the coaching output parsed into a {"steps": [...]} dict.

    Raises RuntimeError (chained from the original exception) on auth/rate-limit/
    connection/API errors, if the model refuses to answer, or if the output is
    truncated/unparseable, so a failure is surfaced clearly rather than silently
    returning an empty/partial result.
    """
    client = get_anthropic_client()

    try:
        response = client.messages.create(**payload)
    except TypeError as e:
        #The SDK raises a plain TypeError (not AuthenticationError) when no
        #credentials are resolvable at all - distinct from a bad-but-present key.
        raise RuntimeError("Anthropic client has no credentials configured - set ANTHROPIC_API_KEY") from e
    except anthropic.AuthenticationError as e:
        raise RuntimeError("Anthropic API authentication failed - check ANTHROPIC_API_KEY") from e
    except anthropic.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "unknown")
        raise RuntimeError(f"Anthropic API rate limited (retry after {retry_after}s)") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError("Could not reach the Anthropic API - network error") from e

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise RuntimeError(f"Coaching LLM declined to respond (category: {category})")

    #Truncated output is cut-off JSON - fail clearly instead of a confusing parse error
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Coaching LLM output was truncated (hit max_tokens)")

    #output_config.format guarantees the text block is JSON matching COACHING_OUTPUT_SCHEMA
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError("Coaching LLM returned invalid JSON") from e


@app.task
def analysis(master_hold_dict: dict[str, list[list[float]]]):
    #master_hold_dict: already-resolved {class_name: [(x, y), ...]} coordinates
    #for the holds the client selected - detection and selection both already
    #happened synchronously before this task was ever queued (see main.py's
    #/detect and /analysis endpoints), so this task's only job is the LLM call.

    coaching_payload = build_coaching_payload(master_hold_dict)
    return call_coaching_llm(coaching_payload)
