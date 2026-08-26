import { api } from '../client'
import type { ChatResponse } from '../types'

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
}