import os
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO
from ultralytics.utils import ops

#Path to the weights file

MODEL_PATH = Path(os.getenv("MODEL_PATH", Path(__file__).parent / "models" / "best.pt"))

#Loaded lazily and cached on first use, not at import time: would fuck with testing
_model = None

#Checks for model already init if not inits

def get_model():
    global _model
    if _model is None:
        _model = YOLO(MODEL_PATH)
    return _model

#Function that finds the centre of the ML hold predictions

def _polygon_centroid(points: np.ndarray) -> tuple[float, float]:
    """True area-weighted centroid of a polygon via the shoelace formula.

    points: shape (N, 2) normalized (0-1) x,y polygon vertices, as produced by
    _mask_to_polygon for one detection instance.

    Falls back to the arithmetic mean of the points for degenerate inputs
    (fewer than 3 points, or near-zero computed area e.g. collinear points),
    where the shoelace formula is undefined/unstable.
    """
    pts = np.asarray(points, dtype=np.float64)
    n = pts.shape[0]
    if n == 0:
        raise ValueError("_polygon_centroid: cannot compute centroid of an empty polygon")
    if n < 3:
        mean = pts.mean(axis=0)
        return (float(mean[0]), float(mean[1]))

    x, y = pts[:, 0], pts[:, 1]
    x_next, y_next = np.roll(x, -1), np.roll(y, -1)
    cross = x * y_next - x_next * y
    area = cross.sum() / 2.0

    if abs(area) < 1e-9:  #collinear / degenerate polygon
        mean = pts.mean(axis=0)
        return (float(mean[0]), float(mean[1]))

    cx = ((x + x_next) * cross).sum() / (6.0 * area)
    cy = ((y + y_next) * cross).sum() / (6.0 * area)
    return (float(cx), float(cy))


#Inference settings tuned against labelled validation images (see
#Docs/decisions.md, "best.pt inference settings"). end2end=False switches
#YOLO26 to its NMS head - the default end-to-end head skips NMS entirely and
#left same-class near-duplicates that broke tap-to-toggle.

PREDICT_KWARGS = {"imgsz": 1024, "end2end": False, "iou": 0.5, "retina_masks": True}

#Per-class floors picked for recall (a missed hold can't be selected at all).
#VOLUME stays at 0.25: lower barely adds recall but costs a lot of precision.

CONFIDENCE_FLOORS = {"HOLD": 0.15, "VOLUME": 0.25}

#The model letterboxes to 1024 regardless, so shrinking first loses nothing -
#but retina masks are built at the input's resolution, and on a 4K phone photo
#that's ~700 MB of masks per request.

MAX_INPUT_SIDE = 1024

#approxPolyDP tolerance as a fraction of each contour's own perimeter - cuts
#polygons from ~65 to ~14 points with no measurable loss of outline fit.

POLYGON_SIMPLIFY_EPS = 0.005

#Largest-area outer contour of one mask, simplified and normalized to 0-1.
#Not masks.xyn: that uses masks2segments(strategy="all"), which stitches every
#disconnected blob of a mask into one polygon joined by bridge lines - the
#"massive line" seen across volumes whose masks split along shaded faces.

def _mask_to_polygon(mask, orig_shape: tuple[int, int]) -> np.ndarray:
    m = (mask.cpu().numpy() > 0.5).astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.zeros((0, 2), dtype=np.float32)
    contour = max(contours, key=cv2.contourArea)
    contour = cv2.approxPolyDP(contour, POLYGON_SIMPLIFY_EPS * cv2.arcLength(contour, True), True)
    xy = contour.reshape(-1, 2).astype(np.float32)
    return ops.scale_coords(m.shape, xy, orig_shape, normalize=True)

#Runs the model on one image and returns plain-JSON-serializable detections,
#each with a stable "id" (its index in this list) that the client references
#in its tap-matching and, later, in its hold selection at submit time.

def run_detection(image) -> list[dict]:
    """One PIL image -> [{"id", "class_name", "centroid", "polygon",
    "confidence", "size"}, ...], one entry per detection above its class's
    CONFIDENCE_FLOORS entry.

    "polygon" is the normalized (0-1) list of {x, y} vertices (for
    point-in-polygon containment matching, done client-side); "size" is a
    characteristic normalized radius (geometric mean of the bbox width/height)
    used to scale each detection's own matching catchment radius client-side -
    a tiny crimp and a huge volume shouldn't share one fixed distance
    threshold.
    """
    model = get_model()
    image = image.copy()
    image.thumbnail((MAX_INPUT_SIDE, MAX_INPUT_SIDE))
    result = model.predict(
        image, conf=min(CONFIDENCE_FLOORS.values()), verbose=False, **PREDICT_KWARGS
    )[0]

    detections: list[dict] = []
    masks = result.masks
    if masks is None:
        return detections  #defensive: non-seg model or no detections

    boxes = result.boxes
    for mask, class_id, conf, bbox in zip(masks.data, boxes.cls, boxes.conf, boxes.xywhn):
        class_name = model.names[int(class_id)]
        confidence = float(conf)
        if confidence < CONFIDENCE_FLOORS.get(class_name, max(CONFIDENCE_FLOORS.values())):
            continue  #drop likely-noise detections before they ever reach the client
        polygon = _mask_to_polygon(mask, result.orig_shape)
        if polygon.shape[0] == 0:
            continue  #defensive: empty mask, shouldn't normally occur
        cx, cy = _polygon_centroid(polygon)
        w, h = float(bbox[2]), float(bbox[3])
        detections.append({
            "id": len(detections),
            "class_name": class_name,
            "centroid": {"x": cx, "y": cy},
            "polygon": [{"x": float(px), "y": float(py)} for px, py in polygon],
            "confidence": confidence,
            "size": (w * h) ** 0.5,
        })
    return detections


class UnknownHoldIdError(ValueError):
    """Raised by select_holds() when the client references a hold id that
    isn't present in the cached detections - either tampered with or from a
    stale/expired detection_id being reused against different detections."""


#Filters+groups a cached detections list down to the subset the client
#actually selected - a pure lookup, no geometry, since the client already
#resolved which detection each tap/selection refers to.

def select_holds(detections: list[dict], selected_ids: list[int]) -> dict[str, list[tuple[float, float]]]:
    by_id = {d["id"]: d for d in detections}

    master: dict[str, list[tuple[float, float]]] = {}
    for hold_id in selected_ids:
        det = by_id.get(hold_id)
        if det is None:
            raise UnknownHoldIdError(f"select_holds: unknown hold id {hold_id!r}")
        centroid = (det["centroid"]["x"], det["centroid"]["y"])
        master.setdefault(det["class_name"], []).append(centroid)
    return master
