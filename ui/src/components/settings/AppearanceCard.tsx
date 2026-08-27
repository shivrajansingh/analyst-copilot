import { Check, Moon, Palette, Sun } from 'lucide-react'
import { ACCENTS, type AccentId } from '@/lib/accents'
import { useUiStore } from '@/stores/ui.store'
import { Card, CardHeader } from '@/components/ui/Card'
import { cn } from '@/lib/cn'

/**
 * Appearance: light or dark, and which accent.
 *
 * Each swatch carries its own `data-accent`, so the CSS that themes the app
 * also themes the preview — the sample below is rendered with the real tokens
 * rather than with a hex value copied into TypeScript, which is the only way a
 * swatch can be guaranteed not to lie about the theme it selects.
 *
 * Unlike the rest of this screen, these settings are genuinely writable: they
 * are per-browser preferences, so they need no endpoint and no database.
 */
export function AppearanceCard() {
  const theme = useUiStore((state) => state.theme)
  const setTheme = useUiStore((state) => state.setTheme)
  const accent = useUiStore((state) => state.accent)
  const setAccent = useUiStore((state) => state.setAccent)

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Palette className="h-4 w-4 text-accent" />
            Appearance
          </span>
        }
        description="Stored in this browser. Nothing here changes what the system answers."
      />

      <div className="space-y-5 p-4">
        <fieldset>
          <legend className="mb-2 text-xs font-medium text-ink-muted">Mode</legend>
          <div className="inline-flex rounded-lg border border-line bg-surface-sunken p-0.5">
            {(
              [
                { id: 'light', label: 'Light', icon: Sun },
                { id: 'dark', label: 'Dark', icon: Moon },
              ] as const
            ).map((option) => (
              <button
                key={option.id}
                onClick={() => setTheme(option.id)}
                aria-pressed={theme === option.id}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  theme === option.id
                    ? 'bg-surface text-ink shadow-card'
                    : 'text-ink-muted hover:text-ink',
                )}
              >
                <option.icon className="h-3.5 w-3.5" />
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="mb-2 text-xs font-medium text-ink-muted">Accent</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {ACCENTS.map((option) => (
              <AccentOption
                key={option.id}
                id={option.id}
                label={option.label}
                description={option.description}
                selected={accent === option.id}
                onSelect={() => setAccent(option.id)}
              />
            ))}
          </div>
          <p className="mt-3 text-2xs leading-relaxed text-ink-subtle">
            Only the accent changes. Green, amber and red are reserved for what the system
            proved, declined or failed to do, so no accent is offered near those hues — a
            colour that could be mistaken for a status would undo the one rule the palette
            has.
          </p>
        </fieldset>
      </div>
    </Card>
  )
}

function AccentOption({
  id,
  label,
  description,
  selected,
  onSelect,
}: {
  id: AccentId
  label: string
  description: string
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      // The themed tokens cascade into this subtree, so everything below paints
      // in the accent it selects — including while another accent is active.
      data-accent={id}
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        'group flex items-start gap-3 rounded-lg border p-3 text-left transition-colors',
        selected
          ? 'border-accent/50 bg-accent-soft/60'
          : 'border-line bg-surface hover:border-line-strong',
      )}
    >
      <span className="mt-0.5 flex shrink-0 items-center gap-1" aria-hidden>
        <span className="h-6 w-6 rounded-md bg-accent ring-1 ring-inset ring-ink/10" />
        <span className="h-6 w-3 rounded-sm bg-accent-soft ring-1 ring-inset ring-ink/10" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="text-xs font-semibold text-ink">{label}</span>
          {selected && <Check className="h-3.5 w-3.5 text-accent" />}
        </span>
        <span className="mt-0.5 block text-2xs leading-relaxed text-ink-muted">
          {description}
        </span>
      </span>
    </button>
  )
}
