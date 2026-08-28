import { create } from 'zustand'
import type { CancelledEvent, ChatResponse, StageEvent, TraceEvent } from '@/api/types'
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
   * Present when the analyst stopped this turn.
   *
   * Local only, and never persisted — the server does not record a cancelled
   * exchange, because a run nobody finished proves nothing. A reload therefore
   * shows the question without this marker, which is the truth: it was never
   * answered.
   */
  stopped?: CancelledEvent
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
 * One thread's in-flight question.
 *
 * This lives on the thread rather than in the chat view, and that is the whole
 * point. A question takes seconds on the fast path and minutes on the deep one,
 * and an analyst will switch threads while it runs. Held as view state, the
 * "searching the filing" indicator followed them — an idle thread claiming to be
 * working, and no way to see the progress of the thread that actually was.
 *
 * Keyed by conversation id, so two threads can be searching at once and each
 * shows only its own progress.
 */
export interface ThreadRun {
  busy: boolean
  stage: StageEvent | null
  traces: TraceEvent[]
  /** The stop was asked for and the server is still unwinding calls in flight. */
  stopping: boolean
  /**
   * The server's id for this run, from the `run` event.
   *
   * Needed to cancel it. Null until the event arrives, which is why stopping
   * before then hangs up instead of calling the endpoint.
   */
  serverRunId: string | null
  /**
   * How to hang up on this run.
   *
   * Lives here rather than in a ref for the same reason everything else in this
   * type does: with one ref per view, starting a question in a second thread
   * would overwrite the first thread's controller, and stopping either would
   * stop the wrong one.
   */
  controller: AbortController | null
}

/**
 * Where a run is filed when there is no thread to file it under.
 *
 * A question asked before a thread exists — the first message, or any question
 * when no database is configured — still needs somewhere to report progress. The
 * chat view reads this key exactly when it is showing no conversation, so the two
 * agree without either knowing about the other.
 */
export const DRAFT_RUN = '__draft__'

export const IDLE_RUN: ThreadRun = {
  busy: false,
  stage: null,
  traces: [],
  stopping: false,
  serverRunId: null,
  controller: null,
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

  /** In-flight questions, by thread. See `ThreadRun`. */
  runs: Record<string, ThreadRun>
  /** Mark a thread as working, clearing any previous run's progress. */
  startRun: (key: string) => void
  /** Report progress on a thread's run. Ignored once the run has ended. */
  updateRun: (key: string, patch: Partial<ThreadRun>) => void
  /** The run finished, one way or another. */
  endRun: (key: string) => void
  /** Hang up on every run in flight. Used when the chat screen is left. */
  abortAllRuns: () => void
  /** A thread's run, or a stable idle value. Never undefined. */
  runFor: (key: string | undefined) => ThreadRun
}

export const useConversationStore = create<ConversationState>()((set, get) => ({
  conversations: {},
  order: [],
  loaded: false,
  runs: {},

  startRun: (key) =>
    set((state) => ({ runs: { ...state.runs, [key]: { ...IDLE_RUN, busy: true } } })),

  updateRun: (key, patch) =>
    set((state) => {
      const current = state.runs[key]
      // A late event from a run that already ended must not resurrect the
      // indicator: the stream is cancelled on unmount, but a queued callback can
      // still land after the `finally` block has run.
      if (!current?.busy) return state
      return { runs: { ...state.runs, [key]: { ...current, ...patch } } }
    }),

  endRun: (key) =>
    set((state) => {
      const { [key]: _finished, ...rest } = state.runs
      return { runs: rest }
    }),

  abortAllRuns: () => {
    // Every controller, not one: several threads can be working at once, and
    // leaving the screen abandons all of them.
    for (const run of Object.values(get().runs)) run.controller?.abort()
  },

  runFor: (key) => (key ? get().runs[key] ?? IDLE_RUN : IDLE_RUN),

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