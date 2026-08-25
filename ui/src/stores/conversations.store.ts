import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { ChatResponse } from '@/api/types'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  /** Present on assistant messages; carries the evidence and the retrieval trace. */
  result?: ChatResponse
  /** Present when the request itself failed, as distinct from a decline. */
  error?: string
}

export interface Conversation {
  id: string
  doc_name: string
  title: string
  created_at: string
  updated_at: string
  messages: Message[]
}

/**
 * Chat history.
 *
 * Persisted to localStorage until the `/conversations` endpoints exist. The
 * store's shape already matches the planned API rows, so the swap replaces the
 * persistence layer without touching a single component.
 */
interface ConversationState {
  conversations: Record<string, Conversation>
  order: string[]
  create: (docName: string) => Conversation
  get: (id: string) => Conversation | undefined
  listFor: (userScope?: string) => Conversation[]
  appendMessage: (id: string, message: Message) => void
  replaceMessage: (id: string, messageId: string, message: Message) => void
  rename: (id: string, title: string) => void
  remove: (id: string) => void
}

const newId = () => `c_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`

export const useConversationStore = create<ConversationState>()(
  persist(
    (set, get) => ({
      conversations: {},
      order: [],

      create: (docName) => {
        const now = new Date().toISOString()
        const conversation: Conversation = {
          id: newId(),
          doc_name: docName,
          title: 'New conversation',
          created_at: now,
          updated_at: now,
          messages: [],
        }
        set((state) => ({
          conversations: { ...state.conversations, [conversation.id]: conversation },
          order: [conversation.id, ...state.order],
        }))
        return conversation
      },

      get: (id) => get().conversations[id],

      listFor: () =>
        get()
          .order.map((id) => get().conversations[id])
          .filter(Boolean),

      appendMessage: (id, message) =>
        set((state) => {
          const conversation = state.conversations[id]
          if (!conversation) return state
          // The first question becomes the title — far more useful in the
          // sidebar than "New conversation" repeated a dozen times.
          const title =
            conversation.messages.length === 0 && message.role === 'user'
              ? truncateTitle(message.content)
              : conversation.title
          return {
            conversations: {
              ...state.conversations,
              [id]: {
                ...conversation,
                title,
                updated_at: new Date().toISOString(),
                messages: [...conversation.messages, message],
              },
            },
            order: [id, ...state.order.filter((other) => other !== id)],
          }
        }),

      replaceMessage: (id, messageId, message) =>
        set((state) => {
          const conversation = state.conversations[id]
          if (!conversation) return state
          return {
            conversations: {
              ...state.conversations,
              [id]: {
                ...conversation,
                updated_at: new Date().toISOString(),
                messages: conversation.messages.map((existing) =>
                  existing.id === messageId ? message : existing,
                ),
              },
            },
          }
        }),

      rename: (id, title) =>
        set((state) => {
          const conversation = state.conversations[id]
          if (!conversation) return state
          return {
            conversations: { ...state.conversations, [id]: { ...conversation, title } },
          }
        }),

      remove: (id) =>
        set((state) => {
          const { [id]: _removed, ...rest } = state.conversations
          return { conversations: rest, order: state.order.filter((other) => other !== id) }
        }),
    }),
    { name: 'analyst-copilot.conversations' },
  ),
)

function truncateTitle(text: string): string {
  const clean = text.trim().replace(/\s+/g, ' ')
  return clean.length > 60 ? `${clean.slice(0, 57)}…` : clean
}
