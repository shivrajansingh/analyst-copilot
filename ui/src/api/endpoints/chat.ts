import { ApiError, api } from '../client'
import type { ChatResponse, StageEvent } from '../types'

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
  /** Called for every progress milestone, in order. */
  onStage?: (stage: StageEvent) => void
  signal?: AbortSignal
}

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
  { onStage, signal }: AskOptions,
): Promise<ChatResponse> {
  const response = await api.stream('/chat/stream', body, signal)
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()

  let buffer = ''
  let answer: ChatResponse | null = null

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const { events, rest } = drain(buffer)
      buffer = rest
      for (const event of events) {
        if (event.name === 'stage') onStage?.(event.data as StageEvent)
        else if (event.name === 'answer') answer = event.data as ChatResponse
        else if (event.name === 'error') {
          const { code, message } = event.data as { code: string; message: string }
          throw new ApiError(409, code, message)
        }
      }
    }
  } finally {
    // Cancelling releases the connection. Without it an abandoned stream leaves
    // a fan-out of reader agents running server-side for nobody.
    await reader.cancel().catch(() => {})
  }

  if (!answer) {
    throw new ApiError(502, 'no_answer', 'The stream ended before an answer arrived.')
  }
  return answer
}

export const chatApi = {
  /** Ask a filing. Retrieval spans every indexed document; the answer cites one. */
  askFiling: (collection: string, question: string, conversationId?: string) =>
    api.post<ChatResponse>('/chat', { collection, question, conversation_id: conversationId }),

  /** Ask a single document, for callers that already know which one. */
  ask: (docName: string, question: string, conversationId?: string) =>
    api.post<ChatResponse>('/chat', {
      doc_name: docName,
      question,
      conversation_id: conversationId,
    }),

  /** Ask a filing, streaming the progress that produced the answer. */
  streamFiling: (collection: string, question: string, options: AskOptions = {}) =>
    askStreaming({ collection, question, conversation_id: options.conversationId }, options),

  /** Ask a single document, streaming progress. */
  streamDocument: (docName: string, question: string, options: AskOptions = {}) =>
    askStreaming({ doc_name: docName, question, conversation_id: options.conversationId }, options),
}
