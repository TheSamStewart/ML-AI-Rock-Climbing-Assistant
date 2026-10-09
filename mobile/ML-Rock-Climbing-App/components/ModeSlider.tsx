import React, { useRef, useState } from 'react'
import { StyleProp, StyleSheet, Text, View, ViewStyle, useWindowDimensions } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

//Snapchat-style mode carousel - option circles sit to the right of the shutter,
//swiping right to left slides one into the shutter ring to select it.
//Stub for now - selecting a mode doesn't change capture.

//style is optional per mode and is applied on top of the default option style
//(colour, border, opacity etc.) - size and position are set by the carousel so
//the circle stays centred in the shutter ring when selected.

type CameraMode = {
  key: string
  label: string
  style?: StyleProp<ViewStyle>
}

//New modes (e.g. Coaching Analysis) get appended here

export const CAMERA_MODES: CameraMode[] = [{ key: 'static-route', label: 'Static Route Analysis' }]

//Typing for props

type ModeSliderProps = {
  size: number
  onModeChange?: (key: string | null) => void
  children: React.ReactNode
}

export function ModeSlider({ size, onModeChange, children }: ModeSliderProps) {
  const { width } = useWindowDimensions()

  //Carousel sizing - index 0 is the plain shutter, index i is CAMERA_MODES[i - 1]

  const itemSize = size * 0.8
  const spacing = size * 1.2
  const maxOffset = CAMERA_MODES.length * spacing

  //Slider states

  const translateX = useSharedValue(0)
  const savedTranslateX = useSharedValue(0)
  const selectedRef = useRef(0)
  const [selected, setSelected] = useState(0)

  //Runs once the slider settles - only fires onModeChange if the position actually changed

  const handleSnap = (index: number) => {
    if (index === selectedRef.current) return
    selectedRef.current = index
    setSelected(index)
    onModeChange?.(index === 0 ? null : CAMERA_MODES[index - 1].key)
  }

  //Horizontal swipe moves the row - activeOffsetX keeps shutter taps from
  //being mistaken for the start of a swipe.

  const panGesture = Gesture.Pan()
    .activeOffsetX([-10, 10])
    .onUpdate((e) => {
      'worklet'
      translateX.value = Math.min(0, Math.max(-maxOffset, savedTranslateX.value + e.translationX))
    })
    .onEnd(() => {
      'worklet'
      const index = Math.round(-translateX.value / spacing)
      translateX.value = withTiming(-index * spacing)
      savedTranslateX.value = -index * spacing
      scheduleOnRN(handleSnap, index)
    })

  const rowStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: translateX.value }],
  }))

  //Render the slider - circles sit behind the shutter so the selected one shows inside the ring

  return (
    <GestureDetector gesture={panGesture}>
      <View style={[styles.strip, { height: size }]}>
        {selected > 0 && (
          <Text style={[styles.label, { bottom: size * 1.1 }]}>{CAMERA_MODES[selected - 1].label}</Text>
        )}
        <Animated.View style={[StyleSheet.absoluteFill, rowStyle]}>
          {CAMERA_MODES.map((mode, i) => (
            <View
              key={mode.key}
              style={[
                styles.option,
                mode.style,
                {
                  width: itemSize,
                  height: itemSize,
                  borderRadius: itemSize / 2,
                  left: width / 2 + (i + 1) * spacing - itemSize / 2,
                  top: (size - itemSize) / 2,
                },
              ]}
            />
          ))}
        </Animated.View>
        {children}
      </View>
    </GestureDetector>
  )
}

const styles = StyleSheet.create({
  strip: {
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
  },
  option: {
    position: 'absolute',
    backgroundColor: 'rgba(255, 255, 255, 0.6)',
  },
  label: {
    position: 'absolute',
    fontSize: 16,
    fontWeight: 'bold',
    color: 'white',
  },
})
