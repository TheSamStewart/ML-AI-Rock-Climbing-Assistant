//Bolt-hole patterns the user can pick in Settings (slice 16).
//
//The backend always works in "side of a square that has a hole in its
//centre" (bolt_spacing_cm). The other two patterns are the very same set of
//holes turned 45 degrees - only the distance people naturally measure
//differs: between neighbouring holes, which is that side / sqrt(2). So the
//app converts here and the backend needs no change.

export type BoltPattern = 'centred' | 'plain' | 'diamond'

export const BOLT_PATTERN_STORAGE_KEY = 'boltPattern'
export const DEFAULT_BOLT_PATTERN: BoltPattern = 'centred'

export const BOLT_PATTERNS: {
  id: BoltPattern
  label: string
  measure: string
  factor: number
}[] = [
  {
    id: 'centred',
    label: 'Squares with a centre hole',
    measure: 'Measure between two corner holes along the side of a square (not to the centre hole).',
    factor: 1,
  },
  {
    id: 'plain',
    label: 'Plain square grid',
    measure: 'Measure between two neighbouring holes in a row.',
    factor: Math.SQRT2,
  },
  {
    id: 'diamond',
    label: 'Diamond grid',
    measure: 'Measure between two neighbouring holes along a diagonal line of holes.',
    factor: Math.SQRT2,
  },
]

export function isBoltPattern(value: string | null): value is BoltPattern {
  return value === 'centred' || value === 'plain' || value === 'diamond'
}

function factorOf(pattern: BoltPattern): number {
  return BOLT_PATTERNS.find((p) => p.id === pattern)?.factor ?? 1
}

//What the user measured on their wall -> the square side the backend uses.

export function toSquareSideCm(measuredCm: number, pattern: BoltPattern): number {
  return measuredCm * factorOf(pattern)
}

//The square side -> what the user would measure for that pattern (1 decimal).

export function toMeasuredCm(squareSideCm: number, pattern: BoltPattern): number {
  return Math.round((squareSideCm / factorOf(pattern)) * 10) / 10
}
