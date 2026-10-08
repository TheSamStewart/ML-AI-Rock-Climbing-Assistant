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

export type DetectHoldsResponse = {
  detection_id: string
  detections: Detection[]
}

export type DetectHoldsVariables = {
  uri: string
}

export async function detectHolds({ uri }: DetectHoldsVariables): Promise<DetectHoldsResponse> {
  //Create unique filename for image

  const filename = uri.split('/').pop() ?? `climb-${Date.now()}.jpg`
  const ext = /\.(\w+)$/.exec(filename)?.[1] ?? 'jpg'
  const type = `image/${ext === 'jpg' ? 'jpeg' : ext}`

  //React Native's classic FormData.append('photo', { uri, name, type }) shorthand
  //is no longer recognized under the New Architecture

  const fileBlob = await (await fetch(uri)).blob()

  const formData = new FormData()
  formData.append('photo', new Blob([fileBlob], { type }), filename)

  const res = await fetch(`${API_URL}/detect`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) throw new Error(`Detection failed: ${res.status}`)
  return (await res.json()) as DetectHoldsResponse
}
