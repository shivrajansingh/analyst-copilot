import { useEffect, useState } from 'react'
import { Layers, Search, ShieldCheck, Sparkles } from 'lucide-react'
import type { StageEvent, TraceEvent } from '@/api/types'
import { SubagentSummary } from './SubagentSummary'
import { ThinkingTrail } from './ThinkingTrail'
import { cn } from '@/lib/cn'

/**
 * What the system is doing, while it does it.
 *
 * The answer itself is never streamed. Verification runs after the model
 * replies, so streaming tokens would put an unproven figure on screen — the one
 * thing this product must never do. What streams is *progress*, which is what
 * makes a sixty-second wait legible: reading a whole 10-K takes a minute, and a
 * minute of silence reads as a hang.
 *
 * With no live events (the non-streaming endpoint) it falls back to a timed
 * animation of the same stages, so the component works either way.
 */
const FALLBACK: { stage: StageEvent['stage']; detail: string; at: number }[] = [
  { stage: 'planning', detail: 'working out what this needs', at: 0 },
  { stage: 'retrieving', detail: 'searching the filing', at: 700 },
  { stage: 'reading', detail: 'reading the excerpts', at: 1800 },
  { stage: 'validating', detail: 'checking the answer', at: 5200 },
]

const LABELS: Record<StageEvent['stage'], string> = {
  planning: 'Working out what this needs',
  decomposing: 'Separating the questions',
  retrieving: 'Searching the filing',
  reading: 'Reading the excerpts',
  validating: 'Checking the answer',
  escalating: 'Not proven yet — reading the whole filing',
  deep_search: 'Reading every page',
  synthesizing: 'Weighing what was found',
  verifying: 'Verifying the evidence',
  done: 'Done',
}

const ICONS: Partial<Record<StageEvent['stage'], typeof Search>> = {
  retrieving: Search,
  deep_search: Layers,
  escalating: Layers,
  synthesizing: Sparkles,
  validating: ShieldCheck,
  verifying: ShieldCheck,
}

export function ThinkingIndicator({
  stage,
  traces = [],
}: {
  stage?: StageEvent | null
  /** The live activity underneath the milestone. Both panels self-hide when empty. */
  traces?: TraceEvent[]
}) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = Date.now()
    const timer = window.setInterval(() => setElapsed(Date.now() - started), 200)
    return () => window.clearInterval(timer)
  }, [])

  const fallback = FALLBACK.reduce((active, item) => (elapsed >= item.at ? item : active), FALLBACK[0])
  const current = stage?.stage ?? fallback.stage
  const detail = stage?.detail ?? fallback.detail
  const Icon = ICONS[current]

  // Only the fan-out has a denominator worth showing. "12 of 31 readers" is
  // real progress; a spinner is not.
  const showBar = stage?.total != null && stage.total > 1 && stage.done != null
  const percent = showBar ? Math.round((stage!.done! / stage!.total!) * 100) : 0

  return (
    <div
      className="rounded-xl border border-line bg-surface px-4 py-3 animate-fade-up"
      aria-live="polite"
      aria-label={LABELS[current]}
    >
      <div className="flex items-center gap-3">
        {Icon ? (
          <Icon className="h-4 w-4 shrink-0 animate-breathe text-accent" aria-hidden />
        ) : (
          <span className="flex gap-1" aria-hidden>
            {[0, 1, 2].map((dot) => (
              <span
                key={dot}
                className="h-1.5 w-1.5 rounded-full bg-accent animate-breathe"
                style={{ animationDelay: `${dot * 180}ms` }}
              />
            ))}
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-medium text-ink">{LABELS[current]}</span>
          {detail && <span className="block truncate text-2xs text-ink-muted">{detail}</span>}
        </span>
        {stage?.part_total != null && stage.part_total > 1 && (
          <span className="tabular shrink-0 rounded-full bg-surface-sunken px-2 py-0.5 font-mono text-2xs text-ink-muted">
            question {stage.part}/{stage.part_total}
          </span>
        )}
        {showBar && (
          <span className="tabular shrink-0 font-mono text-2xs text-ink-muted">
            {stage!.done}/{stage!.total}
          </span>
        )}
      </div>

      {showBar && (
        <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-surface-sunken">
          <div
            className={cn('h-full rounded-full bg-accent transition-[width] duration-300')}
            style={{ width: `${percent}%` }}
          />
        </div>
      )}

      {traces.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <SubagentSummary traces={traces} />
          <ThinkingTrail traces={traces} />
        </div>
      )}
    </div>
  )
}
