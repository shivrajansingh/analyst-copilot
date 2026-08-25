import { FileText } from 'lucide-react'
import { cn } from '@/lib/cn'

/**
 * The inline citation. Monospace, because it names a document and a page and
 * both are read as identifiers rather than prose.
 */
export function CitationChip({
  docName,
  displayPage,
  onClick,
  active,
}: {
  docName: string
  displayPage: number
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
      <span className="tabular font-semibold">p.{displayPage}</span>
    </button>
  )
}
