import logging
from collections import deque
from dataclasses import dataclass
from itertools import product

import cv2
import numpy as np

import angle
from bolts import knn

#Wall scale + hold-to-hold distances, all in GRID UNITS (1 unit = one
#bolt_spacing_cm) - the client and worker multiply by the user's
#bolt_spacing_cm, so changing that setting never needs detection re-run.
#See docs/features/wall_size_hold_distance.md.
#
#The bolt grid is a centred square lattice: a square of side 1 unit with a
#bolt at each corner and one in the middle, so a bolt's nearest neighbours are
#the 4 diagonals at 1/sqrt(2). Each bolt's neighbour vectors in the photo
#give a local 2x2 Jacobian J (pixels per grid unit) - perspective, panel
#angle and lens all just make J vary across the photo. A distance is then
#the integral of the local metric along the segment, sampled at
#SEGMENT_SAMPLES points.
#
#The lattice's own symmetries (90 deg turns, mirror) make J ambiguous up to
#J @ R. Distances only need the metric M = A^T A with A = J^-1, which is the
#same for every R - so M is what's stored and interpolated, and no consistent
#lattice labelling is needed to measure. index_lattice() builds one anyway,
#for accuracy evaluation (eval_scale.py), where it gives the ground truth.

#Lattice basis in grid units: the two nearest-neighbour (diagonal) vectors.

LATTICE_BASIS = np.array([[0.5, 0.5], [0.5, -0.5]]).T

#The 8 symmetries of a square lattice, as grid-space matrices.

LATTICE_SYMMETRIES = [
    np.array([[c, -s], [s, c]]) @ np.diag([1, m])
    for (c, s), m in product([(1, 0), (0, 1), (-1, 0), (0, -1)], [1, -1])
]

#Neighbours used to fit each bolt's Jacobian.

FIT_NEIGHBOURS = 8

#A neighbour vector is an inlier when it lands within this fraction of a
#nearest-neighbour length of an integer lattice offset under the bolt's
#initial J. Also the rounding tolerance for lattice indexing links.

FIT_ROUNDING_TOLERANCE = 0.25

#A candidate basis pair must be at least this far from parallel (radians). Real nearest-neighbour pairs are 90 deg apart on the
#wall, less in a foreshortened photo.

MIN_BASIS_ANGLE = np.radians(35)

#Bolts whose neighbour vectors are pooled for each bolt's fit.

POOL_BOLTS = 5

#Basis candidates: the BASIS_POOL shortest pooled vectors clustered by
#direction (within DIRECTION_CLUSTER radians) and length (within
#CLUSTER_LENGTH_TOLERANCE); up to BASIS_CANDIDATES shortest-per-direction
#plus BASIS_CANDIDATES most frequent clusters - normally the 2 diagonals and
#2 sides, plus whatever false detections add.

BASIS_POOL = 40
DIRECTION_CLUSTER = np.radians(20)
CLUSTER_LENGTH_TOLERANCE = 0.25
BASIS_CANDIDATES = 4

#Basis fits explaining at least this fraction of the best fit's inliers are
#compared on squareness (condition number).

COUNT_FRACTION = 0.65

#Candidates whose nearest-neighbour sites hold fewer than this fraction of
#the best candidate's matching vectors start behind the rest (finer lattices).

MIN_OCCUPANCY_FRACTION = 0.5

#A fitted J is rejected beyond this condition number - a panel seen more
#obliquely than ~75 deg, or a fit across a seam.

MAX_JACOBIAN_CONDITION = 4.0

#A bolt's metric must be within this relative (Frobenius) distance of the
#median metric of its CONSISTENCY_NEIGHBOURS nearest fitted bolts (itself
#included) - and a lattice-indexing link must join bolts whose aligned J
#are this close.

MAX_METRIC_DEVIATION = 0.35
CONSISTENCY_NEIGHBOURS = 7

#Choosing between each bolt's candidate Js (see _choose): consensus over
#this many nearest bolts, repeated this many rounds.

CHOICE_NEIGHBOURS = 12
CHOICE_ITERATIONS = 8

#sqrt(2) boundary rule (see _resolve_sqrt2): bolts are grouped by linking each
#to its SQRT2_NEIGHBOURS nearest bolts whose metric is within
#SQRT2_GROUP_TOLERANCE (relative); a group is re-read on the finer lattice
#when most of its links to another group show that group's metric at 2x its
#own within SQRT2_RATIO_TOLERANCE, the other group has at least
#SQRT2_MIN_REFERENCE bolts, and at least SQRT2_ALIGN_FRACTION of its bolts
#within SQRT2_REACH_UNITS (grid units) of the border sit on the other group's
#lattice. SQRT2_MAX_ROUNDS bounds the repeats.

SQRT2_NEIGHBOURS = 12
SQRT2_GROUP_TOLERANCE = 0.2
SQRT2_RATIO_TOLERANCE = 0.15
SQRT2_REACH_UNITS = 3.0
SQRT2_ALIGN_FRACTION = 0.8
SQRT2_MIN_REFERENCE = 7
SQRT2_MIN_REFERENCE_RADIUS = 1.5
SQRT2_MAX_ROUNDS = 10

#Panels (see segment_panels): a flat panel's grid maps to the photo by one
#homography H (grid units -> px), so within a panel H replaces the
#interpolated field. Residuals and tolerances below are fractions of a bolt's
#nearest-neighbour spacing in px.
#- Seeds: a homography fitted to each bolt's PANEL_SEED_NEIGHBOURS nearest
#  bolts (at least PANEL_MIN_SEED from one lattice patch).
#- Assignment: a bolt's cost under a panel is its distance to that panel's
#  nearest lattice site (capped at PANEL_RESIDUAL_CAP), or the cap when the
#  panel's scale there disagrees with the bolt's own metric by more than
#  MAX_METRIC_DEVIATION. Each bolt takes the panel with the lowest cost summed
#  over its PANEL_WINDOW nearest bolts, if its own cost is within
#  PANEL_RESIDUAL_TOLERANCE; then every panel is refitted, PANEL_ITERATIONS
#  times.
#- A homography is kept only if its scale agrees with at least
#  PANEL_METRIC_AGREEMENT of its bolts' own metrics, and a panel needs at least
#  PANEL_MIN_BOLTS bolts, connected by steps of at most PANEL_REACH_SPACINGS.
#- Merge: two panels are one when a single homography fits both with at least
#  PANEL_MERGE_FRACTION of each side's bolts within PANEL_MERGE_TOLERANCE of
#  their sites, and its RMS residual is at most PANEL_MERGE_RMS_RATIO times
#  the two separate fits' (pooled over sides with PANEL_MIN_BOLTS or more,
#  floored at PANEL_NOISE_FLOOR) - trying lattice offsets up to
#  PANEL_MERGE_SEARCH_UNITS for parts of a panel with no bolts found between
#  them. Only parts within PANEL_MERGE_GAP_SPACINGS of each other merge:
#  across a longer gap a homography bends enough to absorb a grid offset
#  (two coplanar sheets drilled out of line) that must stay separate.

PANEL_SEED_NEIGHBOURS = 12
PANEL_MIN_SEED = 6
PANEL_RESIDUAL_TOLERANCE = 0.15
PANEL_RESIDUAL_CAP = 0.5
PANEL_WINDOW = 7
PANEL_ITERATIONS = 8
PANEL_METRIC_AGREEMENT = 0.8
PANEL_MIN_BOLTS = 8
PANEL_REACH_SPACINGS = 2.6
PANEL_MERGE_TOLERANCE = 0.12
PANEL_MERGE_FRACTION = 0.9
PANEL_MERGE_RMS_RATIO = 1.5
PANEL_NOISE_FLOOR = 0.03
PANEL_MERGE_SEARCH_UNITS = 1.6
PANEL_MERGE_SYMMETRIES = 2
PANEL_MERGE_GAP_SPACINGS = 6.0

#A query point is measured on the panel most of its FIELD_NEIGHBOURS nearest
#bolts belong to - unless that panel's homography there is behind the camera
#or strays more than PANEL_FIELD_DEVIATION (relative) from the interpolated
#field, i.e. it's extrapolated too far to trust; then the field is used.

PANEL_FIELD_DEVIATION = 0.5

#Two panels share one lattice frame (index_lattice) when at least
#PANEL_LINK_FRACTION of the bolts within PANEL_LINK_SPACINGS of the other
#panel land on one consistent site of its lattice, and at least
#PANEL_LINK_MIN_BOLTS do.

PANEL_LINK_SPACINGS = 1.6
PANEL_LINK_FRACTION = 0.8
PANEL_LINK_MIN_BOLTS = 3

#Field interpolation: inverse-square weights over this many nearest fitted
#bolts, softened by the local bolt spacing so a query right on top of a bolt
#doesn't take that bolt alone.

FIELD_NEIGHBOURS = 6

#Off-lattice removal: a point is kept when at least OFF_LATTICE_MAJORITY of
#its OFF_LATTICE_NEIGHBOURS nearest fitted bolts place it on their lattice.

OFF_LATTICE_NEIGHBOURS = 6
OFF_LATTICE_MAJORITY = 0.5

SEGMENT_SAMPLES = 16

#Confidence tiers (docs/features/wall_size_hold_distance.md, slice 5c). A
#distance is tier "A" when every one of its SEGMENT_SAMPLES points is within
#TIER_A_MAX_SUPPORT nearest-neighbour spacings of a fitted bolt, i.e. it is
#measured on lattice evidence right where it runs; otherwise "C": the scale
#along part of it is borrowed from bolts further away (holds or volumes hide
#the bolts there). Calibrated on held-out discs of bolts: error is a few
#percent within about 1.5 spacings of a bolt and about 13% (p95) beyond.

TIER_A_MAX_SUPPORT = 1.5

#Wall length is measured top bolt to bottom bolt, plus half a grid square at
#each end for the wall beyond the outermost bolts.

WALL_END_ALLOWANCE_UNITS = 0.5

#Half-width of that band, in nearest-neighbour spacings - narrower bands miss
#the top/bottom rows wherever holds cover the bolts (IMG_7502).

WALL_BAND_SPACINGS = 4.0

#Rounded so an N x N matrix doesn't bloat the /detect response - 0.001 units
#is 0.02 mm at a 20 cm spacing, far below the method's accuracy.

DISTANCE_DECIMALS = 3


@dataclass
class Lattice:
    xy: np.ndarray        # (N, 2) bolt positions in px, only bolts with a valid fit
    jacobian: np.ndarray  # (N, 2, 2) px per grid unit, up to a lattice symmetry
    metric: np.ndarray    # (N, 2, 2) grid units^2 per px^2 (A^T A)
    spacing_px: np.ndarray  # (N,) nearest-neighbour distance in px
    #Per bolt: panel id (-1 = in no panel) and lattice site in that panel's
    #frame (grid units). None = no panels, measure on the field only. A
    #panel's homography is fitted from its bolts whenever it's measured, so a
    #subset (take()) measures from its own bolts only.
    panel: np.ndarray | None = None  # (N,) int
    grid: np.ndarray | None = None   # (N, 2)

    def take(self, mask: np.ndarray) -> "Lattice":
        """The lattice restricted to the bolts selected by mask (bool or index)."""
        def pick(a):
            return None if a is None else np.asarray(a)[mask]
        return Lattice(pick(self.xy), pick(self.jacobian), pick(self.metric), pick(self.spacing_px),
                       pick(self.panel), pick(self.grid))


def _nn_occupancy(vectors: np.ndarray, j: np.ndarray) -> int:
    """How many vectors are a nearest-neighbour step (+-J e1, +-J e2) under j."""
    steps = (j @ LATTICE_BASIS).T
    steps = np.vstack([steps, -steps])                                            # (4, 2)
    gap = np.hypot(*(vectors[:, None, :] - steps[None]).transpose(2, 0, 1)).min(axis=1)
    return int((gap <= FIT_ROUNDING_TOLERANCE * np.hypot(*steps.T).min()).sum())


def _inlier_count(vectors: np.ndarray, j: np.ndarray) -> int:
    """How many vectors land within FIT_ROUNDING_TOLERANCE nearest-neighbour
    lengths (px) of an integer lattice offset under j."""
    coeffs = np.linalg.solve(LATTICE_BASIS, np.linalg.solve(j, vectors.T))
    residual = np.hypot(*(vectors.T - j @ LATTICE_BASIS @ np.round(coeffs)))
    return int((residual <= FIT_ROUNDING_TOLERANCE * np.hypot(*(j @ LATTICE_BASIS)).min()).sum())


def _refine(vectors: np.ndarray, j0: np.ndarray) -> tuple[np.ndarray, int] | None:
    """Least-squares J over every neighbour vector within FIT_ROUNDING_TOLERANCE
    nearest-neighbour lengths (in px) of an integer lattice offset under j0.
    Returns (J, inlier count).

    The tolerance is in px, not lattice coordinates, so every basis of the
    same lattice gets the same inliers - in lattice coordinates a sheared
    basis stretches the tolerance and catches extra noise."""
    coeffs = np.linalg.solve(LATTICE_BASIS, np.linalg.solve(j0, vectors.T))
    rounded = np.round(coeffs)
    residual = np.hypot(*(vectors.T - j0 @ LATTICE_BASIS @ rounded))
    nn_px = np.hypot(*(j0 @ LATTICE_BASIS)).min()
    inlier = (residual <= FIT_ROUNDING_TOLERANCE * nn_px) & (np.abs(rounded).sum(axis=0) > 0)
    if inlier.sum() < 3:
        return None
    grid = LATTICE_BASIS @ rounded[:, inlier]
    if np.linalg.matrix_rank(grid) < 2:
        return None
    j, *_ = np.linalg.lstsq(grid.T, vectors[inlier], rcond=None)
    return j.T, int(inlier.sum())


def _basis_candidates(vectors: np.ndarray) -> np.ndarray:
    """Candidate lattice vectors from the BASIS_POOL shortest pooled vectors,
    sign-folded and clustered by direction and length. Two picks, merged:
    - the shortest cluster in each direction - the diagonals, even where
      hidden bolts make them rare;
    - the most frequent clusters - real lattice vectors recur from every
      pooled bolt, while a vector to a false detection shows up once or
      twice, so a false detection can't crowd the real diagonals out.
    Pairs built from a false vector then lose on inlier count."""
    lengths = np.hypot(vectors[:, 0], vectors[:, 1])
    order = np.argsort(lengths)[:BASIS_POOL]
    clusters: list[list[np.ndarray]] = []
    for v in vectors[order]:
        if v[1] < 0 or (v[1] == 0 and v[0] < 0):
            v = -v
        for c in clusters:
            ref = c[0]
            cos = (v @ ref) / (np.hypot(*v) * np.hypot(*ref))
            if np.arccos(np.clip(cos, -1.0, 1.0)) < DIRECTION_CLUSTER and abs(np.hypot(*v) / np.hypot(*ref) - 1) < CLUSTER_LENGTH_TOLERANCE:
                c.append(v)
                break
        else:
            clusters.append([v])
    shortest_per_direction: list[int] = []
    for i, c in enumerate(clusters):  # clusters are in length order of their first vector
        ref = c[0]
        if all(np.arccos(np.clip(abs(ref @ clusters[k][0]) / (np.hypot(*ref) * np.hypot(*clusters[k][0])), 0.0, 1.0)) >= DIRECTION_CLUSTER
               for k in shortest_per_direction):
            shortest_per_direction.append(i)
    frequent = sorted(range(len(clusters)), key=lambda i: len(clusters[i]), reverse=True)
    picked = list(dict.fromkeys(shortest_per_direction[:BASIS_CANDIDATES] + frequent[:BASIS_CANDIDATES]))
    return np.array([np.mean(clusters[i], axis=0) for i in picked])


def _fit_candidates(vectors: np.ndarray) -> list[np.ndarray]:
    """Plausible local Js from the neighbour vectors pooled around one bolt,
    most square first.

    Each pair of candidate directions is tried as the two diagonals; fits
    explaining at least COUNT_FRACTION of the best fit's inliers are kept.
    Locally these can't always be told apart:
    - a sheared basis (a diagonal plus a square side) generates the same
      lattice, so fits the same neighbours - only less square (cond ~2.6 vs
      the panel's foreshortening, ~1-1.5);
    - where the centre-of-square bolts are hidden, the rest is a plain square
      grid, and "diagonals" (J) vs "square sides" (J @ E) differ by sqrt(2).
    So the sqrt(2) variants are candidates too, and _choose() picks per bolt
    using the neighbouring bolts' fits.
    """
    reps = _basis_candidates(vectors)
    fits = []
    for i in range(len(reps)):
        for k in range(i + 1, len(reps)):
            v1, v2 = reps[i], reps[k]
            cos = abs(v1 @ v2) / (np.hypot(*v1) * np.hypot(*v2))
            if np.arccos(min(1.0, cos)) < MIN_BASIS_ANGLE:
                continue
            fit = _refine(vectors, np.column_stack([v1, v2]) @ np.linalg.inv(LATTICE_BASIS))
            if fit is None:
                continue
            j, count = fit
            cond = np.linalg.cond(j)
            if cond <= MAX_JACOBIAN_CONDITION:
                fits.append((cond, count, j))
    if not fits:
        return []
    #Each fit plus its sqrt(2) variants, every one scored on its own inliers.
    variants = []
    for _, _, j in fits:
        for v in (j, j @ LATTICE_BASIS, j @ np.linalg.inv(LATTICE_BASIS)):
            variants.append((v, _inlier_count(vectors, v)))
    most = max(count for _, count in variants)
    out = [v for v, count in variants if count >= COUNT_FRACTION * most]
    #Starting choice for _choose(). A finer lattice also fits every real bolt
    #(and any false detection between them), so it can't lose on inlier
    #count - but its nearest-neighbour sites are mostly empty, while the real
    #grid's recur around every pooled bolt. So: well-occupied first, then most
    #square, then the directly fitted basis before its variants (stable sort).
    #Where centre bolts are hidden the true J is itself "poorly occupied" and
    #the coarse sqrt(2) reading starts - the neighbour consensus fixes that.
    occupancy = np.array([_nn_occupancy(vectors, j) for j in out])
    sparse = occupancy < MIN_OCCUPANCY_FRACTION * occupancy.max()
    order = sorted(range(len(out)), key=lambda i: (sparse[i], np.linalg.cond(out[i])))
    return [out[i] for i in order]


def _choose(xy: np.ndarray, candidates: list[list[np.ndarray]]) -> np.ndarray:
    """One J per bolt: start from each bolt's most square fit, then
    repeatedly take the candidate whose metric is closest to the median
    metric of its CHOICE_NEIGHBOURS nearest bolts - wide enough, over
    CHOICE_ITERATIONS rounds, for the right reading to spread ring by ring
    into a patch whose centre bolts are all hidden. Most bolts have an
    unambiguous neighbourhood, so the local majority settles the rest."""
    n = len(xy)
    width = max(len(c) for c in candidates)
    jac = np.full((n, width, 2, 2), np.nan)
    for i, c in enumerate(candidates):
        jac[i, : len(c)] = c
    metric = np.full_like(jac, np.nan)
    ok = ~np.isnan(jac[:, :, 0, 0])
    metric[ok] = _metric(jac[ok])
    choice = np.zeros(n, int)
    if n >= CHOICE_NEIGHBOURS:
        idx, _ = knn(xy, xy, CHOICE_NEIGHBOURS)
        for _ in range(CHOICE_ITERATIONS):
            current = metric[np.arange(n), choice]
            local = np.median(current[np.maximum(idx, 0)], axis=1)                     # (N, 2, 2)
            diff = np.linalg.norm(metric - local[:, None], axis=(2, 3)) / np.linalg.norm(local, axis=(1, 2))[:, None]
            choice = np.argmin(np.where(ok, diff, np.inf), axis=1)
    return jac[np.arange(n), choice]


def _groups(idx: np.ndarray, metric: np.ndarray) -> np.ndarray:
    """Connected components of bolts linked to a knn neighbour whose metric
    is within SQRT2_GROUP_TOLERANCE of their own."""
    n = len(metric)
    parent = np.arange(n)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    norm = np.linalg.norm(metric, axis=(1, 2))
    for i in range(n):
        for k in idx[i]:
            if k < 0 or k == i:
                continue
            if np.linalg.norm(metric[i] - metric[k]) <= SQRT2_GROUP_TOLERANCE * min(norm[i], norm[k]):
                parent[find(i)] = find(k)
    return np.array([find(i) for i in range(n)])


def _aligned_fraction(points: np.ndarray, origin: np.ndarray, j: np.ndarray) -> np.ndarray:
    """Per point, whether (points - origin) is an integer lattice offset
    under j, within FIT_ROUNDING_TOLERANCE nearest-neighbour lengths (px)."""
    v = (points - origin).T
    k = np.linalg.solve(LATTICE_BASIS, np.linalg.solve(j, v))
    residual = np.hypot(*(v - j @ LATTICE_BASIS @ np.round(k)))
    return residual <= FIT_ROUNDING_TOLERANCE * np.hypot(*(j @ LATTICE_BASIS)).min()


def _continues_lattice(xy: np.ndarray, jac: np.ndarray, members: np.ndarray, border: np.ndarray) -> bool:
    """Whether a group's bolts continue the lattice of the neighbouring
    group's border bolts: of the members within SQRT2_REACH_UNITS of each
    border bolt (under its J), at least SQRT2_ALIGN_FRACTION land on its
    lattice. Reaching a few squares in matters - right at a seam a
    different grid can line up by chance, further in it drifts off."""
    hits = []
    for k in border:
        reach = SQRT2_REACH_UNITS * np.linalg.norm(jac[k], 2)
        near = members[np.hypot(*(xy[members] - xy[k]).T) <= reach]
        hits.append(_aligned_fraction(xy[near], xy[k], jac[k]))
    hits = np.concatenate(hits) if hits else np.zeros(0, bool)
    return len(hits) > 0 and hits.mean() >= SQRT2_ALIGN_FRACTION


def _radius_units(xy: np.ndarray, metric: np.ndarray, members: np.ndarray) -> float:
    """Largest distance, in grid units under the group's mean metric, from the
    group's centre to one of its bolts."""
    d = xy[members] - xy[members].mean(axis=0)
    m = metric[members].mean(axis=0)
    return float(np.sqrt(np.einsum("ni,ij,nj->n", d, m, d).max()))


def _resolve_sqrt2(xy: np.ndarray, jac: np.ndarray) -> np.ndarray:
    """Boundary rule for regions whose centre bolts are all hidden.

    There the visible corners form a plain square grid that reads locally as
    the normal lattice sqrt(2) coarser (J @ E^-1, metric 0.5x), and _choose's
    neighbour vote can't reach the middle of a big region or a strip along
    the wall edge. But the region still borders correctly read bolts, and
    across that border the metric jumps by a uniform factor of exactly 2,
    and the region's bolts continue the neighbouring group's lattice (it is
    one physical grid). A real panel change (angle, depth) gives both only
    by coincidence: its scale ratio is rarely ~sqrt(2), and its grid drifts
    off the neighbour's within a few squares. The coarser side is always the
    misread one, so a group whose links to another group mostly show that
    group's metric at 2x its own, and whose bolts continue that group's
    lattice, is re-read as J @ E (metric 2x). The finer group must have at
    least SQRT2_MIN_REFERENCE bolts and reach SQRT2_MIN_REFERENCE_RADIUS
    units from its centre (four false points completing one finer cell round
    a centre bolt make 9 bolts within half a unit: not a real region): a lone bolt fitted on a too-fine
    lattice (a false detection nearby) also borders its coarse neighbours
    at 2x and trivially contains their grid, and must not re-read a whole
    correct panel (seen on IMG_7503). Repeated, since a corrected
    group can expose the next. A photo with no centre bolts anywhere has no
    such border and is left as is."""
    if len(xy) < CONSISTENCY_NEIGHBOURS:
        return jac
    idx, _ = knn(xy, xy, min(SQRT2_NEIGHBOURS, len(xy)))
    for _ in range(SQRT2_MAX_ROUNDS):
        metric = _metric(jac)
        group = _groups(idx, metric)
        norm = np.linalg.norm(metric, axis=(1, 2))
        #Per (group, other group): links where the other side is 2x (votes)
        #out of all links between them (links), and the other side's bolts
        #on those links (border).
        votes: dict[tuple[int, int], int] = {}
        links: dict[tuple[int, int], int] = {}
        border: dict[tuple[int, int], set[int]] = {}
        for i in range(len(xy)):
            for k in idx[i]:
                if k < 0 or group[k] == group[i]:
                    continue
                key = (group[i], group[k])
                links[key] = links.get(key, 0) + 1
                if np.linalg.norm(2 * metric[i] - metric[k]) <= SQRT2_RATIO_TOLERANCE * norm[k]:
                    votes[key] = votes.get(key, 0) + 1
                    border.setdefault(key, set()).add(int(k))
        size = np.bincount(group, minlength=len(xy))
        coarse = {
            g for (g, h), v in votes.items()
            if 2 * v > links[(g, h)] and size[h] >= SQRT2_MIN_REFERENCE
            and _radius_units(xy, metric, group == h) >= SQRT2_MIN_REFERENCE_RADIUS
            and _continues_lattice(xy, jac, np.flatnonzero(group == g), np.array(sorted(border[(g, h)])))
        }
        if not coarse:
            break
        flip = np.isin(group, list(coarse))
        jac = jac.copy()
        jac[flip] = jac[flip] @ LATTICE_BASIS
    return jac


def fit_lattice(xy: np.ndarray) -> Lattice:
    """Bolt positions (N, 2) in px -> per-bolt local Jacobian + metric.
    Bolts without enough lattice-consistent neighbours are dropped.

    Two passes: a false detection between real bolts (e.g. near a square's
    mid-edge) fits a finer lattice that explains it and every real bolt, and
    drags its neighbours' fits with it. So after a first fit, points that sit
    off the lattice of most of their fitted neighbours are removed and the
    fit is redone without them.

    The fitted bolts are then split into flat panels (segment_panels)."""
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    lattice = _fit_lattice_once(xy)
    if len(lattice.xy) >= OFF_LATTICE_NEIGHBOURS:
        on = _on_lattice(xy, lattice)
        if not on.all():
            lattice = _fit_lattice_once(xy[on])
    lattice.panel, lattice.grid = segment_panels(lattice)
    return lattice


def _on_lattice(xy: np.ndarray, lattice: Lattice) -> np.ndarray:
    """Whether each point lies at an integer lattice offset (within
    FIT_ROUNDING_TOLERANCE nearest-neighbour lengths, in px) from most of its
    OFF_LATTICE_NEIGHBOURS nearest fitted bolts, under each bolt's own J. A
    lattice's symmetries map it onto itself, so any variant of J works."""
    idx, _ = knn(xy, lattice.xy, OFF_LATTICE_NEIGHBOURS + 1)
    votes = np.zeros(len(xy))
    counted = np.zeros(len(xy))
    for col in range(idx.shape[1]):
        q = idx[:, col]
        valid = q >= 0
        j = lattice.jacobian[np.maximum(q, 0)]
        v = xy - lattice.xy[np.maximum(q, 0)]
        self_match = np.hypot(*v.T) < 1e-6  #the point itself, if it was fitted
        k = np.einsum("nij,nj->ni", np.linalg.inv(j), v) @ np.linalg.inv(LATTICE_BASIS).T
        snapped = np.einsum("nij,nj->ni", j, np.round(k) @ LATTICE_BASIS.T)
        residual = np.hypot(*(v - snapped).T)
        nn_px = np.linalg.norm(j @ LATTICE_BASIS, axis=1).min(axis=1)
        use = valid & ~self_match
        votes += use & (residual <= FIT_ROUNDING_TOLERANCE * nn_px)
        counted += use
    return votes >= OFF_LATTICE_MAJORITY * np.maximum(counted, 1)


def _fit_lattice_once(xy: np.ndarray) -> Lattice:
    empty = Lattice(np.zeros((0, 2)), np.zeros((0, 2, 2)), np.zeros((0, 2, 2)), np.zeros(0))
    if len(xy) < 3:
        return empty

    idx, dist = knn(xy, xy, FIT_NEIGHBOURS + 1)
    #Per-bolt neighbour vectors, pooled over each bolt's POOL_BOLTS nearest
    #bolts (itself included): one bolt's own neighbours often lack a
    #diagonal or the centre bolts (hidden by holds), a small patch rarely does.
    own = [xy[row[(row >= 0) & (row != i)]] - xy[i] for i, row in enumerate(idx)]
    pool_idx, _ = knn(xy, xy, POOL_BOLTS)
    keep, jacobians = [], []
    for i in range(len(xy)):
        if len(own[i]) < 3:
            continue
        pooled = np.vstack([own[k] for k in pool_idx[i] if k >= 0])
        cands = _fit_candidates(pooled)
        if cands:
            keep.append(i)
            jacobians.append(cands)
    if not keep:
        return empty

    keep = np.array(keep)
    jac = _resolve_sqrt2(xy[keep], _choose(xy[keep], jacobians))
    metric = _metric(jac)
    spacing = np.where(idx[keep, 1] >= 0, dist[keep, 1], np.inf)

    #A bolt at a patch edge or beside a false detection can still fit a
    #wrong (sheared) J; its metric then disagrees with its neighbours'.
    consistent = _metric_consistent(xy[keep], metric)
    return Lattice(xy[keep][consistent], jac[consistent], metric[consistent], spacing[consistent])


def _metric(jac: np.ndarray) -> np.ndarray:
    inv = np.linalg.inv(jac)
    return np.transpose(inv, (0, 2, 1)) @ inv


def _metric_consistent(xy: np.ndarray, metric: np.ndarray) -> np.ndarray:
    if len(xy) < CONSISTENCY_NEIGHBOURS:
        return np.ones(len(xy), bool)
    idx, _ = knn(xy, xy, CONSISTENCY_NEIGHBOURS)
    local = np.median(metric[np.maximum(idx, 0)], axis=1)
    diff = np.linalg.norm(metric - local, axis=(1, 2)) / np.linalg.norm(local, axis=(1, 2))
    return diff <= MAX_METRIC_DEVIATION


# --- panels -------------------------------------------------------------------
#
#A homography H maps a panel's grid (grid units) to px. Every panel has its
#own lattice frame; a bolt's "site" is the lattice point nearest H^-1(bolt).


def _to_site(g: np.ndarray) -> np.ndarray:
    """Nearest lattice points to grid positions (K, 2)."""
    return (LATTICE_BASIS @ np.round(np.linalg.solve(LATTICE_BASIS, g.T))).T


def _apply(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    ph = np.c_[pts, np.ones(len(pts))] @ h.T
    return ph[:, :2] / ph[:, 2:3]


def _fit_homography(grid: np.ndarray, xy: np.ndarray) -> np.ndarray | None:
    """Least-squares homography grid -> px; None when degenerate."""
    if len(grid) < 4 or np.linalg.matrix_rank(np.c_[grid, np.ones(len(grid))]) < 3:
        return None
    h, _ = cv2.findHomography(grid.astype(np.float64), xy.astype(np.float64), 0)
    if h is None or not np.isfinite(h).all() or abs(np.linalg.det(h)) < 1e-12:
        return None
    return h


def _sites(h: np.ndarray, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each point's nearest lattice site under h, and its distance (px) from it."""
    site = _to_site(_apply(np.linalg.inv(h), xy))
    return site, np.hypot(*(_apply(h, site) - xy).T)


def _homography_metric(h: np.ndarray, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Metric (grid units^2 per px^2) of the px -> grid map h^-1 at each point,
    and the homogeneous scale w there (its sign flips behind the camera)."""
    inv = np.linalg.inv(h)
    ph = np.c_[pts, np.ones(len(pts))] @ inv.T
    w = ph[:, 2]
    g = ph[:, :2] / w[:, None]
    jac = (inv[None, :2, :2] - g[:, :, None] * inv[2, :2][None, None, :]) / w[:, None, None]
    return np.transpose(jac, (0, 2, 1)) @ jac, w


def _local_jacobian(h: np.ndarray, g: np.ndarray) -> np.ndarray:
    """d(px)/d(grid) of h at grid point g (2,)."""
    step = np.array([[0.5, 0.0], [-0.5, 0.0], [0.0, 0.5], [0.0, -0.5]])
    p = _apply(h, g + step)
    return np.column_stack([p[0] - p[1], p[2] - p[3]])


def _metric_agrees(h: np.ndarray, xy: np.ndarray, metric: np.ndarray) -> np.ndarray:
    hm, _ = _homography_metric(h, xy)
    return np.linalg.norm(hm - metric, axis=(1, 2)) <= MAX_METRIC_DEVIATION * np.linalg.norm(metric, axis=(1, 2))


def _unique_sites(members: np.ndarray, site: np.ndarray, residual: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop all but the closest bolt on any shared site (a double detection,
    or a bolt pulled onto its neighbour's site)."""
    keep, seen = [], set()
    for i in np.argsort(residual, kind="stable"):
        key = tuple(np.round(2 * site[i]).astype(int))
        if key not in seen:
            seen.add(key)
            keep.append(i)
    keep = np.sort(keep)
    return members[keep], site[keep]


def _refit(lattice: Lattice, h: np.ndarray, members: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Refit h on its members' sites; None when too few bolts remain or the
    new fit's scale disagrees with its bolts' own metrics (a degenerate or
    too-fine homography puts every point near some site)."""
    if len(members) < PANEL_MIN_BOLTS:
        return None
    site, residual = _sites(h, lattice.xy[members])
    members, site = _unique_sites(members, site, residual)
    h = _fit_homography(site, lattice.xy[members])
    if h is None or len(members) < PANEL_MIN_BOLTS:
        return None
    if _metric_agrees(h, lattice.xy[members], lattice.metric[members]).mean() < PANEL_METRIC_AGREEMENT:
        return None
    return h, members


def _joint_fit(lattice: Lattice, a: tuple, b: tuple, search: bool) -> tuple | None:
    """One homography for panels a and b ((h, members) each), with b's bolts
    re-indexed into a's frame - by extrapolating a's homography, or (search)
    by trying each lattice symmetry and offset near that guess, for parts of
    one panel with no bolts found between them. None when no candidate fits
    both sides."""
    (ha, sa), (hb, sb) = a, b
    #Gap in each side's typical spacing (median: one isolated bolt has a long
    #spacing of its own and would make any gap look short).
    gap = np.hypot(*(lattice.xy[sa][:, None] - lattice.xy[sb][None]).transpose(2, 0, 1)).min()
    if gap > PANEL_MERGE_GAP_SPACINGS * max(np.median(lattice.spacing_px[sa]), np.median(lattice.spacing_px[sb])):
        return None
    site_a, _ = _sites(ha, lattice.xy[sa])
    guesses = [_sites(ha, lattice.xy[sb])[0]]
    if search:
        own_b, _ = _sites(hb, lattice.xy[sb])
        projected = _apply(np.linalg.inv(ha), lattice.xy[sb])
        #b's frame turned into a's: J_b = J_a @ S where both homographies
        #describe b's bolts. Only the PANEL_MERGE_SYMMETRIES best-matching S
        #are tried, with every site within PANEL_MERGE_SEARCH_UNITS of the
        #extrapolated offset.
        middle = np.median(own_b, axis=0)
        jac_b = _local_jacobian(hb, middle)
        jac_a = _local_jacobian(ha, _apply(np.linalg.inv(ha), _apply(hb, middle[None]))[0])
        turns = sorted(LATTICE_SYMMETRIES, key=lambda s: np.linalg.norm(jac_b - jac_a @ s))[:PANEL_MERGE_SYMMETRIES]
        steps = np.arange(-PANEL_MERGE_SEARCH_UNITS, PANEL_MERGE_SEARCH_UNITS + 0.25, 0.5)
        for sym in turns:
            turned = own_b @ sym.T
            centre = np.median(projected - turned, axis=0)
            offsets = np.unique(_to_site(np.array([centre + (dx, dy) for dx in steps for dy in steps])), axis=0)
            offsets = offsets[np.hypot(*(offsets - centre).T) <= PANEL_MERGE_SEARCH_UNITS]
            guesses += [turned + t for t in offsets]
    members = np.r_[sa, sb]
    xy, spacing = lattice.xy[members], lattice.spacing_px[members]
    #The separate fits' residual level - a side too small for a reliable
    #homography (it fits its few bolts almost exactly) doesn't set it.
    separate = [(_sites(h, lattice.xy[s])[1] / lattice.spacing_px[s]) for h, s in (a, b) if len(s) >= PANEL_MIN_BOLTS]
    separate_rms = np.sqrt(np.mean(np.concatenate(separate) ** 2)) if separate else 0.0
    limit = PANEL_MERGE_RMS_RATIO * max(separate_rms, PANEL_NOISE_FLOOR)
    best = None
    for site_b in guesses:
        site = np.r_[site_a, site_b]
        if len(np.unique(np.round(2 * site), axis=0)) < len(site):
            continue
        h = _fit_homography(site, xy)
        if h is None:
            continue
        residual = np.hypot(*(_apply(h, site) - xy).T) / spacing
        ok = residual <= PANEL_MERGE_TOLERANCE
        rms = np.sqrt(np.mean(residual**2))
        if ok[: len(sa)].mean() < PANEL_MERGE_FRACTION or ok[len(sa):].mean() < PANEL_MERGE_FRACTION or rms > limit:
            continue
        if _metric_agrees(h, xy, lattice.metric[members]).mean() < PANEL_METRIC_AGREEMENT:
            continue
        if best is None or rms < best[0]:
            best = (rms, h)
    return None if best is None else (best[1], members)


def _merge(lattice: Lattice, panels: list[tuple], search: bool) -> list[tuple]:
    """Merge panels (largest first) that one homography fits."""
    merged: list[tuple] = []
    for panel in sorted(panels, key=lambda p: -len(p[1])):
        for k, other in enumerate(merged):
            joint = _joint_fit(lattice, other, panel, search)
            if joint is not None:
                merged[k] = joint
                break
        else:
            merged.append(panel)
    return merged


def _assign(lattice: Lattice, homographies: list[np.ndarray], window: np.ndarray) -> np.ndarray:
    """Each bolt's panel: the lowest site distance summed over its window of
    nearest bolts (a single bolt is near some site of almost any lattice; a
    neighbourhood isn't), -1 when its own distance is over tolerance."""
    cost = np.stack([
        np.where(_metric_agrees(h, lattice.xy, lattice.metric),
                 np.minimum(_sites(h, lattice.xy)[1] / lattice.spacing_px, PANEL_RESIDUAL_CAP),
                 PANEL_RESIDUAL_CAP)
        for h in homographies
    ], axis=1)
    label = np.argmin(cost[np.maximum(window, 0)].sum(axis=1), axis=1)
    label[cost[np.arange(len(label)), label] > PANEL_RESIDUAL_TOLERANCE] = -1
    return label


def _connected_pieces(lattice: Lattice, members: np.ndarray) -> list[np.ndarray]:
    """Members split into pieces linked by steps of at most
    PANEL_REACH_SPACINGS nearest-neighbour spacings."""
    xy = lattice.xy[members]
    gap = np.hypot(*(xy[:, None] - xy[None]).transpose(2, 0, 1))
    reach = PANEL_REACH_SPACINGS * np.maximum.outer(lattice.spacing_px[members], lattice.spacing_px[members])
    piece = np.full(len(members), -1)
    for start in range(len(members)):
        if piece[start] >= 0:
            continue
        piece[start] = start
        queue = deque([start])
        while queue:
            p = queue.popleft()
            for c in np.flatnonzero((gap[p] <= reach[p]) & (piece < 0)):
                piece[c] = start
                queue.append(c)
    return [members[piece == k] for k in np.unique(piece)]


def segment_panels(lattice: Lattice) -> tuple[np.ndarray, np.ndarray]:
    """Split fitted bolts into flat panels, one homography each: (panel id per
    bolt, -1 = none; lattice site per bolt in its panel's frame).

    Competing homographies, not region growing: grown from one seed, a panel
    creeps over a fold, because a bolt on the next panel still sits near
    *some* site of the extrapolated lattice (about 1 random point in 5 does),
    and each refit then bends the homography further. Instead, local seeds
    compete for every bolt over a window of neighbours, are refitted, and
    seeds on one plane are merged. A fold between panels at a different
    angle, a seam where the grid is offset, and a 45 deg turn of the grid
    (IMG_7503) all break the fit. Parts of one panel separated by a long
    bolt-free gap stay separate panels (IMG_7502's 34 deg panel, top and
    bottom); each measures right, and a point in the gap uses the nearer."""
    n = len(lattice.xy)
    label, site = np.full(n, -1), np.zeros((n, 2))
    if n < PANEL_MIN_BOLTS:
        return label, site
    coords, component = _bfs_index(lattice.xy, lattice.jacobian)

    #Seeds: a local homography per patch of nearest bolts, covering each bolt once.
    near, _ = knn(lattice.xy, lattice.xy, min(PANEL_SEED_NEIGHBOURS, n))
    covered = np.zeros(n, bool)
    homographies = []
    for i in np.random.default_rng(0).permutation(n):
        if covered[i]:
            continue
        patch = np.array([k for k in near[i] if k >= 0 and component[k] == component[i]])
        if len(patch) < PANEL_MIN_SEED:
            continue
        h = _fit_homography(coords[patch], lattice.xy[patch])
        if h is None:
            continue
        _, residual = _sites(h, lattice.xy[patch])
        if (np.median(residual / lattice.spacing_px[patch]) > PANEL_RESIDUAL_TOLERANCE
                or _metric_agrees(h, lattice.xy[patch], lattice.metric[patch]).mean() < PANEL_METRIC_AGREEMENT):
            continue
        homographies.append(h)
        covered[patch] = True

    window, _ = knn(lattice.xy, lattice.xy, min(PANEL_WINDOW, n))
    for _ in range(PANEL_ITERATIONS):
        if not homographies:
            return label, site
        label = _assign(lattice, homographies, window)
        #Seeds start out splitting a panel between them, so one that wins too
        #few bolts to refit keeps its homography for now and can still merge;
        #PANEL_MIN_BOLTS applies to the final pieces.
        panels = []
        for k, h in enumerate(homographies):
            members = np.flatnonzero(label == k)
            if len(members):
                panels.append(_refit(lattice, h, members) or (h, members))
        homographies = [h for h, _ in _merge(lattice, panels, search=False)]
    if not homographies:
        return label, site

    #A homography can win scattered bolts far from its panel: keep connected
    #pieces large enough to be a panel, then merge pieces of one plane again,
    #this time searching offsets across gaps with no bolts.
    label = _assign(lattice, homographies, window)
    pieces = []
    for k, h in enumerate(homographies):
        for piece in _connected_pieces(lattice, np.flatnonzero(label == k)):
            if (p := _refit(lattice, h, piece)):
                pieces.append(p)
    panels = _merge(lattice, pieces, search=True)

    label = np.full(n, -1)
    for k, (h, members) in enumerate(panels):
        s, residual = _sites(h, lattice.xy[members])
        ok = residual <= PANEL_RESIDUAL_TOLERANCE * lattice.spacing_px[members]
        members, s = _unique_sites(members[ok], s[ok], residual[ok])
        label[members], site[members] = k, s
    return label, site


def panel_homographies(lattice: Lattice) -> dict[int, np.ndarray]:
    """Homography (grid units -> px) per panel, least squares over the
    lattice's own bolts in that panel; panels with fewer than
    PANEL_MIN_BOLTS bolts get none."""
    if lattice.panel is None:
        return {}
    if len(lattice.panel) != len(lattice.xy) or len(lattice.grid) != len(lattice.xy):
        raise ValueError("Lattice.panel/grid must have one entry per bolt - subset with Lattice.take()")
    out = {}
    for k in np.unique(lattice.panel[lattice.panel >= 0]):
        m = lattice.panel == k
        if m.sum() >= PANEL_MIN_BOLTS:
            h = _fit_homography(lattice.grid[m], lattice.xy[m])
            if h is not None:
                out[int(k)] = h
    return out


def metric_at(lattice: Lattice, points: np.ndarray) -> np.ndarray:
    """Metric (M, 2, 2) at arbitrary px points (M, 2): from the homography of
    the panel most of the nearest bolts belong to, else interpolated."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    idx, dist = knn(points, lattice.xy, FIELD_NEIGHBOURS)
    valid = idx >= 0
    safe = np.maximum(idx, 0)
    soften = lattice.spacing_px[safe]
    weight = np.where(valid, 1.0 / (dist**2 + soften**2), 0.0)
    weight /= weight.sum(axis=1, keepdims=True)
    field = np.einsum("mk,mkij->mij", weight, lattice.metric[safe])

    homographies = panel_homographies(lattice)
    if not homographies:
        return field
    #Vote among the nearest bolts that are in a panel, the nearest breaking
    #ties. Bolts in no panel don't vote: they're the ones whose own fit
    #failed every panel's checks, typically pooled across a seam, so the
    #field near them is the least reliable thing to measure on. Only a point
    #with no panel bolt among its nearest uses the field.
    ids = list(homographies)
    labels = np.where(valid & np.isin(lattice.panel[safe], ids), lattice.panel[safe], -1)
    first = labels[np.arange(len(labels)), np.argmax(labels >= 0, axis=1)]
    votes = np.stack([(labels == k).sum(axis=1) + 0.5 * (first == k) for k in ids], axis=1)
    choice = np.where((labels >= 0).any(axis=1), np.array(ids)[np.argmax(votes, axis=1)], -1)
    out = field.copy()
    for k, h in homographies.items():
        here = choice == k
        if not here.any():
            continue
        hm, w = _homography_metric(h, points[here])
        _, w_bolts = _homography_metric(h, lattice.xy[lattice.panel == k][:1])
        trusted = (np.sign(w) == np.sign(w_bolts[0])) & (
            np.linalg.norm(hm - field[here], axis=(1, 2)) <= PANEL_FIELD_DEVIATION * np.linalg.norm(field[here], axis=(1, 2)))
        rows = np.flatnonzero(here)[trusted]
        out[rows] = hm[trusted]
    return out


def segment_lengths(lattice: Lattice, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Length in grid units of each straight px segment, integrating the
    local metric at SEGMENT_SAMPLES midpoints."""
    starts = np.asarray(starts, dtype=np.float64).reshape(-1, 2)
    ends = np.asarray(ends, dtype=np.float64).reshape(-1, 2)
    t = (np.arange(SEGMENT_SAMPLES) + 0.5) / SEGMENT_SAMPLES
    step = (ends - starts) / SEGMENT_SAMPLES                       # (P, 2)
    samples = starts[:, None, :] + t[None, :, None] * (ends - starts)[:, None, :]
    m = metric_at(lattice, samples.reshape(-1, 2)).reshape(len(starts), SEGMENT_SAMPLES, 2, 2)
    ds2 = np.einsum("pi,psij,pj->ps", step, m, step)
    return np.sqrt(np.maximum(ds2, 0.0)).sum(axis=1)


def segment_support(lattice: Lattice, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """How far each straight px segment strays from the bolts it is measured
    on: the largest distance from one of its SEGMENT_SAMPLES points to the
    nearest fitted bolt, in that bolt's nearest-neighbour spacings."""
    starts = np.asarray(starts, dtype=np.float64).reshape(-1, 2)
    ends = np.asarray(ends, dtype=np.float64).reshape(-1, 2)
    t = (np.arange(SEGMENT_SAMPLES) + 0.5) / SEGMENT_SAMPLES
    samples = starts[:, None, :] + t[None, :, None] * (ends - starts)[:, None, :]
    idx, dist = knn(samples.reshape(-1, 2), lattice.xy, 1)
    spacing = lattice.spacing_px[np.maximum(idx[:, 0], 0)]
    return (dist[:, 0] / spacing).reshape(len(starts), SEGMENT_SAMPLES).max(axis=1)


def wall_length_units(lattice: Lattice) -> float | None:
    """Top bolt to bottom bolt within a vertical band of bolts around the
    median x, plus WALL_END_ALLOWANCE_UNITS at each end. Along the wall surface, so a
    steep or angled panel counts at its real length, not its height."""
    if len(lattice.xy) < 2:
        return None
    x_mid = np.median(lattice.xy[:, 0])
    band = np.abs(lattice.xy[:, 0] - x_mid) <= WALL_BAND_SPACINGS * np.median(lattice.spacing_px)
    column = lattice.xy[band]
    if len(column) < 2:
        return None
    top, bottom = column[np.argmin(column[:, 1])], column[np.argmax(column[:, 1])]
    return float(segment_lengths(lattice, top, bottom)[0] + 2 * WALL_END_ALLOWANCE_UNITS)


def index_lattice(lattice: Lattice) -> tuple[np.ndarray, np.ndarray]:
    """Integer lattice coordinates for fitted bolts, consistent within each
    component: (coords (N, 2) in grid units, component (N,) id). Used for
    accuracy evaluation, as the ground truth.

    Bolts in a panel take their panel's sites. Panels whose grid continues
    across the seam (the bolts just past it land on one consistent site of
    the neighbouring panel's lattice) share one frame and component, so a
    pair across the seam has a true distance too - along the wall surface,
    since the grid is unfolded with the panels. Bolts in no panel are
    indexed among themselves by _bfs_index.

    Panel sites replace the step-by-step walk wherever there are panels: a
    walk can slip by one site where a link rounds the wrong way, and every
    bolt indexed after the slip inherits it (seen on IMG_7502, where 7 of 83
    bolts were one site off).
    """
    n = len(lattice.xy)
    homographies = panel_homographies(lattice)
    if not homographies:
        return _bfs_index(lattice.xy, lattice.jacobian)
    coords, component = np.zeros((n, 2)), np.full(n, -1)
    members = {k: np.flatnonzero(lattice.panel == k) for k in homographies}
    frame: dict[int, tuple[np.ndarray, np.ndarray]] = {}  # panel -> (symmetry, offset) into its component's frame
    next_id = 0
    for root in sorted(members, key=lambda k: -len(members[k])):
        if root in frame:
            continue
        frame[root] = (np.eye(2), np.zeros(2))
        component[members[root]] = next_id
        queue = deque([root])
        while queue:
            p = queue.popleft()
            for q in members:
                if q in frame:
                    continue
                #Either side's lattice can be the one extended across the
                #seam: the bolts nearest it on one side may be hidden.
                link = _panel_link(lattice, homographies[p], members[p], members[q])
                if link is None:
                    back = _panel_link(lattice, homographies[q], members[q], members[p])
                    if back is None:
                        continue
                    link = (back[0].T, -back[0].T @ back[1])
                sym, t = link
                sym_p, t_p = frame[p]
                frame[q] = (sym_p @ sym, sym_p @ t + t_p)
                component[members[q]] = next_id
                queue.append(q)
        next_id += 1
    for k, (sym, t) in frame.items():
        coords[members[k]] = lattice.grid[members[k]] @ sym.T + t
    rest = np.flatnonzero(component < 0)
    if len(rest):
        c, comp = _bfs_index(lattice.xy[rest], lattice.jacobian[rest])
        coords[rest], component[rest] = c, comp + next_id
    return coords, component


def _panel_link(lattice: Lattice, h: np.ndarray, p: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """(symmetry, offset) taking panel q's sites into panel p's frame, when
    q's bolts within PANEL_LINK_SPACINGS of p sit on p's lattice extended
    across the seam, all shifted by the same lattice symmetry and offset."""
    gap = np.hypot(*(lattice.xy[q][:, None] - lattice.xy[p][None]).transpose(2, 0, 1)).min(axis=1)
    near = q[gap <= PANEL_LINK_SPACINGS * lattice.spacing_px[q]]
    if len(near) < PANEL_LINK_MIN_BOLTS:
        return None
    implied, residual = _sites(h, lattice.xy[near])
    on = residual <= PANEL_RESIDUAL_TOLERANCE * lattice.spacing_px[near]
    best = None
    for sym in LATTICE_SYMMETRIES:
        shift = np.round(2 * (implied - lattice.grid[near] @ sym.T)[on]).astype(int)
        if len(shift) == 0:
            break
        values, counts = np.unique(shift, axis=0, return_counts=True)
        k = np.argmax(counts)
        if best is None or counts[k] > best[0]:
            best = (counts[k], sym, values[k] / 2)
    if best is None or best[0] < PANEL_LINK_MIN_BOLTS or best[0] < PANEL_LINK_FRACTION * len(near):
        return None
    return best[1], best[2]


def _bfs_index(xy: np.ndarray, jacobian: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Integer lattice coordinates consistent within each connected patch,
    by walking neighbour links breadth-first: (coords (N, 2), component (N,)).

    Each bolt's J is aligned to its parent's (picking the lattice symmetry
    that matches best) and the link is rounded to an integer lattice offset.
    A link that doesn't round cleanly (a misaligned seam, a stray detection)
    isn't followed, so it starts a new component instead of corrupting
    coordinates. Also gives segment_panels its seed coordinates."""
    n = len(xy)
    coords = np.zeros((n, 2))
    component = np.full(n, -1)
    jac = jacobian.copy()
    if n == 0:
        return coords, component
    idx, _ = knn(xy, xy, FIT_NEIGHBOURS + 1)

    next_id = 0
    for seed in range(n):
        if component[seed] >= 0:
            continue
        component[seed] = next_id
        queue = deque([seed])
        while queue:
            p = queue.popleft()
            for c in idx[p]:
                if c < 0 or c == p or component[c] >= 0:
                    continue
                aligned = min((jac[c] @ r for r in LATTICE_SYMMETRIES), key=lambda m: np.linalg.norm(m - jac[p]))
                if np.linalg.norm(aligned - jac[p]) > MAX_METRIC_DEVIATION * np.linalg.norm(jac[p]):
                    continue
                mean_j = (aligned + jac[p]) / 2
                k = np.linalg.solve(LATTICE_BASIS, np.linalg.solve(mean_j, xy[c] - xy[p]))
                if np.abs(k - np.round(k)).max() > FIT_ROUNDING_TOLERANCE:
                    continue
                jac[c] = aligned
                coords[c] = coords[p] + LATTICE_BASIS @ np.round(k)
                component[c] = next_id
                queue.append(c)
        next_id += 1
    return coords, component


def _insufficient(bolt_count: int) -> dict:
    return {
        "status": "insufficient_bolts",
        "bolt_count": bolt_count,
        "wall_length_units": None,
        "distances_units": None,
        "tiers": None,
        "angles_deg": None,
        "angle_source": None,
        "angle_margin_deg": None,
    }


def _hold_angles(lattice: Lattice, hold_xy: np.ndarray, image_size: tuple[int, int], gravity, focal_35mm) -> dict:
    """Wall angle at each hold (degrees from vertical, positive = overhanging;
    None where unknown), from the phone's sensor reading when there is a usable
    one, else an assumed camera pitch. Never raises: the angle is extra
    information, and failing here must not take the distances down with it."""
    reading = angle.gravity_from_sensor(gravity) if gravity is not None else None
    if reading is not None:
        down, source, margin = reading[0], "sensor", angle.MARGIN_SENSOR_DEG
    else:
        down, source, margin = angle.gravity_from_pitch(angle.DEFAULT_PITCH_DEG), "assumed", angle.MARGIN_ASSUMED_DEG
    try:
        found = angle.angles_at(lattice, hold_xy, image_size, angle.focal_px(image_size, focal_35mm), down)
        angles = [None if not np.isfinite(a) else round(float(a), 1) for a in found]
    except Exception:  # noqa: BLE001 - see docstring
        logging.getLogger(__name__).exception("scale: wall angle failed")
        return {"angles_deg": None, "angle_source": None, "angle_margin_deg": None}
    return {"angles_deg": angles, "angle_source": source, "angle_margin_deg": margin}


def _tier_rows(support: np.ndarray) -> list[str]:
    """N x N support -> one string per row, "A" or "C" per column (a list of
    N-character strings keeps the /detect payload small)."""
    tiers = np.where(support <= TIER_A_MAX_SUPPORT, "A", "C")
    return ["".join(row) for row in tiers]


def compute_scale(
    detections: list[dict],
    image_size: tuple[int, int],
    bolts: list[dict],
    gravity=None,
    focal_35mm: float | None = None,
) -> dict:
    """Detections (normalized centroids) + the uploaded photo's full-res
    (width, height) + bolts.detect_bolt_holes() output -> the `scale` object
    returned by /detect.

    "insufficient_bolts" (null distances/wall length) when no bolt has enough
    lattice-consistent neighbours to fit - nothing to measure against.

    distances_units is N x N, indexed in the same order as `detections`.

    `gravity` is the phone accelerometer reading (x, y, z) taken when the photo
    was shot, and `focal_35mm` the photo's EXIF 35 mm-equivalent focal length;
    both optional, and only the wall angles (angles_deg, one per detection)
    depend on them - see angle.py.
    """
    width, height = image_size
    bolt_xy = np.array([[b["x"] * width, b["y"] * height] for b in bolts]).reshape(-1, 2)
    lattice = fit_lattice(bolt_xy)
    if len(lattice.xy) == 0:
        return _insufficient(len(bolts))

    hold_xy = np.array([[d["centroid"]["x"] * width, d["centroid"]["y"] * height] for d in detections]).reshape(-1, 2)
    n = len(hold_xy)
    distances = np.zeros((n, n))
    support = np.zeros((n, n))
    if n > 1:
        a, b = np.triu_indices(n, k=1)
        lengths = segment_lengths(lattice, hold_xy[a], hold_xy[b])
        distances[a, b] = distances[b, a] = lengths
        support[a, b] = support[b, a] = segment_support(lattice, hold_xy[a], hold_xy[b])

    wall = wall_length_units(lattice)
    return {
        "status": "ok",
        "bolt_count": len(bolts),
        "wall_length_units": None if wall is None else round(wall, DISTANCE_DECIMALS),
        "distances_units": np.round(distances, DISTANCE_DECIMALS).tolist(),
        "tiers": _tier_rows(support),
        **_hold_angles(lattice, hold_xy, image_size, gravity, focal_35mm),
    }


def select_angles(scale: dict, detections: list[dict], hold_ids: list[int]) -> list[float | None] | None:
    """scale["angles_deg"] for hold_ids, in hold_ids order. None when the
    scale has no angles (an older cached scale, or none could be estimated)."""
    angles = scale.get("angles_deg")
    if angles is None:
        return None
    index_of = {d["id"]: i for i, d in enumerate(detections)}
    return [angles[index_of[hold_id]] for hold_id in hold_ids]


def select_tiers(scale: dict, detections: list[dict], hold_ids: list[int]) -> list[list[str]] | None:
    """Sub-matrix of scale["tiers"] for hold_ids, in hold_ids order, like
    select_distances. None when the scale has no tiers."""
    rows = scale.get("tiers")
    if rows is None:
        return None
    index_of = {d["id"]: i for i, d in enumerate(detections)}
    picked = [index_of[hold_id] for hold_id in hold_ids]
    return [[rows[r][c] for c in picked] for r in picked]


def select_distances(scale: dict, detections: list[dict], hold_ids: list[int]) -> list[list[float]] | None:
    """Sub-matrix of scale["distances_units"] for hold_ids, in hold_ids order.

    None when the scale has no distances (insufficient_bolts). Ids are looked
    up by position in `detections`, since the matrix shares that ordering.
    """
    matrix = scale.get("distances_units")
    if matrix is None:
        return None
    index_of = {d["id"]: i for i, d in enumerate(detections)}
    rows = [index_of[hold_id] for hold_id in hold_ids]
    return [[matrix[r][c] for c in rows] for r in rows]
