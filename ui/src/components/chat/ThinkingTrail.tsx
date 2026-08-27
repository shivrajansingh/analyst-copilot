import { useEffect, useRef, useState } from 'react'
import { ChevronRight, Wrench } from 'lucide-react'
import type { TraceEvent } from '@/api/types'
import { cn } from '@/lib/cn'

/**
 * What the agents actually said and did, collapsed by default.
 *
 * Every line is real: a `thought` is text the model wrote of its own accord
 * before calling a tool, and a `tool` is a call that happened. Nothing is
 * synthesised to fill a quiet moment — a run with little to say shows few lines,
 * because a progress display that invents activity is worse than one that admits
 * there is none.
 *
 * Tool arguments and results are not shown, and not sent: a tool result is
 * document text that has not been through the verifier yet.
 */
const TOOL_LABELS: Record<string, string> = {
  list_pages: 'listing pages',
  search_document: 'searching',
  read_page: 'reading a page',
  read_lines: 'reading lines',
  calculate: 'calculating',
}

export function ThinkingTrail({
  traces,
  defaultOpen = false,
}: {
  traces: TraceEvent[]
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const steps = traces.filter((trace) => trace.kind !== 'agent')
  const bottomRef = useRef<HTMLDivElement>(null)

  // Follow the tail while it is growing, so an open panel shows the newest step
  // rather than stranding the reader at the top of a list that keeps extending.
  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ block: 'nearest' })
  }, [open, steps.length])

  if (steps.length === 0) return null

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
        <span className="text-2xs font-medium uppercase tracking-wide text-ink-muted">
          Thinking
        </span>
        <span className="tabular font-mono text-2xs text-ink-subtle">
          {steps.length} step{steps.length === 1 ? '' : 's'}
        </span>
      </button>

      {open && (
        <ul className="scrollbar-slim max-h-64 space-y-1.5 overflow-y-auto border-t border-line px-3 py-2.5">
          {steps.map((step, index) => (
            <li key={index} className="flex gap-2 text-2xs leading-relaxed">
              {step.agent && (
                <span className="shrink-0 font-mono text-ink-subtle">{step.agent}</span>
              )}
              {step.kind === 'tool' ? (
                <span className="flex min-w-0 items-center gap-1 text-ink-muted">
                  <Wrench className="h-3 w-3 shrink-0 text-ink-subtle" aria-hidden />
                  <span className="font-mono">{TOOL_LABELS[step.tool ?? ''] ?? step.tool}</span>
                </span>
              ) : (
                <span className="min-w-0 text-ink-muted">{step.text}</span>
              )}
            </li>
          ))}
          <div ref={bottomRef} />
        </ul>
      )}
    </div>
  )
}
