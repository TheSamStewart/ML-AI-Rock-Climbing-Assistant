import Constants from 'expo-constants'

//Use expo constant to get IP to send req to DEV ONLY

const host = Constants.expoConfig?.hostUri?.split(':')[0] ?? 'localhost'
export const API_URL = `http://${host}:8000`

//One ML-detected hold/volume - polygon and centroid are normalized (0-1),
//relative to the photo, matching the same convention hold taps already use.

export type Detection = {
  id: number
  class_name: string
  centroid: { x: number; y: number }
  polygon: { x: number; y: number }[]
  confidence: number
  size: number
}

//Wall scale in grid units (1 unit = the user's bolt spacing) - multiply by
//boltSpacingCm for cm. distances_units is N x N, indexed in the same order as
//detections. Keep in sync with backend/wall_analysis/scale.py.

export type Scale = {
  status: 'ok' | 'insufficient_bolts'
  bolt_count: number
  wall_length_units: number | null
  distances_units: number[][] | null
  //One string per row, one 'A' (bolt grid visible along the line) or 'C'
  //(scale borrowed across hidden bolts) per column, same order as detections.
  tiers: string[] | null
  //Wall angle around each hold in degrees from vertical (positive =
  //overhanging, null where unknown), same order as detections. Estimated from
  //the bolt grid's shape plus the phone's tilt; angle_margin_deg is how far
  //off it can be, and angle_source says whether the tilt came from the phone's
  //sensor or was assumed. All null on an older backend or when no bolts were found.
  angles_deg?: (number | null)[] | null
  angle_source?: 'sensor' | 'assumed' | null
  angle_margin_deg?: number | null
}

export type DetectHoldsResponse = {
  detection_id: string
  detections: Detection[]
  scale: Scale
}

export type DetectHoldsVariables = {
  uri: string
  //The phone's accelerometer reading when the photo was taken, or null/absent
  //(test photo, no sensor): the backend then assumes a camera tilt.
  gravity?: [number, number, number] | null
}

export async function detectHolds({
  uri,
  gravity,
}: DetectHoldsVariables): Promise<DetectHoldsResponse> {
  //Create unique filename for image

  const filename = uri.split('/').pop() ?? `climb-${Date.now()}.jpg`
  const ext = /\.(\w+)$/.exec(filename)?.[1] ?? 'jpg'
  const type = `image/${ext === 'jpg' ? 'jpeg' : ext}`

  //React Native's classic FormData.append('photo', { uri, name, type }) shorthand
  //is no longer recognized under the New Architecture

  const fileBlob = await (await fetch(uri)).blob()

  const formData = new FormData()
  formData.append('photo', new Blob([fileBlob], { type }), filename)
  if (gravity) formData.append('gravity', JSON.stringify(gravity))

  const res = await fetch(`${API_URL}/detect`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) throw new Error(`Detection failed: ${res.status}`)
  return (await res.json()) as DetectHoldsResponse
}
