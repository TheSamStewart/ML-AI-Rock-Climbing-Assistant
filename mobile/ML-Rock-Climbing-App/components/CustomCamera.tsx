import { CameraView } from 'expo-camera'
import { StyleSheet, View, TouchableOpacity, useWindowDimensions } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import React, { useRef, useState } from 'react'
import { ModeSlider } from './ModeSlider'

//Typing for props

type CustomCameraProps = {
  onCapture: (uri: string) => void
}

export function CustomCamera({ onCapture }: CustomCameraProps) {
  //Shutter size calculations

  const { width } = useWindowDimensions()
  const insets = useSafeAreaInsets()

  const size = width * 0.2

  const shutter = {
    width: size,
    height: size,
    borderRadius: size / 2,
    borderWidth: size * 0.075,
  }

  //Camera ref - creates a reference to the native camera node in memory, allowing us to take pictures or videos

  const cameraRef = React.useRef<CameraView>(null)

  //isCapturing ref,

  const isCapturing = useRef(false)

  //Camera states

  const [busy, setBusy] = useState(false)

  //Without an explicit pictureSize, takePictureAsync() falls back to sizing the photo
  //off the on-screen preview surface instead of one of the sensor's actual still-capture
  //resolutions - We pick the largest real WxH size once the camera reports ready and pin it via the pictureSize prop below.

  const [pictureSize, setPictureSize] = useState<string | undefined>(undefined)

  const onCameraReady = async () => {
    const sizes = await cameraRef.current?.getAvailablePictureSizesAsync()
    if (!sizes) return

    //Sizes also include qualitative aliases (e.g. "Photo", "High") alongside real
    //"WxH" entries - only the latter are usable as a pictureSize value.

    const best = sizes
      .map((size) => {
        const match = /^(\d+)x(\d+)$/.exec(size)
        return match ? { size, area: Number(match[1]) * Number(match[2]) } : null
      })
      .filter((s): s is { size: string; area: number } => s !== null)
      .reduce<{ size: string; area: number } | null>(
        (max, current) => (!max || current.area > max.area ? current : max),
        null
      )

    if (best) setPictureSize(best.size)
  }

  //Takes picture when shutter button is pressed

  const takePicture = async () => {
    //check isCapturing flag for duplicate button presses

    if (isCapturing.current) return

    isCapturing.current = true
    setBusy(true)

    //Take image

    try {
      const photo = await cameraRef.current?.takePictureAsync()
      if (!photo?.uri) return

      onCapture(photo.uri)
    } catch (e) {
      console.error(e)
    } finally {
      isCapturing.current = false
      setBusy(false)
    }
  }

  //Render the camera

  return (
    <View style={styles.container}>
      <CameraView
        ref={cameraRef}
        style={styles.camera}
        facing="back"
        pictureSize={pictureSize}
        onCameraReady={onCameraReady}
      />
      <View style={[styles.shutterContainer, { bottom: insets.bottom + width * 0.06 }]}>
        <ModeSlider size={size}>
          <TouchableOpacity disabled={busy} onPress={takePicture} style={[styles.shutter, shutter]} />
        </ModeSlider>
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  camera: {
    flex: 1,
  },
  shutterContainer: {
    position: 'absolute',
    left: 0,
    right: 0,
    alignItems: 'center',
  },
  shutter: {
    borderColor: 'white',
    backgroundColor: 'Transparent',
    shadowColor: 'black',
    shadowOpacity: 0.25,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 1 },
  },
  text: {
    fontSize: 24,
    fontWeight: 'bold',
    color: 'white',
  },
})
