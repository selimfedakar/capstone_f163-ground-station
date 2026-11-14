import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev proxy forwards REST (/api) and WebSocket (/ws) traffic to the
// ground-station server so the UI can use relative URLs in all environments.
// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
