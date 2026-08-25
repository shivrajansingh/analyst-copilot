import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

type Tone = 'neutral' | 'accent' | 'verified' | 'declined' | 'failed' | 'building'

const TONES: Record<Tone, string> = {
  neutral: 'bg-surface-sunken text-ink-muted border-line',
  accent: 'bg-accent-soft text-accent border-accent/25',
  verified: 'bg-verified-soft text-verified border-verified/25',
  declined: 'bg-declined-soft text-declined border-declined/25',
  failed: 'bg-failed-soft text-failed border-failed/25',
  building: 'bg-building-soft text-building border-building/25',
}

export function Badge({
  tone = 'neutral',
  children,
  className,
  icon,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
  icon?: ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5',
        'text-2xs font-medium uppercase tracking-wide',
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  )
}
