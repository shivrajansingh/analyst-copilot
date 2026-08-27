import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp, Loader2, Square } from 'lucide-react'
import { cn } from '@/lib/cn'

const SUGGESTIONS = [
  'What was capital expenditure this year?',
  'What drove the change in operating margin?',
  'What is total debt at year end?',
]

/**
 * The composer, and the one control that both sends and stops.
 *
 * Send becomes Stop in the same slot, at the same size, so nothing moves under
 * the cursor at the moment the analyst decides to reach for it. Two buttons
 * would mean aiming; one means the thing under the pointer is always the thing
 * that applies.
 *
 * `stopping` is a real state rather than an optimistic lie. The server is
 * unwinding the model calls already in flight, and saying so for the second that
 * takes is more honest than claiming to have stopped something that has not.
 */
export function Composer({
  onSubmit,
  onStop,
  disabled,
  busy,
  stopping,
  draft,
  onDraftUsed,
  docName,
  showSuggestions,
}: {
  onSubmit: (question: string) => void
  /** Stop the run in flight. Absent means this composer cannot stop anything. */
  onStop?: () => void
  disabled?: boolean
  busy?: boolean
  /** The stop was asked for and the server is still unwinding. */
  stopping?: boolean
  /** Text to put in the box — "Ask again" on a stopped turn. */
  draft?: string | null
  onDraftUsed?: () => void
  docName?: string
  showSuggestions?: boolean
}) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const canStop = Boolean(busy && onStop)

  // A question handed back by "Ask again": filled in and focused, not sent. The
  // point of stopping was usually that the question needed changing.
  useEffect(() => {
    if (draft === null || draft === undefined) return
    setValue(draft)
    textareaRef.current?.focus()
    onDraftUsed?.()
  }, [draft, onDraftUsed])

  // Grow with the question, up to a ceiling — analysts paste long prompts.
  useEffect(() => {
    const node = textareaRef.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${Math.min(node.scrollHeight, 200)}px`
  }, [value])

  const submit = (question: string) => {
    const trimmed = question.trim()
    if (trimmed.length < 3 || disabled || busy) return
    onSubmit(trimmed)
    setValue('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift+Enter breaks the line.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit(value)
    }
    // Esc stops, as it does in every other chat product. It works from the
    // textarea because the textarea keeps focus during a run — see below.
    if (event.key === 'Escape' && canStop && !stopping) {
      event.preventDefault()
      onStop?.()
    }
  }

  // And from anywhere else on the page: the analyst may have clicked into the
  // evidence rail while the readers worked.
  useEffect(() => {
    if (!canStop || stopping) return
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') onStop?.()
    }
    window.addEventListener('keydown', onEscape)
    return () => window.removeEventListener('keydown', onEscape)
  }, [canStop, stopping, onStop])

  return (
    <div className="space-y-2.5">
      {showSuggestions && !value && (
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              onClick={() => submit(suggestion)}
              disabled={disabled || busy}
              className={cn(
                'rounded-full border border-line bg-surface px-3 py-1.5 text-xs text-ink-muted',
                'transition-colors hover:border-accent/40 hover:bg-accent-soft hover:text-accent',
                'disabled:pointer-events-none disabled:opacity-50',
              )}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          submit(value)
        }}
        className={cn(
          'flex items-end gap-2 rounded-xl border bg-surface p-2 shadow-card transition-colors',
          'focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/20',
          disabled ? 'border-line opacity-60' : 'border-line',
        )}
      >
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          // Not disabled during a run: a disabled field drops focus, which would
          // leave Esc landing nowhere at exactly the moment it is wanted. The
          // next question can be typed while this one is still being answered;
          // `submit` is what refuses to send it early.
          disabled={disabled}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            disabled
              ? 'Select a filing to ask about'
              : `Ask about ${docName ?? 'this filing'}…`
          }
          aria-label="Your question"
          className={cn(
            'scrollbar-slim max-h-[200px] flex-1 resize-none bg-transparent px-2 py-2',
            'text-sm text-ink placeholder:text-ink-subtle focus:outline-none',
          )}
        />
        {canStop ? (
          <button
            type="button"
            onClick={onStop}
            disabled={stopping}
            aria-label={stopping ? 'Stopping' : 'Stop this answer'}
            title="Stop (Esc)"
            className={cn(
              'flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg border',
              'transition-all duration-150',
              stopping
                ? 'w-auto border-line bg-surface-sunken px-3 text-2xs text-ink-muted'
                : 'w-9 border-failed/45 bg-failed-soft text-failed hover:bg-failed/15',
            )}
          >
            {stopping ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                Stopping…
              </>
            ) : (
              <Square className="h-3.5 w-3.5 fill-current" aria-hidden />
            )}
          </button>
        ) : (
          <button
            type="submit"
            disabled={disabled || busy || value.trim().length < 3}
            aria-label="Send question"
            className={cn(
              'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-all duration-150',
              'bg-accent text-accent-ink hover:bg-accent/90',
              'disabled:bg-surface-sunken disabled:text-ink-subtle',
            )}
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        )}
      </form>

      <p className="px-1 text-2xs text-ink-subtle">
        {canStop ? (
          stopping ? (
            'Unwinding the model calls already in flight.'
          ) : (
            <>
              Working. Press <kbd className="rounded border border-line-strong px-1 font-mono">Esc</kbd>{' '}
              or the square to stop — every reader stops with it.
            </>
          )
        ) : (
          'Answers are checked against the filing before they appear. When the evidence is not there, the assistant declines.'
        )}
      </p>
    </div>
  )
}
