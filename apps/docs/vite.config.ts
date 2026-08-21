import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// M11：docs 子项目独立 vite 工程（viewer + web-root 双 entry）。
// root=src；outDir=dist（html 入口在 dist 根，JS 分目录 [name]/assets/）。
// base=/docs/：资产引 /docs/<name>/assets/...，由 gateway /docs 挂载 serve（apps/docs/dist）。
// gateway vue_routes 从 static_dir（apps/docs/dist）serve viewer.html / web-root.html（页面 URL 不变）。
const SRC = resolve(__dirname, 'src')
const DIST = resolve(__dirname, 'dist')

// dev 便利：/doc · /code → viewer.html（与原 vite.web.config.ts 一致）
function pageRewritePlugin() {
  const REWRITES: Record<string, string> = {
    '/doc': '/viewer.html',
    '/code': '/viewer.html',
  }
  return {
    name: 'page-rewrite',
    configureServer(server: any) {
      server.middlewares.use((req: any, _res: any, next: any) => {
        const url = req.url || ''
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
  plugins: [vue(), pageRewritePlugin()],
  base: '/docs/',
  root: SRC,
  resolve: {
    alias: { '@': SRC },
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:3456', changeOrigin: true, ws: true },
      '/static': { target: 'http://127.0.0.1:3456', changeOrigin: true },
    },
    hmr: { overlay: false },
  },
  cacheDir: resolve(__dirname, 'node_modules/.vite-docs'),
  build: {
    outDir: DIST,
    emptyOutDir: true,
    rollupOptions: {
      input: {
        viewer: resolve(SRC, 'viewer.html'),
        'web-root': resolve(SRC, 'web-root.html'),
      },
      output: {
        entryFileNames: '[name]/assets/[name].[hash].js',
        chunkFileNames: '[name]/assets/chunk-[hash].js',
        assetFileNames: '[name]/assets/[name].[hash][extname]',
      },
    },
  },
})
