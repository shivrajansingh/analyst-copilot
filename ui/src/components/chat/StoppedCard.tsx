import { Square } from 'lucide-react'
import type { CancelledEvent, StageEvent, TraceEvent } from '@/api/types'
import { ThinkingTrail } from './ThinkingTrail'
import { UsageStrip } from './UsageStrip'

/**
 * A run the analyst stopped.
 *
 * The line that matters is the middle one. Because this product never streams an
 * unverified answer, a stopped run has *no partial answer to show* — and saying
 * that plainly beats an empty card, which reads as a failure. What survives is
 * the trail: sixty seconds of reading stays expandable rather than being thrown
 * away because the run did not finish.
 *
 * Neutral, not red. Nothing failed here; the analyst changed their mind, and
 * colouring that as an error teaches them to read their own decision as a bug.
 *
 * What it *does* show is the spend. Tokens are not an answer — they were
 * genuinely bought whatever the run proved — and this is the moment an analyst
 * most wants the number, because they have just paid for a fan-out that proved
 * nothing.
 */
const STAGE_LABELS: Record<StageEvent['stage'], string> = {
  routing: 'Reading your message',
  decomposing: 'Separating the questions',
  retrieving: 'Searching the filing',
  reading: 'Reading the excerpts',
  validating: 'Checking the answer',
  escalating: 'Escalating to the whole filing',
  deep_search: 'Reading every page',
  synthesizing: 'Weighing what was found',
  verifying: 'Verifying the evidence',
  done: 'Finishing',
}

export function StoppedCard({
  at,
  traces = [],
  onAskAgain,
}: {
  at: CancelledEvent
  /** What the agents did before they were stopped. Kept, not discarded. */
  traces?: TraceEvent[]
  /** Refill the composer with the question. Most stops are followed by a reword. */
  onAskAgain?: () => void
}) {
  const stage = at.stage ? STAGE_LABELS[at.stage] : 'Stopped before it began'
  const progress =
    at.total !== undefined && at.done !== undefined
      ? `${at.done} of ${at.total} pages read`
      : null

  return (
    <article className="rounded-xl border border-line-strong bg-surface p-4 animate-fade-up">
      <header className="flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
        <Square className="h-3 w-3 fill-current" aria-hidden />
        Stopped
      </header>

      <p className="mt-2 text-xs leading-relaxed text-ink-muted">
        {stage}
        {progress && (
          <>
            {' · '}
            <span className="tabular font-mono text-ink">{progress}</span>
          </>
        )}
        {at.elapsed_ms > 0 && (
          <>
            {' · '}
            <span className="tabular font-mono text-ink">
              {(at.elapsed_ms / 1000).toFixed(1)}s
            </span>
          </>
        )}
      </p>

      <p className="mt-1.5 text-xs leading-relaxed text-ink-subtle">
        Nothing was verified, so nothing is shown.
      </p>

      {onAskAgain && (
        <button
          onClick={onAskAgain}
          className="mt-3 rounded-lg border border-line px-3 py-1.5 text-xs text-ink-muted transition-colors hover:border-accent/40 hover:bg-accent-soft hover:text-accent"
        >
          Ask again
        </button>
      )}

      {traces.length > 0 && (
        <div className="mt-3">
          <ThinkingTrail traces={traces} />
        </div>
      )}

      {at.usage && <UsageStrip usage={at.usage} className="mt-3" />}
    </article>
  )
}
