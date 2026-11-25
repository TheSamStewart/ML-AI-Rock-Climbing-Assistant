# Wall size and hold distance: what's in this merge

Branch `feat/more-detail-for-LLM-and-output-format`, merged 2026-11-25. Full detail: `docs/features/handover.md` and `docs/features/wall_size_hold_distance.md`.

## What it does
From one photo, the app now measures the wall itself, using the grid of bolt holes as a ruler:
- **The distance between any two holds**, in cm, with an honest error margin.
- **The length of the wall** in the photo.
- **How steep the wall is under each hold**: + overhang, − slab. This uses the bolt grid plus the phone's tilt.

All of it goes to the coaching AI, so its beta can judge reach and steepness instead of guessing from photo coordinates.

## How good it is
- **Distances:** every reference photo is within the 7% target; the worst went from 12.6% to 1.7% error. A tape measure on 12 real hold pairs confirmed the margins (6% where bolts are visible, 14% where they're hidden, plus 5 cm).
- **Angles:** on a real phone, the median error is 1.2° and the worst 5.2°, over 29 holds.
- **Speed:** server time is halved and uploads are about 4× smaller, with no loss of accuracy.

## What changed for the user
- **Settings:** bolt pattern and spacing, plus the climber's height and arm span (optional).
- **Photo screen:** the distance between each pair of picked holds and a ≈N° wall angle at each hold.
- **Coaching:** each move is split into up and across in cm, with a note when the wall gets steeper, sized to the climber.
- **Volume scan (test only, dev builds):** tap a volume, take one slow step sideways, and see each face's angle.

## Still open
- **Slice 16:** finishing.
- **Slice 17:** final docs.
- **Slice 18:** a Fable review, including the coaching API.
- **Holds on volumes (slice 14):** waits on retraining YOLO to find volumes.
- **Slab photos:** still needed to check the slab-vs-overhang call.
- **Volume scan:** awaiting its gym trial.
