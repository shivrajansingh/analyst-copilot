import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { applyAccent, applyTheme, useUiStore } from './stores/ui.store'
import './styles/globals.css'

// Apply the stored theme and accent before first paint, so the app never
// flashes the wrong palette on the way in.
applyTheme(useUiStore.getState().theme)
applyAccent(useUiStore.getState().accent)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
