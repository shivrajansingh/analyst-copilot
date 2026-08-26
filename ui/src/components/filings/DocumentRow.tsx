import { AlertTriangle, Check, CircleDashed, Loader2, RefreshCw, X } from 'lucide-react'
import type { CollectionDocumentInfo, IndexState, IndexingJob, SourceFormat } from '@/api/types'
import { Button } from '@/components/ui/Button'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/lib/cn'

/** What each format's segments are actually called. Never "pages" for a workbook. */
const UNIT: Record<SourceFormat, { one: string; many: string }> = {
  pdf: { one: 'page', many: 'pages' },
  html: { one: 'page', many: 'pages' },
  docx: { one: 'part', many: 'parts' },
  xlsx: { one: 'sheet', many: 'sheets' },
  csv: { one: 'table', many: 'tables' },
  markdown: { one: 'part', many: 'parts' },
  text: { one: 'part', many: 'parts' },
}

const FORMAT_LABEL: Record<SourceFormat, string> = {
  pdf: 'PDF',
  html: 'HTML',
  docx: 'Word',
  xlsx: 'Excel',
  csv: 'CSV',
  markdown: 'Markdown',
  text: 'Text',
}

const STATE: Record<
  IndexState,
  { icon: JSX.Element; label: string; className: string; hint: string }
> = {
  ready: {
    icon: <Check className="h-3 w-3" />,
    label: 'ready',
    className: 'text-verified',
    hint: 'Indexed and searchable.',
  },
  building: {
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    label: 'indexing',
    className: 'text-building',
    hint: 'Being parsed and embedded right now.',
  },
  stale: {
    icon: <RefreshCw className="h-3 w-3" />,
    label: 'stale',
    className: 'text-declined',
    hint: 'Built with different settings. Re-add it to rebuild.',
  },
  failed: {
    icon: <AlertTriangle className="h-3 w-3" />,
    label: 'failed',
    className: 'text-failed',
    hint: 'The last attempt failed.',
  },
  missing: {
    icon: <CircleDashed className="h-3 w-3" />,
    label: 'queued',
    className: 'text-ink-subtle',
    hint: 'Uploaded, waiting to be indexed.',
  },
}

/**
 * One document inside a folder.
 *
 * The size column counts what the document actually has — 160 pages for a PDF,
 * 4 sheets for a workbook — rather than calling everything a page. A workbook
 * does not have four pages, and a row that claims it does teaches the analyst
 * to expect a page number the citation will never give them.
 */
export function DocumentRow({
  document,
  job,
  onRemove,
}: {
  document: CollectionDocumentInfo
  job?: IndexingJob | null
  onRemove: () => void
}) {
  const state = STATE[document.state]
  const format = document.source_format
  const unit = format ? UNIT[format] : { one: 'segment', many: 'segments' }
  const count = document.segment_count

  return (
    <div className="flex items-center gap-3 bg-surface px-3 py-2.5">
      <Tooltip label={state.hint}>
        <span className={cn('flex shrink-0 items-center gap-1.5 text-2xs', state.className)}>
          {state.icon}
          {state.label}
        </span>
      </Tooltip>

      <span className="min-w-0 flex-1">
        <span className="block truncate font-mono text-[13px] text-ink">{document.doc_name}</span>
        {document.state === 'failed' && job?.error && (
          <span className="mt-0.5 block truncate font-mono text-2xs text-failed" title={job.error}>
            {job.error}
          </span>
        )}
      </span>

      {format && (
        <span className="shrink-0 rounded border border-line px-1.5 py-0.5 text-2xs text-ink-muted">
          {FORMAT_LABEL[format]}
        </span>
      )}

      <span className="tabular w-20 shrink-0 text-right font-mono text-2xs text-ink-subtle">
        {count == null ? '—' : `${count} ${count === 1 ? unit.one : unit.many}`}
      </span>

      <Button
        variant="ghost"
        size="sm"
        onClick={onRemove}
        aria-label={`Remove ${document.doc_name} from this folder`}
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}
