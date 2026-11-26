//Bolt grid spacing (side of one bolt-hole square) - keep in sync with
//DEFAULT/MIN/MAX_BOLT_SPACING_CM in backend/api/main.py.

export const BOLT_SPACING_STORAGE_KEY = 'boltSpacingCm'
export const DEFAULT_BOLT_SPACING_CM = 20
export const MIN_BOLT_SPACING_CM = 10
export const MAX_BOLT_SPACING_CM = 50

//Parses user/storage text into a valid spacing, or null if it isn't one.

export function parseBoltSpacing(text: string | null): number | null {
  if (text === null || text.trim() === '') return null
  const value = Number(text.trim().replace(',', '.'))
  if (!Number.isFinite(value) || value < MIN_BOLT_SPACING_CM || value > MAX_BOLT_SPACING_CM)
    return null
  return value
}

//Distance label for PhotoPreview: cm below 1 m, else m to 1 decimal.

export function formatDistance(cm: number): string {
  return cm < 100 ? `${Math.round(cm)} cm` : `${(cm / 100).toFixed(1)} m`
}
