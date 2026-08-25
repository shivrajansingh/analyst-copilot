import { useEffect, useState } from 'react'
import { cn } from '@/lib/cn'

/**
 * The answer is not streamed.
 *
 * Verification runs after the model replies, so streaming tokens would put an
 * unproven figure on screen — the one thing this product must never do. The
 * stages below are the real pipeline, shown so the wait reads as work rather
 * than as a hang.
 */
const STAGES = [
  { label: 'Retrieving pages', at: 0 },
  { label: 'Reading excerpts', at: 1800 },
  { label: 'Verifying the citation', at: 5200 },
]

export function ThinkingIndicator() {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = Date.now()
    const timer = window.setInterval(() => setElapsed(Date.now() - started), 200)
    return () => window.clearInterval(timer)
  }, [])

  const activeIndex = STAGES.reduce(
    (active, stage, index) => (elapsed >= stage.at ? index : active),
    0,
  )

  return (
    <div
      className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 animate-fade-up"
      aria-live="polite"
      aria-label={STAGES[activeIndex].label}
    >
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((dot) => (
          <span
            key={dot}
            className="h-1.5 w-1.5 rounded-full bg-accent animate-breathe"
            style={{ animationDelay: `${dot * 180}ms` }}
          />
        ))}
      </span>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {STAGES.map((stage, index) => (
          <span
            key={stage.label}
            className={cn(
              'text-2xs uppercase tracking-wide transition-colors duration-300',
              index < activeIndex && 'text-ink-subtle',
              index === activeIndex && 'font-semibold text-ink',
              index > activeIndex && 'text-ink-subtle/40',
            )}
          >
            {stage.label}
          </span>
        ))}
      </div>
    </div>
  )
}
