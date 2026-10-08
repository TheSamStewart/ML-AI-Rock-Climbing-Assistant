import { useEffect, useMemo, useState } from 'react'
import { View, StyleSheet, Text, Button, Image, ActivityIndicator, useWindowDimensions } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated'
import Svg, { Polygon } from 'react-native-svg'
import { scheduleOnRN } from 'react-native-worklets'
import * as Crypto from 'expo-crypto'
import { useClimbAnalysis } from '@/hooks/useClimbAnalysis'
import { useDetectHolds } from '@/hooks/useDetectHolds'
import { matchTapToHold } from '@/utils/holdMatching'

//Handles the captured photo only - preview, retake, and submission to analysis.
//Knows nothing about camera permissions or capture itself.

type PhotoPreviewProps = {
  uri: string
  onRetake: () => void
  onSubmitted: (task_id: string) => void
}

type Box = {
  width: number
  height: number
}

//Two to start one to finish minimum - keep in sync with backend/main.py's MIN_SELECTED_HOLDS

const MIN_SELECTED_HOLDS = 3

//Pinch-zoom bounds - never zoom out past the image's natural "contain" fit,
//and cap zoom-in so the photo can't be magnified too far.

const MIN_SCALE = 1
const MAX_SCALE = 4

//Clamps a translate offset so the zoomed image can never be panned past its
//own edges

function clampTranslate(t: number, boxDim: number, s: number) {
  'worklet'
  const maxT = (boxDim * (s - 1)) / 2
  return Math.min(maxT, Math.max(-maxT, t))
}

export function PhotoPreview({ uri, onRetake, onSubmitted }: PhotoPreviewProps) {
  //Climb analysis submission - mutate() triggers the POST, state drives the UI

  const { mutate, isPending, isError, error } = useClimbAnalysis()

  //Detection runs once, as soon as the photo is captured - by the time the
  //user starts tapping, detections should already be in hand so a tap can
  //resolve straight to a hold instead of the backend guessing after the fact.

  const {
    mutate: detectMutate,
    data: detectData,
    isPending: isDetecting,
    isError: isDetectError,
    error: detectError,
  } = useDetectHolds()

  useEffect(() => {
    detectMutate({ uri })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uri])

  const detections = detectData?.detections ?? []
  const detectionId = detectData?.detection_id ?? null

  //Ordered ids of the detections the user has selected (tap toggles
  //membership) - order is kept so Undo can pop the most recent one.

  const [selectedHoldIds, setSelectedHoldIds] = useState<number[]>([])

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

  //Pinch/pan state - the inner image+markers container is transformed by
  //these; the outer GestureDetector view is never transformed, so raw tap
  //events stay in stable "box" coordinates and only need un-zooming (see
  //handleTap below), not a full inverse of wherever panning left them.

  const scale = useSharedValue(1)
  const savedScale = useSharedValue(1)
  const translateX = useSharedValue(0)
  const translateY = useSharedValue(0)
  const savedTranslateX = useSharedValue(0)
  const savedTranslateY = useSharedValue(0)

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

  const handleTap = (
    rawX: number,
    rawY: number,
    scaleVal: number,
    translateXVal: number,
    translateYVal: number
  ) => {
    // This function runs on the JS thread
    if (!box) {
      console.warn('handleTap called before box was ready')
      return
    }

    //Detections aren't in yet - nothing to resolve a tap against.

    if (isDetecting || detections.length === 0) return

    //Takes the raw coordinate values from the gesture detector and maps them to the actual image
    //- translateXVal undoes pan offset, scaleVal undoes zoom scale, passed in on tapGesture's onEnd

    const imageX = box.width / 2 + (rawX - box.width / 2 - translateXVal) / scaleVal
    const imageY = box.height / 2 + (rawY - box.height / 2 - translateYVal) / scaleVal

    const x = Math.min(1, Math.max(0, imageX / box.width))
    const y = Math.min(1, Math.max(0, imageY / box.height))

    //Resolves the tap against every detection (not just unselected ones) -
    //tapping near an already-selected hold toggles it back off, tapping an
    //unselected one selects it. A tap that misses every hold is a no-op.

    const match = matchTapToHold({ x, y }, detections)
    if (!match) return

    setSelectedHoldIds((prev) =>
      prev.includes(match.id) ? prev.filter((id) => id !== match.id) : [...prev, match.id]
    )
  }

  const undoSelection = () => {
    setSelectedHoldIds((prev) => prev.slice(0, -1))
  }

  //Two-finger pinch to zoom, clamped to [MIN_SCALE, MAX_SCALE].

  const pinchGesture = Gesture.Pinch()
    .onUpdate((e) => {
      'worklet'
      scale.value = Math.min(MAX_SCALE, Math.max(MIN_SCALE, savedScale.value * e.scale))
    })
    .onEnd(() => {
      'worklet'
      savedScale.value = scale.value
      if (box) {
        //Re-clamp translate too - a translate valid at the old scale can
        //overshoot the image edges at the new one.
        translateX.value = clampTranslate(translateX.value, box.width, scale.value)
        translateY.value = clampTranslate(translateY.value, box.height, scale.value)
        savedTranslateX.value = translateX.value
        savedTranslateY.value = translateY.value
      }
    })

  //Pan to look around while zoomed in. minDistance keeps quick taps from
  //ever being mistaken for the start of a pan.

  const panGesture = Gesture.Pan()
    .minDistance(10)
    .onUpdate((e) => {
      'worklet'
      if (!box) return
      translateX.value = clampTranslate(savedTranslateX.value + e.translationX, box.width, scale.value)
      translateY.value = clampTranslate(savedTranslateY.value + e.translationY, box.height, scale.value)
    })
    .onEnd(() => {
      'worklet'
      savedTranslateX.value = translateX.value
      savedTranslateY.value = translateY.value
    })

  //Double-tap resets zoom/pan back to the original fitted view.

  const doubleTapGesture = Gesture.Tap()
    .numberOfTaps(2)
    .onEnd(() => {
      'worklet'
      scale.value = withTiming(1)
      translateX.value = withTiming(0)
      translateY.value = withTiming(0)
      savedScale.value = 1
      savedTranslateX.value = 0
      savedTranslateY.value = 0
    })

  //Single tap toggles a hold's selection - waits to confirm it isn't the
  //first half of a double-tap before firing.

  const tapGesture = Gesture.Tap()
    .requireExternalGestureToFail(doubleTapGesture)
    .onEnd((event, success) => {
      'worklet'
      if (success) {
        scheduleOnRN(handleTap, event.x, event.y, scale.value, translateX.value, translateY.value)
      }
    })

  //Pinch+pan (together) race against tap/double-tap (exclusive) - whichever
  //actually starts moving/pinching wins and cancels the other.

  const composedGesture = Gesture.Race(
    Gesture.Simultaneous(pinchGesture, panGesture),
    Gesture.Exclusive(doubleTapGesture, tapGesture)
  )

  const animatedImageStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: translateX.value }, { translateY: translateY.value }, { scale: scale.value }],
  }))

  //We preview the user the image, if submit is pressed make the call to the API

  return (
    <View style={styles.previewContainer}>
      {box && (
        <GestureDetector gesture={composedGesture}>
          <View style={{ width: box.width, height: box.height, overflow: 'hidden' }}>
            {/* Only this inner container is ever zoomed/panned - the outer
                View (and the gesture events it reports) stays fixed, which
                is what keeps handleTap's coordinate math simple. */}
            <Animated.View style={[StyleSheet.absoluteFill, animatedImageStyle]}>
              <Image source={{ uri }} style={StyleSheet.absoluteFill} resizeMode="contain" />

              {/* Renders the actual detected polygon shape for each selected hold */}

              <Svg style={StyleSheet.absoluteFill} pointerEvents="none">
                {selectedHoldIds.map((id) => {
                  const detection = detections.find((d) => d.id === id)
                  if (!detection) return null
                  return (
                    <Polygon
                      key={detection.id}
                      points={detection.polygon
                        .map((p) => `${p.x * box.width},${p.y * box.height}`)
                        .join(' ')}
                      fill="rgba(255,0,0,0.35)"
                      stroke="red"
                      strokeWidth={2}
                    />
                  )
                })}
              </Svg>
            </Animated.View>
          </View>
        </GestureDetector>
      )}

      {/* Button rendering/logic */}

      <SafeAreaView edges={['bottom']} style={styles.previewActions}>
        {isDetecting && (
          <View style={styles.detectingRow}>
            <ActivityIndicator color="white" />
            <Text style={styles.hintText}>Detecting holds…</Text>
          </View>
        )}
        <View style={styles.buttonsRow}>
          <Button onPress={onRetake} title="Retake" />
          <Button onPress={undoSelection} title="Undo" disabled={selectedHoldIds.length === 0} />
          <Button
            onPress={() =>
              //A fresh idempotency key per press
              detectionId &&
              mutate(
                {
                  detectionId,
                  idempotencyKey: Crypto.randomUUID(),
                  selectedHoldIds,
                },
                { onSuccess: (data) => onSubmitted(data.task_id) }
              )
            }
            title={isPending ? 'Submitting…' : 'Submit'}
            disabled={isPending || isDetecting || !detectionId || selectedHoldIds.length < MIN_SELECTED_HOLDS}
          />
        </View>
        {!isDetecting && selectedHoldIds.length < MIN_SELECTED_HOLDS && (
          <Text style={styles.hintText}>
            Select at least {MIN_SELECTED_HOLDS} holds ({selectedHoldIds.length}/{MIN_SELECTED_HOLDS})
          </Text>
        )}
        {isDetectError && <Text style={styles.errorText}>{detectError.message}</Text>}
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
  detectingRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  buttonsRow: {
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    alignItems: 'baseline',
  },
  hintText: {
    color: 'white',
    textAlign: 'center',
    marginTop: 8,
  },
  errorText: {
    color: 'red',
    textAlign: 'center',
    marginTop: 8,
  },
})
