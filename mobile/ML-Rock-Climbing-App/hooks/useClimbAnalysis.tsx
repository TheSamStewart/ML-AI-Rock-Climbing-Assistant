import { useMutation } from '@tanstack/react-query'
import { climbAnalysis } from '@/api/climbAnalysis'

//useMutation does not retry in the background or need to be cached, better for POST instead of useQuery
//useQuery will be used for the GET polling request
//retry: 0 today, but climbAnalysis's variables carry an idempotency key generated
//at the call site, so retries could be enabled safely later without duplicating work

export function useClimbAnalysis() {
  return useMutation({ mutationFn: climbAnalysis })
}
