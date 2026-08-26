import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AlertTriangle, MessageSquare, PanelRightClose, PanelRightOpen } from 'lucide-react'
import type { ChatResponse } from '@/api/types'
import { ApiError } from '@/api/client'
import { chatApi } from '@/api/endpoints/chat'
import { useSearchableCollections } from '@/hooks/useCollections'
import { useConversationStore, type Message } from '@/stores/conversations.store'
import { useUiStore } from '@/stores/ui.store'
import { AnswerCard } from '@/components/chat/AnswerCard'
import { Composer } from '@/components/chat/Composer'
import { DeclineCard } from '@/components/chat/DeclineCard'
import { FilingPicker } from '@/components/chat/FilingPicker'
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator'
import { EvidencePanel } from '@/components/evidence/EvidencePanel'
import { EmptyState } from '@/components/ui/EmptyState'
import { Sheet } from '@/components/ui/Sheet'
import { cn } from '@/lib/cn'

export function ChatPage() {
  const { conversationId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const { searchable: filings } = useSearchableCollections()
  const store = useConversationStore()
  const conversation = conversationId ? store.conversations[conversationId] : undefined

  const [draftFiling, setDraftFiling] = useState<string | null>(searchParams.get('filing'))
  const [busy, setBusy] = useState(false)
  const [activeEvidence, setActiveEvidence] = useState<ChatResponse | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const evidenceOpen = useUiStore((state) => state.evidenceOpen)
  const setEvidenceOpen = useUiStore((state) => state.setEvidenceOpen)

  const bottomRef = useRef<HTMLDivElement>(null)
  // A conversation is pinned to the filing it was started in, so every
  // citation in the thread stays checkable against the same set of documents.
  const filingName = conversation?.collection ?? draftFiling
  const messages = conversation?.messages ?? []

  // Show the most recent result unless the reader has pinned an older one.
  const shownEvidence = useMemo(() => {
    if (activeEvidence) return activeEvidence
    const last = [...messages].reverse().find((message) => message.result)
    return last?.result ?? null
  }, [activeEvidence, messages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, busy])

  const ask = async (question: string) => {
    if (!filingName) return

    // A conversation is created on the first question, not on arrival, so the
    // sidebar never fills with empty threads.
    const target = conversation ?? store.create(filingName)
    if (!conversation) navigate(`/chat/${target.id}`, { replace: true })

    const asked: Message = {
      id: `m_${Date.now()}`,
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
    }
    store.appendMessage(target.id, asked)
    setBusy(true)

    try {
      const result = await chatApi.askFiling(filingName, question)
      store.appendMessage(target.id, {
        id: `m_${Date.now()}_a`,
        role: 'assistant',
        content: result.answer,
        created_at: new Date().toISOString(),
        result,
      })
      setActiveEvidence(result)
    } catch (caught) {
      const message =
        caught instanceof ApiError ? caught.message : 'The request could not be completed.'
      store.appendMessage(target.id, {
        id: `m_${Date.now()}_e`,
        role: 'assistant',
        content: message,
        created_at: new Date().toISOString(),
        error: message,
      })
    } finally {
      setBusy(false)
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

            {busy && <ThinkingIndicator />}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 border-t border-line bg-canvas px-4 py-4">
          <div className="mx-auto max-w-3xl">
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
