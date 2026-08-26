import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ChevronDown,
  ChevronRight,
  FolderPlus,
  Folders as FoldersIcon,
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
  useRemoveDocument,
} from '@/hooks/useCollections'
import { AddDocumentsDropzone } from '@/components/filings/AddDocumentsDropzone'
import { DocumentRow } from '@/components/filings/DocumentRow'
import { JobProgress } from '@/components/filings/JobProgress'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/Input'
import { Skeleton } from '@/components/ui/Skeleton'
import { useToast } from '@/components/ui/Toast'
import { cn } from '@/lib/cn'

/**
 * The folder library, and the "Add documents" control.
 *
 * A folder is the unit an analyst works with: a question is rarely about one
 * file. Uploads therefore always land in a folder, and several files can go in
 * at once — each getting its own indexing job, so a folder of twelve filings
 * reports which one is slow rather than one bar that says nothing.
 */
export function FoldersPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const { data: folders, isLoading, error } = useCollections()
  const createFolder = useCreateCollection()
  const addDocuments = useAddDocuments()
  const deleteFolder = useDeleteCollection()

  const [newName, setNewName] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return folders ?? []
    return (folders ?? []).filter(
      (folder) =>
        folder.name.toLowerCase().includes(needle) ||
        folder.documents.some((doc) => doc.doc_name.toLowerCase().includes(needle)),
    )
  }, [folders, query])

  const onCreate = () => {
    const name = newName.trim()
    if (!name) return
    createFolder.mutate(
      { name },
      {
        onSuccess: (folder) => {
          setNewName('')
          setExpanded(folder.name)
          toast.push({ tone: 'info', title: `Folder “${folder.name}” ready`, detail: 'Add documents to it below.' })
        },
        onError: (caught) =>
          toast.push({
            tone: 'error',
            title: 'Could not create that folder',
            detail: caught instanceof Error ? caught.message : undefined,
          }),
      },
    )
  }

  return (
    <div className="scrollbar-slim h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-5 py-8 lg:px-8">
        <header className="mb-6">
          <h1 className="text-lg font-semibold tracking-tight text-ink">Folders</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Group the documents a question spans. Asking a folder searches every indexed
            document in it, and the answer still names the one document it came from.
          </p>
        </header>

        <div className="flex flex-wrap items-end gap-2 rounded-xl border border-line bg-surface p-4">
          <label className="min-w-0 flex-1">
            <span className="mb-1.5 block text-xs font-medium text-ink-muted">New folder</span>
            <Input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && onCreate()}
              placeholder="Boeing 2020–2023"
              aria-label="New folder name"
            />
          </label>
          <Button onClick={onCreate} disabled={!newName.trim() || createFolder.isPending}>
            <FolderPlus className="h-4 w-4" />
            Create
          </Button>
        </div>

        <div className="mt-6 flex items-center justify-between gap-3">
          <p className="text-xs text-ink-muted">
            {folders?.length ?? 0} folder{folders?.length === 1 ? '' : 's'}
          </p>
          <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-1.5">
            <Search className="h-3.5 w-3.5 text-ink-subtle" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search folders…"
              aria-label="Search folders"
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
              icon={<FoldersIcon className="h-5 w-5" />}
              title="Could not reach the API"
              description={error instanceof Error ? error.message : 'The service did not respond.'}
            />
          )}

          {!isLoading && !error && visible.length === 0 && (
            <EmptyState
              icon={<FoldersIcon className="h-5 w-5" />}
              title={folders?.length ? 'Nothing matches that search' : 'No folders yet'}
              description={
                folders?.length
                  ? 'Try a different search.'
                  : 'Create a folder above, then drop the filings it should cover into it.'
              }
            />
          )}

          {visible.map((folder) => (
            <FolderCard
              key={folder.name}
              folder={folder}
              open={expanded === folder.name}
              onToggle={() =>
                setExpanded((current) => (current === folder.name ? null : folder.name))
              }
              onAsk={() => navigate(`/chat?folder=${encodeURIComponent(folder.name)}`)}
              onDelete={() => {
                if (
                  !window.confirm(
                    `Delete “${folder.name}”? Its indices are removed; the uploaded files are kept.`,
                  )
                )
                  return
                deleteFolder.mutate(
                  { name: folder.name },
                  {
                    onSuccess: () =>
                      toast.push({ tone: 'info', title: `Deleted “${folder.name}”` }),
                  },
                )
              }}
              onUpload={(files) =>
                addDocuments.mutate(
                  { name: folder.name, files },
                  {
                    onSuccess: (result) => {
                      if (result.accepted.length > 0) {
                        toast.push({
                          tone: 'info',
                          title: `Indexing ${result.accepted.length} document${
                            result.accepted.length === 1 ? '' : 's'
                          }`,
                          detail: 'A full 10-K takes a few minutes to parse and embed.',
                        })
                      }
                      // Partial success is normal: report what the server kept
                      // and what it refused, rather than only the happy half.
                      for (const reject of result.rejected) {
                        toast.push({
                          tone: 'error',
                          title: `Rejected ${reject.filename}`,
                          detail: reject.message,
                        })
                      }
                    },
                    onError: (caught) =>
                      toast.push({
                        tone: 'error',
                        title: 'Upload failed',
                        detail: caught instanceof Error ? caught.message : undefined,
                      }),
                  },
                )
              }
              uploading={addDocuments.isPending}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

function FolderCard({
  folder,
  open,
  onToggle,
  onAsk,
  onDelete,
  onUpload,
  uploading,
}: {
  folder: CollectionSummary
  open: boolean
  onToggle: () => void
  onAsk: () => void
  onDelete: () => void
  onUpload: (files: File[]) => void
  uploading: boolean
}) {
  // Poll only the folder that is open. Twelve collapsed folders polling their
  // jobs would be twelve requests a second for progress nobody is watching.
  const { data: jobs = [] } = useCollectionJobs(open ? folder.name : null)
  const removeDocument = useRemoveDocument(folder.name)
  const running = jobs.filter((job) => job.status !== 'ready' && job.status !== 'failed')
  const complete = folder.ready_count === folder.document_count

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
            <span className="block truncate text-sm font-medium text-ink">{folder.name}</span>
            <span className="mt-0.5 block text-2xs text-ink-muted">
              {folder.document_count === 0
                ? 'Empty — add documents below'
                : complete
                  ? `${folder.document_count} document${folder.document_count === 1 ? '' : 's'} · all indexed`
                  : `${folder.ready_count} of ${folder.document_count} indexed`}
            </span>
          </span>
        </button>

        <span className="flex shrink-0 items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={onAsk}
            disabled={!folder.searchable}
            title={folder.searchable ? undefined : 'No document in this folder is indexed yet'}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Ask
          </Button>
          <Button variant="ghost" size="sm" onClick={onDelete} aria-label={`Delete ${folder.name}`}>
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </span>
      </div>

      {open && (
        <div className={cn('border-t border-line px-4 py-4', 'space-y-4')}>
          <AddDocumentsDropzone
            onSelect={onUpload}
            busy={uploading}
            folderName={folder.name}
          />

          {running.length > 0 && (
            <div className="space-y-2">
              {running.map((job) => (
                <JobProgress key={job.job_id} job={job} />
              ))}
            </div>
          )}

          {folder.documents.length > 0 && (
            <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
              {folder.documents.map((document) => (
                <li key={document.doc_name}>
                  <DocumentRow
                    document={document}
                    job={jobs.find((job) => job.doc_name === document.doc_name) ?? null}
                    onRemove={() => {
                      if (!window.confirm(`Remove “${document.doc_name}” from this folder?`)) return
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
