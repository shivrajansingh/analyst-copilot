import { useEffect, useRef, useState } from 'react'

/**
 * Reveal finished text progressively.
 *
 * This is a **reveal, not a stream.** The answer arrives from the API in one
 * piece, already verified — verification runs after the model replies, so
 * streaming tokens from the model would put an unproven figure on screen, which
 * is the one thing this product exists to prevent. What is animated here is the
 * rendering of text that is already final and already proven.
 *
 * Bounded on both ends: fast enough that a long answer never feels withheld,
 * slow enough to read as arriving. Instant under `prefers-reduced-motion`, and
 * instant for text that has already been revealed once — a re-render must not
 * replay the animation and a reload of history must not animate at all.
 */
const TOTAL_MS = 900
const MIN_MS_PER_CHAR = 4

export function useRevealedText(text: string, animate = true): string {
  const [shown, setShown] = useState(() => (animate ? '' : text))
  const revealed = useRef<string | null>(null)

  useEffect(() => {
    if (!animate || revealed.current === text) {
      setShown(text)
      return
    }
    if (typeof window === 'undefined' || !text) {
      setShown(text)
      return
    }
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      setShown(text)
      revealed.current = text
      return
    }

    const duration = Math.min(TOTAL_MS, text.length * MIN_MS_PER_CHAR)
    let frame = 0
    const started = performance.now()

    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / duration)
      // Ease out: the first words appear briskly, the tail settles.
      const eased = 1 - (1 - progress) * (1 - progress)
      setShown(text.slice(0, Math.ceil(eased * text.length)))
      if (progress < 1) {
        frame = requestAnimationFrame(step)
      } else {
        revealed.current = text
      }
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [text, animate])

  return shown
}
