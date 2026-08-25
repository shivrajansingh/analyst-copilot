import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { filingsApi } from '@/api/endpoints/filings'
import type { FilingSummary, IndexingJob } from '@/api/types'

export const filingKeys = {
  all: ['filings'] as const,
  job: (jobId: string) => ['job', jobId] as const,
}

export function useFilings() {
  return useQuery({
    queryKey: filingKeys.all,
    queryFn: () => filingsApi.list(),
    select: (data) => data.filings,
    staleTime: 10_000,
  })
}

/** Filings both retrievers can serve — the only ones `/chat` will accept. */
export function useSearchableFilings() {
  const query = useFilings()
  const searchable = (query.data ?? []).filter(
    (filing: FilingSummary) => filing.bm25.state === 'ready' && filing.vector.state === 'ready',
  )
  return { ...query, searchable }
}

export function useAddFiling() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => filingsApi.add(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: filingKeys.all }),
  })
}

/**
 * Poll a job while it is running, then stop.
 *
 * Polling rather than SSE: indexing emits a handful of phase changes over
 * minutes, so a stream would add a proxy-buffering failure mode to save almost
 * no traffic. The interval stops the moment the job is terminal.
 */
export function useJobPolling(jobId: string | null) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: filingKeys.job(jobId ?? 'none'),
    queryFn: async () => {
      const job = await filingsApi.job(jobId!)
      if (job.status === 'ready' || job.status === 'failed') {
        queryClient.invalidateQueries({ queryKey: filingKeys.all })
      }
      return job
    },
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const job = query.state.data as IndexingJob | undefined
      if (!job) return 1500
      return job.status === 'ready' || job.status === 'failed' ? false : 1500
    },
  })
}
