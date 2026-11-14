import { useEffect, useState } from 'react'
import AsyncStorage from '@react-native-async-storage/async-storage'
import {
  BOLT_SPACING_STORAGE_KEY,
  DEFAULT_BOLT_SPACING_CM,
  parseBoltSpacing,
} from '@/utils/boltSpacing'

//The user's bolt grid spacing, persisted on device. Starts at the default
//and swaps in the stored value once it loads - a missing or corrupt stored
//value just keeps the default.

export function useBoltSpacing() {
  const [boltSpacingCm, setBoltSpacingCmState] = useState(DEFAULT_BOLT_SPACING_CM)

  useEffect(() => {
    let cancelled = false

    AsyncStorage.getItem(BOLT_SPACING_STORAGE_KEY)
      .then((stored) => {
        const parsed = parseBoltSpacing(stored)
        if (!cancelled && parsed !== null) setBoltSpacingCmState(parsed)
      })
      .catch((err) => console.error('Failed to load bolt spacing', err))

    return () => {
      cancelled = true
    }
  }, [])

  //State updates immediately so the UI never waits on storage.

  const setBoltSpacingCm = (value: number) => {
    setBoltSpacingCmState(value)
    AsyncStorage.setItem(BOLT_SPACING_STORAGE_KEY, String(value)).catch((err) =>
      console.error('Failed to save bolt spacing', err)
    )
  }

  return { boltSpacingCm, setBoltSpacingCm }
}
