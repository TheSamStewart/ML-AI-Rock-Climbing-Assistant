import { useQuery } from '@tanstack/react-query'
import { getClimbAnalysis } from '@/api/getClimbAnalysis'
import { useEffect, useRef, useState } from 'react'

//Make the API call and deal with polling/states with tanstack useQuery
//queryKey is used as an unique identifier for caching etc

export function useGetClimbAnalysis(task_id: string) {
  //Reference for date when we made the first GET request

  const startedAtRef = useRef<number>(Date.now())
  const [timedOut, setTimedOut] = useState<true | false>(false)

  //Resets state/ref for new calls

  useEffect(() => {
    startedAtRef.current = Date.now()
    setTimedOut(false)
  }, [task_id])

  const query = useQuery({
    queryKey: ['climbAnalysis', task_id],
    queryFn: () => getClimbAnalysis(task_id),

    refetchInterval: (query) => {
      const data = query.state.data
      const stillInProgress =
        !data || data.status === 'PENDING' || data.status === 'STARTED' || data.status === 'RETRY'

      //Stop polling if it has been 30s

      const elapsed = Date.now() - startedAtRef.current

      if (elapsed >= 30000) {
        setTimedOut(true)
        return false
      }

      return stillInProgress ? 2000 : false
    },
  })

  //Passes the state to AnalysisResult

  return { ...query, timedOut }
}
