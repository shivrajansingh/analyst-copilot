import { cn } from '@/lib/cn'

export function Logo({ className = '' }: { className?: string }) {
  return (
    <img
      src="/logo.png"
      // Merged rather than concatenated: `h-7 w-7` plus a caller's `h-9 w-9`
      // leaves both in the class list, and which one wins is decided by CSS
      // order rather than by the caller. `cn` lets the later utility win.
      className={cn('h-7 w-7 rounded-full', className)}
      // Empty alt with aria-hidden, not a label with aria-hidden: the link
      // already reads "Analyst Copilot" beside it, so announcing the mark
      // again is noise -- but saying both at once said two opposite things.
      alt=""
      aria-hidden="true"
    />
  )
}
