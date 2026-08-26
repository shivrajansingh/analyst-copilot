import { MapPin } from 'lucide-react'
import type { Evidence } from '@/api/types'

/**
 * Says so when the citation is not the place the model named.
 *
 * Verification is evidence-first: it finds which retrieved page actually
 * carries the proof and cites *that*, treating the model's page number as a
 * hint. The same document paginates differently as filed HTML and as the
 * filer's own PDF — 15 of 62 documents in the practice corpus disagree by one
 * or two pages — so moving a citation onto the page bearing the evidence is
 * normal and correct.
 *
 * It is still disclosed. An analyst who sees the answer cite page 60 while the
 * reasoning said 61 has to be able to find out why in one glance, or the
 * discrepancy reads as a bug.
 *
 * Deliberately styled as a note, not a warning: nothing has gone wrong here.
 */
export function LocationNote({ evidence }: { evidence: Evidence }) {
  const message = describe(evidence)
  if (!message) return null

  return (
    <p className="mt-2 flex items-start gap-1.5 text-2xs leading-relaxed text-ink-muted">
      <MapPin className="mt-0.5 h-3 w-3 shrink-0 text-ink-subtle" aria-hidden />
      <span>{message}</span>
    </p>
  )
}

function describe(evidence: Evidence): string | null {
  const here = evidence.label || `page ${evidence.display_page}`
  const named = evidence.model_cited_page

  switch (evidence.location_match) {
    case 'exact':
      return null
    case 'inferred':
      return `Location inferred from the evidence — the model did not name one. Verified on ${here}.`
    case 'adjusted':
      return named == null
        ? `Located on ${here}, ${plural(evidence.page_shift)} from the page the model named.`
        : `Located on ${here}; the model cited page ${named + 1}. Two readings of the same document paginate a little differently.`
    case 'relocated':
      return named == null
        ? `The quoted evidence was found on ${here}, so the citation points there.`
        : `The model cited page ${named + 1}, but the quoted evidence appears word for word on ${here}, so the citation points there.`
    default:
      return null
  }
}

function plural(shift: number): string {
  return shift === 1 ? 'one page' : `${shift} pages`
}
