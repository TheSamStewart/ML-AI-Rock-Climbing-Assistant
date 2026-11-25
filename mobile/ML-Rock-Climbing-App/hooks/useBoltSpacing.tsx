import { useEffect, useState } from 'react'
import AsyncStorage from '@react-native-async-storage/async-storage'
import {
  BOLT_SPACING_STORAGE_KEY,
  DEFAULT_BOLT_SPACING_CM,
  parseBoltSpacing,
} from '@/utils/boltSpacing'
import {
  BOLT_PATTERN_STORAGE_KEY,
  BoltPattern,
  DEFAULT_BOLT_PATTERN,
  isBoltPattern,
} from '@/utils/boltPattern'

//The user's bolt grid, persisted on device: boltSpacingCm is always the side
//of a square with a centre hole (what the backend and the distance labels
//use), whatever pattern was picked - the pattern (slice 16) only changes
//what the user measures in Settings. Starts at the defaults and swaps in
//the stored values once they load; a missing or corrupt value keeps the
//default, so existing users stay on "squares with a centre hole".

export function useBoltSpacing() {
  const [boltSpacingCm, setBoltSpacingCmState] = useState(DEFAULT_BOLT_SPACING_CM)
  const [boltPattern, setBoltPatternState] = useState<BoltPattern>(DEFAULT_BOLT_PATTERN)

  useEffect(() => {
    let cancelled = false

    AsyncStorage.multiGet([BOLT_SPACING_STORAGE_KEY, BOLT_PATTERN_STORAGE_KEY])
      .then(([[, stored], [, pattern]]) => {
        if (cancelled) return
        const parsed = parseBoltSpacing(stored)
        if (parsed !== null) setBoltSpacingCmState(parsed)
        if (isBoltPattern(pattern)) setBoltPatternState(pattern)
      })
      .catch((err) => console.error('Failed to load bolt spacing', err))

    return () => {
      cancelled = true
    }
  }, [])

  //State updates immediately so the UI never waits on storage.

  const setBoltSettings = (squareSideCm: number, pattern: BoltPattern) => {
    setBoltSpacingCmState(squareSideCm)
    setBoltPatternState(pattern)
    AsyncStorage.multiSet([
      [BOLT_SPACING_STORAGE_KEY, String(squareSideCm)],
      [BOLT_PATTERN_STORAGE_KEY, pattern],
    ]).catch((err) => console.error('Failed to save bolt spacing', err))
  }

  return { boltSpacingCm, boltPattern, setBoltSettings }
}
