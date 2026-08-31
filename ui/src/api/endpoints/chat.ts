import { ApiError, api } from '../client'
import { normalizeChatResponse } from '../normalize'
import type { CancelledEvent, ChatResponse, RunEvent, StageEvent, TraceEvent } from '../types'

/** One parsed server-sent event. */
interface ServerEvent {
  name: string
  data: unknown
}

/**
 * Split an SSE buffer into whole events.
 *
 * Chunk boundaries fall wherever the network puts them, so a partial event has
 * to be carried over to the next read rather than parsed and lost. Returns the
 * complete events plus whatever remains unterminated.
 */
function drain(buffer: string): { events: ServerEvent[]; rest: string } {
  const events: ServerEvent[] = []
  let rest = buffer

  for (;;) {
    const boundary = rest.indexOf('\n\n')
    if (boundary < 0) break
    const block = rest.slice(0, boundary)
    rest = rest.slice(boundary + 2)

    let name = ''
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      // A line beginning with ':' is a keepalive comment, not an event.
      if (line.startsWith(':')) continue
      if (line.startsWith('event:')) name = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!name) continue
    const payload = dataLines.join('\n')
    try {
      events.push({ name, data: payload ? JSON.parse(payload) : {} })
    } catch {
      /* a malformed event is dropped rather than breaking the stream */
    }
  }

  return { events, rest }
}

export interface AskOptions {
  conversationId?: string
  /** Called once, before any work, with the id this run can be stopped by. */
  onRun?: (run: RunEvent) => void
  /** Called for every progress milestone, in order. */
  onStage?: (stage: StageEvent) => void
  /** Called for every step underneath those milestones, in order. */
  onTrace?: (trace: TraceEvent) => void
  signal?: AbortSignal
}

/**
 * How a run ended.
 *
 * A stop is not a failure, so it is a result rather than a thrown error. Throwing
 * would put the analyst's own decision into whatever renders exceptions, which in
 * this UI is a red "something went wrong" card.
 */
export type AskResult =
  | { status: 'answered'; answer: ChatResponse }
  | { status: 'cancelled'; at: CancelledEvent }

/**
 * Ask a question and follow the work.
 *
 * Progress is streamed; the answer is not. It arrives in a single `answer`
 * event, already verified — a figure that rendered before verification finished
 * would be an unproven figure on screen, which is the one thing this product
 * exists to prevent.
 */
async function askStreaming(
  body: Record<string, unknown>,
  { onRun, onStage, onTrace, signal }: AskOptions,
): Promise<AskResult> {
  let response: Response
  try {
    response = await api.stream('/chat/stream', body, signal)
  } catch (caught) {
    // Aborted before the response arrived — a stop pressed in the first instant.
    if (isAbort(caught)) return { status: 'cancelled', at: NOTHING_YET }
    throw caught
  }
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()

  let buffer = ''
  let answer: ChatResponse | null = null
  let cancelled: CancelledEvent | null = null

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const { events, rest } = drain(buffer)
      buffer = rest
      for (const event of events) {
        if (event.name === 'stage') onStage?.(event.data as StageEvent)
        else if (event.name === 'trace') onTrace?.(event.data as TraceEvent)
        else if (event.name === 'run') onRun?.(event.data as RunEvent)
        else if (event.name === 'answer')
          answer = normalizeChatResponse(event.data as ChatResponse)
        else if (event.name === 'cancelled') cancelled = event.data as CancelledEvent
        else if (event.name === 'error') {
          const { code, message } = event.data as { code: string; message: string }
          throw new ApiError(409, code, message)
        }
      }
    }
  } catch (caught) {
    // The abort landed mid-stream. The server sees the hang-up and stops the
    // work; there is no `cancelled` event to wait for, because nobody is reading.
    if (isAbort(caught)) return { status: 'cancelled', at: NOTHING_YET }
    throw caught
  } finally {
    // Cancelling releases the connection. Without it an abandoned stream leaves
    // a fan-out of reader agents running server-side for nobody.
    await reader.cancel().catch(() => {})
  }

  if (cancelled) return { status: 'cancelled', at: cancelled }
  if (!answer) {
    throw new ApiError(502, 'no_answer', 'The stream ended before an answer arrived.')
  }
  return { status: 'answered', answer }
}

/**
 * What a stop reports when the client hung up rather than waiting to be told.
 *
 * The server knows where it stopped; the client that stopped reading does not.
 * Rather than invent a stage, this says nothing and lets the card fall back to
 * the last milestone it rendered.
 */
const NOTHING_YET: CancelledEvent = { stage: null, elapsed_ms: 0 }

function isAbort(caught: unknown): boolean {
  return caught instanceof DOMException && caught.name === 'AbortError'
}

export const chatApi = {
  /** Ask a filing. Retrieval spans every indexed document; the answer cites one. */
  askFiling: (collection: string, question: string, conversationId?: string) =>
    api
      .post<ChatResponse>('/chat', { collection, question, conversation_id: conversationId })
      .then(normalizeChatResponse),

  /** Ask a single document, for callers that already know which one. */
  ask: (docName: string, question: string, conversationId?: string) =>
    api
      .post<ChatResponse>('/chat', {
        doc_name: docName,
        question,
        conversation_id: conversationId,
      })
      .then(normalizeChatResponse),

  /**
   * Stop a run that is still going.
   *
   * Belt and braces with the caller's own `AbortController`: the abort is
   * instant and needs no round trip, and this is the guarantee. Disconnect
   * detection depends on proxy buffering, which we do not control — and an
   * analyst may want to stop a run from a tab that is not the one waiting on it.
   *
   * Best-effort by design: a 404 means the run had already finished, which is
   * not a problem the analyst has.
   */
  cancelRun: (runId: string) =>
    api.post<{ run_id: string; status: string }>(`/chat/runs/${encodeURIComponent(runId)}/cancel`)
      .catch(() => undefined),

  /** Ask a filing, streaming the progress that produced the answer. */
  streamFiling: (collection: string, question: string, options: AskOptions = {}) =>
    askStreaming({ collection, question, conversation_id: options.conversationId }, options),

  /** Ask a single document, streaming progress. */
  streamDocument: (docName: string, question: string, options: AskOptions = {}) =>
    askStreaming({ doc_name: docName, question, conversation_id: options.conversationId }, options),
}
