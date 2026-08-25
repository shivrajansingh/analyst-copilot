import { FileSearch, Quote } from 'lucide-react'
import type { ChatResponse } from '@/api/types'
import { EmptyState } from '@/components/ui/EmptyState'
import { Badge } from '@/components/ui/Badge'
import { RetrievalTrace } from './RetrievalTrace'
import { VerificationStrip } from './VerificationStrip'

/**
 * The evidence rail.
 *
 * Three stacked sections, escalating in scepticism: the exact quoted snippet,
 * then why that page was chosen over the others, then what the verifier
 * checked before the answer was allowed on screen.
 */
export function EvidencePanel({ result }: { result: ChatResponse | null }) {
  if (!result) {
    return (
      <EmptyState
        icon={<FileSearch className="h-5 w-5" />}
        title="No evidence yet"
        description="Ask a question and the page it came from will appear here, with the retrieval scores behind it."
      />
    )
  }

  if (!result.found) {
    return (
      <div className="animate-fade-up">
        <section className="px-4 py-4">
          <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
            Nothing citable
          </h3>
          <p className="text-xs leading-relaxed text-ink-muted">
            The system declined rather than answer from evidence it could not prove. The
            pages it searched are listed below.
          </p>
        </section>
        <RetrievalTrace retrieval={result.retrieval} />
      </div>
    )
  }

  const evidence = result.evidence!

  return (
    <div className="animate-fade-up">
      <section className="px-4 py-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="text-2xs font-semibold uppercase tracking-wider text-ink-muted">
            Cited page
          </h3>
          <Badge tone="accent">page {evidence.display_page}</Badge>
        </div>

        <p className="mb-2.5 truncate font-mono text-xs text-ink-muted">{evidence.doc_name}</p>

        {/* The snippet is the proof. It gets its own surface, an accent rule and
            a generous line-height, because it is read closely rather than skimmed. */}
        <blockquote className="relative rounded-lg border border-line bg-surface-sunken p-3.5">
          <Quote className="absolute right-2.5 top-2.5 h-3.5 w-3.5 text-line-strong" aria-hidden />
          <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-accent" aria-hidden />
          <p className="pl-2.5 font-mono text-[13px] leading-[1.75] text-ink">
            {evidence.snippet}
          </p>
        </blockquote>
      </section>

      <RetrievalTrace retrieval={result.retrieval} />
      <VerificationStrip />
    </div>
  )
}
