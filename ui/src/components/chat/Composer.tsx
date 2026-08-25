import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowUp } from 'lucide-react'
import { cn } from '@/lib/cn'

const SUGGESTIONS = [
  'What was capital expenditure this year?',
  'What drove the change in operating margin?',
  'What is total debt at year end?',
]

export function Composer({
  onSubmit,
  disabled,
  busy,
  docName,
  showSuggestions,
}: {
  onSubmit: (question: string) => void
  disabled?: boolean
  busy?: boolean
  docName?: string
  showSuggestions?: boolean
}) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

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
  }

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
          disabled={disabled || busy}
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
      </form>

      <p className="px-1 text-2xs text-ink-subtle">
        Answers are checked against the filing before they appear. When the evidence is not
        there, the assistant declines.
      </p>
    </div>
  )
}
