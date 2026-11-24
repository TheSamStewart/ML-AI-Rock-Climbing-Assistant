"""DEV ONLY - click a volume's true corners on a photo and store them in that
capture folder's truth.json, for eval_volume_field.py's oracle path.

  LEFT click   a BASE corner (where the volume meets the wall), in order round it
  RIGHT click  a RAISED corner: the apex (pyramid), the two ridge ends (wedge),
               or the top corners in the SAME order as their base corners (box)
  u            undo the last click
  + / -        zoom in / out          arrow keys / WASD   pan
  Enter        save                   Esc                 quit without saving

Only click corners you can actually see - a hidden base corner is left out,
not guessed. Coordinates are stored normalised to the upright photo, the same
frame as capture.json's detections.

Usage (from backend/):
  uv run python draw_volume_corners.py field_captures/<folder> V1
The volume id is created in truth.json's "volumes" list if it is not there.
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import ImageOps, Image

import eval_volume_field

WINDOW = "volume corners"
VIEW = 1000  #window height in px


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    folder, vid = Path(sys.argv[1]), sys.argv[2]
    photo = eval_volume_field._photo(folder)
    if photo is None:
        sys.exit(f"no photo in {folder}")
    image = cv2.cvtColor(np.asarray(ImageOps.exif_transpose(Image.open(photo)).convert("RGB")),
                         cv2.COLOR_RGB2BGR)
    height, width = image.shape[:2]
    base, raised = [], []
    order = []  #which list each click went to, for undo
    state = {"zoom": VIEW / height, "x": 0.0, "y": 0.0}

    def to_image(px, py):
        return (state["x"] + px / state["zoom"], state["y"] + py / state["zoom"])

    def on_mouse(event, px, py, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            base.append(to_image(px, py)); order.append(base)
        elif event == cv2.EVENT_RBUTTONDOWN:
            raised.append(to_image(px, py)); order.append(raised)

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, on_mouse)
    while True:
        z = state["zoom"]
        view_w, view_h = int(VIEW * width / height), VIEW
        M = np.array([[z, 0, -state["x"] * z], [0, z, -state["y"] * z]], np.float32)
        frame = cv2.warpAffine(image, M, (view_w, view_h))
        for points, colour in ((base, (255, 0, 0)), (raised, (255, 0, 255))):
            for i, (x, y) in enumerate(points):
                p = (int((x - state["x"]) * z), int((y - state["y"]) * z))
                cv2.circle(frame, p, 6, colour, -1)
                cv2.putText(frame, str(i), (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
        cv2.putText(frame, f"{vid}: base {len(base)} (left)  raised {len(raised)} (right)  Enter=save Esc=quit",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imshow(WINDOW, frame)
        key = cv2.waitKeyEx(30)
        step = 100 / z
        if key in (27,):
            print("quit, nothing saved")
            break
        if key in (13, 10):
            save(folder, vid, base, raised, width, height)
            break
        if key == ord("u") and order:
            order.pop().pop()
        elif key in (ord("+"), ord("=")):
            state["zoom"] *= 1.5
        elif key == ord("-"):
            state["zoom"] /= 1.5
        elif key in (ord("a"), 2424832):
            state["x"] -= step
        elif key in (ord("d"), 2555904):
            state["x"] += step
        elif key in (ord("w"), 2490368):
            state["y"] -= step
        elif key in (ord("s"), 2621440):
            state["y"] += step
    cv2.destroyAllWindows()


def save(folder: Path, vid: str, base, raised, width, height) -> None:
    path = folder / "truth.json"
    truth = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    volumes = truth.setdefault("volumes", [])
    entry = next((v for v in volumes if v.get("id") == vid), None)
    if entry is None:
        entry = {"id": vid}
        volumes.append(entry)
    entry["base_px"] = [[round(x / width, 5), round(y / height, 5)] for x, y in base]
    entry["raised_px"] = [[round(x / width, 5), round(y / height, 5)] for x, y in raised]
    path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(f"saved {len(base)} base + {len(raised)} raised corners for {vid} in {path}")


if __name__ == "__main__":
    main()
