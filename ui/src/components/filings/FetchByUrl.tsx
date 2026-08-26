import { useState } from 'react'
import { Link2, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'

/**
 * Add a document by pasting its URL.
 *
 * The filings an analyst wants are usually already on the web — an EDGAR
 * archive link, or the PDF on a company's investor-relations site. Making them
 * download it and drag it back in is two steps of nothing.
 *
 * Validation is deliberately thin here. Whether a URL is fetchable depends on
 * what it redirects to, what content type it serves and what address it
 * resolves to, none of which the browser can see — so this checks only that the
 * scheme is http(s), and lets the server give the real answer.
 */
export function FetchByUrl({
  onFetch,
  busy,
}: {
  onFetch: (url: string, docName?: string) => void
  busy?: boolean
}) {
  const [url, setUrl] = useState('')
  const [docName, setDocName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = () => {
    const trimmed = url.trim()
    if (!trimmed) return
    if (!/^https?:\/\//i.test(trimmed)) {
      setError('Enter an http:// or https:// URL.')
      return
    }
    setError(null)
    onFetch(trimmed, docName.trim() || undefined)
    setUrl('')
    setDocName('')
  }

  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="mb-2.5 flex items-center gap-2">
        <Link2 className="h-3.5 w-3.5 text-ink-subtle" />
        <span className="text-xs font-medium text-ink">Or fetch from a URL</span>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-[3]">
          <span className="sr-only">Document URL</span>
          <Input
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && submit()}
            placeholder="https://www.sec.gov/Archives/…/boeing-10k.htm"
            aria-label="Document URL"
            disabled={busy}
          />
        </label>
        <label className="min-w-0 flex-1">
          <span className="sr-only">Name (optional)</span>
          <Input
            value={docName}
            onChange={(event) => setDocName(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && submit()}
            placeholder="Name (optional)"
            aria-label="Name to store it under, optional"
            disabled={busy}
          />
        </label>
        <Button onClick={submit} disabled={!url.trim() || busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
          Fetch
        </Button>
      </div>

      <p className="mt-2 text-2xs leading-relaxed text-ink-subtle">
        PDF, HTML, Word, Excel, CSV or Markdown. The name is taken from the URL when
        you leave it blank. Private and internal addresses are refused.
      </p>

      {error && (
        <p role="alert" className="mt-2 text-xs text-failed">
          {error}
        </p>
      )}
    </div>
  )
}
