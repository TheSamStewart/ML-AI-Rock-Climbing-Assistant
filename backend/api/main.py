import asyncio
import io
import json
import logging
import math
import threading
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from wall_analysis import bolts
from wall_analysis import detection
from wall_analysis import scale as scale_module
from fastapi import FastAPI, File, Form, Header, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.gzip import GZipMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError
from redis.exceptions import RedisError
from coaching.worker import app as celery_app, analysis as analysis_task
from celery.result import AsyncResult
from api.redis_client import redis_client

logger = logging.getLogger(__name__)

def _warm_model() -> None:
    try:
        detection.warm_up()
    except Exception:  # noqa: BLE001 - a failed warm-up just means the first request loads the model
        logger.exception("startup: YOLO warm-up failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    #In a background thread so the server takes requests straight away; a
    #photo that arrives mid-warm-up just loads the model itself, as before.
    threading.Thread(target=_warm_model, name="yolo-warm-up", daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)

#Slice 13: /detect's N x N distance table compresses 3-4x (429 KB -> 116 KB
#for 183 holds) in ~10 ms. Phones' HTTP stacks (OkHttp, NSURLSession) ask for
#gzip and unpack it themselves, so the app needs no change. Small responses
#(polling, errors) stay uncompressed.
app.add_middleware(GZipMiddleware, minimum_size=1000)


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

#Climber stats from Settings (slice 15), optional. Wide enough for children
#and very tall adults; keep in sync with the mobile app's utils/climberStats.ts.

CLIMBER_RANGES_CM = {
    "climber_height_cm": (100.0, 230.0),
    "climber_arm_span_cm": (90.0, 250.0),
}


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

    #Per-stage timing in the log (slice 13), so real-phone timings can be
    #split into upload vs server work instead of guessed. The upload itself
    #happens before this handler runs: compare with the app's round trip.
    #The bolt-hole blob search needs only the photo, not YOLO's holds, and
    #both release the GIL (torch, OpenCV), so they run side by side (slice 13).
    t_yolo = time.perf_counter()
    detections, bolt_candidates = await asyncio.gather(
        run_in_threadpool(detection.run_detection, image),
        run_in_threadpool(bolts.find_candidates, image),
        return_exceptions=True,
    )
    if isinstance(detections, BaseException):
        logger.error("detect: YOLO inference failed", exc_info=detections)
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"detail": "Hold detection failed - try again."}
    if isinstance(bolt_candidates, BaseException):
        #detect_bolt_holes recomputes them, and reports a real failure itself.
        logger.warning("detect: early bolt candidate search failed", exc_info=bolt_candidates)
        bolt_candidates = None

    #Bolt holes are ~10 px on a typical photo, so bolt detection and scale use
    #the full-res image, not the 1024 px detection thumbnail - the detections
    #themselves are normalized, so they line up. Same EXIF-rotated pixels YOLO saw.

    t_bolts = time.perf_counter()
    try:
        found_bolts = await run_in_threadpool(bolts.detect_bolt_holes, image, detections, candidates=bolt_candidates)
        t_scale = time.perf_counter()
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
    t_done = time.perf_counter()
    logger.info(
        "detect: %dx%d, %d KB upload, %d holds, %d bolts | yolo+blobs %.2fs bolts %.2fs scale %.2fs total %.2fs",
        image.size[0], image.size[1], len(contents) // 1024, len(detections), len(found_bolts),
        t_bolts - t_yolo, t_scale - t_bolts, t_done - t_scale, t_done - t_yolo,
    )

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

    #Slice 15: the climber's height and arm span from Settings, both optional
    #(absent or empty = not set). A value that is set but not a sensible
    #number is a client bug: 422, like the bolt spacing.
    climber = {}
    for field, (low, high) in CLIMBER_RANGES_CM.items():
        raw = form.get(field)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = math.nan
        if not math.isfinite(value) or not (low <= value <= high):
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            return {"detail": f"{field} must be between {low:g} and {high:g} cm."}
        climber[field.removeprefix("climber_")] = value

    #Slice 16: the user's answer to "whole wall in the photo?". Optional; only
    #"true"/"false" count, anything else is ignored (it only labels a number).
    whole_wall = {"true": True, "false": False}.get(str(form.get("whole_wall_in_photo", "")).strip().lower())

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
    #Only when present, so an older cached scale or an older app gives the
    #route (and the LLM payload) exactly as before.
    axes = scale_module.select_axes(scale, detections, parsed_ids)
    if axes is not None:
        route["wall_axes"] = axes
    if climber:
        route["climber"] = climber
    if whole_wall is not None:
        route["whole_wall_in_photo"] = whole_wall

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


# -------------------------------------------------------------------------
# DEV ONLY: volume scan test feature (docs/milestones/v0.2/38-volume-scan-trial/spec.md)
# -------------------------------------------------------------------------
#Not part of the normal flow and not used by the coaching AI. No auth, like the
#rest of the API today; gate or remove before release (on the Fable list).

from wall_analysis import volume_scan  # noqa: E402 - kept beside the only endpoint that uses it
from pathlib import Path  # noqa: E402

SCANS_DIR = Path(__file__).resolve().parents[1] / "field_captures_scans"
SCAN_MAX_UPLOADS = 20


def _open_upright(contents: bytes) -> tuple[Image.Image, float | None]:
    image = Image.open(io.BytesIO(contents))
    focal = _focal_35mm(image)
    image.load()
    return ImageOps.exif_transpose(image).convert("RGB"), focal


def _save_scan(scan_id: str, photo_bytes: bytes, frame_bytes: list[bytes], record: dict) -> None:
    """Every scan's inputs and result, for the gym-trial analysis. Never fails the request."""
    try:
        folder = SCANS_DIR / scan_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "photo.jpg").write_bytes(photo_bytes)
        for i, b in enumerate(frame_bytes):
            (folder / f"frame_{i:02d}.jpg").write_bytes(b)
        (folder / "scan.json").write_text(json.dumps(record, indent=1, default=float))
        template = {
            "_help": "Fill by hand: each face's angle with a level along its steepest line, + overhang / - slab; "
                     "'points' = left / right / up / down / at me; 'number' = the face's number in the app's result "
                     "(its order in scan.json result.faces, from 1). null = not measured.",
            "shape": None, "wall_angle_beside_deg": None, "depth_cm": None,
            "faces": [{"number": None, "angle_deg": None, "points": None}],
            "notes": "",
        }
        (folder / "volume.json").write_text(json.dumps(template, indent=2))
    except OSError:
        logger.exception("volume-scan: could not save scan %s", scan_id)


@app.post("/dev/volume-scan")
async def dev_volume_scan(
    response: Response,
    photo: UploadFile = File(),
    frames: list[UploadFile] = File(),
    volume_polygon: str = Form(),
    gravity: str | None = Form(None),
    bolt_spacing_cm: str | None = Form(None),
):
    started = time.perf_counter()
    scan_id = time.strftime("%Y-%m-%d_%H%M%S") + "_" + uuid4().hex[:8]

    photo_bytes = await photo.read()
    frame_bytes = [await f.read() for f in frames]
    record = {"scan_id": scan_id, "frames_received": len(frames),
              "raw": {"volume_polygon": volume_polygon, "gravity": gravity, "bolt_spacing_cm": bolt_spacing_cm}}

    def fail(message: str):
        #Every request is saved, failures included (spec): its scan_id always has a folder.
        record.setdefault("error", message)
        _save_scan(scan_id, photo_bytes, frame_bytes, record)
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return {"detail": message, "scan_id": scan_id}

    if len(frames) > SCAN_MAX_UPLOADS:
        return fail(f"Too many burst photos ({len(frames)}); send at most {SCAN_MAX_UPLOADS}.")
    try:
        polygon = json.loads(volume_polygon)
        polygon = [{"x": float(p["x"]), "y": float(p["y"])} for p in polygon]
        if len(polygon) < 3 or not all(math.isfinite(p["x"]) and math.isfinite(p["y"]) for p in polygon):
            raise ValueError
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return fail("The volume outline isn't readable.")
    try:
        spacing = float(bolt_spacing_cm) if bolt_spacing_cm not in (None, "") else DEFAULT_BOLT_SPACING_CM
    except ValueError:
        spacing = math.nan
    if not math.isfinite(spacing) or not (MIN_BOLT_SPACING_CM <= spacing <= MAX_BOLT_SPACING_CM):
        return fail(f"Bolt spacing must be {MIN_BOLT_SPACING_CM:g}-{MAX_BOLT_SPACING_CM:g} cm.")
    reading = _parse_gravity(gravity)

    record.update(gravity=reading, bolt_spacing_cm=spacing, volume_polygon=polygon)
    try:
        image, focal = _open_upright(photo_bytes)
        burst = [_open_upright(b)[0] for b in frame_bytes]
    except (UnidentifiedImageError, OSError):
        return fail("A photo in the scan isn't a readable image.")
    record["focal_35mm"] = focal

    #Holds keep bolt detection and wall matching off themselves; a YOLO failure
    #only makes those a little noisier, so it doesn't stop the scan.
    try:
        detections = await run_in_threadpool(detection.run_detection, image)
    except Exception:  # noqa: BLE001
        logger.exception("volume-scan: YOLO failed, scanning without hold masks")
        detections = []

    try:
        result = await run_in_threadpool(
            volume_scan.scan_volume, image, burst, polygon, detections,
            gravity_reading=reading, focal_35mm=focal, bolt_spacing_cm=spacing,
        )
    except volume_scan.ScanError as e:
        if e.diagnostics is not None:  #why each burst photo did or didn't line up, for the trial analysis
            record["frame_diagnostics"] = e.diagnostics
        return fail(str(e))
    except Exception:  # noqa: BLE001 - a test feature must not 500
        logger.exception("volume-scan: scan %s failed", scan_id)
        record["error"] = "internal error"
        return fail("The scan failed on the server. It was saved for checking.")

    record["result"] = result
    _save_scan(scan_id, photo_bytes, frame_bytes, record)
    logger.info("volume-scan %s: %d faces, %d/%d frames used, %.1f s total", scan_id, len(result["faces"]),
                result["frames_used"], result["frames_sent"], time.perf_counter() - started)
    return {"scan_id": scan_id, **{k: v for k, v in result.items() if k != "frame_diagnostics"}}
