import { useMemo } from 'react'
import { Coins } from 'lucide-react'
import type { ModelUsage, Usage } from '@/api/types'
import { Tooltip } from '@/components/ui/Tooltip'

/**
 * What this thread has cost so far, in the top bar.
 *
 * A per-answer figure tells an analyst what one question cost; this tells them
 * what the conversation has. They are different questions, and the second is
 * the one that gets asked at the end of the month.
 *
 * It sums only what is on screen — the answers in this thread. Two consequences
 * worth being honest about, and both are stated in the tooltip:
 *
 * - Answers served before cost was recorded contribute their tokens but no
 *   cost, so the total is a floor rather than a figure. Re-pricing them now
 *   would be a fabrication: their `usage` records what was served.
 * - A thread that mixes priced and unpriced answers shows `≥` and the priced
 *   subtotal. Unlike a single answer — where the calls are all part of one
 *   number and a partial total would be a lie — a thread's answers are separate
 *   facts, so the honest report is a floor plus a note saying what is missing.
 *   With nothing priced at all it says so and shows no dollars.
 *
 * Nothing here is `verified`, `declined`, `failed` or `building`: those four
 * mean the system proved, declined, errored or is indexing, and a cost is none
 * of them.
 */
export function SessionCost({ usages }: { usages: (Usage | null | undefined)[] }) {
  const total = useMemo(() => sessionTotal(usages), [usages])
  if (total === null) return null

  return (
    <Tooltip
      label={<Breakdown total={total} />}
      side="bottom"
      align="end"
      contentClassName="whitespace-normal px-3 py-2.5"
    >
      <span className="flex h-7 cursor-help items-center gap-2 rounded-lg border border-line bg-surface px-2.5">
        <Coins className="h-3.5 w-3.5 shrink-0 text-ink-subtle" aria-hidden />
        <span className="tabular font-mono text-2xs text-ink-muted">
          {total.estimated && '~'}
          {total.totalTokens.toLocaleString('en-US')} tokens
        </span>
        <span className="text-2xs text-ink-subtle" aria-hidden>
          ·
        </span>
        {total.pricedAnswers > 0 ? (
          <span className="tabular font-mono text-2xs font-medium text-ink">
            {/* `≥` when part of the thread has no price: those answers cost
                something, it just cannot be said what. A bare total would
                claim they were free; "unpriced" would throw away three
                priced answers to describe one that is not. */}
            {total.complete ? '' : '≥'}
            {total.estimated && '~'}
            {formatCost(total.microUsd)}
          </span>
        ) : (
          <span className="text-2xs text-ink-subtle">unpriced</span>
        )}
      </span>
    </Tooltip>
  )
}

/** model → tokens → cost, one row each, plus what the total does not include. */
function Breakdown({ total }: { total: SessionTotal }) {
  return (
    <span className="block min-w-[15rem] space-y-1.5">
      <span className="block text-2xs font-semibold uppercase tracking-wider text-ink-muted">
        This conversation
      </span>

      <span className="block space-y-0.5">
        {total.models.map((entry) => (
          <span key={entry.model} className="flex items-baseline gap-2 text-2xs">
            <span className="truncate font-mono text-ink-muted">
              {entry.model || 'not attributed'}
            </span>
            <span className="flex-1 border-b border-dotted border-line" aria-hidden />
            <span className="tabular shrink-0 font-mono text-ink-subtle">
              {entry.total_tokens.toLocaleString('en-US')}
            </span>
            <span className="tabular w-[4.75rem] shrink-0 text-right font-mono text-ink">
              {entry.cost_usd === null
                ? '—'
                : entry.cost_usd === 0 && entry.total_tokens > 0
                  ? '<$0.000001'
                  : `$${entry.cost_usd.toFixed(6)}`}
            </span>
          </span>
        ))}
      </span>

      <span className="flex items-baseline gap-2 border-t border-line pt-1.5 text-2xs">
        <span className="font-semibold text-ink">
          {total.answers} answer{total.answers === 1 ? '' : 's'}
        </span>
        <span className="flex-1" aria-hidden />
        <span className="tabular shrink-0 font-mono text-ink-subtle">
          {total.totalTokens.toLocaleString('en-US')}
        </span>
        <span className="tabular w-[4.75rem] shrink-0 text-right font-mono font-semibold text-ink">
          {total.pricedAnswers === 0
            ? '—'
            : `${total.complete ? '' : '≥'}${formatCost(total.microUsd, 6)}`}
        </span>
      </span>

      {total.unrecorded > 0 && (
        <span className="block text-2xs leading-relaxed text-ink-subtle">
          {total.unrecorded} earlier answer{total.unrecorded === 1 ? '' : 's'} in this thread
          {total.unrecorded === 1 ? ' was' : ' were'} served before cost was recorded, so this is
          a floor, not the whole bill.
        </span>
      )}
      {total.estimated && (
        <span className="block text-2xs leading-relaxed text-ink-subtle">
          Some calls were counted locally rather than reported by the provider. Close, not exact.
        </span>
      )}
      {total.unpricedAnswers > 0 && total.pricedAnswers > 0 && (
        <span className="block text-2xs leading-relaxed text-ink-subtle">
          {total.unpricedAnswers} answer{total.unpricedAnswers === 1 ? '' : 's'} used a model with
          no configured price and {total.unpricedAnswers === 1 ? 'is' : 'are'} not in the total,
          so this is a floor.
        </span>
      )}
      {total.pricedAnswers === 0 && (
        <span className="block text-2xs leading-relaxed text-ink-subtle">
          No model in this thread has a configured price, so no cost is shown. Set
          CHAT_PRICE_INPUT and CHAT_PRICE_OUTPUT to price it.
        </span>
      )}
    </span>
  )
}

interface SessionTotal {
  answers: number
  /** Answers with no usage recorded at all — history predating the feature. */
  unrecorded: number
  totalTokens: number
  /** Summed over the priced answers only. */
  microUsd: number
  pricedAnswers: number
  unpricedAnswers: number
  /** Every recorded answer had a price, so the total is the whole bill. */
  complete: boolean
  estimated: boolean
  models: ModelUsage[]
}

/**
 * Add up the thread.
 *
 * Money is summed in integer micro-dollars, the same as the backend: a thread
 * is dozens of answers whose interesting digits sit at the fifth decimal place,
 * and floats added in that range drift exactly where someone is reading.
 */
function sessionTotal(usages: (Usage | null | undefined)[]): SessionTotal | null {
  const recorded = usages.filter((usage): usage is Usage => Boolean(usage))
  if (recorded.length === 0) return null

  const models = new Map<string, ModelUsage>()
  let totalTokens = 0
  let microUsd = 0
  let pricedAnswers = 0
  let unpricedAnswers = 0
  let estimated = false

  for (const usage of recorded) {
    totalTokens += usage.total_tokens
    estimated = estimated || usage.estimated
    if (usage.priced && usage.cost_usd !== null) {
      microUsd += Math.round(usage.cost_usd * 1_000_000)
      pricedAnswers += 1
    } else {
      // Not folded in as a zero. A thread mixing priced and unpriced answers
      // gets a floor and says so, rather than throwing away the answers that
      // *can* be priced to describe the ones that cannot.
      unpricedAnswers += 1
    }

    for (const entry of attributeByModel(usage)) {
      const running = models.get(entry.model) ?? {
        model: entry.model,
        calls: 0,
        input_tokens: 0,
        output_tokens: 0,
        cached_input_tokens: 0,
        total_tokens: 0,
        cost_usd: 0,
      }
      running.calls += entry.calls
      running.input_tokens += entry.input_tokens
      running.output_tokens += entry.output_tokens
      running.cached_input_tokens += entry.cached_input_tokens
      running.total_tokens += entry.total_tokens
      // One unpriced contribution makes the model's whole total unpriced, the
      // same rule the per-answer figure follows.
      running.cost_usd =
        entry.cost_usd === null || running.cost_usd === null
          ? null
          : running.cost_usd + entry.cost_usd
      models.set(entry.model, running)
    }
  }

  return {
    answers: recorded.length,
    unrecorded: usages.length - recorded.length,
    totalTokens,
    microUsd,
    pricedAnswers,
    unpricedAnswers,
    complete: unpricedAnswers === 0,
    estimated,
    // Priciest first: the model that matters is the one to read at a glance.
    models: [...models.values()].sort(
      (a, b) => (b.cost_usd ?? 0) - (a.cost_usd ?? 0) || b.total_tokens - a.total_tokens,
    ),
  }
}

/** Four decimals at a glance, six when the tooltip is comparing rows. */
function formatCost(microUsd: number, decimals = 4): string {
  const value = microUsd / 1_000_000
  const floor = Number(`1e-${decimals}`)
  if (value > 0 && value < floor) return `<$${floor.toFixed(decimals)}`
  return `$${value.toFixed(decimals)}`
}

/** The bucket for spend no model can be named for. Rendered, never hidden. */
const UNATTRIBUTED = ''

/**
 * One answer's spend, split by model, with the remainder shown rather than lost.
 *
 * Three sources, best first: the report's own `by_model`, then the stage rows
 * where a stage names exactly one model, then a residual bucket for whatever
 * neither accounts for. History predates both fields, and an answer whose cost
 * is in the total but attributed to no row would make the breakdown disagree
 * with the headline above it — which is the one thing a breakdown must never
 * do, because it teaches an analyst to distrust a number that is correct.
 */
function attributeByModel(usage: Usage): ModelUsage[] {
  const rows: ModelUsage[] = usage.by_model.length
    ? usage.by_model.map((entry) => ({ ...entry }))
    : fromStages(usage)

  const attributedTokens = rows.reduce((sum, row) => sum + row.total_tokens, 0)
  const attributedMicro = rows.reduce(
    (sum, row) => sum + (row.cost_usd === null ? 0 : Math.round(row.cost_usd * 1_000_000)),
    0,
  )
  const answerMicro =
    usage.priced && usage.cost_usd !== null ? Math.round(usage.cost_usd * 1_000_000) : 0
  const residualTokens = usage.total_tokens - attributedTokens
  const residualMicro = answerMicro - attributedMicro

  if (residualTokens > 0 || residualMicro > 0) {
    rows.push({
      model: UNATTRIBUTED,
      calls: 0,
      input_tokens: 0,
      output_tokens: 0,
      cached_input_tokens: 0,
      total_tokens: Math.max(0, residualTokens),
      cost_usd: residualMicro / 1_000_000,
    })
  }
  return rows
}

/** Fall back to the stage rows, which name a model one level down. */
function fromStages(usage: Usage): ModelUsage[] {
  const rows = new Map<string, ModelUsage>()
  for (const stage of usage.stages) {
    // Only an unambiguous stage. A stage naming two models cannot be split, and
    // guessing a split is worse than letting the residual row report it.
    if (stage.models.length !== 1) continue
    const model = stage.models[0]
    const running = rows.get(model) ?? {
      model,
      calls: 0,
      input_tokens: 0,
      output_tokens: 0,
      cached_input_tokens: 0,
      total_tokens: 0,
      cost_usd: 0,
    }
    running.calls += stage.calls
    running.input_tokens += stage.input_tokens
    running.output_tokens += stage.output_tokens
    running.cached_input_tokens += stage.cached_input_tokens
    running.total_tokens += stage.input_tokens + stage.output_tokens
    running.cost_usd =
      stage.cost_usd === null || running.cost_usd === null
        ? null
        : running.cost_usd + stage.cost_usd
    rows.set(model, running)
  }
  return [...rows.values()]
}
