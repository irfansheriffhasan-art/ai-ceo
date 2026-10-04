import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the dashboard runs on :5173 and proxies the API (same-origin for cookies & SSE).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
})
