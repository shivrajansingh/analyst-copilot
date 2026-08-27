import { MessageCircle } from 'lucide-react'

/**
 * A reply that is not an answer from a filing.
 *
 * Greetings and questions about the assistant itself get this: plain prose, no
 * citation, no verified badge. The distinction is deliberate and visible — an
 * evidenced answer looks like evidence, and this does not, so nothing said here
 * can be mistaken for something the filing proves.
 */
export function ChatBubble({ text }: { text: string }) {
  return (
    <div className="flex items-start gap-2.5 animate-fade-up">
      <span
        className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-sunken"
        aria-hidden
      >
        <MessageCircle className="h-3.5 w-3.5 text-ink-subtle" />
      </span>
      <p className="min-w-0 whitespace-pre-wrap text-sm leading-relaxed text-ink">{text}</p>
    </div>
  )
}
