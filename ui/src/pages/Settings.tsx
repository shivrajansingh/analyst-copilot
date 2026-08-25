import { AlertTriangle, Cpu, Sparkles } from 'lucide-react'
import { Card, CardHeader } from '@/components/ui/Card'
import { Input } from '@/components/ui/Input'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { useHealth } from '@/hooks/useHealth'
import { useFilings } from '@/hooks/useFilings'

/**
 * Provider settings.
 *
 * Read-only until the `/settings/providers` endpoints exist: the values shown
 * are the ones the API reports it is actually using, so the screen is honest
 * about the live configuration rather than presenting inputs that silently do
 * nothing.
 */
export function SettingsPage() {
  const { data: health } = useHealth()
  const { data: filings } = useFilings()
  const indexedCount = filings?.filter((filing) => filing.vector.state === 'ready').length ?? 0
  const embeddingModel = filings?.find((f) => f.vector.model)?.vector.model

  return (
    <div className="scrollbar-slim h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-5 py-8 lg:px-8">
        <header className="mb-6">
          <h1 className="text-lg font-semibold tracking-tight text-ink">Settings</h1>
          <p className="mt-1 text-sm text-ink-muted">
            The model endpoints this service answers with.
          </p>
        </header>

        <div className="space-y-4">
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-accent" />
                  Chat model
                </span>
              }
              description="Reads the retrieved excerpts and drafts the answer."
              action={<Badge tone="verified">connected</Badge>}
            />
            <div className="grid gap-4 p-4 sm:grid-cols-2">
              <Input label="Model" value={health?.chat_model ?? ''} readOnly mono />
              <Input label="Base URL" value="configured server-side" readOnly />
            </div>
          </Card>

          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-accent" />
                  Embedding model
                </span>
              }
              description="Embeds every page at index time and each question at query time."
              action={<Badge tone="verified">connected</Badge>}
            />
            <div className="grid gap-4 p-4 sm:grid-cols-2">
              <Input label="Model" value={health?.embedding_model ?? ''} readOnly mono />
              <Input
                label="Indices built with"
                value={embeddingModel ?? '—'}
                readOnly
                mono
                hint={`${indexedCount} filings embedded`}
              />
            </div>

            {/* The single biggest footgun in the product. */}
            <div className="m-4 mt-0 flex items-start gap-2.5 rounded-lg border border-declined/30 bg-declined-soft/40 p-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-declined" />
              <p className="text-xs leading-relaxed text-ink-muted">
                <strong className="font-semibold text-ink">
                  Changing the embedding model invalidates every index.
                </strong>{' '}
                The same page text maps into a different vector space, so all {indexedCount}{' '}
                embedded filings would need rebuilding before they could be searched again.
              </p>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Editing these from the UI"
              description="Not wired up yet — and deliberately not faked."
            />
            <div className="p-4">
              <p className="text-xs leading-relaxed text-ink-muted">
                Provider configuration is read from the server environment today. Editing it
                here needs the <code className="font-mono text-ink">/settings/providers</code>{' '}
                endpoints, a Postgres row to store it and encryption for the API keys. Until
                those exist this screen reports the live configuration rather than offering
                inputs that would silently do nothing.
              </p>
              <Button variant="secondary" size="sm" className="mt-3" disabled>
                Edit providers
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
