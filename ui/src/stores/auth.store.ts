import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { setAuthToken } from '@/api/client'

export interface User {
  id: string
  username: string
  display_name: string
  role: 'analyst' | 'admin'
}

/**
 * Demo authentication.
 *
 * The credential check runs in the browser because the API has no `/auth`
 * endpoints yet. It is deliberately isolated in `signIn` so that swapping in
 * `POST /api/v1/auth/login` is a change to one function and nothing else — the
 * store's shape, the token plumbing and every consumer stay as they are.
 *
 * This is NOT a security boundary and is labelled as such in the UI.
 */
const DEMO_USERS: Record<string, { password: string; user: User }> = {
  demo: {
    password: 'demo1234',
    user: { id: 'u_demo', username: 'demo', display_name: 'Demo Analyst', role: 'analyst' },
  },
  analyst: {
    password: 'analyst1234',
    user: { id: 'u_analyst', username: 'analyst', display_name: 'Analyst', role: 'analyst' },
  },
}

export const DEMO_CREDENTIALS = { username: 'demo', password: 'demo1234' }

interface AuthState {
  user: User | null
  token: string | null
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,

      signIn: async (username, password) => {
        // Deliberate small delay: an instant transition reads as a bug, and the
        // button's pending state needs somewhere to live.
        await new Promise((resolve) => setTimeout(resolve, 350))
        const record = DEMO_USERS[username.trim().toLowerCase()]
        if (!record || record.password !== password) {
          throw new Error('That username and password do not match.')
        }
        const token = `demo.${btoa(record.user.id)}.${Date.now()}`
        setAuthToken(token)
        set({ user: record.user, token })
      },

      signOut: () => {
        setAuthToken(null)
        set({ user: null, token: null })
      },
    }),
    {
      name: 'analyst-copilot.auth',
      onRehydrateStorage: () => (state) => {
        // Rehydration happens after the module loads, so the client needs the
        // restored token pushed to it explicitly.
        setAuthToken(state?.token ?? null)
      },
    },
  ),
)
