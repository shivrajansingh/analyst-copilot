import { create } from 'zustand'
import type { ChatResponse, TraceEvent } from '@/api/types'
import { conversationsApi } from '@/api/endpoints/conversations'
import { normalizeChatResponse } from '@/api/normalize'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  /** Present on assistant messages; carries the evidence and the retrieval trace. */
  result?: ChatResponse
  /** Present when the request itself failed, as distinct from a decline. */
  error?: string
  /**
   * What the agents did while producing this answer.
   *
   * Client-side only, and deliberately not persisted: it is progress, not
   * evidence. A reloaded thread shows the answer and its citations, which are
   * the parts that have to survive.
   */
  traces?: TraceEvent[]
}

export interface Conversation {
  id: string
  /**
   * The filing this thread is pinned to.
   *
   * A thread never changes filing: switching starts a new one, so every
   * citation in a thread stays checkable against the same set of documents.
   */
  collection: string | null
  title: string
  created_at: string
  updated_at: string
  messages: Message[]
  /**
   * Whether this thread's messages came from the server (or the thread was
   * created this session). Guards against refetching a thread the local state
   * already owns, which could wipe optimistic messages mid-exchange.
   */
  detailFetched?: boolean
}

/**
 * Chat history, stored in Postgres through `/conversations`.
 *
 * The store keeps its shape from the localStorage era so components render the
 * same data — what changed is where it lives: `create`/`appendLocal`/`remove`
 * are optimistic locally and authoritative on the server, and `load`/`refresh`
 * repopulate the thread from the database on arrival or on reload.
 */
interface ConversationState {
  conversations: Record<string, Conversation>
  order: string[]
  loaded: boolean
  /** Fetch the sidebar list. Preserves any message bodies already in memory. */
  load: () => Promise<void>
  /** Start a thread on the server; the sidebar and the chat both show it. */
  create: (collection: string, title?: string) => Promise<Conversation>
  get: (id: string) => Conversation | undefined
  listFor: () => Conversation[]
  /** Fetch one thread with its messages (history reload, or after an exchange). */
  refresh: (id: string) => Promise<Conversation | undefined>
  /** Optimistic local append; the server row arrives via `refresh` or reload. */
  appendLocal: (id: string, message: Message) => void
  rename: (id: string, title: string) => Promise<void>
  remove: (id: string) => Promise<void>
}

export const useConversationStore = create<ConversationState>()((set, get) => ({
  conversations: {},
  order: [],
  loaded: false,

  load: async () => {
    const { conversations } = await conversationsApi.list()
    set((state) => {
      const merged: Record<string, Conversation> = {}
      for (const row of conversations) {
        // A thread already fetched with its messages keeps them; the list
        // response has none, and overwriting would blank an open chat.
        const existing = state.conversations[row.id]
        merged[row.id] = existing ?? _fromSummary(row)
      }
      return {
        conversations: merged,
        order: conversations.map((row) => row.id),
        loaded: true,
      }
    })
  },

  create: async (collection, title) => {
    const row = await conversationsApi.create({ collection, title })
    const conversation = _fromDetail(row)
    set((state) => ({
      conversations: { ...state.conversations, [conversation.id]: conversation },
      order: [conversation.id, ...state.order],
      loaded: true,
    }))
    return conversation
  },

  get: (id) => get().conversations[id],

  listFor: () =>
    get()
      .order.map((id) => get().conversations[id])
      .filter(Boolean),

  refresh: async (id) => {
    try {
      const row = await conversationsApi.get(id)
      const conversation = _fromDetail(row)
      set((state) => ({
        conversations: { ...state.conversations, [id]: conversation },
        order: [id, ...state.order.filter((other) => other !== id)],
      }))
      return conversation
    } catch {
      return undefined
    }
  },

  appendLocal: (id, message) =>
    set((state) => {
      const conversation = state.conversations[id]
      if (!conversation) return state
      return {
        conversations: {
          ...state.conversations,
          [id]: {
            ...conversation,
            updated_at: new Date().toISOString(),
            messages: [...conversation.messages, message],
          },
        },
        order: [id, ...state.order.filter((other) => other !== id)],
      }
    }),

  rename: async (id, title) => {
    const row = await conversationsApi.rename(id, title)
    set((state) => {
      const conversation = state.conversations[id]
      if (!conversation) return state
      return {
        conversations: {
          ...state.conversations,
          [id]: { ...conversation, title: row.title },
        },
      }
    })
  },

  remove: async (id) => {
    await conversationsApi.remove(id)
    set((state) => {
      const { [id]: _removed, ...rest } = state.conversations
      return { conversations: rest, order: state.order.filter((other) => other !== id) }
    })
  },
}))

function _fromSummary(row: { id: string; collection: string | null; title: string; created_at: string; updated_at: string }): Conversation {
  return {
    id: row.id,
    collection: row.collection,
    title: row.title,
    created_at: row.created_at,
    updated_at: row.updated_at,
    messages: [],
  }
}

function _fromDetail(row: {
  id: string
  collection: string | null
  title: string
  created_at: string
  updated_at: string
  messages: {
    id: string
    role: 'user' | 'assistant'
    content: string
    created_at: string
    result: ChatResponse | null
  }[]
}): Conversation {
  return {
    ..._fromSummary(row),
    detailFetched: true,
    messages: row.messages.map((message) => ({
      id: message.id,
      role: message.role,
      content: message.content,
      created_at: message.created_at,
      // Stored answers may predate fields the components now read.
      ...(message.result ? { result: normalizeChatResponse(message.result) } : {}),
    })),
  }
}