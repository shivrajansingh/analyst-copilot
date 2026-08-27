/**
 * The accent themes offered in Settings.
 *
 * The colours themselves live in `styles/globals.css` under
 * `[data-accent='…']`, not here — this file is only the list, the names and the
 * reason each one exists. Duplicating hex values into TypeScript is how a
 * swatch ends up showing a colour the app no longer uses.
 *
 * Why these five and not a full spectrum: `verified` (green), `declined`
 * (amber) and `failed` (red) are reserved for state, so an accent near those
 * hues would read as a status and undo the one rule the colour system has.
 * That leaves the blues, the teals and the neutrals — which is also, not by
 * coincidence, what professional financial tooling actually uses.
 */
export type AccentId = 'navy' | 'teal' | 'slate' | 'graphite' | 'indigo'

export interface Accent {
  id: AccentId
  label: string
  description: string
}

export const ACCENTS: Accent[] = [
  {
    id: 'navy',
    label: 'Navy',
    description: 'Steel blue. Conservative and institutional — the default.',
  },
  {
    id: 'teal',
    label: 'Teal',
    description: 'Deep cyan. Technical rather than corporate.',
  },
  {
    id: 'slate',
    label: 'Slate',
    description: 'Muted blue-grey. Quieter than navy, still clearly blue.',
  },
  {
    id: 'graphite',
    label: 'Graphite',
    description: 'Near-black. The only colour on screen then means something.',
  },
  {
    id: 'indigo',
    label: 'Indigo',
    description: 'The original violet-blue, kept for anyone who preferred it.',
  },
]

export const DEFAULT_ACCENT: AccentId = 'navy'

/** Whether a stored value is still an accent this build offers. */
export function isAccent(value: unknown): value is AccentId {
  return ACCENTS.some((accent) => accent.id === value)
}
