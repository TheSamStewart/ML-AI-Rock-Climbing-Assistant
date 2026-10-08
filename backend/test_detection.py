import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch
from PIL import Image

import detection
from detection import (
    CONFIDENCE_FLOORS,
    MAX_INPUT_SIDE,
    PREDICT_KWARGS,
    UnknownHoldIdError,
    _mask_to_polygon,
    _polygon_centroid,
    run_detection,
    select_holds,
)

# Everything here runs without best.pt: the model is replaced by a stub that
# returns a hand-built ultralytics-shaped result. The one real-model test at
# the bottom is skipped whenever the (gitignored) weights aren't present.


# --- _polygon_centroid ---


def test_centroid_of_unit_square():
    assert _polygon_centroid(np.array([[0, 0], [1, 0], [1, 1], [0, 1]])) == pytest.approx((0.5, 0.5))


def test_centroid_of_right_triangle_is_area_weighted_not_vertex_mean():
    # Vertex mean and true centroid coincide for a triangle, so pad it with a
    # redundant collinear vertex - that shifts the vertex mean but not the area.
    pts = np.array([[0, 0], [0.5, 0], [1, 0], [0, 1]])

    assert _polygon_centroid(pts) == pytest.approx((1 / 3, 1 / 3))
    assert pts.mean(axis=0) != pytest.approx((1 / 3, 1 / 3))


def test_centroid_is_winding_order_independent():
    ccw = np.array([[0.1, 0.1], [0.7, 0.2], [0.6, 0.8], [0.2, 0.5]])

    assert _polygon_centroid(ccw) == pytest.approx(_polygon_centroid(ccw[::-1]))


@pytest.mark.parametrize(
    "pts",
    [
        [[0.3, 0.4]],
        [[0.0, 0.0], [1.0, 1.0]],
        [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]],  # collinear, zero area
    ],
)
def test_centroid_degenerate_inputs_fall_back_to_mean(pts):
    arr = np.array(pts, dtype=float)

    assert _polygon_centroid(arr) == pytest.approx(tuple(arr.mean(axis=0)))


def test_centroid_empty_polygon_raises():
    with pytest.raises(ValueError):
        _polygon_centroid(np.zeros((0, 2)))


# --- select_holds ---


def test_select_holds_groups_by_class_in_selection_order(sample_detections):
    result = select_holds(sample_detections, [3, 2, 0])

    assert result == {"HOLD": [(0.6, 0.1), (0.2, 0.9)], "VOLUME": [(0.5, 0.4)]}


def test_select_holds_duplicate_ids_are_kept(sample_detections):
    assert select_holds(sample_detections, [1, 1]) == {"HOLD": [(0.4, 0.6), (0.4, 0.6)]}


def test_select_holds_empty_selection(sample_detections):
    assert select_holds(sample_detections, []) == {}


def test_select_holds_unknown_id_raises(sample_detections):
    with pytest.raises(UnknownHoldIdError):
        select_holds(sample_detections, [0, 42])

    assert issubclass(UnknownHoldIdError, ValueError)


# --- _mask_to_polygon ---


def _rect_mask(h, w, y0, y1, x0, x1):
    m = torch.zeros((h, w))
    m[y0:y1, x0:x1] = 1.0
    return m


def test_mask_to_polygon_outlines_a_rectangle_normalized():
    mask = _rect_mask(100, 200, 20, 60, 50, 150)

    poly = _mask_to_polygon(mask, (100, 200))

    assert poly.shape[1] == 2
    assert (poly >= 0).all() and (poly <= 1).all()
    assert poly[:, 0].min() == pytest.approx(50 / 200, abs=0.01)
    assert poly[:, 0].max() == pytest.approx(149 / 200, abs=0.01)
    assert poly[:, 1].min() == pytest.approx(20 / 100, abs=0.02)
    assert poly[:, 1].max() == pytest.approx(59 / 100, abs=0.02)


def test_mask_to_polygon_empty_mask():
    poly = _mask_to_polygon(torch.zeros((50, 50)), (50, 50))

    assert poly.shape == (0, 2)


def test_mask_to_polygon_keeps_only_largest_blob():
    # Two disconnected blobs must not be stitched into one polygon with a
    # bridge line between them - only the bigger one survives.
    mask = _rect_mask(100, 100, 10, 30, 10, 30)  # small, top-left
    mask[50:95, 50:95] = 1.0  # large, bottom-right

    poly = _mask_to_polygon(mask, (100, 100))

    assert poly[:, 0].min() >= 0.45
    assert poly[:, 1].min() >= 0.45


# --- run_detection (stubbed model) ---


H, W = 100, 200


def _fake_model(entries, names=None, masks_none=False):
    """entries: list of (class_id, conf, mask_tensor, (cx, cy, w, h) normalized)."""
    names = names or {0: "HOLD", 1: "VOLUME", 2: "MYSTERY"}
    if masks_none:
        masks = None
    else:
        masks = SimpleNamespace(data=torch.stack([e[2] for e in entries]) if entries else torch.zeros((0, H, W)))
    boxes = SimpleNamespace(
        cls=torch.tensor([float(e[0]) for e in entries]),
        conf=torch.tensor([float(e[1]) for e in entries]),
        xywhn=torch.tensor([list(e[3]) for e in entries]) if entries else torch.zeros((0, 4)),
    )
    result = SimpleNamespace(masks=masks, boxes=boxes, orig_shape=(H, W))
    model = MagicMock()
    model.names = names
    model.predict.return_value = [result]
    return model


def _run(model, image=None):
    image = image or Image.new("RGB", (W, H))
    with patch("detection.get_model", return_value=model):
        return run_detection(image)


def test_run_detection_output_shape_is_json_serializable():
    model = _fake_model([(0, 0.9, _rect_mask(H, W, 10, 30, 10, 50), (0.15, 0.2, 0.2, 0.2))])

    [det] = _run(model)

    assert set(det) == {"id", "class_name", "centroid", "polygon", "confidence", "size"}
    assert det["id"] == 0
    assert det["class_name"] == "HOLD"
    assert det["confidence"] == pytest.approx(0.9)
    assert det["size"] == pytest.approx(math.sqrt(0.2 * 0.2))
    assert all(set(p) == {"x", "y"} for p in det["polygon"])
    assert 0.05 < det["centroid"]["x"] < 0.25 and 0.1 < det["centroid"]["y"] < 0.3
    assert json.loads(json.dumps(det)) == det


def test_run_detection_applies_per_class_confidence_floors_and_reindexes():
    mask = _rect_mask(H, W, 10, 30, 10, 50)
    bbox = (0.1, 0.1, 0.1, 0.1)
    model = _fake_model([
        (1, 0.20, mask, bbox),  # VOLUME below its 0.25 floor -> dropped
        (0, 0.20, mask, bbox),  # HOLD above its 0.15 floor -> kept
        (2, 0.20, mask, bbox),  # unknown class uses the max floor -> dropped
        (2, 0.30, mask, bbox),  # unknown class above max floor -> kept
        (1, 0.30, mask, bbox),  # VOLUME above floor -> kept
    ])
    assert CONFIDENCE_FLOORS == {"HOLD": 0.15, "VOLUME": 0.25}

    dets = _run(model)

    assert [(d["id"], d["class_name"]) for d in dets] == [(0, "HOLD"), (1, "MYSTERY"), (2, "VOLUME")]


def test_run_detection_skips_empty_masks_without_consuming_an_id():
    model = _fake_model([
        (0, 0.9, torch.zeros((H, W)), (0.1, 0.1, 0.1, 0.1)),
        (0, 0.9, _rect_mask(H, W, 10, 30, 10, 50), (0.1, 0.1, 0.1, 0.1)),
    ])

    dets = _run(model)

    assert [d["id"] for d in dets] == [0]


def test_run_detection_no_masks_returns_empty_list():
    assert _run(_fake_model([], masks_none=True)) == []


def test_run_detection_downscales_input_without_mutating_callers_image():
    model = _fake_model([])
    big = Image.new("RGB", (4000, 3000))

    _run(model, big)

    passed_image = model.predict.call_args.args[0]
    assert max(passed_image.size) == MAX_INPUT_SIDE
    assert big.size == (4000, 3000)


def test_run_detection_passes_tuned_predict_kwargs():
    model = _fake_model([])

    _run(model)

    kwargs = model.predict.call_args.kwargs
    assert kwargs["conf"] == min(CONFIDENCE_FLOORS.values())
    for key, value in PREDICT_KWARGS.items():
        assert kwargs[key] == value


# --- get_model ---


@pytest.fixture
def reset_model_cache():
    saved = detection._model
    detection._model = None
    yield
    detection._model = saved


def test_get_model_loads_once_and_caches(reset_model_cache):
    with patch("detection.YOLO") as mock_yolo:
        first = detection.get_model()
        second = detection.get_model()

    mock_yolo.assert_called_once_with(detection.MODEL_PATH)
    assert first is second


# --- real-model smoke test (local only - best.pt is gitignored) ---

_SAMPLE_IMAGES = sorted(
    (Path(__file__).parent.parent / "mobile" / "ML-Rock-Climbing-App" / "assets" / "images").glob(
        "climbing-route-detection-*[!d].jpg"
    )
)


@pytest.mark.slow
@pytest.mark.skipif(not detection.MODEL_PATH.exists(), reason="models/best.pt not present (gitignored)")
@pytest.mark.skipif(not _SAMPLE_IMAGES, reason="sample wall photo not present")
def test_run_detection_with_real_model(reset_model_cache):
    with Image.open(_SAMPLE_IMAGES[0]) as image:
        dets = run_detection(image)

    assert dets, "expected the real model to find at least one hold on the sample wall"
    assert [d["id"] for d in dets] == list(range(len(dets)))
    for d in dets:
        assert d["class_name"] in CONFIDENCE_FLOORS
        assert d["confidence"] >= CONFIDENCE_FLOORS[d["class_name"]]
        assert 0 <= d["centroid"]["x"] <= 1 and 0 <= d["centroid"]["y"] <= 1
        assert len(d["polygon"]) >= 3
    json.dumps(dets)
