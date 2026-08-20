import { useState } from 'react'
import { View, StyleSheet, Text, Button, Image } from 'react-native'
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

const CIRCLE_SIZE = 32

export function PhotoPreview({ uri, onRetake, onSubmitted }: PhotoPreviewProps) {
  //Climb analysis submission - mutate() triggers the POST, state drives the UI
  const { mutate, isPending, isError, error } = useClimbAnalysis()

  //Unnormalized screen taps, just view-space coords for now
  const [taps, setTaps] = useState<TapPoint[]>([])

  const addTap = (x: number, y: number) => {
    // This function runs on the JS thread
    setTaps((prev) => [...prev, { key: `${Date.now()}-${Math.random()}`, x, y }])
  }

  const undoTap = () => {
    setTaps((prev) => prev.slice(0, -1))
  }

  const tapGesture = Gesture.Tap().onEnd((event, success) => {
    'worklet'
    if (success) {
      scheduleOnRN(addTap, event.x, event.y)
    }
  })

  //We preview the user the image, if submit is pressed make the call to the API

  return (
    <View style={styles.previewContainer}>
      <GestureDetector gesture={tapGesture}>
        <View style={StyleSheet.absoluteFill}>
          <Image source={{ uri }} style={StyleSheet.absoluteFill} resizeMode="contain" />

          {taps.map((tap) => (
            <View
              key={tap.key}
              pointerEvents="none"
              style={[
                styles.tapCircle,
                { left: tap.x - CIRCLE_SIZE / 2, top: tap.y - CIRCLE_SIZE / 2 },
              ]}
            />
          ))}
        </View>
      </GestureDetector>

      <SafeAreaView edges={['bottom']} style={styles.previewActions}>
        <View style={styles.buttonsRow}>
          <Button onPress={onRetake} title="Retake" />
          <Button onPress={undoTap} title="Undo" disabled={taps.length === 0} />
          <Button
            onPress={() =>
              //A fresh idempotency key per press
              mutate(
                { uri, idempotencyKey: Crypto.randomUUID() },
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
