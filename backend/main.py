import io
import json
import logging
import math
from uuid import uuid4

import bolts
import detection
import scale as scale_module
from fastapi import FastAPI, File, Form, Header, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError
from redis.exceptions import RedisError
from worker import app as celery_app, analysis as analysis_task
from celery.result import AsyncResult
from redis_client import redis_client

logger = logging.getLogger(__name__)

app = FastAPI()


#Idempotency: client sends a unique Idempotency-Key header per submission attempt.
#We reserve it in redis (SET NX) before doing any work, so two
#requests with the same key can't both create tasks.

#keys are scoped globally, not per-user - there's no auth system yet.
#Once one exists, prefix the redis key with the user id to scope it per-user.


#/detect runs YOLO on the photo and caches the detections under a fresh
#detection_id, keyed for lookup by /analysis once the client has resolved
#which detections the user selected. /analysis then dispatches the LLM
#coaching call and returns 202 + a task_id for the polling GET below.

IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24  # 24h

#How long a detection result stays selectable before the user has to retake
#the photo - long enough to finish tapping, short enough not to accumulate
#stale cache entries.

DETECTIONS_TTL_SECONDS = 60 * 60  # 1h

#Fewer than this many holds isn't enough to build a real climbing sequence -
#keep in sync with the mobile app's own minimum in PhotoPreview.tsx.

MIN_SELECTED_HOLDS = 3

#User-set bolt grid spacing - keep in sync with the mobile app's
#utils/boltSpacing.ts. Defaulted so older clients that don't send it still work.

DEFAULT_BOLT_SPACING_CM = 20.0
MIN_BOLT_SPACING_CM = 10.0
MAX_BOLT_SPACING_CM = 50.0


def _parse_gravity(raw: str | None) -> list[float] | None:
    """The phone's accelerometer reading as sent by the app: a JSON list
    "[x, y, z]" (or "x,y,z"). Anything else is ignored, not rejected: the
    reading only improves the wall angle, and a bad one must not fail /detect."""
    if raw is None or not raw.strip():
        return None
    try:
        values = json.loads(raw) if raw.strip().startswith("[") else raw.split(",")
        parsed = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    return parsed if len(parsed) == 3 and all(math.isfinite(v) for v in parsed) else None


def _focal_35mm(image: Image.Image) -> float | None:
    """EXIF FocalLengthIn35mmFilm, or None. Read before exif_transpose."""
    try:
        value = image.getexif().get_ifd(0x8769).get(41989)
        return float(value) if value else None
    except Exception:  # noqa: BLE001 - optional metadata, never fail the request over it
        return None


@app.post("/detect")
async def detect(response: Response, photo: UploadFile = File(), gravity: str | None = Form(None)):
    contents = await photo.read()

    try:
        image = Image.open(io.BytesIO(contents))
        focal_35mm = _focal_35mm(image)
        #Image.open() only reads the header - force the full pixel decode now
        #so a truncated/corrupt body fails here with a clear 422, not deep
        #inside YOLO's own image handling later.
        image.load()
        #Phones often store the photo sideways plus an EXIF "rotate me" tag,
        #which the app's image view applies - so detections, bolts and hold
        #taps must all use the rotated pixels, or tap matching and distances
        #come out sideways. Neither PIL nor ultralytics applies it by itself.
        image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError):
        #UnidentifiedImageError = not an image at all; plain OSError = valid
        #header but truncated body (e.g. a dropped mobile upload).
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": "Uploaded file isn't a readable image."}

    #YOLO inference is CPU/GPU-bound, blocking work - run it off the event
    #loop so concurrent requests (e.g. another client's idempotency check)
    #aren't stalled behind it.

    try:
        detections = await run_in_threadpool(detection.run_detection, image)
    except Exception:
        logger.exception("detect: YOLO inference failed")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"detail": "Hold detection failed - try again."}

    #Bolt holes are ~10 px on a typical photo, so bolt detection and scale use
    #the full-res image, not the 1024 px detection thumbnail - the detections
    #themselves are normalized, so they line up. Same EXIF-rotated pixels YOLO saw.

    try:
        found_bolts = await run_in_threadpool(bolts.detect_bolt_holes, image, detections)
        scale = await run_in_threadpool(
            scale_module.compute_scale,
            detections,
            image.size,
            found_bolts,
            gravity=_parse_gravity(gravity),
            focal_35mm=focal_35mm,
        )
    except Exception:
        logger.exception("detect: scale computation failed")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"detail": "Wall scale estimation failed - try again."}

    #Both keys written in one transaction so /analysis never sees one without the other.

    detection_id = uuid4().hex
    try:
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.set(f"detections:{detection_id}", json.dumps(detections), ex=DETECTIONS_TTL_SECONDS)
            pipe.set(f"scale:{detection_id}", json.dumps(scale), ex=DETECTIONS_TTL_SECONDS)
            await pipe.execute()
    except RedisError:
        logger.exception("detect: failed to cache detections")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"detail": "Couldn't save detection results - try again."}

    return {"detection_id": detection_id, "detections": detections, "scale": scale}


@app.post("/analysis", status_code=status.HTTP_202_ACCEPTED)
async def analysis(
    #Reponse here allows to access metadata, specifically here change status code.

    request: Request,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),

    #The detection_id from a prior /detect call, and the JSON-encoded list of
    #hold ids (from that same call's detections) the user selected.

    detection_id: str = Form(...),
    selected_hold_ids: str = Form(...),
):
    #Lenient on purpose: this mirrors the rest of the endpoint's stub-level

    try:
        parsed_ids = json.loads(selected_hold_ids)
        if not isinstance(parsed_ids, list) or not all(isinstance(i, int) for i in parsed_ids):
            parsed_ids = None
    except (TypeError, ValueError):
        parsed_ids = None

    #Reject too-few selections before touching redis/Celery - the client is
    #expected to enforce this too, but that's bypassable, so this is the
    #check that actually guarantees it.

    if parsed_ids is None or len(parsed_ids) < MIN_SELECTED_HOLDS:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": f"At least {MIN_SELECTED_HOLDS} holds must be selected before submitting for analysis."}

    #bolt_spacing_cm is read from the raw form, not declared as a Form param:
    #FastAPI turns an empty form value into the default, but a field sent
    #empty is a client bug, not "use the default". Absent = older client = default.

    form = await request.form()
    raw_spacing = form.get("bolt_spacing_cm")
    if raw_spacing is None:
        bolt_spacing_cm = DEFAULT_BOLT_SPACING_CM
    elif not isinstance(raw_spacing, str) or raw_spacing.strip() == "":
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": "No bolt spacing provided."}
    else:
        try:
            bolt_spacing_cm = float(raw_spacing)
        except ValueError:
            bolt_spacing_cm = math.nan

        #isfinite first - "nan" parses as a float and fails every comparison.

        if not math.isfinite(bolt_spacing_cm) or not (MIN_BOLT_SPACING_CM <= bolt_spacing_cm <= MAX_BOLT_SPACING_CM):
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            return {"detail": f"Bolt spacing must be between {MIN_BOLT_SPACING_CM:g} and {MAX_BOLT_SPACING_CM:g} cm."}

    cached, cached_scale = await redis_client.mget(f"detections:{detection_id}", f"scale:{detection_id}")
    if cached is None or cached_scale is None:
        response.status_code = status.HTTP_410_GONE
        return {"detail": "Detection results expired or not found - retake the photo and try again."}

    detections = json.loads(cached)
    scale = json.loads(cached_scale)

    try:
        holds = detection.select_holds(detections, parsed_ids)
    except detection.UnknownHoldIdError:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": "One or more selected hold ids were not found in the detection results."}

    #Grid units only - the worker converts to cm with bolt_spacing_cm.

    route = {
        "holds": holds,
        "distances_units": scale_module.select_distances(scale, detections, parsed_ids),
        "tiers": scale_module.select_tiers(scale, detections, parsed_ids),
        "angles_deg": scale_module.select_angles(scale, detections, parsed_ids),
        "angle_source": scale.get("angle_source"),
        "angle_margin_deg": scale.get("angle_margin_deg"),
        "wall_length_units": scale.get("wall_length_units"),
        "bolt_spacing_cm": bolt_spacing_cm,
    }

    redis_key = f"idempotency:{idempotency_key}"

    reserved = await redis_client.set(
        redis_key, "processing", nx=True, ex=IDEMPOTENCY_TTL_SECONDS
    )

    if not reserved:
        existing = await redis_client.get(redis_key)
        if existing == "processing":
            #Another request with this key is still being processed
            response.status_code = status.HTTP_409_CONFLICT
            return {"detail": "Request with this Idempotency-Key is already being processed"}
        #Key already holds a completed task_id - replay the original response
        return {"task_id": existing}

    try:
        task = analysis_task.delay(route)
    except Exception:
        #Don't leave a failed attempt stuck as "processing" for the full TTL
        await redis_client.delete(redis_key)
        raise

    await redis_client.set(redis_key, task.id, ex=IDEMPOTENCY_TTL_SECONDS)

    return {"task_id" : task.id}

@app.get("/analysis/{task_id}")
async def getAnalysis(task_id: str):

    task_result = AsyncResult(task_id, app=celery_app)
    status = task_result.state

    if status == "FAILURE":
        return {"task_id": task_id, "status": status, "error": str(task_result.result)}

    if status == "PENDING" or status == "STARTED" or status == "RETRY":
        return {"task_id": task_id, "status": status}

    return {"task_id": task_id, "status": status, "result": task_result.result}
