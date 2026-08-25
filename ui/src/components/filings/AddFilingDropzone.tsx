import { useCallback, useRef, useState } from 'react'
import { FileUp, Upload } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/Button'
import { formatBytes } from '@/lib/format'

const ACCEPTED = ['.htm', '.html']
const MAX_BYTES = 32 * 1024 * 1024

/**
 * The "Add filing" control.
 *
 * Type and size are checked here as well as on the server, so an obvious
 * mistake is caught before 16 MB crosses the wire — the server check remains
 * the one that counts.
 */
export function AddFilingDropzone({
  onSelect,
  busy,
}: {
  onSelect: (file: File) => void
  busy?: boolean
}) {
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const accept = useCallback(
    (file: File | undefined) => {
      if (!file) return
      const suffix = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
      if (!ACCEPTED.includes(suffix)) {
        setError(`${suffix || 'That file'} is not an SEC HTML filing. Expected .htm or .html.`)
        return
      }
      if (file.size > MAX_BYTES) {
        setError(`${formatBytes(file.size)} is over the ${formatBytes(MAX_BYTES)} limit.`)
        return
      }
      setError(null)
      onSelect(file)
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
          accept(event.dataTransfer.files?.[0])
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
        aria-label="Add a filing"
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
            dragging ? 'border-accent/40 bg-accent/10 text-accent' : 'border-line bg-surface-raised text-ink-subtle',
          )}
        >
          {dragging ? <FileUp className="h-5 w-5" /> : <Upload className="h-5 w-5" />}
        </div>
        <div>
          <p className="text-sm font-medium text-ink">
            {dragging ? 'Drop to add this filing' : 'Drop a 10-K or 10-Q here'}
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            or <span className="text-accent underline underline-offset-2">browse your files</span>
            {' · '}
            .htm or .html, up to {formatBytes(MAX_BYTES)}
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(',')}
          className="sr-only"
          onChange={(event) => {
            accept(event.target.files?.[0])
            event.target.value = ''
          }}
        />
      </div>
      {error && (
        <p role="alert" className="mt-2 flex items-center gap-2 text-xs text-failed">
          {error}
          <Button variant="ghost" size="sm" onClick={() => setError(null)}>
            Dismiss
          </Button>
        </p>
      )}
    </div>
  )
}
