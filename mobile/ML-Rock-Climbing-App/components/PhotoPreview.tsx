import { useEffect, useMemo, useState } from 'react'
import { View, StyleSheet, Text, Button, Image, useWindowDimensions } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import { scheduleOnRN } from 'react-native-worklets'
import * as Crypto from 'expo-crypto'
import { useClimbAnalysis } from '@/hooks/useClimbAnalysis'

//Handles the captured photo only - preview, retake, and submission to analysis.
//Knows nothing about camera permissions or capture itself.

type PhotoPreviewProps = {
  uri: string
  onRetake: () => void
  onSubmitted: (task_id: string) => void
}

type TapPoint = {
  key: string
  x: number
  y: number
}

type Box = {
  width: number
  height: number
}

const CIRCLE_SIZE = 32

export function PhotoPreview({ uri, onRetake, onSubmitted }: PhotoPreviewProps) {
  //Climb analysis submission - mutate() triggers the POST, state drives the UI

  const { mutate, isPending, isError, error } = useClimbAnalysis()

  //Normalized (0-1) taps, relative to the photo itself - not the screen.

  const [taps, setTaps] = useState<TapPoint[]>([])

  //The photo's native pixel size - resizeMode="contain" letterboxes the image inside
  //the screen whenever the photo's aspect ratio doesn't match the screen's, so we need
  //the real dimensions to size a box that matches the photo exactly (no letterbox math).

  const [imgSize, setImgSize] = useState<Box | null>(null)

  useEffect(() => {
    let cancelled = false

    Image.getSize(
      uri,
      (width, height) => {
        if (!cancelled) setImgSize({ width, height })
      },
      (err) => console.error('Failed to read image size', err)
    )

    return () => {
      cancelled = true
    }
  }, [uri])

  //previewContainer below is a bare flex:1 with no constraining ancestor, so the window
  //size is the available space - same pattern CustomCamera.tsx already uses for layout.

  const { width: winW, height: winH } = useWindowDimensions()

  //Fits the photo's aspect ratio inside the available window space (the same "contain"
  //fit resizeMode does internally) so this box's bounds equal the photo's rendered bounds.

  const box = useMemo<Box | null>(() => {
    if (!imgSize) return null

    const containerAspect = winW / winH
    const imgAspect = imgSize.width / imgSize.height

    if (imgAspect > containerAspect) {
      return { width: winW, height: winW / imgAspect }
    }
    return { width: winH * imgAspect, height: winH }
  }, [imgSize, winW, winH])

  const addTap = (rawX: number, rawY: number) => {
    // This function runs on the JS thread
    if (!box) {
      console.warn('addTap called before box was ready')
      return
    }

    const x = Math.min(1, Math.max(0, rawX / box.width))
    const y = Math.min(1, Math.max(0, rawY / box.height))

    setTaps((prev) => [...prev, { key: `${Date.now()}-${Math.random()}`, x, y }])
  }

  const undoTap = () => {
    setTaps((prev) => prev.slice(0, -1))
  }

  //Detects tap and adds to taps state

  const tapGesture = Gesture.Tap().onEnd((event, success) => {
    'worklet'
    if (success) {
      scheduleOnRN(addTap, event.x, event.y)
    }
  })

  //We preview the user the image, if submit is pressed make the call to the API

  return (
    <View style={styles.previewContainer}>
      {box && (
        <GestureDetector gesture={tapGesture}>
          <View style={{ width: box.width, height: box.height }}>
            <Image source={{ uri }} style={StyleSheet.absoluteFill} resizeMode="contain" />

            {/* Renders the screen taps onto the image preview */}

            {taps.map((tap) => (
              <View
                key={tap.key}
                pointerEvents="none"
                style={[
                  styles.tapCircle,
                  {
                    left: tap.x * box.width - CIRCLE_SIZE / 2,
                    top: tap.y * box.height - CIRCLE_SIZE / 2,
                  },
                ]}
              />
            ))}
          </View>
        </GestureDetector>
      )}

      {/* Button rendering/logic */}

      <SafeAreaView edges={['bottom']} style={styles.previewActions}>
        <View style={styles.buttonsRow}>
          <Button onPress={onRetake} title="Retake" />
          <Button onPress={undoTap} title="Undo" disabled={taps.length === 0} />
          <Button
            onPress={() =>
              //A fresh idempotency key per press
              mutate(
                {
                  uri,
                  idempotencyKey: Crypto.randomUUID(),
                  taps: taps.map(({ x, y }) => ({ x, y })),
                },
                { onSuccess: (data) => onSubmitted(data.task_id) }
              )
            }
            title={isPending ? 'Submitting…' : 'Submit'}
            disabled={isPending}
          />
        </View>
        {isError && <Text style={styles.errorText}>{error.message}</Text>}
      </SafeAreaView>
    </View>
  )
}

const styles = StyleSheet.create({
  previewContainer: {
    flex: 1,
    backgroundColor: 'black',
    justifyContent: 'center',
    alignItems: 'center',
  },
  previewActions: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    paddingVertical: 12,
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
  },
  buttonsRow: {
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    alignItems: 'baseline',
  },
  errorText: {
    color: 'red',
    textAlign: 'center',
    marginTop: 8,
  },
  tapCircle: {
    position: 'absolute',
    width: CIRCLE_SIZE,
    height: CIRCLE_SIZE,
    borderRadius: CIRCLE_SIZE / 2,
    backgroundColor: 'red',
  },
})
