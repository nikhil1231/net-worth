import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// `npm run dev` proxies the API to a running `networth serve` (NETWORTH_API to point elsewhere).
// `npm run build` writes into the Python package, which serves it.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../networth/web/static', emptyOutDir: true, chunkSizeWarningLimit: 1000 },
  server: {
    host: true,  // listen on the LAN, not just localhost
    proxy: { '/api': process.env.NETWORTH_API ?? 'http://127.0.0.1:8000' },
  },
})
