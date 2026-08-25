import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ShieldCheck, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { DEMO_CREDENTIALS, useAuthStore } from '@/stores/auth.store'

export function LoginPage() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const signIn = useAuthStore((state) => state.signIn)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/chat" replace />

  const submit = async (event: FormEvent, credentials = { username, password }) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(credentials.username, credentials.password)
      navigate('/chat', { replace: true })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Sign in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-lg font-bold text-accent-ink">
            A
          </span>
          <h1 className="text-xl font-semibold tracking-tight text-ink">Analyst Copilot</h1>
          <p className="mt-1.5 text-sm text-ink-muted">Answers you can prove.</p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-2xl border border-line bg-surface p-6 shadow-card"
        >
          <Input
            name="username"
            label="Username"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="demo"
          />
          <Input
            name="password"
            type="password"
            label="Password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••"
            error={error ?? undefined}
          />

          <Button type="submit" loading={busy} className="w-full" size="lg">
            Sign in
          </Button>

          <div className="flex items-center gap-3">
            <span className="h-px flex-1 bg-line" />
            <span className="text-2xs uppercase tracking-wider text-ink-subtle">or</span>
            <span className="h-px flex-1 bg-line" />
          </div>

          {/* A reviewer must never be blocked at the door. */}
          <Button
            type="button"
            variant="secondary"
            size="lg"
            className="w-full"
            disabled={busy}
            onClick={(event) => submit(event, DEMO_CREDENTIALS)}
          >
            <Sparkles className="h-4 w-4" />
            Continue as demo user
          </Button>

          <p className="text-center font-mono text-2xs text-ink-subtle">
            {DEMO_CREDENTIALS.username} / {DEMO_CREDENTIALS.password}
          </p>
        </form>

        <p className="mt-4 flex items-start gap-2 rounded-lg border border-declined/25 bg-declined-soft/40 p-3 text-2xs leading-relaxed text-ink-muted">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-declined" />
          <span>
            <strong className="font-semibold text-ink">Demo authentication.</strong> Credentials
            are checked in the browser and this is not a security boundary. It will move behind
            the API before anything real is stored.
          </span>
        </p>
      </div>
    </main>
  )
}
