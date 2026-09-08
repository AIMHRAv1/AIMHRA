import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [react(), VitePWA({
    registerType: 'autoUpdate',
    manifest: {
      name: 'AIMHRA - Maternal Health Risk Screening',
      short_name: 'AIMHRA',
      theme_color: '#0b6e69',
      background_color: '#f4f7f2',
      display: 'standalone',
      icons: [
        { src: '/icon-192.svg', sizes: '192x192', type: 'image/svg+xml' },
        { src: '/icon-512.svg', sizes: '512x512', type: 'image/svg+xml' },
      ],
    },
  })],
  server: {
    port: 5173,
    proxy: {
      // API calls go to the Django backend; VITE_API_PROXY_TARGET can override.
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
      '/media': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
