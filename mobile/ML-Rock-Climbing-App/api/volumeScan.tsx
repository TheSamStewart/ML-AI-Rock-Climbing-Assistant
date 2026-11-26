import { API_URL } from '@/api/detectHolds'
import { GravityReading } from '@/hooks/useGravityReading'

//DEV ONLY - the volume scan test feature (docs/milestones/v0.2/38-volume-scan-trial/spec.md).
//Sends the photo, a burst taken while stepping sideways and the tapped volume's
//outline; the server measures each visible face. Keep in sync with
//backend/api/main.py's /dev/volume-scan and backend/wall_analysis/volume_scan.py.

export type ScanFace = {
  //Degrees from vertical, + overhang / - slab (same as the wall angle).
  steepness_deg: number
  facing: 'out' | 'left' | 'right' | 'undefined'
  facing_deg: number | null
  //Normalised outline on the photo.
  outline: { x: number; y: number }[]
  n_points: number
}

export type VolumeScanResponse = {
  scan_id: string
  faces: ScanFace[]
  //Null when the photo's bolt-grid fit can't be trusted for cm.
  depth_cm: number | null
  wall_angle_deg: number
  frames_used: number
  frames_sent: number
  seconds: number
}

export type VolumeScanVariables = {
  photoUri: string
  frameUris: string[]
  gravity: GravityReading | null
  volumePolygon: { x: number; y: number }[]
  boltSpacingCm: number
}

async function asBlob(uri: string): Promise<Blob> {
  const blob = await (await fetch(uri)).blob()
  return new Blob([blob], { type: 'image/jpeg' })
}

export async function scanVolume({
  photoUri,
  frameUris,
  gravity,
  volumePolygon,
  boltSpacingCm,
}: VolumeScanVariables): Promise<VolumeScanResponse> {
  const formData = new FormData()
  formData.append('photo', await asBlob(photoUri), 'photo.jpg')
  for (let i = 0; i < frameUris.length; i++) {
    formData.append('frames', await asBlob(frameUris[i]), `frame_${i}.jpg`)
  }
  formData.append('volume_polygon', JSON.stringify(volumePolygon))
  formData.append('bolt_spacing_cm', String(boltSpacingCm))
  if (gravity) formData.append('gravity', JSON.stringify(gravity))

  const res = await fetch(`${API_URL}/dev/volume-scan`, { method: 'POST', body: formData })
  if (!res.ok) {
    //The server explains every failed scan in `detail` (and saves it).
    let detail = `Scan failed: ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      //not JSON - keep the status message
    }
    throw new Error(detail)
  }
  return (await res.json()) as VolumeScanResponse
}
