import { Layers, ShieldCheck } from 'lucide-react'
import type { ChatResponse, TraceEvent } from '@/api/types'
import { useRevealedText } from '@/hooks/useRevealedText'
import { SubagentSummary } from './SubagentSummary'
import { ThinkingTrail } from './ThinkingTrail'
import { UsageStrip } from './UsageStrip'
import { CitationChip } from '@/components/evidence/CitationChip'
import { Tooltip } from '@/components/ui/Tooltip'

/**
 * A proven answer.
 *
 * Its own surface with an accent rule, so what the filing says is visually
 * separate from anything around it. Figures render in monospace with tabular
 * numerals — misreading 1,577 as 1.577 is the exact error this product exists
 * to prevent.
 *
 * A compound question carries one citation per part, because one citation
 * cannot prove two claims.
 */
export function AnswerCard({
  result,
  onOpenEvidence,
  active,
  traces = [],
  reveal = false,
}: {
  result: ChatResponse
  onOpenEvidence: () => void
  active?: boolean
  /** What the agents did to produce this. Kept so it stays expandable afterwards. */
  traces?: TraceEvent[]
  /** Animate the text in. Only for an answer that just arrived, never for history. */
  reveal?: boolean
}) {
  // A reveal of already-verified text, not a stream from the model: the verifier
  // has already finished, so no unproven figure can appear even for an instant.
  const shown = useRevealedText(result.answer, reveal)
  // `citations` is authoritative; `evidence` repeats the first of them for
  // callers written against the single-answer shape.
  const citations = result.citations.length > 0
    ? result.citations
    : result.evidence
      ? [result.evidence]
      : []

  return (
    <article className="relative overflow-hidden rounded-xl border border-line bg-surface shadow-card animate-fade-up">
      <span className="absolute inset-y-0 left-0 w-[3px] bg-verified" aria-hidden />

      <header className="flex items-center justify-between gap-3 border-b border-line/70 py-2 pl-5 pr-3">
        <span className="text-2xs font-semibold uppercase tracking-wider text-ink-muted">
          Answer
        </span>
        <span className="flex items-center gap-2">
          {result.mode === 'deep' && (
            <Tooltip
              label={`The first pass could not prove an answer, so all ${result.pages_read} pages were read by ${result.shards_run} agents.`}
            >
              <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-2 py-0.5 text-2xs font-medium uppercase tracking-wide text-ink-muted">
                <Layers className="h-3 w-3" />
                full read
              </span>
            </Tooltip>
          )}
          <span className="inline-flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-verified">
            <ShieldCheck className="h-3.5 w-3.5" />
            verified
          </span>
        </span>
      </header>

      <div className="py-4 pl-5 pr-4">
        <p className="tabular whitespace-pre-wrap font-mono text-[15px] leading-relaxed text-ink">
          {shown}
          {shown.length < result.answer.length && (
            <span
              className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[0.1em] bg-accent animate-breathe"
              aria-hidden
            />
          )}
        </p>

        {citations.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5">
            {citations.map((citation, index) => (
              <CitationChip
                key={`${citation.doc_name}-${citation.page}-${index}`}
                docName={citation.doc_name}
                label={citation.label || `p.${citation.display_page}`}
                onClick={onOpenEvidence}
                active={active}
              />
            ))}
          </div>
        )}

        {traces.length > 0 && (
          <div className="mt-4 space-y-1.5 border-t border-line/70 pt-3">
            <SubagentSummary traces={traces} />
            <ThinkingTrail traces={traces} />
          </div>
        )}

        {/* Last on the card, deliberately. What the answer cost is a property
            of the answer, not a headline — and a card that opened with a price
            would put the cheapest thing on it first. */}
        {result.usage && <UsageStrip usage={result.usage} className="mt-4" />}

        {/* A part that could not be proved is stated as such rather than
            quietly dropped: a half-answered question the reader thinks was
            fully answered is worse than one they know was not. */}
        {result.parts.some((part) => !part.found) && (
          <p className="mt-3 border-t border-line/70 pt-3 text-2xs leading-relaxed text-declined">
            {result.parts.filter((part) => !part.found).length} of {result.parts.length} parts
            could not be answered from this filing.
          </p>
        )}
      </div>
    </article>
  )
}
