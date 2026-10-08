import Constants from 'expo-constants'

//Type for response

type InProgressResponse = {
  task_id: string
  status: 'PENDING' | 'STARTED' | 'RETRY'
}

type FailureResponse = {
  task_id: string
  status: 'FAILURE'
  error: string
}

//Shape of the LLM coaching output - keep in sync with COACHING_OUTPUT_SCHEMA in backend/worker.py

export type ClimbStep = {
  step_number: number
  instruction: string
  reason: string
}

export type ClimbAnalysis = {
  steps: ClimbStep[]
}

type SuccessResponse = {
  task_id: string
  status: 'SUCCESS'
  result: ClimbAnalysis
}

export type getClimbAnalysisResponse = InProgressResponse | FailureResponse | SuccessResponse

//Use expo constant to get IP to send req to DEV ONLY

const host = Constants.expoConfig?.hostUri?.split(':')[0] ?? 'localhost'
export const API_URL = `http://${host}:8000`

export async function getClimbAnalysis(task_id: string): Promise<getClimbAnalysisResponse> {
  const res = await fetch(`${API_URL}/analysis/${task_id}`, {
    method: 'GET',
  })

  if (!res.ok) throw new Error(`Analysis failed: ${res.status}`)
  return (await res.json()) as getClimbAnalysisResponse
}
