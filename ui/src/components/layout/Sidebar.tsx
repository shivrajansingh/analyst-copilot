import { useEffect, useMemo } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { FileStack, LogOut, MessageSquarePlus, Settings, Trash2 } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useAuthStore } from '@/stores/auth.store'
import { useConversationStore } from '@/stores/conversations.store'
import { dateBucket } from '@/lib/format'
import { Logo } from '@/components/ui/Logo'

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const signOut = useAuthStore((state) => state.signOut)
  const load = useConversationStore((state) => state.load)
  const loaded = useConversationStore((state) => state.loaded)
  // Subscribed as two stable slices and joined in a memo, rather than as one
  // selector that maps over them. A selector returning a fresh array is compared
  // by reference, so it reported a change on *every* store update — and the
  // store now carries live progress, which updates many times a second.
  const order = useConversationStore((state) => state.order)
  const byId = useConversationStore((state) => state.conversations)
  const conversations = useMemo(
    () => order.map((id) => byId[id]).filter(Boolean),
    [order, byId],
  )
  const remove = useConversationStore((state) => state.remove)

  // History lives in Postgres now: fetch it on arrival, and again when the
  // signed-in user changes, so one user's threads never leak into another's.
  useEffect(() => {
    load()
  }, [load, user?.id])

  // Group by day so a long history stays scannable.
  const groups = conversations.reduce<Record<string, typeof conversations>>((acc, conversation) => {
    const bucket = dateBucket(conversation.updated_at)
    ;(acc[bucket] ??= []).push(conversation)
    return acc
  }, {})

  return (
    <div className="flex h-full flex-col bg-surface-sunken">
      <div className="flex items-center gap-2.5 px-4 py-4">
        <Link to="/chat" onClick={onNavigate} className="flex items-center gap-2.5">
          <Logo className="h-9 w-9" />
          <span className="text-sm font-semibold tracking-tight text-ink">Analyst Copilot</span>
        </Link>
      </div>

      <div className="px-3">
        <button
          onClick={() => {
            navigate('/chat')
            onNavigate?.()
          }}
          className={cn(
            'flex w-full items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2',
            'text-sm font-medium text-ink transition-colors hover:border-accent/40 hover:text-accent',
          )}
        >
          <MessageSquarePlus className="h-4 w-4" />
          New conversation
        </button>
      </div>

      <nav className="scrollbar-slim mt-4 flex-1 overflow-y-auto px-2">
        {!loaded && (
          <p className="px-3 py-6 text-xs leading-relaxed text-ink-subtle">
            Loading conversations…
          </p>
        )}
        {loaded && conversations.length === 0 && (
          <p className="px-3 py-6 text-xs leading-relaxed text-ink-subtle">
            Your conversations appear here. Each one is scoped to a single filing.
          </p>
        )}

        {Object.entries(groups).map(([bucket, items]) => (
          <section key={bucket} className="mb-3">
            <h2 className="px-3 py-1.5 text-2xs font-semibold uppercase tracking-wider text-ink-subtle">
              {bucket}
            </h2>
            <ul className="space-y-0.5">
              {items.map((conversation) => (
                <li key={conversation.id} className="group relative">
                  <NavLink
                    to={`/chat/${conversation.id}`}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cn(
                        'block truncate rounded-lg px-3 py-2 pr-8 text-sm transition-colors',
                        isActive
                          ? 'bg-surface font-medium text-ink'
                          : 'text-ink-muted hover:bg-surface/70 hover:text-ink',
                      )
                    }
                  >
                    <span className="block truncate">{conversation.title}</span>
                    <span className="mt-0.5 block truncate font-mono text-2xs text-ink-subtle">
                      {conversation.collection}
                    </span>
                  </NavLink>
                  <button
                    onClick={() => {
                      void remove(conversation.id)
                      navigate('/chat')
                    }}
                    aria-label={`Delete ${conversation.title}`}
                    className={cn(
                      'absolute right-2 top-2.5 rounded p-1 text-ink-subtle opacity-0 transition-opacity',
                      'hover:text-failed focus-visible:opacity-100 group-hover:opacity-100',
                    )}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </nav>

      <div className="space-y-0.5 border-t border-line p-2">
        {[
          { to: '/filings', icon: FileStack, label: 'Filings' },
          { to: '/settings', icon: Settings, label: 'Settings' },
        ].map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                isActive ? 'bg-surface font-medium text-ink' : 'text-ink-muted hover:bg-surface/70 hover:text-ink',
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}

        <div className="mt-1 flex items-center gap-2.5 rounded-lg px-3 py-2">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-2xs font-semibold text-accent">
            {user?.display_name.slice(0, 1).toUpperCase() ?? '?'}
          </span>
          <span className="min-w-0 flex-1 truncate text-xs text-ink-muted">
            {user?.display_name ?? 'Signed out'}
          </span>
          <button
            onClick={signOut}
            aria-label="Sign out"
            className="rounded p-1 text-ink-subtle transition-colors hover:text-failed"
          >
            <LogOut className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
