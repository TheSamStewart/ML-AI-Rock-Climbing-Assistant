import Constants from 'expo-constants'

//Type for response

export type ClimbAnalysisResponse = {
  task_id: string
}

//Use expo constant to get IP to send req to DEV ONLY

const host = Constants.expoConfig?.hostUri?.split(':')[0] ?? 'localhost'
export const API_URL = `http://${host}:8000`

export async function climbAnalysis(uri: string): Promise<ClimbAnalysisResponse> {
  //Create unique filename for image

  const filename = uri.split('/').pop() ?? `climb-${Date.now()}.jpg`
  const ext = /\.(\w+)$/.exec(filename)?.[1] ?? 'jpg'

  //Create the formData for the request

  const formData = new FormData()
  formData.append('photo', {
    uri,
    name: filename,
    type: `image/${ext === 'jpg' ? 'jpeg' : ext}`,
  } as any)

  //make the request

  const res = await fetch(`${API_URL}/analysis`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) throw new Error(`Analysis failed: ${res.status}`)
  return (await res.json()) as ClimbAnalysisResponse
}
