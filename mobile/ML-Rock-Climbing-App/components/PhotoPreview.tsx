import { View, StyleSheet, Text, Button, Image } from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import * as Crypto from 'expo-crypto'
import { useClimbAnalysis } from '@/hooks/useClimbAnalysis'

//Handles the captured photo only - preview, retake, and submission to analysis.
//Knows nothing about camera permissions or capture itself.

type PhotoPreviewProps = {
  uri: string
  onRetake: () => void
  onSubmitted: (task_id: string) => void
}

export function PhotoPreview({ uri, onRetake, onSubmitted }: PhotoPreviewProps) {
  //Climb analysis submission - mutate() triggers the POST, state drives the UI

  const { mutate, isPending, isError, error } = useClimbAnalysis()

  //We preview the user the image, if submit is pressed make the call to the API

  return (
    <View style={styles.previewContainer}>
      <Image source={{ uri }} style={StyleSheet.absoluteFill} resizeMode="contain" />
      <SafeAreaView edges={['bottom']} style={styles.previewActions}>
        <Button onPress={onRetake} title="Retake" />
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
      </SafeAreaView>
      {isError && <Text style={styles.errorText}>{error.message}</Text>}
    </View>
  )
}

const styles = StyleSheet.create({
  previewContainer: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  previewActions: {
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    alignItems: 'baseline',
    paddingVertical: 12,
  },
  errorText: {
    color: 'red',
    textAlign: 'center',
    paddingBottom: 10,
  },
})
