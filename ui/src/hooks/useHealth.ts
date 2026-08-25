import { useQuery } from '@tanstack/react-query'
import { healthApi } from '@/api/endpoints/health'

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => healthApi.get(),
    staleTime: 60_000,
    retry: 1,
  })
}
