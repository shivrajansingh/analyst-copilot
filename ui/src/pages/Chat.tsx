import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AlertTriangle, MessageSquare, PanelRightClose, PanelRightOpen } from 'lucide-react'
import type { ChatResponse, StageEvent, TraceEvent } from '@/api/types'
import { ApiError } from '@/api/client'
import { chatApi } from '@/api/endpoints/chat'
import { useSearchableCollections } from '@/hooks/useCollections'
import { DRAFT_RUN, useConversationStore } from '@/stores/conversations.store'
import { useUiStore } from '@/stores/ui.store'
import { AnswerCard } from '@/components/chat/AnswerCard'
import { ChatBubble } from '@/components/chat/ChatBubble'
import { Composer } from '@/components/chat/Composer'
import { DeclineCard } from '@/components/chat/DeclineCard'
import { FilingPicker } from '@/components/chat/FilingPicker'
import { SessionCost } from '@/components/chat/SessionCost'
import { StoppedCard } from '@/components/chat/StoppedCard'
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator'
import { EvidencePanel } from '@/components/evidence/EvidencePanel'
import { EmptyState } from '@/components/ui/EmptyState'
import { Sheet } from '@/components/ui/Sheet'
import { cn } from '@/lib/cn'
import { truncateTitle } from '@/lib/format'

/**
 * How many trace steps are kept.
 *
 * A 31-reader run emits several hundred. The panel is a tail, not an archive,
 * and holding every step of every answer in memory buys nothing a reader wants.
 */
const MAX_TRACES = 400

/**
 * How long a stop waits for the server to say where it stopped.
 *
 * The `cancelled` event is the better ending — it carries the stage and the
 * reader counts — so the connection is held open just long enough for it to
 * arrive. After that the client hangs up, which stops the work regardless.
 */
const STOP_GRACE_MS = 1200

/**
 * The question a stopped turn was answering.
 *
 * Read back from the thread rather than stored on the marker: the user message
 * immediately before it is the question, and duplicating it would be a second
 * copy that can disagree with the first.
 */
function questionBefore(messages: { id: string; role: string; content: string }[], id: string) {
  const index = messages.findIndex((message) => message.id === id)
  for (let cursor = index - 1; cursor >= 0; cursor--) {
    if (messages[cursor].role === 'user') return messages[cursor].content
  }
  return ''
}

/**
 * How often live traces are written to the store.
 *
 * A deep search emits several hundred steps in a couple of minutes, in bursts.
 * Writing every one re-renders every consumer of the store; writing eight times
 * a second is indistinguishable to a reader watching a collapsed panel. The
 * complete set is attached to the message when the answer arrives, so nothing is
 * lost by coalescing on the way.
 */
const TRACE_FLUSH_MS = 120

export function ChatPage() {
  const { conversationId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const { searchable: filings } = useSearchableCollections()
  const store = useConversationStore()
  const conversation = conversationId ? store.conversations[conversationId] : undefined

  const [draftFiling, setDraftFiling] = useState<string | null>(searchParams.get('filing'))
  // A question put back in the composer by "Ask again". Most stops are followed
  // by a reworded version of the same question, not a repeat of it.
  const [draft, setDraft] = useState<string | null>(null)
  // The answer whose text should animate in — the one that just arrived, never
  // a message re-rendered from history.
  const [revealId, setRevealId] = useState<string | null>(null)
  const [threadError, setThreadError] = useState<string | null>(null)
  const [activeEvidence, setActiveEvidence] = useState<ChatResponse | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)

  // Progress belongs to the thread, not to this view. A question runs for
  // seconds on the fast path and minutes on the deep one, and switching threads
  // used to carry "searching the filing" along with it — an idle thread claiming
  // to be working. Reading it by key means each thread shows only its own run,
  // and a thread that is genuinely working still shows its progress when you
  // come back to it.
  //
  // Stopping is part of the same state for the same reason: ask thread A to stop
  // and thread B must not say "stopping", and two runs at once must not share
  // one abort controller.
  const runKey = conversationId ?? DRAFT_RUN
  const { busy, stage, traces, stopping } = store.runFor(runKey)
  const evidenceOpen = useUiStore((state) => state.evidenceOpen)
  const setEvidenceOpen = useUiStore((state) => state.setEvidenceOpen)

  const [evidenceWidth, setEvidenceWidth] = useState<number>(320)
  const [resizingEvidence, setResizingEvidence] = useState(false)

  const startResize = (e: React.MouseEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startWidth = evidenceWidth
    const onMouseMove = (move: MouseEvent) => {
      const newWidth = startWidth + (startX - move.clientX)
      setEvidenceWidth(Math.max(200, Math.min(600, newWidth)))
    }
    const onMouseUp = () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      // Set on the document, not the panel: the pointer spends the drag over
      // the chat column to the left of the handle, and that is the text a drag
      // would otherwise select.
      document.body.style.userSelect = ''
      setResizingEvidence(false)
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    document.body.style.userSelect = 'none'
    setResizingEvidence(true)
  }

  const bottomRef = useRef<HTMLDivElement>(null)
  // Which thread is on screen *now*. The callbacks in `ask` close over the
  // thread as it was when the question was asked, so they cannot answer that
  // question themselves — and an answer that lands while another thread is open
  // must not touch that thread's evidence rail.
  const viewingRef = useRef(runKey)
  viewingRef.current = runKey
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

  // Everything below is *about the thread being viewed*, so none of it may
  // survive a change of thread: a pinned citation from one filing shown beside
  // another's messages is the same bug as a stray loading indicator, and a
  // thread's error message is not the next thread's problem.
  useEffect(() => {
    setActiveEvidence(null)
    setThreadError(null)
    setRevealId(null)
    setSheetOpen(false)
    setDraft(null)
  }, [conversationId])

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

  // Leaving the chat screen is a stop. Without it the reader goes away and the
  // fan-out carries on reading a 10-K for nobody.
  //
  // Switching between threads does not come through here — the route parameter
  // changes and this component stays mounted — which is what lets a thread keep
  // working while you read another one. This fires on leaving for Filings,
  // Settings or sign-out, and it stops every run, not just the visible one.
  useEffect(() => () => useConversationStore.getState().abortAllRuns(), [])

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

    // Filed under the thread the answer will land in, which is why the thread is
    // created before this point: the run must never be attributed to the view.
    const runId = target?.id ?? DRAFT_RUN
    const controller = new AbortController()
    store.startRun(runId)
    store.updateRun(runId, { controller })
    const collected: TraceEvent[] = []
    let flushedAt = 0
    // A holder, not a plain `let`: the assignment happens inside a callback, and
    // TypeScript's flow analysis would otherwise narrow the read back to null.
    // Read back on cancellation, where a store read would be a stale closure.
    const latest: { stage: StageEvent | null } = { stage: null }
    try {
      const outcome = await chatApi.streamFiling(filingName, question, {
        conversationId: target?.id,
        signal: controller.signal,
        onRun: (run) => store.updateRun(runId, { serverRunId: run.run_id }),
        onStage: (event) => {
          latest.stage = event
          store.updateRun(runId, { stage: event })
        },
        onTrace: (trace) => {
          collected.push(trace)
          const now = performance.now()
          if (now - flushedAt < TRACE_FLUSH_MS) return
          flushedAt = now
          store.updateRun(runId, { traces: collected.slice(-MAX_TRACES) })
        },
      })

      if (outcome.status === 'cancelled') {
        // A stop is not an error and must not land in the red card. The
        // question stays in the thread — it was asked — and the assistant turn
        // becomes a marker of how far the work got before it was stopped.
        // Nothing is persisted: the server records no cancelled exchange.
        const at = outcome.at.stage
          ? outcome.at
          : // The client hung up rather than waiting to be told where it
            // stopped, so fall back to the last milestone it rendered.
            {
              ...outcome.at,
              stage: latest.stage?.stage ?? null,
              done: latest.stage?.done,
              total: latest.stage?.total,
            }
        if (target) {
          store.appendLocal(target.id, {
            id: `m_${Date.now()}_s`,
            role: 'assistant',
            content: '',
            created_at: new Date().toISOString(),
            stopped: at,
            traces: collected.slice(-MAX_TRACES),
          })
        }
        return
      }

      const result = outcome.answer
      const answerId = `m_${Date.now()}_a`
      const stillViewing = viewingRef.current === runId
      // Animate the text in only if the reader is here to see it. Revealing a
      // message they are not looking at just means it animates when they arrive.
      if (stillViewing) setRevealId(answerId)
      if (target) {
        store.appendLocal(target.id, {
          id: answerId,
          role: 'assistant',
          content: result.answer,
          created_at: new Date().toISOString(),
          result,
          traces: collected.slice(-MAX_TRACES),
        })
        // Adopt the server's rows so a reload or a second tab shows the same
        // message ids; optimistic local ids are only ever temporary.
        await store.refresh(target.id)
      }
      // A conversational reply cites nothing, so it must not replace the
      // evidence a previous answer put in the rail — and neither may an answer
      // that arrived for a thread the reader has since navigated away from.
      if (stillViewing && result.mode !== 'conversational') setActiveEvidence(result)
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
      } else if (viewingRef.current === runId) {
        // No thread to record it against, so it goes on screen — but only if
        // this is still the screen the question was asked from.
        setThreadError(message)
      }
    } finally {
      // Clears the stage, the traces, the controller and the stopping flag with
      // it: they were all one run's state.
      store.endRun(runId)
    }
  }

  /**
   * Stop the run in flight — all of it, not just the waiting.
   *
   * Two signals, on purpose. The abort is instant and needs no round trip; the
   * cancel call is the guarantee, because how quickly the server notices a
   * hang-up depends on proxy buffering we do not control. Both set the same
   * token, and setting it twice is free.
   *
   * The endpoint goes first: it is a live connection that will exist for another
   * millisecond, and aborting before asking would throw the request away.
   */
  const stop = () => {
    if (!busy || stopping) return
    // Read from the thread's own run, so stopping the thread on screen cannot
    // reach into another thread that is also working.
    const { serverRunId, controller } = store.runFor(runKey)
    store.updateRun(runKey, { stopping: true })
    if (!serverRunId) {
      // Stopped before the run was even named. Nothing to call, so hang up.
      controller?.abort()
      return
    }
    void chatApi.cancelRun(serverRunId)
    // Give the server the moment it needs to answer with `cancelled` and say
    // where it stopped. If it does not, the abort ends the wait anyway. The
    // controller is captured, not read later: by then it may belong to the next
    // question, and this stop has no business ending that one.
    window.setTimeout(() => controller?.abort(), STOP_GRACE_MS)
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
          {/* What the thread has cost, not what the last answer did. Pushed to
              the right of the bar, beside the evidence toggle: it is a property
              of the conversation, so it belongs in the conversation's own bar
              rather than on any one answer. */}
          <div className="ml-auto flex shrink-0 items-center gap-3">
            <SessionCost
              usages={messages
                .filter((message) => message.role === 'assistant' && !message.error)
                .map((message) => message.result?.usage)}
            />

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
          </div>
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
              ) : message.stopped ? (
                <StoppedCard
                  key={message.id}
                  at={message.stopped}
                  traces={message.traces}
                  onAskAgain={() => setDraft(questionBefore(messages, message.id))}
                />
              ) : message.result?.mode === 'conversational' ? (
                <ChatBubble key={message.id} text={message.content} />
              ) : message.result?.found ? (
                <AnswerCard
                  key={message.id}
                  result={message.result}
                  active={shownEvidence === message.result}
                  onOpenEvidence={() => openEvidence(message.result!)}
                  traces={message.traces}
                  reveal={revealId === message.id}
                />
              ) : (
                <DeclineCard
                  key={message.id}
                  result={message.result!}
                  onOpenEvidence={() => openEvidence(message.result!)}
                />
              ),
            )}

            {busy && <ThinkingIndicator stage={stage} traces={traces} />}
            <div ref={bottomRef} />
          </div>
        </div>

        <div className="shrink-0 border-t border-line bg-surface-sunken px-4 py-4">
          <div className="mx-auto max-w-3xl">
            {threadError && (
              <div className="mb-3 flex items-start gap-2.5 rounded-xl border border-failed/30 bg-failed-soft/40 p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-failed" />
                <p className="text-xs leading-relaxed text-ink-muted">{threadError}</p>
              </div>
            )}
            <Composer
              onSubmit={ask}
              onStop={stop}
              disabled={!filingName}
              busy={busy}
              stopping={stopping}
              draft={draft}
              onDraftUsed={() => setDraft(null)}
              docName={filingName ?? undefined}
              showSuggestions={messages.length === 0}
            />
          </div>
        </div>
      </section>

      {evidenceOpen ? (
        <>
          {/* `hidden lg:block`, like the panel it drags: below `lg` the evidence
              lives in the Sheet, and a drag handle for a panel that is not on
              screen is a one-pixel strip that does nothing. */}
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize evidence panel"
            onMouseDown={startResize}
            className={cn(
              'hidden w-1 shrink-0 cursor-col-resize lg:block',
              resizingEvidence ? 'bg-accent/40' : 'bg-transparent hover:bg-accent/30',
            )}
          />
          <aside
            className="hidden shrink-0 overflow-hidden border-l border-line bg-surface lg:block"
            style={{ width: `${evidenceWidth}px`, minWidth: 200, maxWidth: 600 }}
          >
            <div className="scrollbar-slim h-full overflow-y-auto">
              <h2 className="border-b border-line px-4 py-3 text-2xs font-semibold uppercase tracking-wider text-ink-muted">
                Evidence
              </h2>
              <EvidencePanel result={shownEvidence} />
            </div>
          </aside>
        </>
      ) : (
        <aside className="hidden shrink-0 w-0 overflow-hidden border-l-0 lg:block" />
      )}

      <Sheet open={sheetOpen} onClose={() => setSheetOpen(false)} title="Evidence">
        <EvidencePanel result={shownEvidence} />
      </Sheet>
    </div>
  )
}
