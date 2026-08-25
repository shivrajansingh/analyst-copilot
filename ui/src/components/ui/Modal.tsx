import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'

/**
 * A centred dialog. Closes on Escape or backdrop click, locks body scroll and
 * traps nothing — the content is read-only, so a focus trap would add
 * complexity without changing what a keyboard user can do.
 */
export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  className,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
  className?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          'relative flex max-h-[86vh] w-full max-w-3xl flex-col overflow-hidden',
          'rounded-2xl border border-line bg-surface shadow-panel animate-fade-up',
          className,
        )}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
            {subtitle && <div className="mt-1 text-xs text-ink-muted">{subtitle}</div>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-lg p-1.5 text-ink-subtle transition-colors hover:bg-surface-raised hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto">{children}</div>

        {footer && (
          <footer className="shrink-0 border-t border-line px-5 py-3">{footer}</footer>
        )}
      </div>
    </div>
  )
}
