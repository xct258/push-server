import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 开发时把接口反代到本机 push-server（默认 8383），生产构建走同源。
// push-server 的接口分两段：REST 在 /api 下，历史记录在 /records（无前缀）。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5180,
    // 允许隧道/反代域名访问 dev server。
    allowedHosts: ['.xct258.top'],
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8383',
        changeOrigin: true,
      },
      '/records': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8383',
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: true,
    port: 5181,
    allowedHosts: ['.xct258.top'],
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8383',
        changeOrigin: true,
      },
      '/records': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8383',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
