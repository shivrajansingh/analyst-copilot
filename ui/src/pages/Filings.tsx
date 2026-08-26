import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { FileStack, Search } from 'lucide-react'
import type { IndexState } from '@/api/types'
import { useAddFiling, useFilings, useJobPolling } from '@/hooks/useFilings'
import { AddFilingDropzone } from '@/components/filings/AddFilingDropzone'
import { FilingTable } from '@/components/filings/FilingTable'
import { JobProgress } from '@/components/filings/JobProgress'
import { EmptyState } from '@/components/ui/EmptyState'
import { Skeleton } from '@/components/ui/Skeleton'
import { useToast } from '@/components/ui/Toast'
import { cn } from '@/lib/cn'

type Filter = 'all' | IndexState

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'ready', label: 'Ready' },
  { key: 'building', label: 'Building' },
  { key: 'missing', label: 'Incomplete' },
  { key: 'stale', label: 'Stale' },
  { key: 'failed', label: 'Failed' },
]

export function FilingsPage() {
  const toast = useToast()
  const { data: filings, isLoading, error } = useFilings()
  const addFiling = useAddFiling()
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const { data: job } = useJobPolling(activeJobId)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')

  const counts = useMemo(() => {
    const tally: Record<string, number> = { all: filings?.length ?? 0 }
    for (const filing of filings ?? []) {
      tally[filing.status] = (tally[filing.status] ?? 0) + 1
    }
    return tally
  }, [filings])

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (filings ?? []).filter((filing) => {
      if (filter !== 'all' && filing.status !== filter) return false
      return !needle || filing.doc_name.toLowerCase().includes(needle)
    })
  }, [filings, filter, query])

  const onSelect = (file: File) => {
    addFiling.mutate(file, {
      onSuccess: (created) => {
        setActiveJobId(created.job_id)
        toast.push({
          tone: 'info',
          title: `Indexing ${created.doc_name}`,
          detail: 'Parsing and embedding can take a few minutes for a full 10-K.',
        })
      },
      onError: (caught) =>
        toast.push({
          tone: 'error',
          title: 'Could not add that filing',
          detail: caught instanceof Error ? caught.message : undefined,
        }),
    })
  }

  return (
    <div className="scrollbar-slim h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-5 py-8 lg:px-8">
        <header className="mb-6">
          <h1 className="text-lg font-semibold tracking-tight text-ink">Filings</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Documents indexed outside any folder, and the state of each retrieval index.
            Questions are asked of{' '}
            <Link to="/folders" className="text-accent underline underline-offset-2">
              folders
            </Link>
            , so add a document to one to ask about it.
          </p>
        </header>

        <AddFilingDropzone onSelect={onSelect} busy={addFiling.isPending} />

        {job && (
          <div className="mt-4">
            <JobProgress job={job} />
          </div>
        )}

        <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1.5">
            {FILTERS.map(({ key, label }) => {
              const count = counts[key] ?? 0
              if (key !== 'all' && count === 0) return null
              return (
                <button
                  key={key}
                  onClick={() => setFilter(key)}
                  className={cn(
                    'rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors',
                    filter === key
                      ? 'border-accent/40 bg-accent-soft text-accent'
                      : 'border-line bg-surface text-ink-muted hover:text-ink',
                  )}
                >
                  {label}
                  <span className="tabular ml-1.5 font-mono text-2xs text-ink-subtle">{count}</span>
                </button>
              )
            })}
          </div>

          <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-1.5">
            <Search className="h-3.5 w-3.5 text-ink-subtle" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search filings…"
              aria-label="Search filings"
              className="w-40 bg-transparent text-xs text-ink placeholder:text-ink-subtle focus:outline-none"
            />
          </div>
        </div>

        <div className="mt-3">
          {isLoading && (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          )}

          {error && (
            <EmptyState
              icon={<FileStack className="h-5 w-5" />}
              title="Could not reach the API"
              description={error instanceof Error ? error.message : 'The service did not respond.'}
            />
          )}

          {!isLoading && !error && visible.length === 0 && (
            <EmptyState
              icon={<FileStack className="h-5 w-5" />}
              title={filings?.length ? 'Nothing matches that filter' : 'No filings yet'}
              description={
                filings?.length
                  ? 'Try a different filter or clear the search.'
                  : 'Add a 10-K or 10-Q above. Once it is parsed and embedded you can ask questions about it.'
              }
            />
          )}

          {!isLoading && visible.length > 0 && (
            <FilingTable filings={visible} />
          )}
        </div>
      </div>
    </div>
  )
}
