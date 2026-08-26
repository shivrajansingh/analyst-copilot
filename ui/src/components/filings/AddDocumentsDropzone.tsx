import { useCallback, useRef, useState } from 'react'
import { FileUp, Upload, X } from 'lucide-react'
import type { SourceFormat } from '@/api/types'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/Button'
import { formatBytes } from '@/lib/format'

/** Every extension the parser registry handles. Kept in sync with `formats.py`. */
const ACCEPTED: Record<string, SourceFormat> = {
  '.pdf': 'pdf',
  '.htm': 'html',
  '.html': 'html',
  '.xhtml': 'html',
  '.docx': 'docx',
  '.xlsx': 'xlsx',
  '.xlsm': 'xlsx',
  '.csv': 'csv',
  '.tsv': 'csv',
  '.md': 'markdown',
  '.markdown': 'markdown',
  '.txt': 'text',
  '.text': 'text',
}

const MAX_BYTES = 64 * 1024 * 1024

/** First bytes that prove a file is what its name claims. */
const MAGIC: Partial<Record<SourceFormat, { bytes: number[]; label: string }>> = {
  pdf: { bytes: [0x25, 0x50, 0x44, 0x46], label: '%PDF-' },
  docx: { bytes: [0x50, 0x4b, 0x03, 0x04], label: 'a ZIP container' },
  xlsx: { bytes: [0x50, 0x4b, 0x03, 0x04], label: 'a ZIP container' },
}

export interface RejectedFile {
  filename: string
  message: string
}

export function suffixOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot === -1 ? '' : name.slice(dot).toLowerCase()
}

/**
 * The "Add documents" control: many files, one filing, one request.
 *
 * Checks run here as well as on the server, and the server's remain the ones
 * that count. Doing them in the browser matters more than usual now that PDFs
 * are accepted: a 60 MB upload that the server was always going to refuse is a
 * minute of the analyst's time spent to learn the file had the wrong extension.
 *
 * A bad file never blocks the good ones. Rejects are reported alongside the
 * accepted files rather than replacing them.
 */
export function AddDocumentsDropzone({
  onSelect,
  busy,
  filingName,
}: {
  onSelect: (files: File[]) => void
  busy?: boolean
  filingName?: string | null
}) {
  const [dragging, setDragging] = useState(false)
  const [rejected, setRejected] = useState<RejectedFile[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  const accept = useCallback(
    async (fileList: FileList | null) => {
      const files = Array.from(fileList ?? [])
      if (files.length === 0) return

      const good: File[] = []
      const bad: RejectedFile[] = []

      for (const file of files) {
        const problem = await checkFile(file)
        if (problem) bad.push({ filename: file.name, message: problem })
        else good.push(file)
      }

      setRejected(bad)
      if (good.length > 0) onSelect(good)
    },
    [onSelect],
  )

  return (
    <div>
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          void accept(event.dataTransfer.files)
        }}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            inputRef.current?.click()
          }
        }}
        role="button"
        tabIndex={0}
        aria-label={filingName ? `Add documents to ${filingName}` : 'Add documents'}
        className={cn(
          'group flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl',
          'border-2 border-dashed px-6 py-10 text-center transition-all duration-200',
          dragging
            ? 'border-accent bg-accent-soft/60 scale-[1.01]'
            : 'border-line bg-surface hover:border-line-strong hover:bg-surface-raised',
          busy && 'pointer-events-none opacity-60',
        )}
      >
        <div
          className={cn(
            'flex h-11 w-11 items-center justify-center rounded-xl border transition-colors',
            dragging
              ? 'border-accent/40 bg-accent/10 text-accent'
              : 'border-line bg-surface-raised text-ink-subtle',
          )}
        >
          {dragging ? <FileUp className="h-5 w-5" /> : <Upload className="h-5 w-5" />}
        </div>
        <div>
          <p className="text-sm font-medium text-ink">
            {dragging
              ? `Drop to add to ${filingName ?? 'this filing'}`
              : 'Drop documents here'}
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            or <span className="text-accent underline underline-offset-2">browse your files</span>
            {' · '}
            PDF, HTML, Word, Excel, CSV, Markdown
            {' · '}
            up to {formatBytes(MAX_BYTES)} each
          </p>
          <p className="mt-1 text-2xs text-ink-subtle">
            Select several at once — each is indexed separately.
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={Object.keys(ACCEPTED).join(',')}
          className="sr-only"
          onChange={(event) => {
            void accept(event.target.files)
            event.target.value = ''
          }}
        />
      </div>

      {rejected.length > 0 && (
        <ul role="alert" className="mt-2 space-y-1">
          {rejected.map((item) => (
            <li
              key={item.filename}
              className="flex items-start justify-between gap-2 rounded-lg border border-failed/30 bg-failed-soft/40 px-3 py-2"
            >
              <span className="min-w-0 text-xs text-ink">
                <span className="font-mono">{item.filename}</span>
                <span className="text-ink-muted"> — {item.message}</span>
              </span>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`Dismiss ${item.filename}`}
                onClick={() =>
                  setRejected((current) =>
                    current.filter((entry) => entry.filename !== item.filename),
                  )
                }
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Returns a message when the file cannot be accepted, or null when it can. */
async function checkFile(file: File): Promise<string | null> {
  const suffix = suffixOf(file.name)
  const format = ACCEPTED[suffix]
  if (!format) {
    return `${suffix || 'that type'} is not supported. Try PDF, HTML, Word, Excel or CSV.`
  }
  if (file.size > MAX_BYTES) {
    return `${formatBytes(file.size)} is over the ${formatBytes(MAX_BYTES)} limit.`
  }

  const magic = MAGIC[format]
  if (magic) {
    const head = new Uint8Array(await file.slice(0, magic.bytes.length).arrayBuffer())
    const matches =
      head.length === magic.bytes.length &&
      magic.bytes.every((byte, index) => head[index] === byte)
    if (!matches) {
      return `named ${suffix} but does not begin with ${magic.label}.`
    }
  }
  return null
}
