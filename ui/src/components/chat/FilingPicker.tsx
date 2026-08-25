import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'
import type { FilingSummary } from '@/api/types'
import { cn } from '@/lib/cn'
import { IndexBadge } from '@/components/filings/IndexBadge'

/**
 * Choose the filing a conversation is about.
 *
 * Index state is shown inline so a filing that cannot be searched is visibly
 * unusable *before* the question is typed, rather than after it fails.
 */
export function FilingPicker({
  filings,
  value,
  onChange,
  disabled,
}: {
  filings: FilingSummary[]
  value: string | null
  onChange: (docName: string) => void
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
    const ranked = [...filings].sort((a, b) => a.doc_name.localeCompare(b.doc_name))
    if (!needle) return ranked
    return ranked.filter((filing) => filing.doc_name.toLowerCase().includes(needle))
  }, [filings, query])

  const selected = filings.find((filing) => filing.doc_name === value)

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
          <span className="truncate font-mono text-sm text-ink">
            {selected?.doc_name ?? 'Select a filing'}
          </span>
          {selected?.page_count != null && (
            <span className="tabular shrink-0 font-mono text-2xs text-ink-subtle">
              {selected.page_count} pages
            </span>
          )}
        </span>
        <ChevronDown
          className={cn('h-4 w-4 shrink-0 text-ink-subtle transition-transform', open && 'rotate-180')}
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
              placeholder="Search filings…"
              className="w-full bg-transparent text-sm text-ink placeholder:text-ink-subtle focus:outline-none"
            />
          </div>

          <ul role="listbox" className="scrollbar-slim max-h-72 overflow-y-auto py-1">
            {matches.length === 0 && (
              <li className="px-3 py-6 text-center text-xs text-ink-subtle">
                No filing matches “{query}”.
              </li>
            )}
            {matches.map((filing) => {
              const searchable =
                filing.bm25.state === 'ready' && filing.vector.state === 'ready'
              return (
                <li key={filing.doc_name}>
                  <button
                    role="option"
                    aria-selected={filing.doc_name === value}
                    disabled={!searchable}
                    onClick={() => {
                      onChange(filing.doc_name)
                      setOpen(false)
                      setQuery('')
                    }}
                    className={cn(
                      'flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors',
                      searchable ? 'hover:bg-surface' : 'cursor-not-allowed opacity-50',
                    )}
                    title={searchable ? undefined : 'Both indices must be ready before this filing can be searched'}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      {filing.doc_name === value ? (
                        <Check className="h-3.5 w-3.5 shrink-0 text-accent" />
                      ) : (
                        <span className="w-3.5" />
                      )}
                      <span className="truncate font-mono text-[13px] text-ink">
                        {filing.doc_name}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      <IndexBadge kind="BM25" info={filing.bm25} />
                      <IndexBadge kind="Embeddings" info={filing.vector} />
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
