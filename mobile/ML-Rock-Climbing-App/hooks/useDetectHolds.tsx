import { useMutation } from '@tanstack/react-query'
import { detectHolds } from '@/api/detectHolds'

//useMutation does not retry in the background or need to be cached, better for POST instead of useQuery
//Fires once per captured photo, from PhotoPreview on mount - no idempotency
//key needed here, unlike useClimbAnalysis: a duplicate call just re-runs
//inference, not a duplicate LLM call.

export function useDetectHolds() {
  return useMutation({ mutationFn: detectHolds })
}
