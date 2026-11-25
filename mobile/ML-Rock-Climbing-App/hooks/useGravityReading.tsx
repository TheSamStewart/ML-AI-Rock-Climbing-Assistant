import { useEffect, useRef } from 'react'
import { Accelerometer } from 'expo-sensors'

//The phone's tilt at the moment a photo is taken, so the backend can turn the
//wall's shape in the photo into an angle from vertical (backend/angle.py).
//Accelerometer reading in G in the device frame (x right, y up the screen,
//z out of the screen). The backend works out the Android/iOS sign difference
//itself, so the raw reading is sent as is.
//
//Optional by design: no sensor, no permission or a failed subscription just
//leaves the reading null, and the backend falls back to an assumed camera tilt.

export type GravityReading = [number, number, number]

//Low-pass factor per sample at SAMPLE_INTERVAL_MS: smooths hand shake so the
//reading at the shutter is the held tilt, not a jolt (about 0.5 s of memory).

const SAMPLE_INTERVAL_MS = 100
const SMOOTHING = 0.3

export function useGravityReading() {
  const latest = useRef<GravityReading | null>(null)

  useEffect(() => {
    let subscription: { remove: () => void } | null = null
    let cancelled = false

    ;(async () => {
      try {
        if (!(await Accelerometer.isAvailableAsync()) || cancelled) return
        Accelerometer.setUpdateInterval(SAMPLE_INTERVAL_MS)
        subscription = Accelerometer.addListener(({ x, y, z }) => {
          const prev = latest.current
          latest.current = prev
            ? [
                prev[0] + SMOOTHING * (x - prev[0]),
                prev[1] + SMOOTHING * (y - prev[1]),
                prev[2] + SMOOTHING * (z - prev[2]),
              ]
            : [x, y, z]
        })
      } catch (e) {
        console.warn('Accelerometer unavailable - wall angle will use an assumed tilt', e)
      }
    })()

    return () => {
      cancelled = true
      subscription?.remove()
    }
  }, [])

  return latest
}
