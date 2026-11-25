import { CameraView } from 'expo-camera'
import { useRef, useState } from 'react'
import { Button, Modal, Pressable, StyleSheet, Text, View } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { largestPictureSize } from '@/utils/pictureSize'

//DEV ONLY - the volume scan burst (docs/features/volume_scan.md). While the
//button is held the camera takes photos back to back, at the same picture size
//as the main photo, so the server knows each one's lens. The user steps slowly
//sideways meanwhile, keeping the volume and the wall around it in frame.

type VolumeScanCameraProps = {
  visible: boolean
  onDone: (frameUris: string[]) => void
  onCancel: () => void
}

//Enough frames for the server (it uses up to 12), and a stop in case the
//button is never released.
const MAX_FRAMES = 12
const MAX_DURATION_MS = 6000
const MIN_FRAMES = 3

export function VolumeScanCamera({ visible, onDone, onCancel }: VolumeScanCameraProps) {
  const cameraRef = useRef<CameraView>(null)
  const [pictureSize, setPictureSize] = useState<string | undefined>(undefined)
  const [count, setCount] = useState(0)
  const [recording, setRecording] = useState(false)
  const holding = useRef(false)
  const frames = useRef<string[]>([])

  const onCameraReady = async () => {
    const best = largestPictureSize(await cameraRef.current?.getAvailablePictureSizesAsync())
    if (best) setPictureSize(best)
  }

  const startBurst = async () => {
    if (recording) return
    holding.current = true
    frames.current = []
    setCount(0)
    setRecording(true)
    const started = Date.now()
    try {
      while (
        holding.current &&
        frames.current.length < MAX_FRAMES &&
        Date.now() - started < MAX_DURATION_MS
      ) {
        //Same quality as the main photo (CustomCamera); no shutter sound in a burst.
        const photo = await cameraRef.current?.takePictureAsync({ quality: 0.85, shutterSound: false })
        if (photo?.uri) {
          frames.current.push(photo.uri)
          setCount(frames.current.length)
        }
      }
    } catch (e) {
      console.error('volume scan burst failed', e)
    } finally {
      holding.current = false
      setRecording(false)
    }
    if (frames.current.length >= MIN_FRAMES) onDone(frames.current)
  }

  const stopBurst = () => {
    holding.current = false
  }

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onCancel}>
      <View style={styles.container}>
        <CameraView
          ref={cameraRef}
          style={styles.camera}
          facing="back"
          pictureSize={pictureSize}
          onCameraReady={onCameraReady}
        />
        <SafeAreaView edges={['top']} style={styles.top}>
          <Text style={styles.title}>Volume scan (test)</Text>
          <Text style={styles.hint}>
            Stand where you took the photo. Hold the button and take one slow step sideways
            (about half a metre), keeping the volume and the wall around it in frame.
          </Text>
        </SafeAreaView>
        <SafeAreaView edges={['bottom']} style={styles.bottom}>
          <Text style={styles.count}>
            {recording
              ? `${count} photos…`
              : count > 0 && count < MIN_FRAMES
                ? `Only ${count} photos - hold a little longer`
                : ' '}
          </Text>
          <Pressable
            onPressIn={startBurst}
            onPressOut={stopBurst}
            style={[styles.record, recording && styles.recordActive]}
          >
            <Text style={styles.recordText}>{recording ? 'Scanning…' : 'Hold to scan'}</Text>
          </Pressable>
          <Button title="Cancel" onPress={onCancel} disabled={recording} />
        </SafeAreaView>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: 'black' },
  camera: { flex: 1 },
  top: { position: 'absolute', top: 0, left: 0, right: 0, padding: 16, backgroundColor: 'rgba(0,0,0,0.4)' },
  title: { color: 'white', fontSize: 18, fontWeight: 'bold', textAlign: 'center' },
  hint: { color: 'white', textAlign: 'center', marginTop: 6 },
  bottom: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    alignItems: 'center',
    paddingVertical: 16,
    backgroundColor: 'rgba(0,0,0,0.4)',
    gap: 10,
  },
  count: { color: 'white' },
  record: {
    width: 180,
    paddingVertical: 18,
    borderRadius: 40,
    backgroundColor: '#c0392b',
    alignItems: 'center',
  },
  recordActive: { backgroundColor: '#e74c3c' },
  recordText: { color: 'white', fontSize: 16, fontWeight: 'bold' },
})
