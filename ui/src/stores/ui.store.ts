import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { DEFAULT_ACCENT, isAccent, type AccentId } from '@/lib/accents'

type Theme = 'dark' | 'light'

interface UiState {
  theme: Theme
  /** Which accent theme is selected. See `lib/accents.ts`. */
  accent: AccentId
  evidenceOpen: boolean
  sidebarOpen: boolean
  toggleTheme: () => void
  setTheme: (theme: Theme) => void
  setAccent: (accent: AccentId) => void
  setEvidenceOpen: (open: boolean) => void
  setSidebarOpen: (open: boolean) => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: 'dark',
      accent: DEFAULT_ACCENT,
      evidenceOpen: true,
      sidebarOpen: true,
      toggleTheme: () =>
        set((state) => {
          const theme = state.theme === 'dark' ? 'light' : 'dark'
          applyTheme(theme)
          return { theme }
        }),
      setTheme: (theme) => {
        applyTheme(theme)
        set({ theme })
      },
      setAccent: (accent) => {
        applyAccent(accent)
        set({ accent })
      },
      setEvidenceOpen: (evidenceOpen) => set({ evidenceOpen }),
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
    }),
    {
      name: 'analyst-copilot.ui',
      onRehydrateStorage: () => (state) => {
        // Rehydration happens after the module has already applied whatever was
        // read synchronously at boot, so the restored values are pushed to the
        // document here. A stored accent this build no longer offers falls back
        // rather than leaving the app with no accent at all.
        applyTheme(state?.theme ?? 'dark')
        applyAccent(isAccent(state?.accent) ? state.accent : DEFAULT_ACCENT)
      },
    },
  ),
)

/** Keep the `dark` class on <html> in step with the store. */
export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  document.documentElement.style.colorScheme = theme
}

/** Keep `data-accent` on <html> in step with the store. */
export function applyAccent(accent: AccentId) {
  document.documentElement.dataset.accent = isAccent(accent) ? accent : DEFAULT_ACCENT
}
