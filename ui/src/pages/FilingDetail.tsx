import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, MessagesSquare } from 'lucide-react'
import type { IndexInfo } from '@/api/types'
import { useFilings } from '@/hooks/useFilings'
import { Card, CardHeader } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { EmptyState } from '@/components/ui/EmptyState'
import { IndexBadge } from '@/components/filings/IndexBadge'
import { formatBytes, formatTimestamp } from '@/lib/format'
import { FileStack } from 'lucide-react'

export function FilingDetailPage() {
  const { docName = '' } = useParams()
  const { data: filings, isLoading } = useFilings()
  const filing = filings?.find((item) => item.doc_name === docName)

  if (isLoading) {
    return (
      <div className="mx-auto max-w-3xl space-y-3 px-5 py-8">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  }

  if (!filing) {
    return (
      <EmptyState
        icon={<FileStack className="h-5 w-5" />}
        title="No such filing"
        description={`Nothing indexed under “${docName}”.`}
        action={
          <Link to="/filings">
            <Button variant="secondary" size="sm">
              Back to filings
            </Button>
          </Link>
        }
      />
    )
  }

  const searchable = filing.bm25.state === 'ready' && filing.vector.state === 'ready'

  return (
    <div className="scrollbar-slim h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-5 py-8 lg:px-8">
        <Link
          to="/filings"
          className="mb-4 inline-flex items-center gap-1.5 text-xs text-ink-muted transition-colors hover:text-ink"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Filings
        </Link>

        <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-mono text-lg font-semibold tracking-tight text-ink">
              {filing.doc_name}
            </h1>
            <p className="tabular mt-1 font-mono text-xs text-ink-muted">
              {filing.page_count ?? '—'} pages
            </p>
          </div>
          <Link to={`/chat?doc=${encodeURIComponent(filing.doc_name)}`}>
            <Button size="sm" disabled={!searchable}>
              <MessagesSquare className="h-3.5 w-3.5" />
              Ask a question
            </Button>
          </Link>
        </header>

        <div className="grid gap-4 sm:grid-cols-2">
          <IndexCard kind="BM25" subtitle="Lexical index — exact wording" info={filing.bm25} />
          <IndexCard
            kind="Embeddings"
            subtitle="Dense index — meaning, not wording"
            info={filing.vector}
          />
        </div>

        {!searchable && (
          <p className="mt-4 rounded-lg border border-declined/30 bg-declined-soft/40 p-3 text-xs leading-relaxed text-ink-muted">
            Both indices must be ready before this filing can be searched. Retrieval fuses the
            two, so a missing index is not a degraded search — it is no search at all.
          </p>
        )}
      </div>
    </div>
  )
}

function IndexCard({
  kind,
  subtitle,
  info,
}: {
  kind: 'BM25' | 'Embeddings'
  subtitle: string
  info: IndexInfo
}) {
  const rows: [string, string][] = [
    ['Pages', info.page_count != null ? String(info.page_count) : '—'],
    ['Model', info.model ?? '—'],
    ...(info.dimensions ? ([['Dimensions', String(info.dimensions)]] as [string, string][]) : []),
    ['Parser version', info.parser_version ?? '—'],
    ['Built', formatTimestamp(info.built_at)],
    ['Size on disk', formatBytes(info.size_bytes)],
  ]

  return (
    <Card>
      <CardHeader
        title={kind}
        description={subtitle}
        action={<IndexBadge kind={kind} info={info} />}
      />
      <dl className="divide-y divide-line/60">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3 px-4 py-2.5">
            <dt className="text-xs text-ink-muted">{label}</dt>
            <dd className="tabular truncate font-mono text-xs text-ink">{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}
