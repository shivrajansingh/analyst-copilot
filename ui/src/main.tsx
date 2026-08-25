import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { applyTheme, useUiStore } from './stores/ui.store'
import './styles/globals.css'

// Apply the stored theme before first paint so the app never flashes light.
applyTheme(useUiStore.getState().theme)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
