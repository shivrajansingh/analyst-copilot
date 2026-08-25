import { AlertTriangle, Check, CircleDashed, Loader2, RefreshCw } from 'lucide-react'
import type { IndexInfo, IndexState } from '@/api/types'
import { Badge } from '@/components/ui/Badge'
import { Tooltip } from '@/components/ui/Tooltip'
import { formatBytes, formatTimestamp } from '@/lib/format'

const PRESENTATION: Record<
  IndexState,
  { tone: 'verified' | 'building' | 'declined' | 'failed' | 'neutral'; label: string; icon: JSX.Element }
> = {
  ready: { tone: 'verified', label: 'ready', icon: <Check className="h-3 w-3" /> },
  building: { tone: 'building', label: 'building', icon: <Loader2 className="h-3 w-3 animate-spin" /> },
  stale: { tone: 'declined', label: 'stale', icon: <RefreshCw className="h-3 w-3" /> },
  failed: { tone: 'failed', label: 'failed', icon: <AlertTriangle className="h-3 w-3" /> },
  missing: { tone: 'neutral', label: 'missing', icon: <CircleDashed className="h-3 w-3" /> },
}

const EXPLANATION: Record<IndexState, string> = {
  ready: 'Built and searchable.',
  building: 'Being built right now.',
  stale: 'On disk, but built with different settings. Rebuild before searching.',
  failed: 'The last attempt failed. Retry indexing.',
  missing: 'Not built yet.',
}

/**
 * BM25 and embeddings each get their own badge.
 *
 * They are separate artefacts that fail independently — BM25 is local and
 * instant, embedding is a network call that can die halfway — so one combined
 * light would hide the most common real failure.
 */
export function IndexBadge({ kind, info }: { kind: 'BM25' | 'Embeddings'; info: IndexInfo }) {
  const { tone, label, icon } = PRESENTATION[info.state]

  return (
    <Tooltip
      label={
        <span className="flex flex-col gap-0.5 text-left">
          <span className="font-medium">
            {kind}: {EXPLANATION[info.state]}
          </span>
          {info.model && <span className="text-ink-muted">model {info.model}</span>}
          {info.dimensions && <span className="text-ink-muted">{info.dimensions} dimensions</span>}
          {info.built_at && <span className="text-ink-muted">built {formatTimestamp(info.built_at)}</span>}
          {info.size_bytes != null && (
            <span className="text-ink-muted">{formatBytes(info.size_bytes)} on disk</span>
          )}
        </span>
      }
    >
      <Badge tone={tone} icon={icon}>
        {label}
      </Badge>
    </Tooltip>
  )
}
