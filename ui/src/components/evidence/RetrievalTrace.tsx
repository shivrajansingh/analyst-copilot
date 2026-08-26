import { Maximize2, Star } from 'lucide-react'
import type { RetrievedPage } from '@/api/types'
import { cn } from '@/lib/cn'
import { Tooltip } from '@/components/ui/Tooltip'

/**
 * Why this page and not another.
 *
 * Turns retrieval from a black box into something an analyst can audit: the
 * pages that were considered, how each scored lexically and semantically, and
 * which one the answer was drawn from.
 */
export function RetrievalTrace({
  retrieval,
  onOpenPage,
}: {
  retrieval: RetrievedPage[]
  onOpenPage?: (hit: RetrievedPage) => void
}) {
  if (retrieval.length === 0) return null
  // A filing ranks pages from several documents against each other, and page 59
  // exists in all of them, so the document has to be shown alongside the page.
  const multiDocument = new Set(retrieval.map((hit) => hit.doc_name)).size > 1
  const max = Math.max(...retrieval.map((hit) => hit.fused_score), 0.0001)

  return (
    <section className="border-t border-line px-4 py-4">
      <h3 className="mb-1 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
        Why this page
      </h3>
      <p className="mb-3 text-2xs leading-relaxed text-ink-subtle">
        {multiDocument
          ? 'Pages from across the filing, ranked against each other, best first. Open one to read it and see how each retriever scored it.'
          : 'Pages the retriever considered, best first. Open one to read it and see how each retriever scored it.'}
      </p>

      <ul className="space-y-2">
        {retrieval.map((hit) => (
          <li key={`${hit.doc_name}:${hit.page}`} className="group">
            <button
              type="button"
              onClick={() => onOpenPage?.(hit)}
              disabled={!onOpenPage}
              aria-label={
                multiDocument
                  ? `Read ${hit.doc_name} ${hit.label || `page ${hit.display_page}`}`
                  : `Read page ${hit.display_page}`
              }
              className={cn(
                'flex w-full items-center gap-2 rounded-md px-1 py-0.5 text-left transition-colors',
                onOpenPage && 'hover:bg-surface-sunken',
              )}
            >
              <span
                className={cn(
                  'flex shrink-0 items-center gap-0.5',
                  multiDocument ? 'w-40' : 'w-9',
                )}
              >
                {hit.cited ? (
                  <Star className="h-3 w-3 shrink-0 fill-accent text-accent" />
                ) : (
                  <span className="w-3 shrink-0" />
                )}
                <span
                  className={cn(
                    'tabular min-w-0 truncate font-mono text-xs',
                    hit.cited ? 'font-semibold text-accent' : 'text-ink-muted',
                  )}
                  title={multiDocument ? `${hit.doc_name} · ${hit.label}` : undefined}
                >
                  {multiDocument ? `${hit.doc_name} ${hit.display_page}` : hit.display_page}
                </span>
              </span>

              <Tooltip
                label={
                  <span className="flex flex-col text-left">
                    <span>BM25 {hit.bm25_score?.toFixed(2) ?? '—'}</span>
                    <span>vector {hit.vector_score?.toFixed(3) ?? '—'}</span>
                  </span>
                }
                className="flex-1"
              >
                <span className="block h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
                  <span
                    className={cn(
                      'block h-full rounded-full transition-all duration-500',
                      hit.cited ? 'bg-accent' : 'bg-line-strong group-hover:bg-ink-subtle',
                    )}
                    style={{ width: `${Math.max(3, (hit.fused_score / max) * 100)}%` }}
                  />
                </span>
              </Tooltip>

              <span className="tabular w-10 shrink-0 text-right font-mono text-2xs text-ink-subtle">
                {hit.fused_score.toFixed(2)}
              </span>
              {onOpenPage && (
                <Maximize2 className="h-3 w-3 shrink-0 text-ink-subtle opacity-0 transition-opacity group-hover:opacity-100" />
              )}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
