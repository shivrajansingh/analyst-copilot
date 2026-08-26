import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ChevronDown,
  ChevronRight,
  FilePlus2,
  FileStack,
  MessageSquare,
  Search,
  Trash2,
} from 'lucide-react'
import type { CollectionSummary } from '@/api/types'
import {
  useAddDocuments,
  useCollectionJobs,
  useCollections,
  useCreateCollection,
  useDeleteCollection,
  useFetchDocument,
  useRemoveDocument,
} from '@/hooks/useCollections'
import { AddDocumentsDropzone } from '@/components/filings/AddDocumentsDropzone'
import { DocumentRow } from '@/components/filings/DocumentRow'
import { FetchByUrl } from '@/components/filings/FetchByUrl'
import { JobProgress } from '@/components/filings/JobProgress'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/Input'
import { Skeleton } from '@/components/ui/Skeleton'
import { useToast } from '@/components/ui/Toast'
import { cn } from '@/lib/cn'

/**
 * The filing library, and the "Add documents" control.
 *
 * A **filing** here is a set of documents, not a single file: an analyst's
 * question is rarely about one file, and "how did margin move over three years"
 * spans three annual reports. So a filing holds however many documents it takes
 * to answer questions about it, and questions are asked of the filing.
 *
 * Uploads always land in a filing, and several files can go in at once — each
 * getting its own indexing job, so a filing of twelve documents reports which
 * one is slow rather than one bar that says nothing.
 */
export function FilingsPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const { data: filings, isLoading, error } = useCollections()
  const createFiling = useCreateCollection()
  const addDocuments = useAddDocuments()
  const fetchDocument = useFetchDocument()
  const deleteFiling = useDeleteCollection()

  const [newName, setNewName] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return filings ?? []
    return (filings ?? []).filter(
      (filing) =>
        filing.name.toLowerCase().includes(needle) ||
        filing.documents.some((doc) => doc.doc_name.toLowerCase().includes(needle)),
    )
  }, [filings, query])

  /**
   * One report for both intake paths.
   *
   * Uploading files and fetching a URL return the same accepted/rejected shape,
   * and a rejected URL is reported the same way as a rejected file — the user
   * does not care which code path refused their document, only why.
   */
  const reportIntake = (result: {
    accepted: { length: number }
    rejected: { filename: string; message: string }[]
  }) => {
    if (result.accepted.length > 0) {
      toast.push({
        tone: 'info',
        title: `Indexing ${result.accepted.length} document${
          result.accepted.length === 1 ? '' : 's'
        }`,
        detail: 'A full 10-K takes a few minutes to parse and embed.',
      })
    }
    for (const reject of result.rejected) {
      toast.push({ tone: 'error', title: `Rejected ${reject.filename}`, detail: reject.message })
    }
  }

  const onCreate = () => {
    const name = newName.trim()
    if (!name) return
    createFiling.mutate(
      { name },
      {
        onSuccess: (filing) => {
          setNewName('')
          setExpanded(filing.name)
          toast.push({
            tone: 'info',
            title: `“${filing.name}” ready`,
            detail: 'Add documents to it below.',
          })
        },
        onError: (caught) =>
          toast.push({
            tone: 'error',
            title: 'Could not create that filing',
            detail: caught instanceof Error ? caught.message : undefined,
          }),
      },
    )
  }

  return (
    <div className="scrollbar-slim h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-5 py-8 lg:px-8">
        <header className="mb-6">
          <h1 className="text-lg font-semibold tracking-tight text-ink">Filings</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Each filing holds the documents a question spans. Asking one searches every
            indexed document in it, and the answer still names the single document it
            came from.
          </p>
        </header>

        <div className="flex flex-wrap items-end gap-2 rounded-xl border border-line bg-surface p-4">
          <label className="min-w-0 flex-1">
            <span className="mb-1.5 block text-xs font-medium text-ink-muted">New filing</span>
            <Input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && onCreate()}
              placeholder="Boeing 2020–2023"
              aria-label="New filing name"
            />
          </label>
          <Button onClick={onCreate} disabled={!newName.trim() || createFiling.isPending}>
            <FilePlus2 className="h-4 w-4" />
            Create
          </Button>
        </div>

        <div className="mt-6 flex items-center justify-between gap-3">
          <p className="text-xs text-ink-muted">
            {filings?.length ?? 0} filing{filings?.length === 1 ? '' : 's'}
          </p>
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

        <div className="mt-3 space-y-3">
          {isLoading &&
            Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-16 w-full" />
            ))}

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
              title={filings?.length ? 'Nothing matches that search' : 'No filings yet'}
              description={
                filings?.length
                  ? 'Try a different search.'
                  : 'Create a filing above, then add the documents it should cover — upload them or fetch them by URL.'
              }
            />
          )}

          {visible.map((filing) => (
            <FilingCard
              key={filing.name}
              filing={filing}
              open={expanded === filing.name}
              onToggle={() =>
                setExpanded((current) => (current === filing.name ? null : filing.name))
              }
              onAsk={() => navigate(`/chat?filing=${encodeURIComponent(filing.name)}`)}
              onDelete={() => {
                if (
                  !window.confirm(
                    `Delete “${filing.name}”? Its indices are removed; the uploaded documents are kept.`,
                  )
                )
                  return
                deleteFiling.mutate(
                  { name: filing.name },
                  {
                    onSuccess: () =>
                      toast.push({ tone: 'info', title: `Deleted “${filing.name}”` }),
                  },
                )
              }}
              onUpload={(files) =>
                addDocuments.mutate(
                  { name: filing.name, files },
                  {
                    onSuccess: reportIntake,
                    onError: (caught) =>
                      toast.push({
                        tone: 'error',
                        title: 'Upload failed',
                        detail: caught instanceof Error ? caught.message : undefined,
                      }),
                  },
                )
              }
              onFetch={(url, docName) =>
                fetchDocument.mutate(
                  { name: filing.name, url, docName },
                  {
                    onSuccess: reportIntake,
                    onError: (caught: unknown) =>
                      toast.push({
                        tone: 'error',
                        title: 'Could not fetch that URL',
                        detail: caught instanceof Error ? caught.message : undefined,
                      }),
                  },
                )
              }
              uploading={addDocuments.isPending}
              fetching={fetchDocument.isPending}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function FilingCard({
  filing,
  open,
  onToggle,
  onAsk,
  onDelete,
  onUpload,
  onFetch,
  uploading,
  fetching,
}: {
  filing: CollectionSummary
  open: boolean
  onToggle: () => void
  onAsk: () => void
  onDelete: () => void
  onUpload: (files: File[]) => void
  onFetch: (url: string, docName?: string) => void
  uploading: boolean
  fetching: boolean
}) {
  // Poll only the filing that is open. Twelve collapsed filings polling their
  // jobs would be twelve requests a second for progress nobody is watching.
  const { data: jobs = [] } = useCollectionJobs(open ? filing.name : null)
  const removeDocument = useRemoveDocument(filing.name)
  const running = jobs.filter((job) => job.status !== 'ready' && job.status !== 'failed')
  const complete = filing.ready_count === filing.document_count

  return (
    <section className="overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
        >
          {open ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-ink-subtle" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-ink-subtle" />
          )}
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-ink">{filing.name}</span>
            <span className="mt-0.5 block text-2xs text-ink-muted">
              {filing.document_count === 0
                ? 'Empty — add documents below'
                : complete
                  ? `${filing.document_count} document${filing.document_count === 1 ? '' : 's'} · all indexed`
                  : `${filing.ready_count} of ${filing.document_count} indexed`}
            </span>
          </span>
        </button>

        <span className="flex shrink-0 items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={onAsk}
            disabled={!filing.searchable}
            title={filing.searchable ? undefined : 'No document in this filing is indexed yet'}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Ask
          </Button>
          <Button variant="ghost" size="sm" onClick={onDelete} aria-label={`Delete ${filing.name}`}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </span>
      </div>

      {open && (
        <div className={cn('border-t border-line px-4 py-4', 'space-y-4')}>
          <AddDocumentsDropzone
            onSelect={onUpload}
            busy={uploading}
            filingName={filing.name}
          />

          <FetchByUrl onFetch={onFetch} busy={fetching} />

          {running.length > 0 && (
            <div className="space-y-2">
              {running.map((job) => (
                <JobProgress key={job.job_id} job={job} />
              ))}
            </div>
          )}

          {filing.documents.length > 0 && (
            <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
              {filing.documents.map((document) => (
                <li key={document.doc_name}>
                  <DocumentRow
                    document={document}
                    job={jobs.find((job) => job.doc_name === document.doc_name) ?? null}
                    onRemove={() => {
                      if (!window.confirm(`Remove “${document.doc_name}” from this filing?`)) return
                      removeDocument.mutate(document.doc_name)
                    }}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
