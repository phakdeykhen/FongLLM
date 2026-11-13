import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the React app runs on :5173 and forwards API and media requests to FastAPI on :8000.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },   // import x from '@/lib/x.js'
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/media': 'http://localhost:8000',
      '/files': 'http://localhost:8000',
    },
  },
})
