import { format, formatDistanceToNowStrict, isToday, isYesterday } from 'date-fns'

export function formatBytes(bytes?: number | null): string {
  if (bytes == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`
}

/** `4:12` — used for elapsed indexing time against the 10-minute budget. */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const mins = Math.floor(total / 60)
  const secs = total % 60
  return `${mins}:${String(secs).padStart(2, '0')}`
}

export function formatTimestamp(unixSeconds?: number | null): string {
  if (unixSeconds == null) return '—'
  return format(new Date(unixSeconds * 1000), 'd MMM yyyy, HH:mm')
}

export function formatRelative(iso: string): string {
  return `${formatDistanceToNowStrict(new Date(iso))} ago`
}

/** Buckets for the conversation sidebar. */
export function dateBucket(iso: string): string {
  const date = new Date(iso)
  if (isToday(date)) return 'Today'
  if (isYesterday(date)) return 'Yesterday'
  return format(date, 'MMMM yyyy')
}

/** A thread's title, taken from its first question. */
export function truncateTitle(text: string): string {
  const clean = text.trim().replace(/\s+/g, ' ')
  return clean.length > 60 ? `${clean.slice(0, 57)}…` : clean
}

/** `3M_2018_10K` → `3M · 2018 · 10-K`, for headings where the stem is noise. */
export function prettyDocName(docName: string): string {
  return docName.replace(/_/g, ' · ').replace(/10K/g, '10-K').replace(/10Q/g, '10-Q')
}

export function scoreBar(score: number, max: number): number {
  if (max <= 0) return 0
  return Math.max(2, Math.round((score / max) * 100))
}
