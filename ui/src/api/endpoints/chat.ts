import { api } from '../client'
import type { ChatResponse } from '../types'

export const chatApi = {
  ask: (docName: string, question: string) =>
    api.post<ChatResponse>('/chat', { doc_name: docName, question }),
}
