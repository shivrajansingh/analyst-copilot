import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Folder, Search } from 'lucide-react'
import type { CollectionSummary } from '@/api/types'
import { cn } from '@/lib/cn'

/**
 * Choose the folder a conversation is about.
 *
 * A question is asked of a folder, not a file: "how did margin move over three
 * years" spans three annual reports, and making the analyst pick one of them
 * first is asking them to answer half the question themselves.
 *
 * How much of a folder is ready is shown inline — `9 of 12 ready` — because a
 * folder is searchable as soon as one document is indexed, and an analyst
 * asking a question against a partly-built folder should know that the answer
 * may not have seen everything yet.
 */
export function FolderPicker({
  folders,
  value,
  onChange,
  disabled,
}: {
  folders: CollectionSummary[]
  value: string | null
  onChange: (name: string) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClickAway = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClickAway)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClickAway)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const ranked = [...folders].sort((a, b) => a.name.localeCompare(b.name))
    if (!needle) return ranked
    return ranked.filter(
      (folder) =>
        folder.name.toLowerCase().includes(needle) ||
        folder.documents.some((doc) => doc.doc_name.toLowerCase().includes(needle)),
    )
  }, [folders, query])

  const selected = folders.find((folder) => folder.name === value)

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setOpen((current) => !current)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          'flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2',
          'transition-colors disabled:opacity-60',
          open ? 'border-accent bg-surface' : 'border-line bg-surface hover:border-line-strong',
        )}
      >
        <span className="flex min-w-0 items-center gap-2.5">
          <Folder className="h-4 w-4 shrink-0 text-ink-subtle" />
          <span className="truncate text-sm text-ink">
            {selected?.name ?? 'Select a folder'}
          </span>
          {selected && <ReadyCount folder={selected} />}
        </span>
        <ChevronDown
          className={cn(
            'h-4 w-4 shrink-0 text-ink-subtle transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <div className="absolute z-40 mt-1.5 w-full overflow-hidden rounded-xl border border-line bg-surface-raised shadow-panel animate-fade-up">
          <div className="flex items-center gap-2 border-b border-line px-3 py-2">
            <Search className="h-3.5 w-3.5 shrink-0 text-ink-subtle" />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search folders and documents…"
              className="w-full bg-transparent text-sm text-ink placeholder:text-ink-subtle focus:outline-none"
            />
          </div>

          <ul role="listbox" className="scrollbar-slim max-h-80 overflow-y-auto py-1">
            {matches.length === 0 && (
              <li className="px-3 py-6 text-center text-xs text-ink-subtle">
                {folders.length === 0
                  ? 'No folders yet. Create one on the Folders screen and add documents to it.'
                  : `Nothing matches “${query}”.`}
              </li>
            )}
            {matches.map((folder) => (
              <li key={folder.name}>
                <button
                  role="option"
                  aria-selected={folder.name === value}
                  disabled={!folder.searchable}
                  onClick={() => {
                    onChange(folder.name)
                    setOpen(false)
                    setQuery('')
                  }}
                  className={cn(
                    'flex w-full items-start justify-between gap-3 px-3 py-2 text-left transition-colors',
                    folder.searchable ? 'hover:bg-surface' : 'cursor-not-allowed opacity-50',
                  )}
                  title={
                    folder.searchable
                      ? undefined
                      : 'No document in this folder is indexed yet'
                  }
                >
                  <span className="flex min-w-0 items-start gap-2">
                    {folder.name === value ? (
                      <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                    ) : (
                      <span className="w-3.5" />
                    )}
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] text-ink">{folder.name}</span>
                      {folder.documents.length > 0 && (
                        <span className="mt-0.5 block truncate font-mono text-2xs text-ink-subtle">
                          {folder.documents
                            .slice(0, 3)
                            .map((doc) => doc.doc_name)
                            .join(' · ')}
                          {folder.documents.length > 3 &&
                            ` +${folder.documents.length - 3} more`}
                        </span>
                      )}
                    </span>
                  </span>
                  <ReadyCount folder={folder} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ReadyCount({ folder }: { folder: CollectionSummary }) {
  const complete = folder.ready_count === folder.document_count
  return (
    <span
      className={cn(
        'tabular shrink-0 whitespace-nowrap font-mono text-2xs',
        complete ? 'text-ink-subtle' : 'text-building',
      )}
      title={
        complete
          ? `${folder.document_count} documents indexed`
          : `${folder.ready_count} of ${folder.document_count} indexed — answers may not have seen the rest yet`
      }
    >
      {complete
        ? `${folder.document_count} doc${folder.document_count === 1 ? '' : 's'}`
        : `${folder.ready_count}/${folder.document_count} ready`}
    </span>
  )
}
