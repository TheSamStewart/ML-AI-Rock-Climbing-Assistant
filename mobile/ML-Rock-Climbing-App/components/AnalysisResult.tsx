import { useGetClimbAnalysis } from '@/hooks/useGetClimbAnalysis'
import { View, Text, ScrollView, StyleSheet } from 'react-native'

type AnalysisResultProps = {
  task_id: string
}

export function AnalysisResult({ task_id }: AnalysisResultProps) {
  //When this components is rendered useGetClimbAnalysis hook is called automaticlly
  //queryKey in useGetClimbAnalysis stops new call being made every time this page re renders, only when task_id is different it makes new calls

  const { data, isPending, isError, error, timedOut } = useGetClimbAnalysis(task_id)

  let content
  if (isPending) {
    content = <Text>Analysing...</Text>
  } else if (isError) {
    content = <Text>{error.message}</Text>
  } else if (data.status === 'FAILURE') {
    content = <Text>{data.error}</Text>
  } else if (timedOut && data.status !== 'SUCCESS') {
    content = <Text>This is taking longer than expected. Please try again later.</Text>
  } else if (data.status !== 'SUCCESS') {
    content = <Text>Analysing...</Text>
  } else {
    //Placeholder list of the coaching steps - styling to be improved later
    return (
      <ScrollView contentContainerStyle={styles.stepsList}>
        {data.result.steps.map((step) => (
          <View key={step.step_number} style={styles.step}>
            <Text style={styles.instruction}>
              Step {step.step_number}: {step.instruction}
            </Text>
            <Text>{step.reason}</Text>
          </View>
        ))}
      </ScrollView>
    )
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
  stepsList: {
    padding: 24,
    gap: 16,
  },
  step: {
    gap: 4,
  },
  instruction: {
    fontWeight: 'bold',
  },
})
