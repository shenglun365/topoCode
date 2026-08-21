import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// M12：chat 子项目独立 vite 工程（单 entry：chat.html）。
// root=src；outDir=dist；base=/chat/（资产引 /chat/assets/...，由 gateway /chat 挂载 serve）。
// gateway vue_routes serve /chat 页面（dist/chat.html）；manifest static_mount=["/chat"] serve 资产。
const SRC = resolve(__dirname, 'src')
const DIST = resolve(__dirname, 'dist')

export default defineConfig({
  plugins: [vue()],
  base: '/chat/',
  root: SRC,
  resolve: {
    alias: { '@': SRC },
  },
  server: {
    host: '0.0.0.0',
    port: 5175,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:3456', changeOrigin: true, ws: true },
      '/static': { target: 'http://127.0.0.1:3456', changeOrigin: true },
    },
    hmr: { overlay: false },
  },
  cacheDir: resolve(__dirname, 'node_modules/.vite-chat'),
  build: {
    outDir: DIST,
    emptyOutDir: true,
    rollupOptions: {
      input: {
        chat: resolve(SRC, 'chat.html'),
      },
    },
  },
})
