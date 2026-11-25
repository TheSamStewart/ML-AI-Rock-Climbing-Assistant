import { useEffect, useState } from 'react'
import AsyncStorage from '@react-native-async-storage/async-storage'
import {
  CLIMBER_ARM_SPAN_STORAGE_KEY,
  CLIMBER_HEIGHT_STORAGE_KEY,
  ClimberStats,
  MAX_CLIMBER_ARM_SPAN_CM,
  MAX_CLIMBER_HEIGHT_CM,
  MIN_CLIMBER_ARM_SPAN_CM,
  MIN_CLIMBER_HEIGHT_CM,
  parseOptionalCm,
} from '@/utils/climberStats'

//The climber's height and arm span, persisted on device like the bolt
//spacing (useBoltSpacing). Both start unset; a missing or corrupt stored
//value stays unset.

export function useClimberStats() {
  const [climberStats, setClimberStatsState] = useState<ClimberStats>({
    heightCm: null,
    armSpanCm: null,
  })

  useEffect(() => {
    let cancelled = false

    AsyncStorage.multiGet([CLIMBER_HEIGHT_STORAGE_KEY, CLIMBER_ARM_SPAN_STORAGE_KEY])
      .then(([[, height], [, span]]) => {
        const h = parseOptionalCm(height, MIN_CLIMBER_HEIGHT_CM, MAX_CLIMBER_HEIGHT_CM)
        const s = parseOptionalCm(span, MIN_CLIMBER_ARM_SPAN_CM, MAX_CLIMBER_ARM_SPAN_CM)
        if (!cancelled)
          setClimberStatsState({
            heightCm: h.ok ? h.value : null,
            armSpanCm: s.ok ? s.value : null,
          })
      })
      .catch((err) => console.error('Failed to load climber stats', err))

    return () => {
      cancelled = true
    }
  }, [])

  //State updates immediately; an unset value is removed from storage.

  const setClimberStats = (value: ClimberStats) => {
    setClimberStatsState(value)
    const save = (key: string, cm: number | null) =>
      cm === null ? AsyncStorage.removeItem(key) : AsyncStorage.setItem(key, String(cm))
    Promise.all([
      save(CLIMBER_HEIGHT_STORAGE_KEY, value.heightCm),
      save(CLIMBER_ARM_SPAN_STORAGE_KEY, value.armSpanCm),
    ]).catch((err) => console.error('Failed to save climber stats', err))
  }

  return { climberStats, setClimberStats }
}
