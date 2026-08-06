import { useGetClimbAnalysis } from '@/hooks/useGetClimbAnalysis'
import { View, Text, StyleSheet } from 'react-native'

type AnalysisResultProps = {
  task_id: string
}

export function AnalysisResult({ task_id }: AnalysisResultProps) {
  
  const {data, isPending, isError, error} = useGetClimbAnalysis(task_id)


  let content
  if (isPending) {
    content = <Text>Analysing...</Text>
  } else if (isError) {
    content = <Text>{error.message}</Text>
  } else if (data.status === 'FAILURE') {
    content = <Text>{data.error}</Text>
  } else if (data.status !== 'SUCCESS') {
    content = <Text>Analysing...</Text>
  } else {
    content = <Text>{data.result}</Text>
  }

  return <View style={styles.container}>{content}</View>
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
