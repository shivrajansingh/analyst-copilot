import { useState, type ReactNode } from 'react'
import { Menu, Moon, Sun, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Sidebar } from './Sidebar'
import { useUiStore } from '@/stores/ui.store'

export function AppShell({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const theme = useUiStore((state) => state.theme)
  const toggleTheme = useUiStore((state) => state.toggleTheme)

  // No effect syncing the document here: the store applies theme and accent
  // itself on every change, at boot and on rehydration. Two mechanisms writing
  // the same attribute is how one of them silently stops mattering.

  return (
    <div className="flex h-dvh overflow-hidden ">
      {/* Persistent rail from lg up; a drawer below it. */}
      <aside className="hidden w-64 shrink-0 border-r border-line lg:block">
        <Sidebar />
      </aside>

      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setMobileNavOpen(false)} aria-hidden />
          <aside className="absolute inset-y-0 left-0 w-72 border-r border-line shadow-panel animate-slide-in">
            <Sidebar onNavigate={() => setMobileNavOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-line px-3 lg:hidden">
          <button
            onClick={() => setMobileNavOpen((open) => !open)}
            aria-label="Toggle navigation"
            className="rounded-lg p-2 text-ink-muted transition-colors hover:bg-surface-raised hover:text-ink"
          >
            {mobileNavOpen ? <Menu className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
          <span className="text-sm font-semibold text-ink">Analyst Copilot</span>
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
        </header>

        <div className="relative min-h-0 flex-1">
          <div className="absolute right-4 top-3 z-30 hidden lg:block">
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
          </div>
          {children}
        </div>
      </div>
    </div>
  )
}

function ThemeToggle({ theme, onToggle }: { theme: 'dark' | 'light'; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      className={cn(
        'rounded-lg border border-line bg-surface/80 p-2 text-ink-subtle backdrop-blur',
        'transition-colors hover:text-ink',
      )}
    >
      {theme === 'dark' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
    </button>
  )
}

export { X }
