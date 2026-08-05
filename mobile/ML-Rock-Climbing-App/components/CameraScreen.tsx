import { View, StyleSheet } from 'react-native'
import { AnalysisResult } from './AnalysisResult'
import { CustomCamera } from '@/components/CustomCamera'
import { CameraPermissionGate } from '@/components/CameraPermissionGate'
import { PhotoPreview } from '@/components/PhotoPreview'
import { useState } from 'react'

//Main camera screen: composes permission gating, camera capture, and photo preview/submission.
//Rendered by app/index.tsx - kept out of app/ so it isn't itself a route.

export function CameraScreen() {
  //Photo uri state to render image, passed down to camera component

  const [uri, setUri] = useState<string | null>(null)
  const [task_id, setTaskId] = useState<string | null>(null)

  return (
    <CameraPermissionGate>
      {!uri ? (
        <View style={styles.container}>
          <CustomCamera onCapture={setUri} />
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

//Styles

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
})
