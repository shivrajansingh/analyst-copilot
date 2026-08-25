import { useMemo } from 'react'
import { cn } from '@/lib/cn'

/** Collapse whitespace so a snippet matches page text that was flattened from HTML. */
const squash = (value: string) => value.replace(/\s+/g, ' ').trim()

/**
 * Page text with the cited snippet highlighted and the embedding boundary
 * marked.
 *
 * The boundary is the point past which the vector index saw nothing. On a long
 * page that is the difference between evidence the system could find and
 * evidence it could not, and it is invisible unless drawn.
 */
export function PageText({
  text,
  snippet,
  embeddedChars,
  truncated,
  className,
}: {
  text: string
  snippet?: string
  embeddedChars?: number
  truncated?: boolean
  className?: string
}) {
  const segments = useMemo(() => {
    if (!snippet) return null
    // Match on squashed text, then map the hit back to the original offsets.
    const probe = squash(snippet).slice(0, 120).toLowerCase()
    if (probe.length < 12) return null
    const haystack = squash(text).toLowerCase()
    const at = haystack.indexOf(probe)
    if (at < 0) return null

    const ratio = text.length / Math.max(1, squash(text).length)
    const start = Math.max(0, Math.round(at * ratio))
    const end = Math.min(text.length, start + Math.round(squash(snippet).length * ratio) + 8)
    return { before: text.slice(0, start), hit: text.slice(start, end), after: text.slice(end) }
  }, [text, snippet])

  const boundary = truncated && embeddedChars ? embeddedChars : null

  return (
    <div className={cn('font-mono text-[13px] leading-[1.8] text-ink', className)}>
      {segments ? (
        <p className="whitespace-pre-wrap">
          <span className="text-ink-muted">{segments.before}</span>
          <mark className="rounded bg-accent/20 px-0.5 text-ink ring-1 ring-accent/30">
            {segments.hit}
          </mark>
          <span className="text-ink-muted">{segments.after}</span>
        </p>
      ) : boundary ? (
        <p className="whitespace-pre-wrap">
          <span>{text.slice(0, boundary)}</span>
          <span
            className="my-3 flex select-none items-center gap-2 text-2xs uppercase tracking-wider text-declined"
            aria-label="End of the text the embedding index saw"
          >
            <span className="h-px flex-1 bg-declined/40" />
            embedding stopped here
            <span className="h-px flex-1 bg-declined/40" />
          </span>
          <span className="text-ink-subtle">{text.slice(boundary)}</span>
        </p>
      ) : (
        <p className="whitespace-pre-wrap">{text}</p>
      )}
    </div>
  )
}
