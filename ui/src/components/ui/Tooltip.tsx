import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/**
 * CSS-only tooltip. No portal, no positioning library: everything it labels is
 * inline and short, and a dependency here would earn nothing.
 */
export function Tooltip({
  label,
  children,
  side = 'top',
  align = 'center',
  className,
  contentClassName,
}: {
  label: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom'
  /**
   * Where the bubble sits horizontally. `end` right-aligns it, for a trigger
   * near the right edge where a centred bubble would run off the viewport.
   */
  align?: 'center' | 'end'
  className?: string
  /**
   * Restyles the bubble, for a tooltip carrying a small panel rather than a
   * line of text — the default is `whitespace-nowrap`, which a table cannot
   * live inside.
   */
  contentClassName?: string
}) {
  return (
    <span className={cn('group/tt relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-50 whitespace-nowrap',
          'rounded-md border border-line bg-surface-raised px-2 py-1 text-2xs text-ink shadow-panel',
          'opacity-0 transition-opacity duration-150 group-hover/tt:opacity-100 group-focus-within/tt:opacity-100',
          side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
          align === 'end' ? 'right-0' : 'left-1/2 -translate-x-1/2',
          contentClassName,
        )}
      >
        {label}
      </span>
    </span>
  )
}
