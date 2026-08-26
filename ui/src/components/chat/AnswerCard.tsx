import { ShieldCheck } from 'lucide-react'
import type { ChatResponse } from '@/api/types'
import { CitationChip } from '@/components/evidence/CitationChip'

/**
 * A proven answer.
 *
 * Its own surface with an accent rule, so what the filing says is visually
 * separate from anything around it. Figures render in monospace with tabular
 * numerals — misreading 1,577 as 1.577 is the exact error this product exists
 * to prevent.
 */
export function AnswerCard({
  result,
  onOpenEvidence,
  active,
}: {
  result: ChatResponse
  onOpenEvidence: () => void
  active?: boolean
}) {
  return (
    <article className="relative overflow-hidden rounded-xl border border-line bg-surface shadow-card animate-fade-up">
      <span className="absolute inset-y-0 left-0 w-[3px] bg-verified" aria-hidden />

      <header className="flex items-center justify-between gap-3 border-b border-line/70 py-2 pl-5 pr-3">
        <span className="text-2xs font-semibold uppercase tracking-wider text-ink-muted">
          Answer
        </span>
        <span className="inline-flex items-center gap-1.5 text-2xs font-medium uppercase tracking-wide text-verified">
          <ShieldCheck className="h-3.5 w-3.5" />
          verified
        </span>
      </header>

      <div className="py-4 pl-5 pr-4">
        <p className="tabular whitespace-pre-wrap font-mono text-[15px] leading-relaxed text-ink">
          {result.answer}
        </p>

        {result.evidence && (
          <div className="mt-4">
            <CitationChip
              docName={result.evidence.doc_name}
              label={result.evidence.label || `p.${result.evidence.display_page}`}
              onClick={onOpenEvidence}
              active={active}
            />
          </div>
        )}
      </div>
    </article>
  )
}
