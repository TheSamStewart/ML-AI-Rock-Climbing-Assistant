import json, sys, numpy as np, cv2
from pathlib import Path
sys.path.insert(0, r"d:/ML-Rock-Climbing-Coach-App/ML-AI-Rock-Climbing-Assistant/backend")
import volume, fakewall
N = Path(sys.argv[1])
def ang(a, b): return float(np.degrees(np.arccos(np.clip(volume.unit(a) @ volume.unit(b), -1, 1))))
def rot_between(a, b):
    a, b = volume.unit(a), volume.unit(b); v = np.cross(a, b); c = a @ b
    if np.linalg.norm(v) < 1e-9: return np.eye(3)
    V = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + V + V @ V / (1 + c)
raw_all, cor_all, wall_all, pyr = [], [], [], []
for p in sorted((N / "out_syn").glob("*.npy")):
    sc = fakewall.load(p.stem); m = sc["meta"]; ids = sc["ids"]; H, W = ids.shape
    pred = np.load(p); ph, pw = pred.shape[:2]
    nm = pred[..., :3] / np.maximum(np.linalg.norm(pred[..., :3], axis=-1, keepdims=True), 1e-9)
    small = cv2.resize(ids.astype(np.int32), (pw, ph), interpolation=cv2.INTER_NEAREST)
    wall_id = np.bincount(small[small >= 0].ravel()).argmax()
    n_true = np.array(m["wall_normal"]); K = np.array(m["K"]); d = m["d_cm"]
    def orient(v): return v if v @ n_true > 0 else -v
    wm = small == wall_id
    wall_all.append(ang(n_true, orient(nm[wm].mean(0))))
    for v in m["volumes"]:
        vis = [f for f in v["faces"] if f["visible"]]
        vm = np.isin(small, v["face_ids"])
        if vm.sum() < 50: continue
        ring = cv2.dilate(vm.astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool) & ~vm & wm
        if ring.sum() < 50: continue
        R = rot_between(orient(nm[ring].mean(0)), n_true)
        est = {}
        for f in vis:
            fm = cv2.erode((small == f["id"]).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            if fm.sum() < 15: continue
            raw = orient(nm[fm].mean(0)); cor = R @ raw
            raw_all.append(ang(raw, f["normal"])); cor_all.append(ang(cor, f["normal"]))
            est[f["face_index"]] = (cor, fm.sum())
        if v["family"].startswith("pyramid") and len(est) >= 2:
            base = np.array(v["base_px"], float); apex = np.array(v["raised_px"], float)[0]
            best = None
            for h in np.arange(3, 80, 0.5):
                fit = volume.fit_pyramid(base, apex, n_true, d, K, height_cm=h)
                if fit is None: continue
                cost = 0; ok = True
                for i, (cn, w) in est.items():
                    if i >= len(fit["faces"]): ok = False; break
                    cost += w * ang(orient(fit["faces"][i]["normal"]), cn) ** 2
                if ok and (best is None or cost < best[0]): best = (cost, h)
            cen = volume.fit_pyramid(base, apex, n_true, d, K)
            if best:
                pyr.append((p.stem, v["name"], float(np.linalg.norm(v["apex_offset_cm"])), v["height_cm"], best[1],
                            cen["heights"][0] if cen else np.nan))
print(f"wall (whole scene) normal err: median {np.median(wall_all):.1f}, p90 {np.percentile(wall_all, 90):.1f}")
print(f"volume faces RAW:       median {np.median(raw_all):.1f}, p90 {np.percentile(raw_all, 90):.1f}, n={len(raw_all)}")
print(f"volume faces CORRECTED: median {np.median(cor_all):.1f}, p90 {np.percentile(cor_all, 90):.1f}")
print("pyramid height: scene vol offset true | network-search | centroid-assumed")
for r in pyr:
    print(f"  {r[0]:16s} {r[1]:9s} off {r[2]:4.1f} true {r[3]:5.1f} | net {r[4]:5.1f} ({r[4]-r[3]:+5.1f}) | centroid {r[5]:5.1f} ({r[5]-r[3]:+5.1f})")
e_net = [abs(r[4] - r[3]) for r in pyr]; e_c = [abs(r[5] - r[3]) for r in pyr]
print(f"pyramid |height err| median: network {np.median(e_net):.1f} cm, centroid {np.nanmedian(e_c):.1f} cm")
off = [r for r in pyr if r[2] > 0]
if off:
    print(f"  off-centre only (n={len(off)}): network {np.median([abs(r[4]-r[3]) for r in off]):.1f} cm, centroid {np.nanmedian([abs(r[5]-r[3]) for r in off]):.1f} cm")
