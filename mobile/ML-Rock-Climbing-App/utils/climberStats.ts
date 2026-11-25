//Climber height and arm span (slice 15), both optional - keep the ranges in
//sync with CLIMBER_RANGES_CM in backend/main.py.

export const CLIMBER_HEIGHT_STORAGE_KEY = 'climberHeightCm'
export const CLIMBER_ARM_SPAN_STORAGE_KEY = 'climberArmSpanCm'
export const MIN_CLIMBER_HEIGHT_CM = 100
export const MAX_CLIMBER_HEIGHT_CM = 230
export const MIN_CLIMBER_ARM_SPAN_CM = 90
export const MAX_CLIMBER_ARM_SPAN_CM = 250

export type ClimberStats = {
  heightCm: number | null
  armSpanCm: number | null
}

//Parses user/storage text for an optional measurement: empty means "not set"
//(null), anything else must be a number within [min, max] or it's invalid.

export function parseOptionalCm(
  text: string | null,
  min: number,
  max: number
): { ok: true; value: number | null } | { ok: false } {
  if (text === null || text.trim() === '') return { ok: true, value: null }
  const value = Number(text.trim().replace(',', '.'))
  if (!Number.isFinite(value) || value < min || value > max) return { ok: false }
  return { ok: true, value }
}
