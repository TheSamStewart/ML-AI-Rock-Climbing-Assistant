import { useMutation } from '@tanstack/react-query'
import { scanVolume } from '@/api/volumeScan'

//DEV ONLY - one scan per burst; a retry is just another scan (the server saves each).

export function useVolumeScan() {
  return useMutation({ mutationFn: scanVolume })
}
