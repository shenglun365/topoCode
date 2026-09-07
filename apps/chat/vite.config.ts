import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { devAuthProxyHooks } from '../../scripts/vite-dev-auth'

import { resolve } from 'path'

// M12：chat 子项目独立 vite 工程（单 entry：chat.html）。
// root=src；outDir=dist；base=/chat/（资产引 /chat/assets/...，由 gateway /chat 挂载 serve）。
// gateway vue_routes serve /chat 页面（dist/chat.html）；manifest static_mount=["/chat"] serve 资产。
const SRC = resolve(__dirname, 'src')
const DIST = resolve(__dirname, 'dist')

// dev 便利：/chat?... → /chat/chat.html（302，与生产网关挂载路径对齐；
// 纯 URL 重写会让相对模块路径落到站点根 404，故用重定向）
function pageRewritePlugin() {
  return {
    name: 'page-rewrite',
    configureServer(server: any) {
      server.middlewares.use((req: any, res: any, next: any) => {
        const url = req.url || ''
        const pathname = url.split('?')[0]
        if (pathname === '/chat') {
          const qs = url.includes('?') ? '?' + url.split('?')[1] : ''
          res.statusCode = 302
          res.setHeader('Location', '/chat/chat.html' + qs)
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
      '/api': { target: 'http://127.0.0.1:3456', changeOrigin: true, ...devAuthProxyHooks(), ws: true },
      '/static': { target: 'http://127.0.0.1:3456', changeOrigin: true, ...devAuthProxyHooks() },
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
