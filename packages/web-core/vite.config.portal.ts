import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { renameSync, existsSync, copyFileSync } from 'fs'

// 门户独立构建：portal.html → dist-portal/home.html + assets/
// M06/M10 前 gateway 的 / 仍走 legacy static；本产物为 web-core 自有门户构建。
// 门户为纯 scoped CSS（无 tailwind 工具类），故禁用 postcss 管道。
const ROOT = resolve(__dirname)

function renamePortalHtml() {
  return {
    name: 'rename-portal-html',
    writeBundle() {
      const from = resolve(ROOT, 'dist-portal/portal.html')
      const to = resolve(ROOT, 'dist-portal/home.html')
      if (existsSync(from)) renameSync(from, to)
      // 品牌 logo SVG 输出到 assets/：gateway 挂载 /assets → 全站 favicon 统一引用 /assets/star-logo-mark-v8*.svg
      for (const f of ['star-logo-mark-v8.svg', 'star-logo-mark-v8-light.svg']) {
        const src = resolve(ROOT, 'src/assets', f)
        if (existsSync(src)) copyFileSync(src, resolve(ROOT, 'dist-portal/assets', f))
      }
    },
  }
}

export default defineConfig({
  plugins: [vue(), renamePortalHtml()],
  root: ROOT,
  base: './',
  css: {
    postcss: { plugins: [] },
  },
  build: {
    outDir: 'dist-portal',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        home: resolve(ROOT, 'portal.html'),
      },
      output: {
        entryFileNames: 'assets/[name].[hash].js',
        chunkFileNames: 'assets/chunk-[hash].js',
        assetFileNames: 'assets/[name].[hash][extname]',
      },
    },
  },
})
