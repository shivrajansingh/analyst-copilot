import type { ChatResponse, Usage } from './types'

/**
 * Fill in the fields a stored answer may predate.
 *
 * Every assistant message keeps the full `ChatResponse` as it was served, so the
 * evidence panel can re-render history verbatim. That is the right design and it
 * has one consequence: a thread answered before a field existed comes back
 * without it, and a component that reads `result.citations.length` on such a row
 * throws and blanks the whole conversation.
 *
 * So every `ChatResponse` entering the app passes through here — from the POST,
 * from the stream, and from stored history — and components can rely on the
 * arrays being arrays. **Nested objects need the same treatment**: a stored
 * `usage` predating per-stage model attribution has stages without `models`,
 * and a component mapping over it throws exactly as if the field were top-level. Defaults are chosen to describe what the old answer
 * actually was: `mode: 'fast'` because it came from the retrieval pipeline, and
 * an empty `citations` so `evidence` remains the single source of the citation.
 */
export function normalizeChatResponse(raw: ChatResponse | null | undefined): ChatResponse {
  const value = (raw ?? {}) as Partial<ChatResponse>
  return {
    ...(value as ChatResponse),
    retrieval: value.retrieval ?? [],
    citations: value.citations ?? [],
    parts: value.parts ?? [],
    inputs: value.inputs ?? [],
    computation: value.computation ?? '',
    mode: value.mode ?? 'fast',
    intent: value.intent ?? 'document_question',
    validation: value.validation ?? null,
    pages_read: value.pages_read ?? 0,
    shards_run: value.shards_run ?? 0,
    // Null rather than a zeroed report: an answer served before this existed
    // was not free, its cost was never recorded, and a row of zeros would
    // claim otherwise.
    usage: normalizeUsage(value.usage),
  }
}

/**
 * Fill in the fields a stored usage report may predate.
 *
 * `models` on a stage arrived after the first answers were recorded, so history
 * holds stages without it. Defaulting to `[]` here means every consumer can map
 * over it — the alternative is an optional chain at every call site, and the
 * one that gets forgotten blanks the whole conversation.
 */
function normalizeUsage(raw: Usage | null | undefined): Usage | null {
  if (!raw) return null
  return {
    ...raw,
    cached_input_tokens: raw.cached_input_tokens ?? 0,
    models: raw.models ?? [],
    by_model: raw.by_model ?? [],
    stages: (raw.stages ?? []).map((stage) => ({
      ...stage,
      cached_input_tokens: stage.cached_input_tokens ?? 0,
      models: stage.models ?? [],
    })),
  }
}
