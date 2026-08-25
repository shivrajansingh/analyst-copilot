import { Ban } from 'lucide-react'
import type { ChatResponse } from '@/api/types'

const REASONS: Record<string, string> = {
  model_abstain: 'The model judged the retrieved excerpts insufficient.',
  number_not_on_page: 'A figure in the draft answer could not be traced back to the cited page.',
  page_not_in_retrieval: 'The model cited a page it had not been shown.',
  snippet_not_on_page: 'The quoted evidence was not found on the cited page.',
  no_retrieval_hits: 'No page in this filing matched the question.',
}

/**
 * A decline.
 *
 * Calm and deliberate, not an error: under the rubric, declining is a correct
 * outcome and a guess is worse than silence. Showing *which pages were
 * searched* is what makes it read as diligence rather than as a shrug.
 */
export function DeclineCard({
  result,
  onOpenEvidence,
}: {
  result: ChatResponse
  onOpenEvidence: () => void
}) {
  const pages = result.retrieval.map((hit) => hit.display_page)
  const reason = result.abstention_reason
    ? (REASONS[result.abstention_reason] ?? result.abstention_reason)
    : null

  return (
    <article className="relative overflow-hidden rounded-xl border border-declined/30 bg-declined-soft/40 animate-fade-up">
      <span className="absolute inset-y-0 left-0 w-[3px] bg-declined" aria-hidden />

      <div className="py-4 pl-5 pr-4">
        <div className="flex items-center gap-2">
          <Ban className="h-4 w-4 text-declined" />
          <h3 className="text-sm font-semibold text-ink">Not found in this filing</h3>
        </div>

        <p className="mt-2 text-sm leading-relaxed text-ink-muted">
          The evidence for this question is not in{' '}
          <span className="font-mono text-[13px] text-ink">{result.doc_name}</span>, or it is
          not strong enough to cite. No figure is shown, because none could be proved.
        </p>

        {pages.length > 0 && (
          <p className="mt-3 text-xs text-ink-subtle">
            Searched pages{' '}
            <button
              onClick={onOpenEvidence}
              className="tabular font-mono text-ink-muted underline decoration-dotted underline-offset-2 hover:text-accent"
            >
              {pages.join(', ')}
            </button>
          </p>
        )}
        {reason && <p className="mt-1 text-xs text-ink-subtle">Reason: {reason}</p>}
      </div>
    </article>
  )
}
