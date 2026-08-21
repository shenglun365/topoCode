import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import { resolve } from 'path'

// M13：architect 子项目独立 vite 工程。
// root=src；build outDir=topoone_app_architect/static（architect 服务自托管，server.py serve）；
// entryFileNames 保持 web/architect/assets/... 结构（与 server.py /web 挂载对齐）。
const ROOT = resolve(__dirname)
const SRC = resolve(__dirname, 'src')
const OUT_DIR = resolve(__dirname, 'topoone_app_architect/static')

export default defineConfig({
  plugins: [vue(), vueJsx()],
  root: SRC,
  envDir: ROOT,
  resolve: {
    alias: {
      '@': SRC,
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5176,
    strictPort: true,
    proxy: {
      '/api/architect': { target: 'http://127.0.0.1:3470', changeOrigin: true, ws: true },
    },
    hmr: { overlay: false },
  },
  cacheDir: resolve(__dirname, 'node_modules/.vite-architect'),
  optimizeDeps: {
    include: ['cytoscape', 'cytoscape-cose-bilkent', 'marked', 'marked-highlight', 'highlight.js', 'mermaid'],
    exclude: ['@/services/ipc', '@/services/*', '@/stores/*', '@/composables/*', '@/utils/*'],
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    rollupOptions: {
      input: {
        architect: resolve(SRC, 'architect.html'),
      },
      output: {
        entryFileNames: 'web/architect/assets/[name].[hash].js',
        chunkFileNames: 'web/architect/assets/chunk-[hash].js',
        assetFileNames: 'web/architect/assets/[name].[hash][extname]',
        manualChunks(id: string) {
          if (id.includes('topoone_app_architect') || id.includes('/src/')) return 'architect/vendor'
        },
      },
    },
  },
})
