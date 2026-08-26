import { Link } from 'react-router-dom'
import { FileText } from 'lucide-react'
import type { FilingSummary } from '@/api/types'
import { IndexBadge } from './IndexBadge'

/**
 * The top-level document inventory.
 *
 * These are documents indexed outside any folder — by `scripts/index_all.py`,
 * mostly. Questions are asked of folders, so there is no "Ask" action here:
 * add the document to a folder and ask there. Showing a button that leads to a
 * scope chat no longer accepts would be worse than showing none.
 */
export function FilingTable({ filings }: { filings: FilingSummary[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Filings and the state of each retrieval index</caption>
        <thead>
          <tr className="border-b border-line bg-surface-sunken/60 text-left">
            <th scope="col" className="px-4 py-2.5 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
              Filing
            </th>
            <th scope="col" className="px-4 py-2.5 text-right text-2xs font-semibold uppercase tracking-wider text-ink-muted">
              Pages
            </th>
            <th scope="col" className="px-4 py-2.5 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
              BM25
            </th>
            <th scope="col" className="px-4 py-2.5 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
              Embeddings
            </th>
          </tr>
        </thead>
        <tbody>
          {filings.map((filing) => {
            return (
              <tr
                key={filing.doc_name}
                className="border-b border-line/60 transition-colors last:border-0 hover:bg-surface-raised/60"
              >
                <td className="px-4 py-3">
                  <Link
                    to={`/filings/${encodeURIComponent(filing.doc_name)}`}
                    className="flex items-center gap-2.5 font-mono text-[13px] text-ink hover:text-accent"
                  >
                    <FileText className="h-3.5 w-3.5 shrink-0 text-ink-subtle" />
                    <span className="truncate">{filing.doc_name}</span>
                  </Link>
                </td>
                <td className="tabular px-4 py-3 text-right font-mono text-xs text-ink-muted">
                  {filing.page_count ?? '—'}
                </td>
                <td className="px-4 py-3">
                  <IndexBadge kind="BM25" info={filing.bm25} />
                </td>
                <td className="px-4 py-3">
                  <IndexBadge kind="Embeddings" info={filing.vector} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
