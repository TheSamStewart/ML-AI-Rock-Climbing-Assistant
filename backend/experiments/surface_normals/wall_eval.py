import json, sys, numpy as np, cv2
from pathlib import Path
sys.path.insert(0, r"d:/ML-Rock-Climbing-Coach-App/ML-AI-Rock-Climbing-Assistant/backend")
import scale, volume, angle
N = Path(sys.argv[1]); CAP = Path(r"d:/ML-Rock-Climbing-Coach-App/ML-AI-Rock-Climbing-Assistant/backend/field_captures")
def ang(a, b): return float(np.degrees(np.arccos(np.clip(abs(volume.unit(a) @ volume.unit(b)), -1, 1))))
allerr = {"mine": [], "alt": []}; per = []
for f in sorted(CAP.iterdir()):
    if not (N / "out" / f"{f.name}.npy").exists(): continue
    c = json.loads((f / "capture.json").read_text())
    W, H = c["photo"]["upright_size"]
    pred = np.load(N / "out" / f"{f.name}.npy"); ph, pw = pred.shape[:2]
    bolts = np.array([[b["x"] * W, b["y"] * H] for b in c["bolts"]])
    lat = scale.fit_lattice(bolts)
    K = volume.camera_matrix((W, H), angle.focal_px((W, H), None))
    occ = np.zeros((ph, pw), np.uint8)
    for d in c["detections"]:
        pts = np.array([[p["x"] * pw, p["y"] * ph] for p in d["polygon"]], np.int32)
        cv2.fillPoly(occ, [pts], 1)
    occ = cv2.dilate(occ, np.ones((9, 9), np.uint8))
    g = angle.gravity_from_sensor(c["sensor"]["gravity_sent"])[0]
    e_m, e_a, steep = [], [], []
    for x, y in lat.xy[:: max(1, len(lat.xy) // 40)]:
        wp = volume.wall_plane(lat, np.array([x, y]), K, 25)
        if wp is None or not wp["trusted"]: continue
        u, v = int(x / W * pw), int(y / H * ph)
        if occ[max(0, v - 3):v + 4, max(0, u - 3):u + 4].any(): continue
        p = pred[max(0, v - 3):v + 4, max(0, u - 3):u + 4, :3].reshape(-1, 3).mean(0)
        alt = np.array([-p[1], p[0], p[2]])  # what the vector would be with the opposite rotation
        e_m.append(ang(wp["n"], p)); e_a.append(ang(wp["n"], alt))
        pp = volume.unit(p); pp = pp if pp @ wp["n"] > 0 else -pp
        steep.append((volume.describe_face(wp["n"], wp["n"], g)["steepness_deg"], volume.describe_face(pp, wp["n"], g)["steepness_deg"]))
    if not e_m: continue
    allerr["mine"] += e_m; allerr["alt"] += e_a
    s = np.array(steep)
    print(f"{f.name}: {len(e_m):2d} pts | normal err median {np.median(e_m):5.1f} (alt rotation {np.median(e_a):5.1f})"
          f" | wall angle bolts {np.median(s[:, 0]):+5.1f}  network {np.median(s[:, 1]):+5.1f}")
for k, v in allerr.items():
    print(f"ALL {k}: median {np.median(v):.1f} deg, p90 {np.percentile(v, 90):.1f}, n={len(v)}")
