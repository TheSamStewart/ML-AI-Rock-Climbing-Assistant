import { View, StyleSheet, Button } from 'react-native'
import { AnalysisResult } from './AnalysisResult'
import { CustomCamera } from './CustomCamera'
import { CameraPermissionGate } from '@/components/CameraPermissionGate'
import { PhotoPreview } from '@/components/PhotoPreview'
import { useState } from 'react'
import { Asset } from 'expo-asset'

//Main camera screen: composes permission gating, camera capture, and photo preview/submission.
//Rendered by app/index.tsx - kept out of app/ so it isn't itself a route.

//DEV ONLY - lets us skip the camera and pipe a bundled test photo straight
//into PhotoPreview/the API, so the analysis pipeline can be tested without a real capture.

async function useTestPhoto(setUri: (uri: string) => void) {
  const [asset] = await Asset.loadAsync(
    require('../assets/images/climbing-route-detection-slise-z8djc_EJAcI33FosVzoc3oVr1R_jpg.rf.7zMZpydPD8vpamzWBLEv.jpg')
  )
  setUri(asset.localUri ?? asset.uri)
}

export function CameraScreen() {
  //Photo uri state to render image, passed down to camera component

  const [uri, setUri] = useState<string | null>(null)
  const [task_id, setTaskId] = useState<string | null>(null)

  return (
    <CameraPermissionGate>
      {!uri ? (
        <View style={styles.container}>
          <CustomCamera onCapture={setUri} />
          {__DEV__ && (
            <View style={styles.testButton}>
              <Button title="Use Test Photo" onPress={() => useTestPhoto(setUri)} />
            </View>
          )}
        </View>
      ) : !task_id ? (
        <PhotoPreview
          uri={uri}
          onRetake={() => setUri(null)}
          onSubmitted={(task_id) => setTaskId(task_id)}
        />
      ) : (
        <AnalysisResult task_id={task_id} />
      )}
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
