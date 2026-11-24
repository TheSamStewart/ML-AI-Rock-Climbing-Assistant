"""Run Metric3D v2 ViT-S on photos; save the normal map (camera frame of the
UPRIGHT photo: x right, y down, z forward) at network resolution as .npy.
Usage: predict.py <repo> <out_dir> <image>... (image = path; name taken from parent folder)"""
import sys, time, numpy as np, cv2, torch
from pathlib import Path
from PIL import Image, ImageOps
repo, out = sys.argv[1], Path(sys.argv[2])
model = torch.hub.load(repo, "metric3d_vit_small", pretrain=True, source="local", trust_repo=True).eval()
torch.set_num_threads(max(1, torch.get_num_threads()))
MEAN = np.array([123.675, 116.28, 103.53]); STD = np.array([58.395, 57.12, 57.375])
IN_H, IN_W = 616, 1064
def run(rgb):
    h, w = rgb.shape[:2]; s = min(IN_H / h, IN_W / w)
    img = cv2.resize(rgb, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    h2, w2 = img.shape[:2]; ph, pw = IN_H - h2, IN_W - w2
    img = cv2.copyMakeBorder(img, ph // 2, ph - ph // 2, pw // 2, pw - pw // 2, cv2.BORDER_CONSTANT, value=MEAN.tolist())
    x = torch.from_numpy(((img - MEAN) / STD).transpose(2, 0, 1)).float()[None]
    with torch.no_grad():
        _, _, o = model.inference({"input": x})
    n = o["prediction_normal"][0].numpy()
    n = n[:, ph // 2: IN_H - (ph - ph // 2), pw // 2: IN_W - (pw - pw // 2)]
    return n[:3].transpose(1, 2, 0), n[3]
for p in sys.argv[3:]:
    p = Path(p)
    rgb = np.asarray(ImageOps.exif_transpose(Image.open(p)).convert("RGB"))
    t = time.time()
    # portrait: rotate to landscape so the photo fills the 616x1064 input
    rot = rgb.shape[0] > rgb.shape[1]
    nmap, conf = run(cv2.rotate(rgb, cv2.ROTATE_90_CLOCKWISE) if rot else rgb)
    if rot:  # back to upright pixels, and rotate the vectors with them
        nmap = cv2.rotate(nmap, cv2.ROTATE_90_COUNTERCLOCKWISE)
        conf = cv2.rotate(conf, cv2.ROTATE_90_COUNTERCLOCKWISE)
        nmap = np.stack([nmap[..., 1], -nmap[..., 0], nmap[..., 2]], axis=-1)
    name = p.parent.name if p.stem == "photo" else p.stem
    np.save(out / f"{name}.npy", np.concatenate([nmap, conf[..., None]], axis=-1).astype(np.float32))
    print(name, nmap.shape, round(time.time() - t, 1), "s", flush=True)
