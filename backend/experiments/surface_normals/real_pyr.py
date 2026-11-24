import sys, json, numpy as np, cv2
from pathlib import Path
B = r"d:/ML-Rock-Climbing-Coach-App/ML-AI-Rock-Climbing-Assistant/backend"; sys.path.insert(0, B)
import eval_volume_field as e, volume, bolts, scale, angle
N = Path(sys.argv[1])
def ang(a, b): return float(np.degrees(np.arccos(np.clip(volume.unit(a) @ volume.unit(b), -1, 1))))
def rot_between(a, b):
    a, b = volume.unit(a), volume.unit(b); v = np.cross(a, b); c = a @ b
    V = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]]); return np.eye(3) + V + V @ V / (1 + c)
cases = {"2026-11-18_172513_a23e8649": [41], "2026-11-18_171935_d09906ce": [4], "2026-11-18_173610_3c85ab53": [11],
         "2026-11-18_173933_109f12fb": [3], "2026-11-18_174142_ac2132d6": [59]}
for folder, ids in cases.items():
    cap = e.load(Path(B) / "field_captures" / folder); img = cap["image"]; size = img.size
    dets = e.yolo(img, 0.25); found = bolts.detect_bolt_holes(img, dets)
    lat = scale.fit_lattice(np.array([[b["x"] * size[0], b["y"] * size[1]] for b in found]))
    K = volume.camera_matrix(size, angle.focal_px(size, cap["focal_35mm"])); gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
    g = angle.gravity_from_sensor(cap["capture"]["sensor"]["gravity_sent"])[0]
    pred = np.load(N / "out" / f"{folder}.npy")[..., :3]; ph, pw = pred.shape[:2]; sx, sy = pw / size[0], ph / size[1]
    for i in ids:
        m = e.full_mask(dets[i]); ys, xs = np.nonzero(m)
        wp = volume.wall_plane(lat, np.array([xs.mean(), ys.mean()]), K, 25); n, d = wp["n"], wp["d"]
        fit = volume.fit_volume(volume.outline_from_mask(m), n, d, K, m, gray, g)
        if fit is None or fit.get("apex_source") != "ridges": print(folder, i, "no ridge pyramid"); continue
        base_px = volume.project(fit["base"], K); apex_px = np.asarray(fit["apex_px"], float)
        ms = cv2.resize(m.astype(np.uint8), (pw, ph), interpolation=cv2.INTER_NEAREST).astype(bool)
        def orient(v): return v if v @ n > 0 else -v
        ring = cv2.dilate(ms.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool) & ~cv2.dilate(ms.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        R = rot_between(orient(pred[ring].mean(0)), n)
        # each face's pixels: triangle base[k], base[k+1], apex in px, eroded
        est = {}
        for k in range(len(base_px)):
            tri = np.array([base_px[k], base_px[(k + 1) % len(base_px)], apex_px]) * [sx, sy]
            fm = np.zeros((ph, pw), np.uint8); cv2.fillConvexPoly(fm, np.round(tri).astype(np.int32), 1)
            fm = cv2.erode(fm, np.ones((5, 5), np.uint8)).astype(bool) & ms
            if fm.sum() >= 10: est[k] = (R @ orient(pred[fm].mean(0)), fm.sum())
        rows = []
        for h in np.arange(5, 60, 0.5):
            f2 = volume.fit_pyramid(base_px, apex_px, n, d, K, height_cm=h)
            if f2 is None: continue
            cost = sum(w * ang(orient(f2["faces"][k]["normal"]), v) ** 2 for k, (v, w) in est.items() if f2["faces"][k]["visible"])
            rows.append((cost, h))
        best = min(rows)[1] if rows else float("nan")
        edges = np.linalg.norm(fit["base"] - np.roll(fit["base"], -1, 0), axis=1)
        print(f"{folder[-8:]} det{i}: base edges {np.round(edges).astype(int).tolist()} cm | depth: centroid {fit['depth_cm']:.1f}, network {best:.1f}, catalogue-typical {0.33 * edges.max():.1f} | faces used {len(est)} | ring correction {ang(orient(pred[ring].mean(0)), n):.1f} deg")
