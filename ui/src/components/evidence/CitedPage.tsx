import { useState } from 'react'
import { ChevronDown, Maximize2, Quote } from 'lucide-react'
import type { Evidence } from '@/api/types'
import { usePage } from '@/hooks/usePage'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { LocationNote } from './LocationNote'
import { PageText } from './PageText'
import { cn } from '@/lib/cn'

/**
 * The cited snippet, expandable to the whole page.
 *
 * The snippet is what the verifier matched, so it leads. But a figure read out
 * of its table is a figure an analyst cannot act on, so the full page is one
 * click away with the snippet highlighted inside it — that is the difference
 * between a citation and a proof. The page is only fetched once expanded.
 */
export function CitedPage({
  evidence,
  collection,
  onOpenFull,
}: {
  evidence: Evidence
  collection?: string | null
  onOpenFull?: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading } = usePage(
    expanded ? evidence.doc_name : null,
    evidence.page,
    collection,
  )

  return (
    <section className="px-4 py-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-2xs font-semibold uppercase tracking-wider text-ink-muted">
          Cited {evidence.segment_kind === 'page' ? 'page' : 'location'}
        </h3>
        <div className="flex items-center gap-1.5">
          {/* Named the way the source names it: a workbook has no page 4. */}
          <Badge tone="accent">{evidence.label || `page ${evidence.display_page}`}</Badge>
          {onOpenFull && (
            <button
              onClick={onOpenFull}
              aria-label="Open this page full size"
              className="rounded p-1 text-ink-subtle transition-colors hover:text-accent"
            >
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      <p className="truncate font-mono text-xs text-ink-muted">{evidence.doc_name}</p>
      <LocationNote evidence={evidence} />
      <div className="mb-2.5" />

      <blockquote className="relative rounded-lg border border-line bg-surface-sunken p-3.5">
        <Quote className="absolute right-2.5 top-2.5 h-3.5 w-3.5 text-line-strong" aria-hidden />
        <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent" aria-hidden />
        <p className="pl-2.5 font-mono text-[13px] leading-[1.75] text-ink">{evidence.snippet}</p>
      </blockquote>

      <button
        onClick={() => setExpanded((open) => !open)}
        aria-expanded={expanded}
        className={cn(
          'mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-line',
          'py-1.5 text-2xs font-medium uppercase tracking-wide text-ink-muted',
          'transition-colors hover:border-accent/40 hover:text-accent',
        )}
      >
        {expanded ? 'Show less' : 'Show the full page'}
        <ChevronDown className={cn('h-3 w-3 transition-transform', expanded && 'rotate-180')} />
      </button>

      {expanded && (
        <div className="mt-2 rounded-lg border border-line bg-surface-sunken p-3.5 animate-fade-up">
          {isLoading && (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className={cn('h-3.5', index % 3 === 2 ? 'w-2/3' : 'w-full')} />
              ))}
            </div>
          )}
          {data && (
            <>
              <p className="tabular mb-2.5 font-mono text-2xs text-ink-subtle">
                {data.char_count.toLocaleString()} characters
                {data.truncated && (
                  <span className="text-declined">
                    {' '}
                    · only {data.embedded_chars.toLocaleString()} were embedded
                  </span>
                )}
              </p>
              <PageText
                text={data.text}
                snippet={evidence.snippet}
                embeddedChars={data.embedded_chars}
                truncated={data.truncated}
                className="max-h-96 overflow-y-auto scrollbar-slim"
              />
            </>
          )}
        </div>
      )}
    </section>
  )
}
