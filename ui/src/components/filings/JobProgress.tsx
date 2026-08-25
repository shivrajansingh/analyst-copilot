import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import type { IndexingJob, JobStatus } from '@/api/types'
import { cn } from '@/lib/cn'
import { formatDuration } from '@/lib/format'

const PHASES: { key: JobStatus; label: string }[] = [
  { key: 'queued', label: 'Queued' },
  { key: 'parsing', label: 'Parsing pages' },
  { key: 'embedding', label: 'Embedding' },
  { key: 'saving', label: 'Saving' },
]

/**
 * Progress against the spec's per-filing budget rather than an unbounded
 * spinner: the requirement is that a filing indexes within ten minutes, so the
 * bar has to be drawn against that number to mean anything.
 */
export function JobProgress({ job }: { job: IndexingJob }) {
  const activeIndex = PHASES.findIndex((phase) => phase.key === job.status)
  const done = job.status === 'ready'
  const failed = job.status === 'failed'
  const fraction = Math.min(1, job.elapsed_seconds / Math.max(1, job.budget_seconds))

  return (
    <div className="rounded-xl border border-line bg-surface p-4 animate-fade-up">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {done && <CheckCircle2 className="h-4 w-4 shrink-0 text-verified" />}
          {failed && <AlertTriangle className="h-4 w-4 shrink-0 text-failed" />}
          <span className="truncate font-mono text-sm font-medium text-ink">{job.doc_name}</span>
        </div>
        <span
          className={cn(
            'tabular shrink-0 font-mono text-xs',
            job.over_budget ? 'text-declined' : 'text-ink-muted',
          )}
        >
          {formatDuration(job.elapsed_seconds)} / {formatDuration(job.budget_seconds)}
        </span>
      </div>

      {!done && !failed && (
        <>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-sunken">
            <div
              className={cn(
                'h-full rounded-full transition-[width] duration-700 ease-out',
                job.over_budget ? 'bg-declined' : 'bg-building',
              )}
              style={{ width: `${Math.max(4, fraction * 100)}%` }}
            />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
            {PHASES.map((phase, index) => (
              <span
                key={phase.key}
                className={cn(
                  'flex items-center gap-1.5 text-2xs uppercase tracking-wide transition-colors',
                  index < activeIndex && 'text-ink-subtle',
                  index === activeIndex && 'font-semibold text-building',
                  index > activeIndex && 'text-ink-subtle/50',
                )}
              >
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    index < activeIndex && 'bg-verified',
                    index === activeIndex && 'animate-breathe bg-building',
                    index > activeIndex && 'bg-line-strong',
                  )}
                />
                {phase.label}
              </span>
            ))}
          </div>
        </>
      )}

      {done && (
        <p className="mt-2 text-xs text-ink-muted">
          Indexed {job.page_count} pages. Ready to answer questions.
        </p>
      )}
      {failed && <p className="mt-2 font-mono text-xs text-failed">{job.error}</p>}
      {job.over_budget && !failed && (
        <p className="mt-2 text-xs text-declined">
          Past the 10-minute budget this filing is expected to finish within.
        </p>
      )}
    </div>
  )
}
