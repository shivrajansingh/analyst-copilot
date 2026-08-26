import { Navigate, Outlet, createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { useAuthStore } from '@/stores/auth.store'
import { ChatPage } from '@/pages/Chat'
import { FilingsPage } from '@/pages/Filings'
import { LoginPage } from '@/pages/Login'
import { SettingsPage } from '@/pages/Settings'

/** Everything behind the shell requires a session. */
function Protected() {
  const user = useAuthStore((state) => state.user)
  if (!user) return <Navigate to="/login" replace />
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <Protected />,
    children: [
      { path: '/', element: <Navigate to="/chat" replace /> },
      { path: '/chat', element: <ChatPage /> },
      { path: '/chat/:conversationId', element: <ChatPage /> },
      { path: '/filings', element: <FilingsPage /> },
      { path: '/settings', element: <SettingsPage /> },
    ],
  },
  { path: '*', element: <Navigate to="/chat" replace /> },
])
