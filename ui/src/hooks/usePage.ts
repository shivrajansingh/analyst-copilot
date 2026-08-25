import { useQuery } from '@tanstack/react-query'
import { pagesApi } from '@/api/endpoints/pages'

/** Page text is immutable once indexed, so it is cached for the session. */
export function usePage(docName: string | null, page: number | null) {
  return useQuery({
    queryKey: ['page', docName, page],
    queryFn: () => pagesApi.get(docName!, page!),
    enabled: Boolean(docName) && page != null,
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
  })
}
