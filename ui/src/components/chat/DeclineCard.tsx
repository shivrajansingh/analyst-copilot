import { Ban, Layers } from 'lucide-react'
import type { ChatResponse } from '@/api/types'

/**
 * A decline.
 *
 * Calm and deliberate, not an error: under the rubric a decline is a correct
 * outcome and a guess is worse than silence. What makes it read as diligence
 * rather than a shrug is showing the work — which pages were searched, and when
 * the deep path ran, that every page of the filing was read and still did not
 * contain the answer. That is a much stronger statement than "no match", and it
 * is the one an analyst needs before going to look themselves.
 */
const REASONS: Record<string, string> = {
  model_abstain: 'The retrieved excerpts were judged insufficient.',
  number_not_on_page: 'A figure in the draft answer could not be traced back to the cited page.',
  page_not_in_retrieval: 'The model cited a page it had not been shown.',
  snippet_not_on_page: 'The quoted evidence was not found on the cited page.',
  no_retrieval_hits: 'No page in this filing matched the question.',
  evidence_not_on_any_page: 'No retrieved page carried evidence for the answer.',
  evidence_too_far_from_citation:
    'The only supporting figures were far from the cited page — a coincidence, not evidence.',
  deep_search_found_nothing: 'Every page was read, and none of them answered the question.',
  no_indexed_documents: 'Nothing in this filing has finished indexing yet.',
}

function explain(reason: string | null): string | null {
  if (!reason) return null
  if (REASONS[reason]) return REASONS[reason]
  // The deep path reports why verification refused, after the colon.
  if (reason.startsWith('deep_unverified:')) {
    return `An answer was found but the filing did not support it, so it was withheld (${reason
      .slice('deep_unverified:'.length)
      .trim()}).`
  }
  return reason
}

export function DeclineCard({
  result,
  onOpenEvidence,
}: {
  result: ChatResponse
  onOpenEvidence: () => void
}) {
  const pages = result.retrieval.map((hit) => hit.display_page)
  const reason = explain(result.abstention_reason)
  const readEverything = result.mode === 'deep' && result.pages_read > 0

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

        {readEverything && (
          <p className="mt-3 flex items-start gap-1.5 text-xs leading-relaxed text-ink-muted">
            <Layers className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-subtle" aria-hidden />
            <span>
              Retrieval found nothing citable, so all{' '}
              <span className="tabular font-mono text-ink">{result.pages_read}</span> pages were
              read in full by{' '}
              <span className="tabular font-mono text-ink">{result.shards_run}</span> agents. This
              is not a search that gave up early.
            </span>
          </p>
        )}

        {pages.length > 0 && (
          <p className="mt-3 text-xs text-ink-subtle">
            {readEverything ? 'Retrieval had ranked pages' : 'Searched pages'}{' '}
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
