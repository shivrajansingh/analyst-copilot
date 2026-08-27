import type { ChatResponse } from './types'

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
 * arrays being arrays. Defaults are chosen to describe what the old answer
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
  }
}
