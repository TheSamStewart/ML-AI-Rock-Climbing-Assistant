import { View, Text, StyleSheet } from 'react-native'

type AnalysisResultProps = {
  task_id: string
}

export function AnalysisResult({ task_id }: AnalysisResultProps) {
  return (
    <View style={styles.container}>
      <Text>{task_id}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
    gap: 12,
  },
})
