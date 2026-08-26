import { FileText } from 'lucide-react'
import { cn } from '@/lib/cn'

/**
 * The inline citation. Monospace, because it names a document and a place and
 * both are read as identifiers rather than prose.
 *
 * `label` comes from the API rather than being formatted here: a workbook
 * citation reads "sheet 'Q4 Revenue'" and a CSV one reads "rows 402-601".
 * Writing `p.{n}` locally would put a page number on a document that has none.
 */
export function CitationChip({
  docName,
  label,
  onClick,
  active,
}: {
  docName: string
  label: string
  onClick?: () => void
  active?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'group inline-flex items-center gap-1.5 rounded-lg border px-2 py-1',
        'font-mono text-xs transition-all duration-150',
        active
          ? 'border-accent/40 bg-accent-soft text-accent'
          : 'border-line bg-surface-sunken text-ink-muted hover:border-accent/40 hover:bg-accent-soft hover:text-accent',
      )}
    >
      <FileText className="h-3 w-3" />
      <span className="truncate">{docName}</span>
      <span className="text-ink-subtle group-hover:text-accent/70">·</span>
      <span className="tabular truncate font-semibold">{label}</span>
    </button>
  )
}
