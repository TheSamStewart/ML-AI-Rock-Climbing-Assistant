"""Synthetic volume-scan test cases: a photo plus a sideways burst. Dev only.

Used by backend/tests/test_volume_scan.py (acceptance criterion 1 of
docs/features/volume_scan.md) through sweep_case() and scenes().

A small ray caster, separate from fakewall.py: fakewall draws in image space
(its grain is screen noise), so the same wall would look different from each
camera. Here every texture is fixed to the wall or the face, in cm, so every
photo sees one physical scene. Volume shapes and wall conventions are
fakewall's (fakewall.Vol, fakewall.solid). Each rendered image takes ~15 s.
"""
import io
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/
import fakewall  # noqa: E402
import volume  # noqa: E402

WIDTH, HEIGHT = fakewall.WIDTH, fakewall.HEIGHT
BOLT_SPACING_CM = 25.0
TEX_EXTENT_CM = 700.0
TEX_RES_CM = 0.25
ROWS_PER_CHUNK = 320


@dataclass
class Synth:
    name: str
    vol: fakewall.Vol
    wall_deg: float = 0.0
    distance_cm: float = 250.0
    camera_height_cm: float = 30.0   # camera above the volume centre (positive = looking down)
    focal_35mm: float = 26.0         # the render's lens; the pipeline assumes 26
    vol_texture: float = 1.0         # volume speckle/grain strength, x the default
    wall_texture: float = 1.0
    light: tuple = (-0.35, 0.55, 1.0)
    note: str = ""


# -------------------------------------------------------------------------
# textures fixed in cm
# -------------------------------------------------------------------------

def _texture(seed: int) -> np.ndarray:
    """A square noise texture over [-E, E] cm at TEX_RES_CM: grain (10 cm),
    blotches (2 cm) and speckle (0.5 cm), roughly zero mean, unit-ish spread."""
    rng = np.random.default_rng(seed)
    n = int(2 * TEX_EXTENT_CM / TEX_RES_CM)
    out = np.zeros((n, n), np.float32)
    for cell_cm, amp, stretch in ((10.0, 1.0, 4.0), (2.0, 0.6, 1.0), (0.5, 0.5, 1.0)):
        k = max(2, int(2 * TEX_EXTENT_CM / cell_cm))
        small = rng.normal(0, 1, (max(2, int(k / stretch)), k)).astype(np.float32)
        out += amp * cv2.resize(small, (n, n), interpolation=cv2.INTER_CUBIC)
    return out


def _sample(tex: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    n = tex.shape[0]
    x = np.clip((np.asarray(u, np.float64) + TEX_EXTENT_CM) / TEX_RES_CM, 0, n - 1.001)
    y = np.clip((np.asarray(v, np.float64) + TEX_EXTENT_CM) / TEX_RES_CM, 0, n - 1.001)
    x0, y0 = x.astype(np.int64), y.astype(np.int64)
    fx, fy = (x - x0).astype(np.float32), (y - y0).astype(np.float32)
    return ((tex[y0, x0] * (1 - fx) + tex[y0, x0 + 1] * fx) * (1 - fy)
            + (tex[y0 + 1, x0] * (1 - fx) + tex[y0 + 1, x0 + 1] * fx) * fy)


def _bolt_factor(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Darkening from the centred-square bolt lattice at wall cm (a, b)."""
    da, db = a / BOLT_SPACING_CM, b / BOLT_SPACING_CM
    r1 = np.hypot(da - np.round(da), db - np.round(db))
    r2 = np.hypot(da - 0.5 - np.round(da - 0.5), db - 0.5 - np.round(db - 0.5))
    r = np.minimum(r1, r2) * BOLT_SPACING_CM
    outer = np.clip((r - 0.95) / 0.15, 0, 1)          # 1 outside the 1.1 cm hole
    inner = np.clip((r - 0.45) / 0.15, 0, 1)
    return 0.10 + 0.12 * inner + 0.78 * outer


# -------------------------------------------------------------------------
# cameras
# -------------------------------------------------------------------------

def look_at(position: np.ndarray, target: np.ndarray) -> np.ndarray:
    """World -> camera rotation (rows x right, y down, z forward), no roll."""
    z = volume.unit(target - position)
    x = volume.unit(np.cross(z, [0.0, 1.0, 0.0]))
    y = np.cross(z, x)
    return np.vstack([x, y, z])


def wall_frame(wall_deg: float) -> dict:
    w = np.radians(wall_deg)
    return {"n_world": np.array([0.0, -np.sin(w), np.cos(w)]),
            "u_world": np.array([0.0, np.cos(w), np.sin(w)]),
            "r_world": np.array([1.0, 0.0, 0.0])}


# -------------------------------------------------------------------------
# render
# -------------------------------------------------------------------------

def render(sc: Synth, position: np.ndarray, target: np.ndarray, textures: dict, faces: list) -> tuple:
    """(BGR image, volume mask) seen from `position` looking at `target`."""
    R = look_at(position, target)
    f = fakewall.focal_px((WIDTH, HEIGHT), sc.focal_35mm)
    Kinv = np.linalg.inv(volume.camera_matrix((WIDTH, HEIGHT), f))
    fr = wall_frame(sc.wall_deg)
    light = volume.unit(np.asarray(sc.light, float))
    wall_albedo = np.array([120, 165, 205], np.float32)
    wall_shade = 0.45 + 0.55 * max(0.0, float(fr["n_world"] @ light))
    image = np.zeros((HEIGHT, WIDTH, 3), np.float32)
    vmask = np.zeros((HEIGHT, WIDTH), bool)
    us = np.arange(WIDTH, dtype=np.float64)
    for r0 in range(0, HEIGHT, ROWS_PER_CHUNK):
        rows = np.arange(r0, min(HEIGHT, r0 + ROWS_PER_CHUNK), dtype=np.float64)
        uu, vv = np.meshgrid(us, rows)
        pix = np.stack([uu.ravel(), vv.ravel(), np.ones(uu.size)], 1)
        dirs = (pix @ Kinv.T) @ R                       # camera -> world directions
        # wall
        denom = dirs @ fr["n_world"]
        t_best = -(position @ fr["n_world"]) / np.where(np.abs(denom) < 1e-12, -1e-12, denom)
        t_best = np.where(t_best > 0, t_best, np.inf)
        hit = np.full(len(dirs), -1)
        for k, face in enumerate(faces):
            dn = dirs @ face["n"]
            t = (face["n"] @ face["c0"] - position @ face["n"]) / np.where(np.abs(dn) < 1e-12, 1e-12, dn)
            P = position + t[:, None] * dirs
            s = (P - face["c0"]) @ face["e1"]
            q = (P - face["c0"]) @ face["e2"]
            inside = (t > 0) & (t < t_best)
            for (s1, q1), (s2, q2) in zip(face["poly2d"], np.roll(face["poly2d"], -1, axis=0)):
                inside &= (s2 - s1) * (q - q1) - (q2 - q1) * (s - s1) >= 0
            t_best = np.where(inside, t, t_best)
            hit = np.where(inside, k, hit)
        P = position + np.where(np.isfinite(t_best), t_best, 0)[:, None] * dirs
        col = np.zeros((len(dirs), 3), np.float32)
        on_wall = (hit < 0) & np.isfinite(t_best)
        if on_wall.any():
            a, b = P[on_wall] @ fr["r_world"], P[on_wall] @ fr["u_world"]
            tex = _sample(textures["wall"], a.astype(np.float32), b.astype(np.float32)).ravel()
            val = wall_shade * (1 + 0.06 * sc.wall_texture * tex) * _bolt_factor(a, b)
            col[on_wall] = wall_albedo[None] * val[:, None].astype(np.float32)
        for k, face in enumerate(faces):
            m = hit == k
            if not m.any():
                continue
            s = (P[m] - face["c0"]) @ face["e1"]
            q = (P[m] - face["c0"]) @ face["e2"]
            tex = _sample(textures["vol"], (s + 37 * k).astype(np.float32), (q - 53 * k).astype(np.float32)).ravel()
            val = face["shade"] * (1 + 0.08 * sc.vol_texture * tex)
            col[m] = np.asarray(sc.vol.albedo, np.float32)[None] * val[:, None].astype(np.float32)
        image[r0:r0 + len(rows)] = col.reshape(len(rows), WIDTH, 3)
        vmask[r0:r0 + len(rows)] = (hit >= 0).reshape(len(rows), WIDTH)
    image = cv2.GaussianBlur(image, (0, 0), 0.6)
    image += np.random.default_rng(abs(hash((sc.name, tuple(position)))) % 2**32).normal(0, 2.0, image.shape).astype(np.float32)
    return np.clip(image, 0, 255).astype(np.uint8), vmask, R


def _setup(sc: Synth) -> dict:
    """Scene geometry for sweep_case(): wall frame, faces,
    look-at target, the front camera position and the textures."""
    fr = wall_frame(sc.wall_deg)
    s = fakewall.solid(sc.vol, fr)
    groups = [np.asarray(g, float) for g in s["groups"]]
    middle = np.vstack(groups).mean(0)
    light = volume.unit(np.asarray(sc.light, float))
    faces = []
    for g in groups:
        n = volume.unit(np.cross(g[1] - g[0], g[-1] - g[0]))
        if n @ (g.mean(0) - middle) < 0:
            n = -n
        e1 = volume.unit(g[1] - g[0])
        e2 = np.cross(n, e1)
        poly = np.column_stack([(g - g[0]) @ e1, (g - g[0]) @ e2])
        area = 0.5 * np.sum(poly[:, 0] * np.roll(poly[:, 1], -1) - np.roll(poly[:, 0], -1) * poly[:, 1])
        if area < 0:
            poly = poly[::-1]
        faces.append({"c0": g[0], "e1": e1, "e2": e2, "n": n, "poly2d": poly, "corners": g,
                      "shade": 0.45 + 0.55 * max(0.0, float(n @ light))})
    centre_wall = np.asarray(sc.vol.centre, float)
    target = fakewall.wall_point(centre_wall[0], centre_wall[1], fr, sc.vol.height_cm / 2)[0]
    horiz = volume.unit(np.array([fr["n_world"][0], 0.0, fr["n_world"][2]]))
    base_pos = target + sc.distance_cm * horiz + np.array([0, sc.camera_height_cm, 0])
    return {"fr": fr, "faces": faces, "target": target, "base_pos": base_pos,
            "textures": {"wall": _texture(1), "vol": _texture(2)}}


def _truth_faces(setup: dict, camera_pos: np.ndarray) -> list[dict]:
    """Faces visible from `camera_pos`, steepness / facing as volume.describe_face gives them."""
    out = []
    for k, face in enumerate(setup["faces"]):
        if face["n"] @ (camera_pos - face["corners"].mean(0)) <= 0:
            continue
        d = volume.describe_face(face["n"], setup["fr"]["n_world"], np.array([0.0, -1.0, 0.0]))
        out.append({"number": k + 1, "angle_deg": d["steepness_deg"], "facing": d["facing"],
                    "facing_deg": d["facing_deg"], "area_cm2": round(float(_area(face["corners"])), 1)})
    return out


def _as_photo(img_bgr: np.ndarray, quality: int = 92) -> Image.Image:
    """The rendered image through a JPEG round trip, as the phone would send it."""
    ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return Image.open(io.BytesIO(buf.tobytes())).convert("RGB")


def sweep_case(sc: Synth, n_frames: int = 8, span_cm: float = 60.0) -> dict:
    """A volume-scan test case in memory: the front photo plus `n_frames` burst
    frames along one sideways step of `span_cm` (to the right; negative = left),
    every frame turned to look at the volume.

    Returns photo (PIL), frames (PIL list), gravity (the phone reading at the
    photo), volume_polygon (normalised, on the photo), detections (one VOLUME),
    truth_faces (visible from the photo) and depth_cm."""
    setup = _setup(sc)
    target, base = setup["target"], setup["base_pos"]
    img, vmask, R = render(sc, base, target, setup["textures"], setup["faces"])
    cs, _ = cv2.findContours(vmask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cs, key=cv2.contourArea).reshape(-1, 2)
    polygon = [{"x": float(x) / WIDTH, "y": float(y) / HEIGHT} for x, y in c[:: max(1, len(c) // 200)]]
    g_cam = R @ np.array([0.0, -1.0, 0.0])
    gravity = [float(g_cam[0]), float(-g_cam[1]), float(-g_cam[2])]  # iOS device-frame convention
    frames = []
    for dx in np.linspace(span_cm / n_frames, span_cm, n_frames):
        f_img, _, _ = render(sc, base + np.array([dx, 0.0, 0.0]), target, setup["textures"], setup["faces"])
        frames.append(_as_photo(f_img))
    return {"photo": _as_photo(img), "frames": frames, "gravity": gravity, "volume_polygon": polygon,
            "detections": [{"id": 0, "class_name": "VOLUME", "confidence": 1.0, "polygon": polygon}],
            "truth_faces": _truth_faces(setup, base), "depth_cm": sc.vol.height_cm,
            "wall_deg": sc.wall_deg}


def _area(corners: np.ndarray) -> float:
    c = corners - corners.mean(0)
    return 0.5 * float(np.linalg.norm(sum(np.cross(c[i], c[(i + 1) % len(c)]) for i in range(len(c)))))


# -------------------------------------------------------------------------
# scenes
# -------------------------------------------------------------------------
GREY, RED, BLUE, YELLOW, PURPLE = (150, 150, 150), (60, 60, 185), (185, 110, 60), (70, 200, 220), (140, 70, 120)


def scenes() -> list[Synth]:
    V = fakewall.Vol
    return [
        Synth("s_pyr4_wall0", V("p", "pyramid4", (0, 0), (70, 70), 30, (4, -3), PURPLE)),
        Synth("s_pyr3_wall0", V("p", "pyramid3", (0, 0), (80, 80), 25, (0, 0), PURPLE, 10)),
        Synth("s_wedge_wall0", V("w", "wedge", (0, 0), (90, 45), 35, albedo=YELLOW)),
        Synth("s_box_wall0", V("b", "box", (0, 0), (50, 35), 25, albedo=GREY, rotation_deg=15)),
        Synth("s_pyr4_over20", V("p", "pyramid4", (0, 0), (70, 60), 35, (-6, 4), RED), wall_deg=20),
        Synth("s_wedge_over35", V("w", "wedge", (0, 0), (80, 50), 30, albedo=BLUE, rotation_deg=90), wall_deg=35),
        Synth("s_box_over20", V("b", "box", (0, 0), (40, 40), 20, albedo=YELLOW), wall_deg=20),
        Synth("s_pyr3_slab15", V("p", "pyramid3", (0, 0), (90, 90), 30, (5, 0), GREY, -20), wall_deg=-15),
        Synth("s_wedge_slab15", V("w", "wedge", (0, 0), (70, 40), 25, albedo=RED), wall_deg=-15),
        Synth("s_pyr4_big", V("p", "pyramid4", (0, 0), (110, 100), 50, (0, 8), BLUE), distance_cm=300),
        Synth("s_wedge_thin", V("w", "wedge", (0, 0), (100, 20), 15, albedo=YELLOW), note="thin faces"),
        Synth("s_box_dark", V("b", "box", (0, 0), (60, 30), 20, albedo=(36, 36, 40)), note="dark volume"),
        Synth("s_pyr3_far", V("p", "pyramid3", (0, 0), (60, 60), 20, (0, 0), RED), distance_cm=320),
    ]
