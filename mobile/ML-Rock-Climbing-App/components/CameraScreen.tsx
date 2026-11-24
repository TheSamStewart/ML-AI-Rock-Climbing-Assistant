import { View, StyleSheet, Button } from 'react-native'
import { AnalysisResult } from './AnalysisResult'
import { CustomCamera } from './CustomCamera'
import { CameraPermissionGate } from '@/components/CameraPermissionGate'
import { PhotoPreview } from '@/components/PhotoPreview'
import { SettingsButton } from '@/components/SettingsButton'
import { SettingsModal } from '@/components/SettingsModal'
import { useBoltSpacing } from '@/hooks/useBoltSpacing'
import { GravityReading } from '@/hooks/useGravityReading'
import { useState } from 'react'
import { Asset } from 'expo-asset'

//Main camera screen: composes permission gating, camera capture, and photo preview/submission.
//Rendered by app/index.tsx - kept out of app/ so it isn't itself a route.

//DEV ONLY - lets us skip the camera and pipe a bundled test photo straight
//into PhotoPreview/the API, so the analysis pipeline can be tested without a real capture.
//Uses a full-res reference photo: bolt-hole detection (and so distances) needs
//roughly phone-camera resolution - below ~3000 px tall bolts are lost.

async function useTestPhoto(setUri: (uri: string) => void) {
  const [asset] = await Asset.loadAsync(require('../assets/known_measurements/reference/IMG_7504.jpeg'))
  setUri(asset.localUri ?? asset.uri)
}

export function CameraScreen() {
  //Photo uri state to render image, passed down to camera component

  const [uri, setUri] = useState<string | null>(null)

  //Phone tilt when the photo was taken (null for the test photo or with no
  //sensor) - sent with the photo so the backend can estimate the wall angle.

  const [gravity, setGravity] = useState<GravityReading | null>(null)
  const [task_id, setTaskId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

  //Owned here (not in PhotoPreview) so the settings panel and the distance
  //labels share one value - saving a new spacing relabels PhotoPreview live.

  const { boltSpacingCm, setBoltSpacingCm } = useBoltSpacing()

  return (
    <CameraPermissionGate>
      <View style={styles.container}>
        {!uri ? (
          <>
            <CustomCamera
              onCapture={(photoUri, tilt) => {
                setGravity(tilt)
                setUri(photoUri)
              }}
            />
            {__DEV__ && (
              <View style={styles.testButton}>
                <Button
                  title="Use Test Photo"
                  onPress={() => {
                    setGravity(null)
                    useTestPhoto(setUri)
                  }}
                />
              </View>
            )}
          </>
        ) : !task_id ? (
          <PhotoPreview
            uri={uri}
            gravity={gravity}
            boltSpacingCm={boltSpacingCm}
            onRetake={() => setUri(null)}
            onSubmitted={(task_id) => setTaskId(task_id)}
          />
        ) : (
          <AnalysisResult task_id={task_id} />
        )}

        {/* Rendered after the camera/preview so it sits on top of both */}

        {!task_id && <SettingsButton onPress={() => setSettingsOpen(true)} />}
        <SettingsModal
          visible={settingsOpen}
          boltSpacingCm={boltSpacingCm}
          onSave={setBoltSpacingCm}
          onClose={() => setSettingsOpen(false)}
        />
      </View>
    </CameraPermissionGate>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  testButton: {
    position: 'absolute',
    bottom: 40,
    left: 20,
  },
})
