import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'dark' | 'light'

interface UiState {
  theme: Theme
  evidenceOpen: boolean
  sidebarOpen: boolean
  toggleTheme: () => void
  setEvidenceOpen: (open: boolean) => void
  setSidebarOpen: (open: boolean) => void
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: 'dark',
      evidenceOpen: true,
      sidebarOpen: true,
      toggleTheme: () => set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
      setEvidenceOpen: (evidenceOpen) => set({ evidenceOpen }),
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
    }),
    { name: 'analyst-copilot.ui' },
  ),
)

/** Keep the `dark` class on <html> in step with the store. */
export function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  document.documentElement.style.colorScheme = theme
}
