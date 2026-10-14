import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { devAuthProxyHooks } from '../../scripts/vite-dev-auth'

import vueJsx from '@vitejs/plugin-vue-jsx'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueJsx(),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
          },
  },
  envPrefix: ['VITE_', 'TOPOCODE_'],
  // history 路由基座：gateway 以 /app 挂载 dist（dev 同样在 /app/ 下访问）
  base: '/app/',
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:3456', changeOrigin: true, ...devAuthProxyHooks(), ws: true },
      '/ws': { target: 'http://127.0.0.1:3456', changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: resolve(__dirname, 'index.html'),
      },
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        additionalData: `@use "@topo/web-core/styles/variables.scss" as *;`,
        api: 'modern',
      },
    },
  },
})
