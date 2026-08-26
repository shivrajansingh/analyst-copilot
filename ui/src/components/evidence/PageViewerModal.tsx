import type { RetrievedPage } from '@/api/types'
import { usePage } from '@/hooks/usePage'
import { Modal } from '@/components/ui/Modal'
import { Skeleton } from '@/components/ui/Skeleton'
import { Badge } from '@/components/ui/Badge'
import { PageText } from './PageText'
import { cn } from '@/lib/cn'

/**
 * What each retriever saw on this page, and how each scored it.
 *
 * Framed as "saw and scored" rather than "retrieved", because both retrievers
 * cover the same pages — only the ranking differs. The one real difference is
 * how much text each worked from, which the boundary marker shows.
 */
export function PageViewerModal({
  docName,
  collection,
  hit,
  snippet,
  onClose,
}: {
  docName: string | null
  collection?: string | null
  hit: RetrievedPage | null
  snippet?: string
  onClose: () => void
}) {
  const { data, isLoading, error } = usePage(docName, hit?.page ?? null, collection)
  const open = Boolean(docName && hit)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={
        <span className="font-mono">
          {docName} · {hit?.label || `page ${hit?.display_page}`}
        </span>
      }
      subtitle={
        data && (
          <span className="tabular font-mono">
            {data.char_count.toLocaleString()} characters
            {data.truncated && (
              <>
                {' · '}
                <span className="text-declined">
                  {data.embedded_chars.toLocaleString()} embedded
                </span>
              </>
            )}
            {' · '}page {data.display_page} of {data.page_count}
          </span>
        )
      }
    >
      {hit && (
        <div className="grid gap-3 border-b border-line bg-surface-sunken/50 px-5 py-4 sm:grid-cols-3">
          <ScoreTile
            label="BM25"
            caption="lexical · whole page"
            value={hit.bm25_score}
            format={(value) => value.toFixed(2)}
          />
          <ScoreTile
            label="Embeddings"
            caption={
              data?.truncated
                ? `semantic · first ${data.embedded_chars.toLocaleString()} chars`
                : 'semantic · whole page'
            }
            value={hit.vector_score}
            format={(value) => value.toFixed(3)}
          />
          <ScoreTile
            label="Fused"
            caption={hit.cited ? 'cited for this answer' : `ranked #${hit.rank}`}
            value={hit.fused_score}
            format={(value) => value.toFixed(3)}
            highlight={hit.cited}
          />
        </div>
      )}

      {data?.truncated && (
        <p className="border-b border-line bg-declined-soft/30 px-5 py-2.5 text-xs leading-relaxed text-ink-muted">
          This page is longer than the embedding window. BM25 scored all{' '}
          <span className="tabular font-mono">{data.char_count.toLocaleString()}</span>{' '}
          characters; the embedding only saw the first{' '}
          <span className="tabular font-mono">{data.embedded_chars.toLocaleString()}</span>.
          Anything after the marker below is invisible to semantic search.
        </p>
      )}

      <div className="px-5 py-4">
        {isLoading && (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className={cn('h-4', index % 3 === 2 ? 'w-2/3' : 'w-full')} />
            ))}
          </div>
        )}
        {error && (
          <p className="text-sm text-failed">
            {error instanceof Error ? error.message : 'Could not load this page.'}
          </p>
        )}
        {data && (
          <PageText
            text={data.text}
            snippet={hit?.cited ? snippet : undefined}
            embeddedChars={data.embedded_chars}
            truncated={data.truncated}
          />
        )}
      </div>
    </Modal>
  )
}

function ScoreTile({
  label,
  caption,
  value,
  format,
  highlight,
}: {
  label: string
  caption: string
  value: number | null
  format: (value: number) => string
  highlight?: boolean
}) {
  return (
    <div
      className={cn(
        'rounded-lg border px-3 py-2',
        highlight ? 'border-accent/40 bg-accent-soft/50' : 'border-line bg-surface',
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-2xs font-semibold uppercase tracking-wider text-ink-muted">
          {label}
        </span>
        <span
          className={cn(
            'tabular font-mono text-sm font-semibold',
            highlight ? 'text-accent' : 'text-ink',
          )}
        >
          {value == null ? '—' : format(value)}
        </span>
      </div>
      <p className="mt-0.5 text-2xs text-ink-subtle">{caption}</p>
      {value == null && (
        <Badge tone="neutral" className="mt-1.5">
          not ranked
        </Badge>
      )}
    </div>
  )
}
