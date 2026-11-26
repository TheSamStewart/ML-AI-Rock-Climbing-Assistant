import json
import logging
import math
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

Each hold has an "id". Refer to holds by their position and type in your
instructions (e.g. "the high left hold"), not by id - the id is only there so
you can match a hold to its distances.

Distances: "distances_cm" gives the straight-line distance in centimetres
between every pair of selected holds, measured along the wall surface, and
"wall_length_cm" gives the length of the wall in the photo; when present,
"wall_length_is" says whether that is the wall's full height or only part of
it. Use them to judge which holds are within reach of each other and how big
each move is (e.g. a long reach, a dyno, or a short move between close holds).

Accuracy: the distances are estimated from a photo, so they are approximate.
The "accuracy" block explains the margin of error: a percentage of the
distance plus a fixed allowance in cm for where the centre of each hold is.
Each entry in "distances_cm" already has its margin worked out as
"margin_cm", and a "tier": "A" means the wall's bolt grid was visible along
the whole line, so the distance is the more reliable; "C" means holds or
volumes hide the bolt grid along part of the line, so its scale is borrowed
from further away and its margin is wider. If a move looks out of reach by no
more than its margin_cm, give the climber the benefit of the doubt and treat
it as reachable, rather than routing around it.

Wall angle: when present, each hold has a "wall_angle_deg" - how steep the wall
is around that hold, in degrees from vertical. 0 is a vertical wall, a positive
angle is an overhang (the wall leans out over the climber, so the arms and core
carry more of the load and the feet are easier to lose), and a small angle is
gentle (about 10 degrees or less) while 30 or more is steep. The wall can change
angle between holds, so look at the angle of both holds in a move. It is
estimated from the photo: the "wall_angle" block gives its margin in degrees.
Use the general steepness, and don't lean on the exact number - an angle that
differs from another by less than the margin is the same steepness for your
purposes. Where the margin makes a hold's angle uncertain, keep the advice
about body position general. The estimate assumes the wall leans out, so a
slab (a wall leaning back) can be mistaken for an overhang.

Moves and positions: when present, "moves" lists each move in the order the
climber picked the holds, with its length "cm" and how much of it is "up_cm"
(up the wall; negative = down) and "across_cm" (to the right as you face the
wall; negative = to the left), measured along the wall. Each hold may also have
"position_from_start_cm": where it is, up and across, from the first picked
hold. Prefer these to the photo coordinates for judging moves - the photo is
taller than it is wide and seen in perspective, so photo coordinates distort
distances. A move's "from_wall_angle_deg" and "to_wall_angle_deg" give the
steepness at each end, and "wall_angle_change" appears when the wall gets
clearly steeper or less steep during the move - mention it, as the body
position has to change there.

Climber: when present, "climber" gives the climber's height and arm span (and
ape index) in cm. Use it to judge which moves are a stretch for this climber
and suggest technique accordingly (e.g. high feet or a dynamic move for a long
reach).

Only reference holds present in the data you are given - never invent holds or
coordinates. Keep instructions concise, one instruction per step."""

#Distance margin given to the LLM (docs/features_deprecated/wall_size_hold_distance.md,
#"Accuracy results"), per confidence tier (scale.py, TIER_A_MAX_SUPPORT).
#"A" (bolt grid visible along the whole line): the pooled p95 relative error
#of held-out in-panel bolt pairs at reach range, rounded up - re-derive with
#`eval_scale.py --accuracy` when the fit changes. "C" (scale borrowed across
#hidden bolts): the pooled p95 of pairs measured across held-out discs of
#bolts, rounded up. A distance with no tier is treated as "A".
#CENTROID_ALLOWANCE_CM covers hold centres being estimates (centroid of the
#hold's outline, standing off the wall); added to hold-to-hold distances
#only, as wall length is measured bolt to bolt. Slice 10 re-calibrates it.

DISTANCE_MARGIN_PCT_BY_TIER = {"A": 6, "C": 14}
DISTANCE_MARGIN_PCT = DISTANCE_MARGIN_PCT_BY_TIER["A"]  #also the wall length's margin (bolt to bolt)
DEFAULT_TIER = "A"
CENTROID_ALLOWANCE_CM = 5

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


#Grid units -> cm, rounded to the nearest mm - finer than that is false precision.

def _to_cm(units: float | None, bolt_spacing_cm: float) -> float | None:
    return None if units is None else round(units * bolt_spacing_cm, 1)


def _margin_cm(cm: float | None, tier: str = DEFAULT_TIER) -> float | None:
    pct = DISTANCE_MARGIN_PCT_BY_TIER.get(tier, DISTANCE_MARGIN_PCT_BY_TIER[DEFAULT_TIER])
    return None if cm is None else round(cm * pct / 100 + CENTROID_ALLOWANCE_CM, 1)


def _up_across_fraction(dx: float, dy: float, axes: list) -> tuple[float, float] | None:
    """Split a photo displacement (normalised coordinates) into its up-the-wall
    and across-to-the-right parts, as fractions of its length along the wall,
    using each endpoint's wall_axes ([down, across] photo directions, see
    angle.wall_axes) and averaging. None when no endpoint has axes."""
    parts = []
    for ax in axes:
        if ax is None:
            continue
        (d0, d1), (a0, a1) = ax
        det = d0 * a1 - a0 * d1
        if abs(det) < 1e-12:
            continue
        down = (dx * a1 - a0 * dy) / det
        across = (d0 * dy - d1 * dx) / det
        length = math.hypot(down, across)
        if length > 0:
            parts.append((-down / length, across / length))
    if not parts:
        return None
    up = sum(p[0] for p in parts) / len(parts)
    across = sum(p[1] for p in parts) / len(parts)
    length = math.hypot(up, across)
    return (up / length, across / length) if length > 0 else None


def _moves_and_positions(route: dict, holds: list[dict], angles, margin_deg) -> tuple[list[dict], list[dict | None]]:
    """Slice 15. Each move in pick order with its up/across parts in cm and
    the wall angle at both ends, plus each hold's position in cm relative to
    the first picked hold. The parts are proportions (from the wall's local
    directions at each end) of the distance measured along the wall, so they
    always add up to distances_cm, folds included."""
    axes = route["wall_axes"]
    matrix, spacing = route["distances_units"], route["bolt_spacing_cm"]

    def split(i: int, j: int) -> tuple[float, float] | None:
        frac = _up_across_fraction(holds[j]["x"] - holds[i]["x"], holds[j]["y"] - holds[i]["y"], [axes[i], axes[j]])
        cm = _to_cm(matrix[i][j], spacing)
        if frac is None or cm is None:
            return None
        return round(frac[0] * cm, 1), round(frac[1] * cm, 1)

    moves = []
    for i in range(len(holds) - 1):
        j = i + 1
        if holds[i]["id"] == holds[j]["id"]:
            continue
        move = {"from": holds[i]["id"], "to": holds[j]["id"], "cm": _to_cm(matrix[i][j], spacing)}
        parts = split(i, j)
        if parts is not None:
            move["up_cm"], move["across_cm"] = parts
        if angles is not None and angles[i] is not None and angles[j] is not None:
            move["from_wall_angle_deg"], move["to_wall_angle_deg"] = angles[i], angles[j]
            change = angles[j] - angles[i]
            if margin_deg is not None and abs(change) > margin_deg:
                move["wall_angle_change"] = f"{'steeper' if change > 0 else 'less steep'}: {angles[i]:g} to {angles[j]:g} degrees"
        moves.append(move)

    positions = [{"up_cm": 0.0, "across_cm": 0.0}] + [split(0, k) for k in range(1, len(holds))]
    positions = [p if p is None or isinstance(p, dict) else {"up_cm": p[0], "across_cm": p[1]} for p in positions]
    if holds and axes[0] is None:
        positions[0] = None
    return moves, positions


def _climber_block(climber: dict) -> dict:
    """Slice 15: the climber's height and arm span from Settings, and their
    ape index (arm span minus height; positive = longer reach than height)."""
    out = {k + "_cm": round(v, 1) for k, v in climber.items()}
    if "height" in climber and "arm_span" in climber:
        out["ape_index_cm"] = round(climber["arm_span"] - climber["height"], 1)
    out["guidance"] = (
        "Use the climber's own size to judge reach: a move that is long for an average "
        "climber may be comfortable for this one, and the reverse. Arm span is fingertip to "
        "fingertip with arms out; a positive ape index means a longer reach than their height."
    )
    return out


def build_route_data(route: dict) -> dict:
    """route (as built by main.py's /analysis, in grid units) -> the JSON the
    LLM sees, in cm.

    distances_cm has one entry per unordered pair of distinct holds; repeated
    ids (allowed by /analysis) are only paired once.
    """
    holds = route["holds"]
    spacing = route["bolt_spacing_cm"]
    matrix = route.get("distances_units")
    tiers = route.get("tiers")

    distances_cm = None
    if matrix is not None:
        distances_cm = []
        first_index: dict[int, int] = {}
        for i, hold in enumerate(holds):
            first_index.setdefault(hold["id"], i)
        unique = [i for i, hold in enumerate(holds) if first_index[hold["id"]] == i]
        for a_pos, i in enumerate(unique):
            for j in unique[a_pos + 1:]:
                cm = _to_cm(matrix[i][j], spacing)
                tier = tiers[i][j] if tiers is not None else DEFAULT_TIER
                distances_cm.append({
                    "from": holds[i]["id"],
                    "to": holds[j]["id"],
                    "cm": cm,
                    "tier": tier,
                    "margin_cm": _margin_cm(cm, tier),
                })

    #Wall angle per hold, in pick order like the holds themselves. Left out
    #entirely (not null) when the scale has none - an older cached scale, or
    #the photo gave no usable angle - so the LLM isn't shown a gap to explain.
    angles = route.get("angles_deg")
    has_angles = angles is not None and len(angles) == len(holds) and any(a is not None for a in angles)

    hold_data = []
    for i, h in enumerate(holds):
        item = {"id": h["id"], "class_name": h["class_name"], "x": h["x"], "y": h["y"]}
        if has_angles and angles[i] is not None:
            item["wall_angle_deg"] = angles[i]
        hold_data.append(item)

    wall_angle = None
    if has_angles:
        margin = route.get("angle_margin_deg")
        source = route.get("angle_source")
        tilt = "and the phone's tilt when it was taken" if source == "sensor" else "with an assumed camera tilt"
        wall_angle = {
            "margin_deg": margin,
            "source": source,
            "guidance": (
                f"wall_angle_deg is the wall's steepness around each hold in degrees from vertical "
                f"(positive = overhanging), estimated from the photo {tilt}; "
                f"it can be off by about {margin:g} degrees. Treat differences smaller than that as the same steepness."
            ),
        }

    data = {
        "holds": hold_data,
        "distances_cm": distances_cm,
        "wall_length_cm": _to_cm(route.get("wall_length_units"), spacing),
        "accuracy": {
            "margin_pct": DISTANCE_MARGIN_PCT,
            "margin_pct_by_tier": dict(DISTANCE_MARGIN_PCT_BY_TIER),
            "centroid_allowance_cm": CENTROID_ALLOWANCE_CM,
            "applies_to": (
                f"distances_cm (tier A: ±{DISTANCE_MARGIN_PCT_BY_TIER['A']}%, tier C: ±{DISTANCE_MARGIN_PCT_BY_TIER['C']}%, "
                f"plus {CENTROID_ALLOWANCE_CM} cm, given per pair as margin_cm) "
                f"and wall_length_cm (±{DISTANCE_MARGIN_PCT}%)"
            ),
            "guidance": (
                f"Distances are photo estimates. A hold-to-hold distance can be off by up to "
                f"{DISTANCE_MARGIN_PCT_BY_TIER['A']}% of its length for tier A (the bolt grid is visible along the "
                f"whole line) or {DISTANCE_MARGIN_PCT_BY_TIER['C']}% for tier C (holds hide the bolt grid along part "
                f"of the line, so the scale is borrowed), plus {CENTROID_ALLOWANCE_CM} cm, because hold "
                f"centres are estimated; that margin is given for each pair as margin_cm. "
                f"If a move looks out of reach by no more than its margin_cm, treat it as reachable."
            ),
        },
    }
    if wall_angle is not None:
        data["wall_angle"] = wall_angle

    #Slice 15, only when the cached scale has the wall's directions (an older
    #scale gives the payload exactly as before).
    axes = route.get("wall_axes")
    if matrix is not None and axes is not None and len(axes) == len(holds):
        moves, positions = _moves_and_positions(
            route, holds, angles if has_angles else None, route.get("angle_margin_deg"))
        data["moves"] = moves
        for item, position in zip(hold_data, positions):
            if position is not None:
                item["position_from_start_cm"] = position
    if route.get("climber"):
        data["climber"] = _climber_block(route["climber"])
    #Slice 16: the user's answer; wall_length_cm is only the wall's full
    #height when the whole wall was in the photo.
    if "whole_wall_in_photo" in route and data["wall_length_cm"] is not None:
        data["wall_length_is"] = (
            "the full height of the wall (the climber says the whole wall is in the photo)"
            if route["whole_wall_in_photo"]
            else "only the part of the wall in the photo; the wall is taller"
        )
    return data


def build_coaching_payload(
    route: dict,
    model: str = "claude-opus-5",
) -> dict:
    """Compile the route (selected holds + grid-unit distances, see
    build_route_data) + coaching system prompt into a Claude Messages API
    request payload - i.e. the kwargs for client.messages.create(**payload).

    Only builds the request payload; call_coaching_llm() below sends it.
    """
    route_data = build_route_data(route)

    user_content = (
        "Here is the detected route data (holds in the order the climber "
        "selected them, normalized image coordinates, plus hold-to-hold "
        "distances):\n" + json.dumps(route_data)
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


#Named explicitly so the task name never depends on the folder layout - the API
#and the worker must agree on it, and tasks already queued use it.
@app.task(name="worker.analysis")
def analysis(route: dict):
    #route: the already-resolved selected holds + their grid-unit distances
    #(see build_route_data) - detection, scale and selection all happened
    #synchronously before this task was ever queued (see main.py's /detect
    #and /analysis endpoints), so this task's only job is the LLM call.

    coaching_payload = build_coaching_payload(route)
    return call_coaching_llm(coaching_payload)
