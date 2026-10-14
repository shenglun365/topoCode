import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { devAuthProxyHooks } from '../../scripts/vite-dev-auth'

import { resolve } from 'path'

// M11：docs 子项目独立 vite 工程（viewer + web-root 双 entry）。
// root=src；outDir=dist（html 入口在 dist 根，JS 分目录 [name]/assets/）。
// base=/docs/：资产引 /docs/<name>/assets/...，由 gateway /docs 挂载 serve（apps/docs/dist）。
// gateway vue_routes 从 static_dir（apps/docs/dist）serve viewer.html / web-root.html（页面 URL 不变）。
const SRC = resolve(__dirname, 'src')
const DIST = resolve(__dirname, 'dist')

// dev 便利：/doc · /code → viewer.html，/projects · /web-root → web-root.html
// （302 到带 base 的真实入口：相对模块路径必须按 /docs/ 前缀解析，纯 URL 重写会导致
//   ./entry-*.ts 落到站点根上 404；与生产网关挂载路径对齐）
function pageRewritePlugin() {
  const REWRITES: Record<string, string> = {
    '/doc': '/docs/viewer.html',
    '/code': '/docs/viewer.html',
    '/projects': '/docs/web-root.html',
    '/web-root': '/docs/web-root.html',
  }
  return {
    name: 'page-rewrite',
    configureServer(server: any) {
      server.middlewares.use((req: any, res: any, next: any) => {
        const url = req.url || ''
        const pathname = url.split('?')[0]
        const target = REWRITES[pathname]
        if (target) {
          const qs = url.includes('?') ? '?' + url.split('?')[1] : ''
          res.statusCode = 302
          res.setHeader('Location', target + qs)
          res.end()
          return
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
      '/api': { target: 'http://127.0.0.1:3456', changeOrigin: true, ...devAuthProxyHooks(), ws: true },
      '/static': { target: 'http://127.0.0.1:3456', changeOrigin: true, ...devAuthProxyHooks() },
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
