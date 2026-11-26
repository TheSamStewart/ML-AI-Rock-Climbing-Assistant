# Synthetic test cases for the volume scan (dev only)

`synth.py` renders synthetic volume-scan cases: a front-on photo plus a burst of
frames along one sideways step, with exact face angles and depth. The scan
tests (`backend/tests/test_volume_scan.py`, acceptance criterion 1 of
`docs/milestones/v0.2/38-volume-scan-trial/spec.md`) use `synth.scenes()` and `synth.sweep_case()`.

```python
import synth
scene = next(s for s in synth.scenes() if s.name == "s_wedge_over35")
case = synth.sweep_case(scene, n_frames=6, span_cm=60)
# case: photo, frames, gravity, volume_polygon, detections, truth_faces, depth_cm
```

It's a small ray caster with textures fixed to the wall and the faces in cm, so
every frame sees one physical scene. `fakewall.py` draws in image space, so it
can't do this. Each image takes about 15 s to render.

## History

This folder started as the two- and three-photo experiment (slice 11,
2026-11-25). Its scripts (`two_view.py`, `wallfix.py`, `sweep2.py`) were
superseded by `backend/wall_analysis/volume_scan.py` and deleted the same day; they were never
committed. What was tried, the results and the dead ends are in
`docs/features_deprecated/wall_size_hold_distance_handover.md`, slice 11 entries of 2026-11-25.
