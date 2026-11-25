"""DEV ONLY - a synthetic "fake wall" renderer with exact ground truth, for
eval_volume.py. Not used by the API.

Renders, per scene, a plywood wall carrying the real bolt grid (a centred
square lattice: a 25 cm square with a bolt at each corner and one in the
middle, the same lattice scale.py fits) plus climbing volumes under a simple
Lambertian light (ambient + one directional term), and writes:

  <scene>.jpg        the photo, 1776 x 3840 like the field phone
  <scene>_faces.npy  int16 per-pixel id map: -1 off-wall, 0 wall,
                     1..N one id per volume FACE, 1000+k one id per hold
  <scene>.json       camera matrix, gravity, wall normal/angle/pitch/distance,
                     per-face truth (steepness_deg, facing_deg, normal, volume),
                     per-volume shape family / base in wall cm / true height,
                     per-hold truth point and standoff.

Conventions are volume.py's: camera x right, y down, z forward; the wall is
`n . X = d` with `n` facing the camera so d is negative; a point h cm proud of
the wall has `n . X = d + h`.

World frame used to lay scenes out (right-handed): X right, Y up, Z out of the
wall towards the climber. A wall at `wall_deg` from vertical (positive =
overhanging) has normal (0, -sin w, cos w) and its own "up" (0, cos w, sin w),
so wall coordinates are (a = right, b = up the wall) in cm from the point that
lands on the optical axis.

Truth face angles are produced by volume._face / volume.describe_face on the
exact cm corners, so the only difference between truth and a fit is the
geometry recovered - not the code that names the angle. eval_volume.py checks
describe_face against hand-computed cases separately.

Usage (from backend/):
  uv run python fakewall.py                      # every scene -> fakewall_out/
  uv run python fakewall.py --only box_centre sq_centre
  uv run python fakewall.py --out /tmp/wall --quality 88
  uv run python fakewall.py --list
"""

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

import volume

WIDTH, HEIGHT = 1776, 3840
FOCAL_35MM = 26.0
DIAGONAL_35MM = 43.27
BOLT_SPACING_CM = 25.0
# The wall slab rendered, in wall cm: wide enough to fill the frame at 400 cm.
WALL_EXTENT = 600.0
HOLD_ID_BASE = 1000
OUT_DIR = Path("fakewall_out")


def focal_px(size=(WIDTH, HEIGHT), focal_35mm=FOCAL_35MM) -> float:
    """Focal length in px from the 35 mm equivalent (angle.focal_px's maths)."""
    return focal_35mm / DIAGONAL_35MM * float(np.hypot(*size))


@dataclass
class Vol:
    """One volume, laid out in wall coordinates (cm)."""
    name: str
    family: str                      # pyramid3 | pyramid4 | wedge | box | cylinder
    centre: tuple                    # (a, b) of the base centre, wall cm
    size: tuple                      # (width across a, length along b), cm
    height_cm: float
    apex_offset: tuple = (0.0, 0.0)  # pyramids: how far off the base centroid
    albedo: tuple = (150, 150, 150)  # BGR
    rotation_deg: float = 0.0
    facets: int = 10                 # cylinder only


@dataclass
class Hold:
    """A hold blob. `vol`/`face` index the volume face it sits on, or (-1, -1)
    for a hold on the wall itself, which then occludes whatever is behind it."""
    vol: int
    face: int
    uv: tuple                        # within-face coordinates, or wall (a, b)
    radius_cm: float = 5.0
    albedo: tuple = (40, 60, 200)


@dataclass
class Scene:
    name: str
    wall_deg: float = 0.0
    pitch_deg: float = 12.0
    distance_cm: float = 300.0
    volumes: list = field(default_factory=list)
    holds: list = field(default_factory=list)
    wall_albedo: tuple = (120, 165, 205)   # plywood, BGR
    light: tuple = (-0.35, 0.55, 1.0)      # world direction TO the light
    ambient: float = 0.45
    diffuse: float = 0.55
    grain: float = 7.0                     # plywood grain amplitude, grey levels
    pixel_noise: float = 2.0
    wall_top_cm: float | None = None       # finite wall top, to show off-wall
    note: str = ""


# -------------------------------------------------------------------------
# frames
# -------------------------------------------------------------------------

def frames(scene: Scene, f: float | None = None) -> dict:
    """Everything fixed by the wall angle, camera pitch and distance."""
    f = focal_px() if f is None else f
    w, p = np.radians(scene.wall_deg), np.radians(scene.pitch_deg)
    n_world = np.array([0.0, -np.sin(w), np.cos(w)])
    u_world = np.array([0.0, np.cos(w), np.sin(w)])
    r_world = np.array([1.0, 0.0, 0.0])
    z_cam = np.array([0.0, np.sin(p), -np.cos(p)])      # camera forward
    x_cam = np.array([1.0, 0.0, 0.0])
    y_cam = np.cross(z_cam, x_cam)                      # camera down
    R = np.vstack([x_cam, y_cam, z_cam])                # world -> camera
    target = np.zeros(3)                                # wall origin on the axis
    camera = target - scene.distance_cm * z_cam
    n_cam = R @ n_world
    d = float(n_cam @ (R @ (target - camera)))
    return {
        "f": f, "K": volume.camera_matrix((WIDTH, HEIGHT), f), "R": R, "camera": camera,
        "n_world": n_world, "u_world": u_world, "r_world": r_world,
        "n": n_cam, "d": d, "gravity": R @ np.array([0.0, -1.0, 0.0]),
        "light": volume.unit(np.asarray(scene.light, dtype=float)),
    }


def to_cam(points: np.ndarray, fr: dict) -> np.ndarray:
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    return (points - fr["camera"]) @ fr["R"].T


def wall_point(a, b, fr: dict, h: float = 0.0) -> np.ndarray:
    """Wall coordinates (a right, b up) plus h cm off the wall -> world cm."""
    a, b = np.atleast_1d(a).astype(float), np.atleast_1d(b).astype(float)
    return a[:, None] * fr["r_world"] + b[:, None] * fr["u_world"] + h * fr["n_world"]


def px(points_world: np.ndarray, fr: dict) -> np.ndarray:
    return volume.project(to_cam(points_world, fr), fr["K"])


# -------------------------------------------------------------------------
# solids
# -------------------------------------------------------------------------

def _base_wall(vol: Vol) -> np.ndarray:
    """Base corners in wall cm, ordered so that for a wedge base[1]-base[2] and
    base[3]-base[0] are the two edges the ridge spans (volume.faces_from_top's
    convention)."""
    w, l = vol.size
    if vol.family == "pyramid3":
        angles = np.radians([90.0, 210.0, 330.0])
        pts = np.column_stack([w / 2 * np.cos(angles), l / 2 * np.sin(angles)])
    else:
        pts = np.array([[-w / 2, -l / 2], [w / 2, -l / 2], [w / 2, l / 2], [-w / 2, l / 2]])
    t = np.radians(vol.rotation_deg)
    rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    return pts @ rot.T + np.asarray(vol.centre, dtype=float)


def solid(vol: Vol, fr: dict) -> dict:
    """World-cm geometry of one volume: base, raised vertices and face corner
    groups. Never the bottom face - it is flush against the wall."""
    base_wall = _base_wall(vol)
    base = wall_point(base_wall[:, 0], base_wall[:, 1], fr)
    h = vol.height_cm
    out = {"base_wall": base_wall, "base": base, "height_cm": h, "family": vol.family}

    if vol.family in ("pyramid3", "pyramid4"):
        centroid = base_wall.mean(axis=0) + np.asarray(vol.apex_offset, dtype=float)
        apex = wall_point(centroid[0], centroid[1], fr, h)[0]
        out["groups"] = [[base[i], base[(i + 1) % len(base)], apex] for i in range(len(base))]
        out["raised"] = apex.reshape(1, 3)
    elif vol.family == "wedge":
        mid = np.vstack([(base_wall[1] + base_wall[2]) / 2, (base_wall[3] + base_wall[0]) / 2])
        top = wall_point(mid[:, 0], mid[:, 1], fr, h)
        out["raised"] = top
        out["groups"] = [[base[0], base[1], top[0], top[1]],
                         [base[2], base[3], top[1], top[0]],
                         [base[1], base[2], top[0]],
                         [base[3], base[0], top[1]]]
    elif vol.family == "box":
        top = wall_point(base_wall[:, 0], base_wall[:, 1], fr, h)
        out["raised"] = top
        groups = [[base[i], base[(i + 1) % 4], top[(i + 1) % 4], top[i]] for i in range(4)]
        groups.append(list(top[::-1]))
        out["groups"] = groups
    elif vol.family == "cylinder":
        # Half-cylinder lying on the wall, axis horizontal (along a), radius h.
        w, _ = vol.size
        a0, b0 = vol.centre
        t = np.linspace(0.0, np.pi, vol.facets + 1)
        prof = np.column_stack([b0 + h * np.cos(t), h * np.sin(t)])   # (b, standoff)
        left = np.vstack([wall_point(a0 - w / 2, b, fr, s)[0] for b, s in prof])
        right = np.vstack([wall_point(a0 + w / 2, b, fr, s)[0] for b, s in prof])
        groups = [[left[i], right[i], right[i + 1], left[i + 1]] for i in range(vol.facets)]
        groups.append(list(left))
        groups.append(list(right[::-1]))
        out["groups"] = groups
        out["raised"] = np.vstack([left[1:-1], right[1:-1]])
        out["base"] = np.vstack([left[0], right[0], right[-1], left[-1]])
        out["base_wall"] = np.array([[a0 - w / 2, b0 + h], [a0 + w / 2, b0 + h],
                                     [a0 + w / 2, b0 - h], [a0 - w / 2, b0 - h]])
    else:
        raise ValueError(vol.family)
    return out


def face_truth(groups, fr: dict) -> list[dict | None]:
    """volume._face + describe_face on the exact cm corners of each face."""
    middle = to_cam(np.vstack([np.asarray(g) for g in groups]), fr).mean(axis=0)
    out = []
    for g in groups:
        face = volume._face(to_cam(np.asarray(g), fr), middle)
        if face is not None:
            face.update(volume.describe_face(face["normal"], fr["n"], fr["gravity"]))
        out.append(face)
    return out


# -------------------------------------------------------------------------
# rendering
# -------------------------------------------------------------------------

def _shade(normal_world: np.ndarray, fr: dict, scene: Scene) -> float:
    lit = max(0.0, float(volume.unit(normal_world) @ fr["light"]))
    return scene.ambient + scene.diffuse * lit


def _fill(image, ids, poly_px, colour, face_id) -> None:
    if poly_px is None or not np.isfinite(poly_px).all():
        return
    pts = np.round(np.clip(poly_px, -1e5, 1e5)).astype(np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(image, [pts], tuple(float(c) for c in colour), lineType=cv2.LINE_AA)
    cv2.fillPoly(ids, [pts], int(face_id))


def _blob(image, ids, centre_world, radius_cm, colour, blob_id, fr) -> None:
    c = px(centre_world.reshape(1, 3), fr)[0]
    if not np.isfinite(c).all() or abs(c[0]) > 1e5 or abs(c[1]) > 1e5:
        return
    edge_r = px((centre_world + radius_cm * fr["r_world"]).reshape(1, 3), fr)[0]
    edge_u = px((centre_world + radius_cm * fr["u_world"]).reshape(1, 3), fr)[0]
    if not (np.isfinite(edge_r).all() and np.isfinite(edge_u).all()):
        return
    ax = max(1.5, float(np.linalg.norm(edge_r - c)))
    ay = max(1.5, float(np.linalg.norm(edge_u - c)))
    ang = float(np.degrees(np.arctan2(edge_r[1] - c[1], edge_r[0] - c[0])))
    box = ((float(c[0]), float(c[1])), (2 * ax, 2 * ay), ang)
    cv2.ellipse(image, box, tuple(float(v) for v in colour), -1, cv2.LINE_AA)
    cv2.ellipse(ids, box, int(blob_id), -1)


def render(scene: Scene) -> dict:
    """The scene's image, id map and ground truth, all in memory."""
    fr = frames(scene)
    rng = np.random.default_rng(abs(hash(scene.name)) % (2**32))
    ids = np.zeros((HEIGHT, WIDTH), dtype=np.int16)

    # Plywood: flat Lambertian base plus low-frequency grain, streaked along a.
    wall_shade = _shade(fr["n_world"], fr, scene)
    base_colour = np.asarray(scene.wall_albedo, dtype=float) * wall_shade
    coarse = rng.normal(0.0, 1.0, (HEIGHT // 24, max(2, WIDTH // 96)))
    grain = cv2.resize(coarse, (WIDTH, HEIGHT), interpolation=cv2.INTER_CUBIC) * scene.grain
    image = np.clip(base_colour[None, None, :] + grain[:, :, None], 0, 255)

    # Off-wall: everything above a finite wall top is dark room.
    if scene.wall_top_cm is not None:
        a = np.array([-WALL_EXTENT, WALL_EXTENT])
        b = np.array([scene.wall_top_cm, scene.wall_top_cm])
        edge = px(wall_point(a, b, fr), fr)
        #The camera has no roll, so "off the top of the wall" is everything
        #above that edge: the edge extended straight up out of the frame.
        corners = np.vstack([edge, [edge[1, 0], -1e4], [edge[0, 0], -1e4]])
        if np.isfinite(corners).all():
            dark = np.zeros((HEIGHT, WIDTH), np.uint8)
            cv2.fillPoly(dark, [np.round(np.clip(corners, -1e5, 1e5)).astype(np.int32)], 1)
            off = dark.astype(bool)
            image[off] = (28.0, 30.0, 34.0)
            ids[off] = -1

    # Bolt holes on the centred square lattice: corners plus centres.
    reach = int(np.ceil(WALL_EXTENT / BOLT_SPACING_CM))
    gi, gj = np.meshgrid(np.arange(-reach, reach + 1), np.arange(-reach, reach + 1))
    grid = np.vstack([np.column_stack([gi.ravel(), gj.ravel()]).astype(float),
                      np.column_stack([gi.ravel() + 0.5, gj.ravel() + 0.5])])
    bolt_world = wall_point(grid[:, 0] * BOLT_SPACING_CM, grid[:, 1] * BOLT_SPACING_CM, fr)
    bolt_px = px(bolt_world, fr)
    inside = (np.isfinite(bolt_px).all(axis=1)
              & (bolt_px[:, 0] > -40) & (bolt_px[:, 0] < WIDTH + 40)
              & (bolt_px[:, 1] > -40) & (bolt_px[:, 1] < HEIGHT + 40))
    if scene.wall_top_cm is not None:
        inside &= grid[:, 1] * BOLT_SPACING_CM <= scene.wall_top_cm
    for world in bolt_world[inside]:
        _blob(image, ids, world, 1.1, base_colour * 0.22, 0, fr)
        _blob(image, ids, world, 0.55, base_colour * 0.10, 0, fr)

    # Volumes, far face first (they are convex, so only front faces are drawn).
    truth_volumes, groups_world, next_id, drawn = [], [], 1, []
    for vi, vol in enumerate(scene.volumes):
        s = solid(vol, fr)
        faces = face_truth(s["groups"], fr)
        middle = np.vstack([np.asarray(g) for g in s["groups"]]).mean(axis=0)
        entry = {"index": vi, "name": vol.name, "family": vol.family,
                 "height_cm": vol.height_cm, "apex_offset_cm": list(vol.apex_offset),
                 "base_wall_cm": np.round(s["base_wall"], 4).tolist(),
                 "base_cm": np.round(to_cam(s["base"], fr), 6).tolist(),
                 "base_px": np.round(px(s["base"], fr), 3).tolist(),
                 "raised_px": np.round(px(s["raised"], fr), 3).tolist(),
                 "raised_cm": np.round(to_cam(s["raised"], fr), 6).tolist(),
                 "face_ids": [], "faces": []}
        groups_world.append(s["groups"])
        for fi, (group, face) in enumerate(zip(s["groups"], faces)):
            fid, next_id = next_id, next_id + 1
            entry["face_ids"].append(fid)
            if face is None:
                entry["faces"].append({"id": fid, "volume": vi, "face_index": fi,
                                       "degenerate": True, "visible": False})
                continue
            g = np.asarray(group)
            normal_world = volume.unit(np.cross(g[1] - g[0], g[-1] - g[0]))
            if normal_world @ (g.mean(axis=0) - middle) < 0:
                normal_world = -normal_world
            entry["faces"].append({
                "id": fid, "volume": vi, "volume_name": vol.name, "face_index": fi,
                "steepness_deg": face["steepness_deg"], "facing_deg": face["facing_deg"],
                "facing": face["facing"], "off_wall_deg": face["off_wall_deg"],
                "normal": np.round(face["normal"], 9).tolist(),
                "area_cm2": face["area_cm2"], "visible": bool(face["visible"]),
                "corners_cm": np.round(face["corners"], 6).tolist(),
            })
            if face["visible"]:
                shade = _shade(normal_world, fr, scene)
                jitter = 1.0 + 0.04 * (fi % 3 - 1)
                colour = np.clip(np.asarray(vol.albedo, dtype=float) * shade * jitter, 0, 255)
                drawn.append((float(to_cam(g.mean(axis=0).reshape(1, 3), fr)[0, 2]),
                              px(g, fr), colour, fid))
        truth_volumes.append(entry)

    for _, poly, colour, fid in sorted(drawn, key=lambda t: -t[0]):
        _fill(image, ids, poly, colour, fid)

    # Holds last, so a hold on the wall in front of a base edge occludes it.
    truth_holds = []
    for hi, hold in enumerate(scene.holds):
        hidden = False
        if hold.vol < 0:
            point = wall_point(hold.uv[0], hold.uv[1], fr)[0]
            normal_world, face_id, face_index = fr["n_world"], 0, -1
        else:
            g = np.asarray(groups_world[hold.vol][hold.face])
            point = g[0] + hold.uv[0] * (g[1] - g[0]) + hold.uv[1] * (g[-1] - g[0])
            normal_world = volume.unit(np.cross(g[1] - g[0], g[-1] - g[0]))
            face_id = truth_volumes[hold.vol]["face_ids"][hold.face]
            face_index = hold.face
            hidden = not truth_volumes[hold.vol]["faces"][hold.face].get("visible")
        blob_id = HOLD_ID_BASE + hi
        shade = _shade(normal_world, fr, scene)
        _blob(image, ids, point, hold.radius_cm,
              np.clip(np.asarray(hold.albedo, dtype=float) * shade, 0, 255), blob_id, fr)
        point_cam = to_cam(point.reshape(1, 3), fr)[0]
        truth_holds.append({
            "id": blob_id, "volume": hold.vol, "face": face_index, "face_id": face_id,
            "px": np.round(px(point.reshape(1, 3), fr)[0], 3).tolist(),
            "point_cm": np.round(point_cam, 6).tolist(), "radius_cm": hold.radius_cm,
            "standoff_cm": round(volume.height_of(point_cam, fr["n"], fr["d"]), 4),
            "on_wall": bool(hold.vol < 0),
            #A hold put on a face that is turned away from the camera is drawn
            #anyway, but nothing could see it: the evaluation skips it.
            "hidden": bool(hidden),
        })

    if scene.pixel_noise > 0:
        image = image + rng.normal(0.0, scene.pixel_noise, image.shape)
    image = np.clip(image, 0, 255).astype(np.uint8)

    meta = {
        "scene": scene.name, "note": scene.note,
        "size": [WIDTH, HEIGHT], "f_px": round(fr["f"], 4), "focal_35mm": FOCAL_35MM,
        "K": fr["K"].tolist(), "down": fr["gravity"].tolist(), "wall_normal": fr["n"].tolist(),
        "wall_deg": scene.wall_deg, "pitch_deg": scene.pitch_deg,
        "distance_cm": scene.distance_cm, "d_cm": round(fr["d"], 6),
        "bolt_spacing_cm": BOLT_SPACING_CM,
        "bolts_px": np.round(bolt_px[inside], 3).tolist(),
        "bolts_grid": grid[inside].tolist(),
        "light_world": fr["light"].tolist(), "ambient": scene.ambient, "diffuse": scene.diffuse,
        "volumes": truth_volumes, "holds": truth_holds, "hold_id_base": HOLD_ID_BASE,
    }
    return {"image": image, "ids": ids, "meta": meta}


def write(scene: Scene, out: Path, quality: int = 92) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    result = render(scene)
    cv2.imwrite(str(out / f"{scene.name}.jpg"), result["image"],
                [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    np.save(out / f"{scene.name}_faces.npy", result["ids"])
    (out / f"{scene.name}.json").write_text(json.dumps(result["meta"]))
    return result


def load(name: str, out: Path = OUT_DIR) -> dict:
    """A rendered scene back from disk, the way the pipeline would see it."""
    meta = json.loads((out / f"{name}.json").read_text())
    image = cv2.imread(str(out / f"{name}.jpg"), cv2.IMREAD_COLOR)
    ids = np.load(out / f"{name}_faces.npy")
    return {"meta": meta, "image": image, "ids": ids,
            "gray": cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)}


# -------------------------------------------------------------------------
# the scenes
# -------------------------------------------------------------------------
GREY = (150, 150, 150)
RED = (60, 60, 185)
BLUE = (185, 110, 60)
YELLOW = (70, 200, 220)
BLACK = (34, 34, 36)


def _scenes() -> list[Scene]:
    s = []

    # 1. One clean confirmation per shape family, in a generic (off-axis) view.
    #    A portrait frame is only +-105 cm wide at 300 cm, so a volume can only
    #    be pushed so far sideways before it leaves the frame.
    s.append(Scene("tri_centre", 0.0, 12.0, 300.0, note="triangular pyramid, generic view",
                   volumes=[Vol("tri", "pyramid3", (45, 130), (90, 90), 35.0, albedo=GREY)]))
    s.append(Scene("sq_centre", 0.0, 12.0, 300.0, note="square pyramid, generic view",
                   volumes=[Vol("sq", "pyramid4", (45, 130), (80, 80), 40.0, albedo=BLUE)]))
    s.append(Scene("wedge_centre", 0.0, 12.0, 300.0, note="wedge, ridge over base-edge midpoints",
                   volumes=[Vol("wedge", "wedge", (40, 130), (100, 70), 30.0, albedo=RED)]))
    s.append(Scene("box_centre", 0.0, 12.0, 300.0, note="box/riser, generic view",
                   volumes=[Vol("box", "box", (50, 140), (80, 60), 30.0, albedo=YELLOW)]))

    # 2. Pyramid off-centre apex, same volume at the same place in the frame.
    for off in (0, 4, 8, 16, 24):
        s.append(Scene(f"pyr_off{off:02d}", 0.0, 12.0, 300.0,
                       note=f"square pyramid, apex {off} cm off the base centroid",
                       volumes=[Vol("sq", "pyramid4", (0, 0), (80, 80), 40.0,
                                    apex_offset=(off * 0.8, off * 0.6), albedo=BLUE)]))

    # 3. Off-axis sweep: the same volume at five positions out from the axis.
    #    The frame is portrait, so the sweep runs mostly up the frame.
    off_axis = [(0, 0), (25, 55), (45, 110), (60, 165), (72, 215)]
    s.append(Scene("offaxis_pyr", 0.0, 12.0, 320.0, note="square pyramid, 5 frame positions",
                   volumes=[Vol(f"p{i}", "pyramid4", c, (70, 70), 35.0, albedo=BLUE)
                            for i, c in enumerate(off_axis)]))
    s.append(Scene("offaxis_box", 0.0, 12.0, 320.0, note="box, 5 frame positions",
                   volumes=[Vol(f"b{i}", "box", c, (70, 55), 28.0, albedo=YELLOW)
                            for i, c in enumerate(off_axis)]))
    s.append(Scene("offaxis_pyr_off", 0.0, 12.0, 320.0,
                   note="square pyramid with a 10 cm off-centre apex, 5 frame positions",
                   volumes=[Vol(f"q{i}", "pyramid4", c, (70, 70), 35.0,
                                apex_offset=(6.0, 8.0), albedo=BLUE)
                            for i, c in enumerate(off_axis)]))
    s.append(Scene("offaxis_wedge", 0.0, 12.0, 320.0, note="wedge, 5 frame positions",
                   volumes=[Vol(f"w{i}", "wedge", c, (80, 60), 30.0, albedo=RED)
                            for i, c in enumerate(off_axis)]))

    # 4. Wall angle / pitch / distance coverage, mixed families.
    for name, wall, pitch, dist in (("slab_m10", -10.0, -5.0, 220.0),
                                    ("vertical_00", 0.0, 8.0, 260.0),
                                    ("over_20", 20.0, 18.0, 340.0),
                                    ("over_40", 40.0, 25.0, 400.0)):
        #Spread scales with distance so the same layout fills the frame at any
        #of them; the volumes themselves keep their real size.
        k = dist / 300.0
        s.append(Scene(name, wall, pitch, dist,
                       note=f"wall {wall:+g} deg, pitch {pitch:+g} deg, {dist:g} cm",
                       volumes=[Vol("pyr", "pyramid4", (-35 * k, 120 * k), (65, 65), 35.0, albedo=BLUE),
                                Vol("wedge", "wedge", (35 * k, 5 * k), (75, 55), 28.0, albedo=RED,
                                    rotation_deg=12.0),
                                Vol("box", "box", (-30 * k, -105 * k), (70, 55), 24.0, albedo=YELLOW),
                                Vol("tri", "pyramid3", (38 * k, -175 * k), (85, 85), 32.0, albedo=GREY)]))

    # 5. Dark on dark, and a light volume, plus low light contrast.
    s.append(Scene("dark_on_dark", 0.0, 10.0, 280.0, wall_albedo=(44, 48, 54),
                   ambient=0.5, diffuse=0.5, grain=4.0,
                   note="near-black volumes on a dark wall",
                   volumes=[Vol("blackpyr", "pyramid4", (0, 150), (75, 75), 38.0, albedo=BLACK),
                            Vol("blackwedge", "wedge", (0, 10), (85, 60), 28.0, albedo=BLACK),
                            Vol("blackbox", "box", (0, -120), (70, 55), 24.0, albedo=(42, 44, 48))]))
    s.append(Scene("light_vol", 0.0, 10.0, 280.0, note="pale volumes, varied albedo",
                   volumes=[Vol("white", "pyramid4", (0, 150), (75, 75), 38.0, albedo=(238, 240, 242)),
                            Vol("cream", "wedge", (0, 10), (85, 60), 28.0, albedo=(205, 225, 235)),
                            Vol("pale", "box", (0, -120), (70, 55), 24.0, albedo=(215, 215, 210))]))
    s.append(Scene("lowcontrast", 0.0, 12.0, 300.0, light=(0.0, 0.05, 1.0),
                   ambient=0.78, diffuse=0.22, grain=3.0,
                   note="light along the wall normal: faces nearly equal in brightness",
                   volumes=[Vol("pyr", "pyramid4", (0, 100), (80, 80), 40.0, albedo=(140, 140, 145)),
                            Vol("wedge", "wedge", (0, -95), (90, 65), 30.0, albedo=(140, 140, 145))]))

    # 6. Holds occluding a base edge, and a base clipped by the frame.
    s.append(Scene("occluded_base", 0.0, 12.0, 300.0,
                   note="wall holds drawn over the base edges of each volume",
                   volumes=[Vol("pyr", "pyramid4", (0, 120), (80, 80), 40.0, albedo=BLUE),
                            Vol("box", "box", (0, -120), (75, 60), 26.0, albedo=YELLOW)],
                   holds=[Hold(-1, -1, (-20, 80), 11.0), Hold(-1, -1, (22, 82), 9.0),
                          Hold(-1, -1, (-22, -150), 10.0), Hold(-1, -1, (20, -148), 11.0),
                          Hold(-1, -1, (38, -120), 9.0)]))
    s.append(Scene("clipped_base", 0.0, 2.0, 240.0, wall_top_cm=150.0,
                   note="one base off the bottom of the frame, one off the side; wall top visible",
                   volumes=[Vol("lowpyr", "pyramid4", (0, -155), (85, 85), 40.0, albedo=BLUE),
                            Vol("sidebox", "box", (92, 15), (80, 60), 26.0, albedo=YELLOW)]))

    # 7. A curved volume: no primitive exists for it, so the question is how it fails.
    s.append(Scene("curved", 0.0, 12.0, 300.0,
                   note="half-cylinder (no matching primitive) next to a square pyramid",
                   volumes=[Vol("halfcyl", "cylinder", (0, 110), (120, 0), 30.0, albedo=RED, facets=12),
                            Vol("ref", "pyramid4", (0, -120), (75, 75), 36.0, albedo=BLUE)]))

    # 8. Holds at known points on known faces (hold_face).
    s.append(Scene("holds_on_faces", 10.0, 14.0, 300.0,
                   note="holds at known uv on known faces of a pyramid, wedge and box",
                   volumes=[Vol("pyr", "pyramid4", (0, 125), (85, 85), 40.0, albedo=BLUE),
                            Vol("wedge", "wedge", (0, -20), (90, 65), 30.0, albedo=RED),
                            Vol("box", "box", (0, -150), (75, 60), 26.0, albedo=YELLOW)],
                   holds=[Hold(0, 0, (0.45, 0.30), 5.0), Hold(0, 2, (0.5, 0.25), 5.0),
                          Hold(0, 1, (0.25, 0.12), 4.0),
                          Hold(1, 0, (0.35, 0.45), 5.0), Hold(1, 1, (0.6, 0.35), 5.0),
                          Hold(1, 0, (0.5, 0.92), 4.0),   # right on the ridge
                          Hold(2, 2, (0.5, 0.5), 5.0), Hold(2, 4, (0.45, 0.45), 5.0),
                          Hold(-1, -1, (60, 40), 5.0)]))

    # 9. Rotated / tall-thin volumes, as a shape-confusion stress.
    s.append(Scene("rotated_mix", 15.0, 16.0, 300.0, note="rotated bases, varied aspect ratios",
                   volumes=[Vol("tallbox", "box", (-30, 130), (40, 95), 30.0, albedo=YELLOW,
                                rotation_deg=22.0),
                            Vol("flatwedge", "wedge", (32, 20), (110, 45), 16.0, albedo=RED,
                                rotation_deg=-18.0),
                            Vol("steeppyr", "pyramid4", (-28, -100), (60, 60), 55.0, albedo=BLUE,
                                rotation_deg=35.0),
                            Vol("tri2", "pyramid3", (36, -170), (95, 80), 30.0, albedo=GREY,
                                rotation_deg=20.0)]))
    return s


SCENES = {sc.name: sc for sc in _scenes()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--only", nargs="*", default=None, help="scene names to render")
    parser.add_argument("--quality", type=int, default=92, help="JPEG quality")
    parser.add_argument("--list", action="store_true", help="list the scenes and exit")
    args = parser.parse_args()
    if args.list:
        for name, sc in SCENES.items():
            print(f"{name:16s} wall {sc.wall_deg:+6.1f} pitch {sc.pitch_deg:+5.1f} "
                  f"dist {sc.distance_cm:5.0f}  {len(sc.volumes)} vol  {sc.note}")
        return
    names = args.only or list(SCENES)
    for name in names:
        result = write(SCENES[name], args.out, args.quality)
        faces = sum(len(v["faces"]) for v in result["meta"]["volumes"])
        visible = sum(1 for v in result["meta"]["volumes"] for f in v["faces"] if f.get("visible"))
        print(f"{name:16s} {len(result['meta']['volumes'])} volumes, {faces} faces "
              f"({visible} visible), {len(result['meta']['bolts_px'])} bolts -> {args.out}")


if __name__ == "__main__":
    main()
