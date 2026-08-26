import { api } from '../client'
import type { ChatResponse } from '../types'

export const chatApi = {
  /** Ask a folder. Retrieval spans every indexed document; the answer cites one. */
  askFolder: (collection: string, question: string) =>
    api.post<ChatResponse>('/chat', { collection, question }),

  /** Ask a single document, for callers that already know which one. */
  ask: (docName: string, question: string) =>
    api.post<ChatResponse>('/chat', { doc_name: docName, question }),
}
