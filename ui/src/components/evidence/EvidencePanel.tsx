import { useState } from 'react'
import { FileSearch } from 'lucide-react'
import type { ChatResponse, RetrievedPage } from '@/api/types'
import { EmptyState } from '@/components/ui/EmptyState'
import { CitedPage } from './CitedPage'
import { PageViewerModal } from './PageViewerModal'
import { RetrievalTrace } from './RetrievalTrace'
import { VerificationStrip } from './VerificationStrip'

/**
 * The evidence rail.
 *
 * Three stacked sections, escalating in scepticism: the exact quoted snippet
 * (expandable to the whole page), then why that page was chosen over the
 * others, then what the verifier checked before the answer reached the screen.
 * Any listed page can be opened and read.
 */
export function EvidencePanel({ result }: { result: ChatResponse | null }) {
  const [openHit, setOpenHit] = useState<RetrievedPage | null>(null)

  if (!result) {
    return (
      <EmptyState
        icon={<FileSearch className="h-5 w-5" />}
        title="No evidence yet"
        description="Ask a question and the page it came from will appear here, with the retrieval scores behind it."
      />
    )
  }

  const citedHit = result.retrieval.find((hit) => hit.cited) ?? null

  return (
    <>
      {result.collection && (
        <p className="border-b border-line px-4 py-2 text-2xs text-ink-subtle">
          Searched {result.searched_documents} document
          {result.searched_documents === 1 ? '' : 's'} in{' '}
          <span className="text-ink-muted">{result.collection}</span>
        </p>
      )}
      {result.found && result.evidence ? (
        <div className="animate-fade-up">
          <CitedPage
            evidence={result.evidence}
            collection={result.collection}
            onOpenFull={citedHit ? () => setOpenHit(citedHit) : undefined}
          />
          <RetrievalTrace retrieval={result.retrieval} onOpenPage={setOpenHit} />
          <VerificationStrip />
        </div>
      ) : (
        <div className="animate-fade-up">
          <section className="px-4 py-4">
            <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
              Nothing citable
            </h3>
            <p className="text-xs leading-relaxed text-ink-muted">
              The system declined rather than answer from evidence it could not prove. Open any
              page below to see what it searched.
            </p>
          </section>
          <RetrievalTrace retrieval={result.retrieval} onOpenPage={setOpenHit} />
        </div>
      )}

      <PageViewerModal
        docName={openHit ? openHit.doc_name || result.doc_name : null}
        collection={result.collection}
        hit={openHit}
        snippet={result.evidence?.snippet}
        onClose={() => setOpenHit(null)}
      />
    </>
  )
}
