import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import { resolve } from 'path'

const ROOT = resolve(__dirname)
const STATIC_DIR = resolve(ROOT, 'plugins/reports/static')
const WEB_DIR = resolve(ROOT, 'web')
const ARCHITECT_SRC = resolve(WEB_DIR, 'architect-src')

// Plugin: rewrite /doc → /viewer.html, /chat → /chat.html, /architect → /architect.html
function pageRewritePlugin() {
  const REWRITES: Record<string, string> = {
    '/doc': '/viewer.html',
    '/chat': '/chat.html',
    '/code': '/code.html',
    '/architect': '/architect.html',
  }
  return {
    name: 'page-rewrite',
    configureServer(server: any) {
      server.middlewares.use((req: any, res: any, next: any) => {
        const url = req.url || ''
        // Only rewrite exact matches or query-string variants
        const pathname = url.split('?')[0]
        if (REWRITES[pathname]) {
          req.url = REWRITES[pathname] + (url.includes('?') ? '?' + url.split('?')[1] : '')
        }
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [vue(), vueJsx(), pageRewritePlugin()],
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
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:3456', changeOrigin: true },
      '/web': { target: 'http://127.0.0.1:3456', changeOrigin: true },
      '/static': { target: 'http://127.0.0.1:3456', changeOrigin: true },
    },
    hmr: {
      overlay: false,
    },
  },
  cacheDir: resolve(__dirname, 'node_modules/.vite-web'),
  optimizeDeps: {
    include: ['cytoscape', 'cytoscape-cose-bilkent', 'marked', 'marked-highlight', 'highlight.js', 'mermaid'],
    exclude: ['@/services/ipc', '@/services/*', '@/stores/*', '@/composables/*', '@/utils/*', 'architect-src/*'],
  },
  build: {
    outDir: STATIC_DIR,
    emptyOutDir: false,
    rollupOptions: {
      input: {
        'web-root': resolve(WEB_DIR, 'web-root.html'),
        viewer: resolve(WEB_DIR, 'viewer.html'),
        chat: resolve(WEB_DIR, 'chat.html'),
        architect: resolve(WEB_DIR, 'architect.html'),
      },
      output: {
        entryFileNames: 'web/[name]/assets/[name].[hash].js',
        chunkFileNames: 'web/[name]/assets/chunk-[hash].js',
        assetFileNames: 'web/[name]/assets/[name].[hash][extname]',
        manualChunks(id: string) {
          if (id.includes('architect-src')) return 'architect/vendor'
        },
      },
    },
  },
})
