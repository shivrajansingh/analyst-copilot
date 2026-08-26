import { api } from '../client'
import type { ConversationDetail, ConversationListResponse, ConversationSummary } from '../types'

export const conversationsApi = {
  /** The caller's threads, newest first. No message bodies. */
  list: () => api.get<ConversationListResponse>('/conversations'),

  /** Start a thread, pinned to one filing. */
  create: (body: { collection?: string; title?: string }) =>
    api.post<ConversationDetail>('/conversations', body),

  /** A thread with all its messages, for re-rendering history. */
  get: (id: string) => api.get<ConversationDetail>(`/conversations/${id}`),

  rename: (id: string, title: string) =>
    api.patch<ConversationSummary>(`/conversations/${id}`, { title }),

  remove: (id: string) => api.delete<void>(`/conversations/${id}`),
}