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
  className,
}: {
  label: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom'
  className?: string
}) {
  return (
    <span className={cn('group/tt relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap',
          'rounded-md border border-line bg-surface-raised px-2 py-1 text-2xs text-ink shadow-panel',
          'opacity-0 transition-opacity duration-150 group-hover/tt:opacity-100 group-focus-within/tt:opacity-100',
          side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
        )}
      >
        {label}
      </span>
    </span>
  )
}
