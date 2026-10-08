import type { Detection } from '@/api/detectHolds'

//Client-side port of backend/detection.py's per-detection matching logic
//(from the pre-refactor worker.py) - detection and selection both now happen
//before submission, so a tap needs to resolve to one of the already-fetched
//detections rather than waiting for the backend to match it after the fact.

//A tap that misses every polygon still gets one nearest-centroid fallback
//chance, but only within its own catchment - CATCHMENT_MULTIPLIER times that
//detection's own size - so it can't reach across the wall to a merely-closer
//hold. MIN_CATCHMENT_RADIUS floors this for very small detections.
//
//Same constants as the original backend implementation - starting guesses,
//not measured against real best.pt output.

const CATCHMENT_MULTIPLIER = 0.75
const MIN_CATCHMENT_RADIUS = 0.02

function distance(a: { x: number; y: number }, b: { x: number; y: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

//Ray-casting point-in-polygon test in normalized (0-1) coordinates.

function isPointInPolygon(point: { x: number; y: number }, polygon: { x: number; y: number }[]) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const { x: xi, y: yi } = polygon[i]
    const { x: xj, y: yj } = polygon[j]
    const crosses =
      yi > point.y !== yj > point.y &&
      point.x < ((xj - xi) * (point.y - yi)) / (yj - yi + 1e-15) + xi
    if (crosses) inside = !inside
  }
  return inside
}

//Resolves a single tap to the detection it refers to, or null if it misses
//every candidate. `excludeIds` lets the caller keep already-selected holds
//out of consideration - mirrors the old backend's one-tap-per-detection
//invariant, now expressed by the caller as toggle-selection.

export function matchTapToHold(
  tap: { x: number; y: number },
  detections: Detection[],
  excludeIds: Set<number> = new Set()
): Detection | null {
  const candidates = detections.filter((d) => !excludeIds.has(d.id))
  if (candidates.length === 0) return null

  //Phase 1: containment - a tap inside a detection's polygon matches it
  //directly (nearest-centroid tie-break if it falls inside more than one
  //overlapping polygon).

  const containing = candidates.filter((d) => isPointInPolygon(tap, d.polygon))
  if (containing.length > 0) {
    return containing.reduce((closest, d) =>
      distance(tap, d.centroid) < distance(tap, closest.centroid) ? d : closest
    )
  }

  //Phase 2: nearest-centroid fallback, bounded by each candidate's own
  //size-scaled catchment radius so a tap can't be force-matched to
  //something far away.

  let best: Detection | null = null
  let bestDist = Infinity
  for (const d of candidates) {
    const dist = distance(tap, d.centroid)
    const threshold = Math.max(d.size * CATCHMENT_MULTIPLIER, MIN_CATCHMENT_RADIUS)
    if (dist <= threshold && dist < bestDist) {
      best = d
      bestDist = dist
    }
  }
  return best
}
