import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AlertTriangle, MessageSquare, PanelRightClose, PanelRightOpen } from 'lucide-react'
import type { ChatResponse, StageEvent } from '@/api/types'
import { ApiError } from '@/api/client'
import { chatApi } from '@/api/endpoints/chat'
import { useSearchableCollections } from '@/hooks/useCollections'
import { useConversationStore } from '@/stores/conversations.store'
import { useUiStore } from '@/stores/ui.store'
import { AnswerCard } from '@/components/chat/AnswerCard'
import { ChatBubble } from '@/components/chat/ChatBubble'
import { Composer } from '@/components/chat/Composer'
import { DeclineCard } from '@/components/chat/DeclineCard'
import { FilingPicker } from '@/components/chat/FilingPicker'
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator'
import { EvidencePanel } from '@/components/evidence/EvidencePanel'
import { EmptyState } from '@/components/ui/EmptyState'
import { Sheet } from '@/components/ui/Sheet'
import { cn } from '@/lib/cn'
import { truncateTitle } from '@/lib/format'

export function ChatPage() {
  const { conversationId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const { searchable: filings } = useSearchableCollections()
  const store = useConversationStore()
  const conversation = conversationId ? store.conversations[conversationId] : undefined

  const [draftFiling, setDraftFiling] = useState<string | null>(searchParams.get('filing'))
  const [busy, setBusy] = useState(false)
  // The live stage from the streaming endpoint. Reading a whole filing takes a
  // minute, and a minute of silence reads as a hang.
  const [stage, setStage] = useState<StageEvent | null>(null)
  const [threadError, setThreadError] = useState<string | null>(null)
  const [activeEvidence, setActiveEvidence] = useState<ChatResponse | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const evidenceOpen = useUiStore((state) => state.evidenceOpen)
  const setEvidenceOpen = useUiStore((state) => state.setEvidenceOpen)

  const bottomRef = useRef<HTMLDivElement>(null)
  // A conversation is pinned to the filing it was started in, so every
  // citation in the thread stays checkable against the same set of documents.
  const filingName = conversation?.collection ?? draftFiling
  const messages = conversation?.messages ?? []

  // A thread opened from the sidebar or a reload carries only its summary;
  // fetch its messages once, unless this session already owns them (created
  // or refreshed here, where optimistic rows are the truth). Depending on the
  // conversation object (not a subfield) is what lets this fire when the
  // store's `load()` populates the thread after mount.
  useEffect(() => {
    if (!conversationId || !conversation || conversation.detailFetched) return
    store.refresh(conversationId)
  }, [conversationId, conversation, store])

  // Show the most recent result unless the reader has pinned an older one.
  const shownEvidence = useMemo(() => {
    if (activeEvidence) return activeEvidence
    const last = [...messages]
      .reverse()
      .find((message) => message.result && message.result.mode !== 'conversational')
    return last?.result ?? null
  }, [activeEvidence, messages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, busy])

  const ask = async (question: string) => {
    if (!filingName) return

    // A conversation is created on the first question, not on arrival, so the
    // sidebar never fills with empty threads. Its title is the question.
    let target = conversation
    if (!target) {
      try {
        target = await store.create(filingName, truncateTitle(question))
        navigate(`/chat/${target.id}`, { replace: true })
        setThreadError(null)
      } catch (caught) {
        // Chat history needs Postgres; the question itself does not. Without a
        // thread the exchange is still answered, just not recorded.
        setThreadError(
          caught instanceof ApiError
            ? caught.message
            : 'Conversation history is unavailable; the question will still be answered.',
        )
      }
    }

    if (target) {
      store.appendLocal(target.id, {
        id: `m_${Date.now()}`,
        role: 'user',
        content: question,
        created_at: new Date().toISOString(),
      })
    }

    setBusy(true)
    setStage(null)
    try {
      const result = await chatApi.streamFiling(filingName, question, {
        conversationId: target?.id,
        onStage: setStage,
      })
      if (target) {
        store.appendLocal(target.id, {
          id: `m_${Date.now()}_a`,
          role: 'assistant',
          content: result.answer,
          created_at: new Date().toISOString(),
          result,
        })
        // Adopt the server's rows so a reload or a second tab shows the same
        // message ids; optimistic local ids are only ever temporary.
        await store.refresh(target.id)
      }
      // A conversational reply cites nothing, so it must not replace the
      // evidence a previous answer put in the rail.
      if (result.mode !== 'conversational') setActiveEvidence(result)
    } catch (caught) {
      const message =
        caught instanceof ApiError ? caught.message : 'The request could not be completed.'
      if (target) {
        store.appendLocal(target.id, {
          id: `m_${Date.now()}_e`,
          role: 'assistant',
          content: message,
          created_at: new Date().toISOString(),
          error: message,
        })
      } else {
        setThreadError(message)
      }
    } finally {
      setBusy(false)
      setStage(null)
    }
  }

  const openEvidence = (result: ChatResponse) => {
    setActiveEvidence(result)
    setEvidenceOpen(true)
    setSheetOpen(true)
  }

  return (
    <div className="flex h-full min-h-0">
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center gap-3 border-b border-line px-4 py-3 lg:pr-16">
          <div className="min-w-0 flex-1 lg:max-w-md">
            <FilingPicker
              filings={filings}
              value={filingName}
              onChange={(next) => {
                // A thread is pinned to one filing: switching starts a new one,
                // so every citation in a thread stays checkable.
                setDraftFiling(next)
                setActiveEvidence(null)
                navigate(`/chat?filing=${encodeURIComponent(next)}`)
              }}
            />
          </div>
          <button
            onClick={() => setEvidenceOpen(!evidenceOpen)}
            aria-label={evidenceOpen ? 'Hide evidence' : 'Show evidence'}
            className="hidden rounded-lg border border-line bg-surface p-2 text-ink-subtle transition-colors hover:text-ink lg:block"
          >
            {evidenceOpen ? (
              <PanelRightClose className="h-4 w-4" />
            ) : (
              <PanelRightOpen className="h-4 w-4" />
            )}
          </button>
        </header>

        <div className="scrollbar-slim min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-5 px-4 py-6">
            {messages.length === 0 && !busy && (
              <EmptyState
                icon={<MessageSquare className="h-5 w-5" />}
                title={filingName ? 'Ask about this filing' : 'Choose a filing to begin'}
                description={
                  filingName
                    ? 'Every document in this filing is searched, and the answer names the one it came from. When the evidence is not there, the assistant says so rather than guessing.'
                    : 'Pick a filing above. A conversation stays pinned to one filing, so its citations remain checkable.'
                }
              />
            )}

            {messages.map((message) =>
              message.role === 'user' ? (
                <div key={message.id} className="flex justify-end animate-fade-up">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-sm bg-accent px-4 py-2.5 text-sm leading-relaxed text-accent-ink">
                    {message.content}
                  </p>
                </div>
              ) : message.error ? (
                <div
                  key={message.id}
                  className="flex items-start gap-2.5 rounded-xl border border-failed/30 bg-failed-soft/40 p-4 animate-fade-up"
                >
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-failed" />
                  <div>
                    <p className="text-sm font-medium text-ink">Something went wrong</p>
                    <p className="mt-0.5 text-xs text-ink-muted">{message.error}</p>
                  </div>
                </div>
              ) : message.result?.mode === 'conversational' ? (
                <ChatBubble key={message.id} text={message.content} />
              ) : message.result?.found ? (
                <AnswerCard
                  key={message.id}
                  result={message.result}
                  active={shownEvidence === message.result}
                  onOpenEvidence={() => openEvidence(message.result!)}
                />
              ) : (
                <DeclineCard
                  key={message.id}
                  result={message.result!}
                  onOpenEvidence={() => openEvidence(message.result!)}
                />
              ),
            )}

            {busy && <ThinkingIndicator stage={stage} />}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 border-t border-line bg-canvas px-4 py-4">
          <div className="mx-auto max-w-3xl">
            {threadError && (
              <div className="mb-3 flex items-start gap-2.5 rounded-xl border border-failed/30 bg-failed-soft/40 p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-failed" />
                <p className="text-xs leading-relaxed text-ink-muted">{threadError}</p>
              </div>
            )}
            <Composer
              onSubmit={ask}
              disabled={!filingName}
              busy={busy}
              docName={filingName ?? undefined}
              showSuggestions={messages.length === 0}
            />
          </div>
        </div>
      </section>

      <aside
        className={cn(
          'hidden shrink-0 border-l border-line bg-surface transition-[width] duration-200 lg:block',
          evidenceOpen ? 'w-80 xl:w-96' : 'w-0 overflow-hidden border-l-0',
        )}
      >
        <div className="scrollbar-slim h-full overflow-y-auto">
          <h2 className="border-b border-line px-4 py-3 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
            Evidence
          </h2>
          <EvidencePanel result={shownEvidence} />
        </div>
      </aside>

      <Sheet open={sheetOpen} onClose={() => setSheetOpen(false)} title="Evidence">
        <EvidencePanel result={shownEvidence} />
      </Sheet>
    </div>
  )
}
