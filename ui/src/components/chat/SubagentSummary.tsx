import { useMemo, useState } from 'react'
import { ChevronRight, Users } from 'lucide-react'
import type { AgentStatus, TraceEvent } from '@/api/types'
import { cn } from '@/lib/cn'

/**
 * How many readers are working, and how they finished. Collapsed by default.
 *
 * A reader's status is its actual outcome, not an estimate: `found` means it
 * reported evidence, `partial` that it handed over figures it could not finish
 * with, `empty` that it read its pages and there was nothing there. Most readers
 * end `empty` on any given question and that is the honest, expected result.
 *
 * Note what these colours are *not*: `verified` is reserved for something the
 * system proved, and a reader reporting evidence is not proof — the verifier has
 * not run yet. So activity is drawn in the accent and in ink, and only a genuine
 * failure gets the failure colour.
 */
const ORDER: AgentStatus[] = ['running', 'found', 'partial', 'empty', 'failed']

const LABELS: Record<AgentStatus, string> = {
  running: 'working',
  found: 'found evidence',
  partial: 'part of it',
  empty: 'nothing there',
  failed: 'failed',
}

const DOT: Record<AgentStatus, string> = {
  running: 'bg-accent animate-breathe',
  found: 'bg-accent',
  partial: 'bg-accent/50',
  empty: 'bg-line-strong',
  failed: 'bg-failed',
}

export function SubagentSummary({ traces }: { traces: TraceEvent[] }) {
  const [open, setOpen] = useState(false)

  // Last status per agent wins: an agent goes `running` then reaches an outcome.
  const agents = useMemo(() => {
    const latest = new Map<string, AgentStatus>()
    for (const trace of traces) {
      if (trace.kind === 'agent' && trace.agent && trace.status) {
        latest.set(trace.agent, trace.status)
      }
    }
    return [...latest.entries()].sort((a, b) => collate(a[0], b[0]))
  }, [traces])

  if (agents.length === 0) return null

  const counts = ORDER.map((status) => ({
    status,
    count: agents.filter(([, value]) => value === status).length,
  })).filter((entry) => entry.count > 0)

  return (
    <div className="rounded-lg border border-line bg-surface-sunken/60">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-ink-subtle transition-transform',
            open && 'rotate-90',
          )}
          aria-hidden
        />
        <Users className="h-3.5 w-3.5 shrink-0 text-ink-subtle" aria-hidden />
        <span className="tabular text-2xs font-medium text-ink-muted">
          {agents.length} agent{agents.length === 1 ? '' : 's'}
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
          {counts.map((entry) => (
            <span key={entry.status} className="flex items-center gap-1 text-2xs text-ink-subtle">
              <span className={cn('h-1.5 w-1.5 rounded-full', DOT[entry.status])} aria-hidden />
              <span className="tabular">{entry.count}</span>
              <span>{LABELS[entry.status]}</span>
            </span>
          ))}
        </span>
      </button>

      {open && (
        <ul className="grid gap-1 border-t border-line px-3 py-2.5 sm:grid-cols-2">
          {agents.map(([name, status]) => (
            <li key={name} className="flex items-center gap-1.5 text-2xs">
              <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', DOT[status])} aria-hidden />
              <span className="min-w-0 truncate font-mono text-ink-muted">{name}</span>
              <span className="ml-auto shrink-0 text-ink-subtle">{LABELS[status]}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** "reader 2" before "reader 10", and named agents last. */
function collate(left: string, right: string): number {
  const parse = (value: string) => {
    const match = /^(\D+)(\d+)$/.exec(value)
    return match ? { prefix: match[1], index: Number(match[2]) } : { prefix: '￿', index: 0 }
  }
  const a = parse(left)
  const b = parse(right)
  return a.prefix === b.prefix ? a.index - b.index : a.prefix.localeCompare(b.prefix)
}
