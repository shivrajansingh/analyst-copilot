import { Check, ShieldCheck } from 'lucide-react'

/**
 * What the verifier actually checked.
 *
 * This is the trust surface. Claiming an answer is "verified" without showing
 * what that meant asks for faith; listing the checks lets an analyst decide
 * whether the guarantee is the one they needed.
 */
const CHECKS = [
  {
    label: 'Every figure traces to the cited page',
    detail: 'compared by significant digits, so a filing in millions supports an answer in billions',
  },
  {
    label: 'The quoted snippet appears there',
    detail: 'the evidence text was matched against the page, not paraphrased',
  },
  {
    label: 'The citation points where the evidence is',
    detail:
      'the page the model named is a hint; the citation follows the page that actually carries the proof',
  },
]

export function VerificationStrip({
  derived = false,
  mode = 'fast',
}: {
  /** A computed figure is proven through its inputs, not by appearing on a page. */
  derived?: boolean
  mode?: 'conversational' | 'fast' | 'deep'
}) {
  const checks = [
    derived
      ? {
          label: 'Every input traces to the page it was read from',
          detail:
            'the answer is computed, so its inputs were checked instead of the result, and the arithmetic was re-run exactly',
        }
      : CHECKS[0],
    CHECKS[1],
    CHECKS[2],
    ...(mode === 'deep'
      ? [
          {
            label: 'Every page of the filing was read',
            detail:
              'the first pass could not prove an answer, so no page was left to a retrieval ranking',
          },
        ]
      : []),
  ]

  return (
    <section className="border-t border-line px-4 py-4">
      <h3 className="mb-3 flex items-center gap-2 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
        <ShieldCheck className="h-3.5 w-3.5 text-verified" />
        Verification
      </h3>
      <ul className="space-y-2.5">
        {checks.map((check) => (
          <li key={check.label} className="flex gap-2.5">
            <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-verified-soft">
              <Check className="h-2.5 w-2.5 text-verified" />
            </span>
            <span className="min-w-0">
              <span className="block text-xs font-medium text-ink">{check.label}</span>
              <span className="block text-2xs leading-relaxed text-ink-subtle">{check.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
