import { useState } from 'react'
import { ChevronRight, Coins } from 'lucide-react'
import type { StageUsage, Usage } from '@/api/types'
import { cn } from '@/lib/cn'
import { Tooltip } from '@/components/ui/Tooltip'

/**
 * What this answer cost, as a footer on the card it belongs to.
 *
 * A footer and not a sibling card: the cost is a property *of this answer*, and
 * a floating panel beside it would compete with the answer for the eye. It sits
 * last, below the citations and the agent trail, because it is the least
 * important thing on the card and a card must not open with a price.
 *
 * Two refusals are the whole design:
 *
 * - **No price is better than a wrong price.** `priced: false` means no rate is
 *   configured for the model, and the strip says so rather than falling back to
 *   a guess. This service talks to a gateway that can put any model behind any
 *   name at any margin, and an analyst acts on a number.
 * - **An estimate never looks like a measurement.** `estimated: true` means the
 *   provider omitted `usage` and the tokens were counted locally; the figures
 *   carry a `~` and say why.
 *
 * Note what colour is *not* used. `verified`, `declined`, `failed` and
 * `building` are reserved for state — the system proved, declined, errored, is
 * indexing — and a cost is none of those. Everything here is ink and accent.
 */
export function UsageStrip({ usage, className }: { usage: Usage; className?: string }) {
  const [open, setOpen] = useState(false)

  const rows = usage.stages.filter((stage) => stage.calls > 0)
  // `models` is in first-use order, and the query embedding runs before any
  // chat call — so models[0] is reliably the cheapest model in the run and
  // naming it here hid the one that did the spending. Name the model that
  // actually cost the most instead, and say how many others there were.
  const principal = usage.models.length > 1 ? dominantModel(usage) : usage.models[0]
  const others = usage.models.length - 1
  // The share bar is relative to the most expensive stage, not to the total: a
  // deep run is ~71% reader fan-out, and scaling to the total would leave every
  // other row an invisible sliver.
  const peak = Math.max(1, ...rows.map((stage) => stage.cost_usd ?? 0))
  const tilde = usage.estimated ? '~' : ''

  return (
    <div className={cn('border-t border-line/70 pt-3', className)}>
      <button
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="group flex h-5 w-full items-center gap-2 text-left"
      >
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-ink-subtle transition-transform',
            open && 'rotate-90 text-accent',
          )}
          aria-hidden
        />
        <Coins className="h-3.5 w-3.5 shrink-0 text-ink-subtle" aria-hidden />

        {usage.estimated ? (
          <Tooltip label="The provider did not report usage for one or more calls, so these tokens were counted here instead. Close, not exact.">
            <span className="tabular cursor-help border-b border-dashed border-ink-subtle/60 font-mono text-2xs text-ink-muted">
              {tilde}
              {formatTokens(usage.total_tokens)} tokens
            </span>
          </Tooltip>
        ) : (
          <span className="tabular font-mono text-2xs text-ink-muted">
            {formatTokens(usage.total_tokens)} tokens
          </span>
        )}

        <span className="text-2xs text-ink-subtle" aria-hidden>
          ·
        </span>

        {usage.priced && usage.cost_usd !== null ? (
          <span className="tabular font-mono text-2xs font-medium text-ink transition-colors group-hover:text-accent">
            {tilde}
            {formatCost(usage.cost_usd, 4)}
          </span>
        ) : (
          <Tooltip label="No price is configured for this model, so no cost is shown. Set CHAT_PRICE_INPUT and CHAT_PRICE_OUTPUT to price it.">
            <span className="cursor-help text-2xs text-ink-subtle">no price configured</span>
          </Tooltip>
        )}

        <span className="flex-1" />

        <span className="truncate font-mono text-2xs text-ink-subtle">
          {usage.calls} call{usage.calls === 1 ? '' : 's'}
          {principal && ` · ${principal}`}
          {others > 0 && ` +${others}`}
        </span>
      </button>

      {open && (
        <div className="mt-2.5 border-t border-line pt-1.5">
          <div className="grid grid-cols-[minmax(0,1fr)_2.125rem_3.625rem_3.25rem_4.625rem] items-center gap-x-2.5 text-[0.625rem] uppercase tracking-wider text-ink-subtle">
            <span>Stage · model</span>
            <span className="text-right">×</span>
            <span className="text-right">In</span>
            <span className="text-right">Out</span>
            <span className="text-right">Cost</span>
          </div>

          {rows.map((stage) => (
            <StageRow key={stage.stage} stage={stage} peak={peak} />
          ))}

          <div className="mt-1.5 grid grid-cols-[minmax(0,1fr)_2.125rem_3.625rem_3.25rem_4.625rem] items-center gap-x-2.5 border-t border-line/70 pt-1.5 text-2xs text-ink">
            <span className="font-semibold">Total</span>
            <span className="tabular text-right font-mono">{usage.calls}</span>
            <span className="tabular text-right font-mono">
              {formatTokens(usage.input_tokens)}
            </span>
            <span className="tabular text-right font-mono">
              {formatTokens(usage.output_tokens)}
            </span>
            <span className="tabular text-right font-mono font-semibold">
              {usage.priced && usage.cost_usd !== null ? formatCost(usage.cost_usd, 6) : '—'}
            </span>
          </div>

          <p className="mt-2 text-2xs leading-relaxed text-ink-subtle">{footnote(usage)}</p>
        </div>
      )}
    </div>
  )
}

/**
 * One stage.
 *
 * The row's own background is its share of the run's cost — no chart, no second
 * colour, and the fan-out that dominates a deep run is visible at a glance.
 * Costs render to six decimals here where the headline uses four: these numbers
 * are compared against each other, and `$0.0001` would collapse four distinct
 * stages into one.
 */
function StageRow({ stage, peak }: { stage: StageUsage; peak: number }) {
  const share = stage.cost_usd !== null ? Math.min(1, stage.cost_usd / peak) : 0
  // Cost is carried as integer micro-dollars, so anything cheaper than that
  // arrives here as an exact 0 — the query embedding is ~$0.00000026. Tokens
  // were spent and a rate was configured, so this is "too small to write down",
  // not "free", and `$0.000000` says the wrong one of those.
  //
  // The one case this reads wrong is a model configured at a rate of zero,
  // where the cost really is nothing. That is a deliberate setting for a model
  // you host yourself, and the operator who set it knows.
  const subMicro =
    stage.cost_usd === 0 && stage.input_tokens + stage.output_tokens > 0

  return (
    <div
      className="tabular grid h-6 grid-cols-[minmax(0,1fr)_2.125rem_3.625rem_3.25rem_4.625rem] items-center gap-x-2.5 rounded-sm bg-no-repeat text-2xs text-ink-muted"
      style={{
        backgroundImage: `linear-gradient(to right, hsl(var(--accent) / 0.10) 0 ${(
          share * 100
        ).toFixed(1)}%, transparent 0)`,
      }}
    >
      <span className="flex min-w-0 items-baseline gap-2">
        <span className="shrink-0 font-sans">{stage.label || stage.stage}</span>
        {stage.models?.length > 0 && (
          <span className="truncate font-mono text-ink-subtle/80">
            {stage.models.join(', ')}
          </span>
        )}
      </span>
      <span className="text-right font-mono text-ink-subtle">{stage.calls}</span>
      <span className="text-right font-mono text-ink-subtle">
        {formatTokens(stage.input_tokens)}
      </span>
      <span className="text-right font-mono text-ink-subtle">
        {stage.output_tokens > 0 ? formatTokens(stage.output_tokens) : '—'}
      </span>
      <span className="text-right font-mono text-ink">
        {stage.cost_usd === null ? '—' : subMicro ? '<$0.000001' : formatCost(stage.cost_usd, 6)}
      </span>
    </div>
  )
}

function footnote(usage: Usage): string {
  const parts: string[] = []
  if (!usage.priced) {
    parts.push(
      'No rate is configured for this model, so no cost is shown. Set CHAT_PRICE_INPUT and CHAT_PRICE_OUTPUT to price it.',
    )
  }
  if (usage.estimated) {
    parts.push(
      'The provider did not report usage for every call, so those tokens were counted here. Treat them as close, not exact.',
    )
  }
  if (usage.cached_input_tokens > 0) {
    parts.push(
      `${formatTokens(usage.cached_input_tokens)} input tokens were served from the provider's cache.`,
    )
  }
  if (parts.length === 0) {
    parts.push('Counted from the provider’s own usage report for every call.')
  }
  return parts.join(' ')
}

/** Grouped, never abbreviated: `57,272`, not `57.3k`. This is a figure. */
function formatTokens(value: number): string {
  return value.toLocaleString('en-US')
}

/**
 * Four decimals in the headline, six in the table.
 *
 * The headline is read at a glance; the rows are compared against each other,
 * where four decimals would render four different stages as the same number.
 *
 * A cost that rounds to nothing is shown as `<$0.000001`, not `$0.000000`.
 * The query embedding really does cost a fraction of a micro-dollar, and a row
 * of zeros reads as "free" rather than "too small to write down".
 */
function formatCost(value: number, decimals: number): string {
  if (value > 0 && value < Number(`1e-${decimals}`)) return `<$${Number(`1e-${decimals}`).toFixed(decimals)}`
  return `$${value.toFixed(decimals)}`
}

/**
 * The model that cost the most, for the one slot the header has.
 *
 * Cost first, tokens as the tie-break: an unpriced run still has a model worth
 * naming, and "most tokens" is the honest stand-in when there are no dollars to
 * compare. Read off the stage itself rather than inferred from the run's model
 * list — which is what `models[0]` got wrong, since the query embedding runs
 * first and is reliably the cheapest thing in the run.
 */
function dominantModel(usage: Usage): string {
  const ranked = [...usage.stages].sort(
    (a, b) =>
      (b.cost_usd ?? 0) - (a.cost_usd ?? 0) ||
      b.input_tokens + b.output_tokens - (a.input_tokens + a.output_tokens),
  )
  return ranked[0]?.models?.[0] ?? usage.models[usage.models.length - 1] ?? ''
}
