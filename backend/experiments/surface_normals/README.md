# Surface-normal network experiment (DEV ONLY, not used by the API)

Slice 6b, 2026-11-20. Can a surface-normal network (Metric3D v2 ViT-Small, BSD-2) give a
pyramid volume's depth from ONE photo? See the handover entry of 2026-11-20 (later) for
the results so far.

It runs in its **own** Python environment, kept apart from the backend's dependencies
(torch, mmengine and the model code are not in `pyproject.toml`).

## Setup (Windows, CPU)

```
cd <any scratch dir>
uv venv --python 3.12 env
uv pip install --python env/Scripts/python.exe torch torchvision --index-url https://download.pytorch.org/whl/cpu
uv pip install --python env/Scripts/python.exe timm opencv-python-headless pillow numpy mmengine
git clone https://github.com/YvanYin/Metric3D.git      # tested at eb5b6fa (2025-03-13)
```

Two local patches to the clone (CPU-only, no mmcv):
1. `mono/utils/comm.py`: wrap `from mmcv.utils import collect_env as collect_base_env` in
   `try/except ImportError` and fall back to `from mmengine.utils.dl_utils import collect_env as collect_base_env`.
2. `mono/model/decode_heads/RAFTDepthNormalDPTDecoder5.py` and `HourGlassDecoder.py`:
   replace `device="cuda"` / `device='cuda'` with `device="cpu"`.

Weights (about 150 MB) download from `huggingface.co/JUGGHM/Metric3D` on first load; set
`TORCH_HOME` to keep them in the scratch dir.

## Scripts

| Script | Env | What |
|---|---|---|
| `predict.py <repo> <out_dir> <images...>` | the separate env | Normal map per photo, in the upright photo's camera frame (x right, y down, z forward), saved as `.npy` (H x W x 4, last channel = confidence). Portrait photos are rotated to landscape to fill the 616x1064 input. About 3.3 s per photo on CPU. |
| `wall_eval.py <dir>` | backend (`uv run python -I`) | Network wall normal vs the bolt-grid wall plane on the field captures (`<dir>/out/*.npy`). |
| `syn_eval.py <dir>` | backend | The same on `fakewall` scenes (`<dir>/out_syn`). **Not meaningful**: the network sees the synthetic renders as flat (faces 3° off the wall against a true 45°), a domain gap. |
| `real_pyr.py <dir>` | backend | Pyramid depth by searching the height whose model faces best match the network's normals, after rotating the network normals so the wall ring around the volume matches the bolt-grid wall. |

## Results so far (2026-11-20)
- Real walls, 15 captures: median error 8.4°, p90 15°. It is biased: it under-reads
  overhangs (25.8° read as 8.1°). Near-vertical walls come out at 2.6-4.5°.
- Real ridge-apex pyramids, 5 volumes, no ground truth: network depth 5-11.5 cm
  against 8.4-17.5 cm from the centroid assumption and 8.7-14.3 cm from the catalogue
  median (0.33 x edge). The ring correction needed was 8-19°.
- Verdict pending the measured volumes. If it is not within a few degrees on real faces, drop it.
