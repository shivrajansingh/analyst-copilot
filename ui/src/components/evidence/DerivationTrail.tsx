import { Calculator } from 'lucide-react'
import type { EvidenceInput } from '@/api/types'

/**
 * How a computed figure was arrived at.
 *
 * A margin, a ratio or a year-on-year change appears nowhere in a filing — only
 * the figures behind it do. So a derived answer is proven one level down: each
 * input is shown with the page it was read from, and the expression is the one
 * the verifier re-evaluated. Without this the analyst is asked to trust a number
 * that no page contains.
 */
export function DerivationTrail({
  computation,
  inputs,
  onOpenPage,
}: {
  computation: string
  inputs: EvidenceInput[]
  onOpenPage?: (docName: string, page: number) => void
}) {
  if (!computation && inputs.length === 0) return null

  return (
    <section className="border-t border-line px-4 py-4">
      <h3 className="mb-2.5 flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
        <Calculator className="h-3.5 w-3.5 text-verified" />
        Computed, not quoted
      </h3>
      <p className="mb-3 text-2xs leading-relaxed text-ink-subtle">
        This figure is not printed in the filing. Each input below was read off the page it
        names, and the arithmetic was re-run during verification.
      </p>

      {inputs.length > 0 && (
        <ul className="mb-3 space-y-1.5">
          {inputs.map((input, index) => (
            <li
              key={`${input.label}-${index}`}
              className="flex items-baseline justify-between gap-2 text-xs"
            >
              <span className="min-w-0 truncate text-ink-muted">{input.label}</span>
              <span className="flex shrink-0 items-baseline gap-1.5">
                <span className="tabular font-mono font-semibold text-ink">{input.value}</span>
                {input.display_page != null &&
                  (onOpenPage ? (
                    <button
                      onClick={() => onOpenPage(input.doc_name, input.page!)}
                      className="font-mono text-2xs text-ink-subtle underline decoration-dotted underline-offset-2 hover:text-accent"
                    >
                      p.{input.display_page}
                    </button>
                  ) : (
                    <span className="font-mono text-2xs text-ink-subtle">
                      p.{input.display_page}
                    </span>
                  ))}
              </span>
            </li>
          ))}
        </ul>
      )}

      {computation && (
        <code className="block overflow-x-auto scrollbar-slim rounded-lg border border-line bg-surface-sunken px-3 py-2 font-mono text-xs text-ink">
          {computation}
        </code>
      )}
    </section>
  )
}
