import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { collectionsApi } from '@/api/endpoints/collections'
import type { CollectionSummary, IndexingJob } from '@/api/types'

export const collectionKeys = {
  all: ['collections'] as const,
  one: (name: string) => ['collection', name] as const,
  jobs: (name: string) => ['collection-jobs', name] as const,
}

export function useCollections() {
  return useQuery({
    queryKey: collectionKeys.all,
    queryFn: () => collectionsApi.list(),
    select: (data) => data.collections,
    staleTime: 10_000,
  })
}

/** Folders with at least one indexed document — the only ones `/chat` accepts. */
export function useSearchableCollections() {
  const query = useCollections()
  const searchable = (query.data ?? []).filter(
    (folder: CollectionSummary) => folder.searchable,
  )
  return { ...query, searchable }
}

export function useCollection(name: string | null) {
  return useQuery({
    queryKey: collectionKeys.one(name ?? 'none'),
    queryFn: () => collectionsApi.get(name!),
    enabled: Boolean(name),
  })
}

export function useCreateCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ name, description }: { name: string; description?: string }) =>
      collectionsApi.create(name, description ?? ''),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: collectionKeys.all }),
  })
}

export function useAddDocuments() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ name, files }: { name: string; files: File[] }) =>
      collectionsApi.addDocuments(name, files),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: collectionKeys.all })
      queryClient.invalidateQueries({ queryKey: collectionKeys.one(variables.name) })
      queryClient.invalidateQueries({ queryKey: collectionKeys.jobs(variables.name) })
    },
  })
}

export function useDeleteCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ name, removeUploads }: { name: string; removeUploads?: boolean }) =>
      collectionsApi.remove(name, removeUploads ?? false),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: collectionKeys.all }),
  })
}

export function useRemoveDocument(collection: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (docName: string) => collectionsApi.removeDocument(collection, docName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: collectionKeys.all })
      queryClient.invalidateQueries({ queryKey: collectionKeys.one(collection) })
    },
  })
}

/**
 * Poll a folder's jobs while any of them is still running.
 *
 * One job per document, so a folder of twelve filings reports which one is slow
 * rather than a single bar that says nothing. Polling stops once every job is
 * terminal — an idle folder costs no requests.
 */
export function useCollectionJobs(name: string | null) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: collectionKeys.jobs(name ?? 'none'),
    queryFn: async () => {
      const jobs = await collectionsApi.jobs(name!)
      if (jobs.every((job) => job.status === 'ready' || job.status === 'failed')) {
        queryClient.invalidateQueries({ queryKey: collectionKeys.all })
        queryClient.invalidateQueries({ queryKey: collectionKeys.one(name!) })
      }
      return jobs
    },
    enabled: Boolean(name),
    refetchInterval: (query) => {
      const jobs = query.state.data as IndexingJob[] | undefined
      if (!jobs || jobs.length === 0) return false
      const running = jobs.some(
        (job) => job.status !== 'ready' && job.status !== 'failed',
      )
      return running ? 1500 : false
    },
  })
}
