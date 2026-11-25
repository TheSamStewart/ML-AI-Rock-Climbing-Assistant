import { CameraView } from 'expo-camera'
import { StyleSheet, Text, View, TouchableOpacity, useWindowDimensions } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import React, { useRef, useState } from 'react'
import { ModeSlider } from './ModeSlider'
import { GravityReading, useGravityReading } from '@/hooks/useGravityReading'
import { largestPictureSize } from '@/utils/pictureSize'

//Typing for props - gravity is the phone's tilt when the shutter was pressed
//(null when there is no sensor), used to work out the wall angle.

type CustomCameraProps = {
  onCapture: (uri: string, gravity: GravityReading | null) => void
}

export function CustomCamera({ onCapture }: CustomCameraProps) {
  //Latest smoothed accelerometer reading, kept in a ref so reading it at the
  //shutter doesn't re-render the camera

  const gravity = useGravityReading()

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
    const best = largestPictureSize(await cameraRef.current?.getAvailablePictureSizesAsync())
    if (best) setPictureSize(best)
  }

  //Takes picture when shutter button is pressed

  const takePicture = async () => {
    //check isCapturing flag for duplicate button presses

    if (isCapturing.current) return

    isCapturing.current = true
    setBusy(true)

    //Take image

    //Read the tilt before the (slow) capture call so it is the tilt the phone
    //was held at, not wherever it moved to while the photo was saved.

    const tilt = gravity.current

    try {
      //JPEG quality 0.85 (default 1.0): about 4x smaller uploads (3.8 -> 0.9 MB)
      //with the same holds, bolts, angles and distances on the field captures
      //(human-approved, 2026-11-24, slice 16). Never lower the RESOLUTION -
      //bolt detection needs it (pictureSize above).
      const photo = await cameraRef.current?.takePictureAsync({ quality: 0.85 })
      if (!photo?.uri) return

      onCapture(photo.uri, tilt)
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
      {/* The wall length is only the full wall's height when all of it is in frame (slice 16). */}
      <Text style={[styles.hint, { bottom: insets.bottom + width * 0.06 + size + 16 }]}>
        Fit the whole wall in the shot, floor to top
      </Text>
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
  hint: {
    position: 'absolute',
    left: 16,
    right: 16,
    textAlign: 'center',
    color: 'white',
    fontSize: 14,
    textShadowColor: 'black',
    textShadowRadius: 4,
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
