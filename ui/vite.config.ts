import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    host: true,
    port: 5173,
    // The UI is also reachable through the public tunnel, so accept its host.
    allowedHosts: ['analyst-copilot.technicalheist.com'],
    // The app always calls same-origin `/api`. In development Vite forwards it
    // to the backend; in production nginx does. Nothing bakes an API host into
    // the bundle, so the same build runs anywhere.
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
})
