import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import { resolve } from 'path'

// Architect 独立 SPA 构建 → plugins/architect/static/ (由 architect 服务自身提供)。
const ROOT = resolve(__dirname)
const WEB_DIR = resolve(ROOT, 'web')
const ARCHITECT_SRC = resolve(WEB_DIR, 'architect-src')
const OUT_DIR = resolve(ROOT, 'plugins/architect/static')

export default defineConfig({
  plugins: [vue(), vueJsx()],
  root: WEB_DIR,
  envDir: ROOT,
  resolve: {
    alias: {
      '@web': WEB_DIR,
      '@': ARCHITECT_SRC,
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5175,
    strictPort: true,
    proxy: {
      '/api/architect': { target: 'http://127.0.0.1:3470', changeOrigin: true, ws: true },
    },
    hmr: { overlay: false },
  },
  cacheDir: resolve(__dirname, 'node_modules/.vite-architect'),
  optimizeDeps: {
    include: ['cytoscape', 'cytoscape-cose-bilkent', 'marked', 'marked-highlight', 'highlight.js', 'mermaid'],
    exclude: ['@/services/ipc', '@/services/*', '@/stores/*', '@/composables/*', '@/utils/*', 'architect-src/*'],
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    rollupOptions: {
      input: {
        architect: resolve(WEB_DIR, 'architect.html'),
      },
      output: {
        entryFileNames: 'web/architect/assets/[name].[hash].js',
        chunkFileNames: 'web/architect/assets/chunk-[hash].js',
        assetFileNames: 'web/architect/assets/[name].[hash][extname]',
        manualChunks(id: string) {
          if (id.includes('architect-src')) return 'architect/vendor'
        },
      },
    },
  },
})