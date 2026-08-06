import { useQuery } from "@tanstack/react-query";
import { getClimbAnalysis } from "@/api/getClimbAnalysis";

//Make the API call and deal with polling/states with tanstack useQuery
//queryKey is used as an unique identifier for caching etc

export function useGetClimbAnalysis (task_id : string)
{
    return useQuery({
        queryKey: ['climbAnalysis', task_id],
        queryFn : () => getClimbAnalysis(task_id),
        refetchInterval: (query) => {
            const data = query.state.data
            const stillInProgress = 
                !data || data.status === 'PENDING' || data.status === 'STARTED' || data.status === 'RETRY'
            return stillInProgress ? 2000 : false
        }
    })
}