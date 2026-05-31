/** 预编译 render-worker 为单个 ES 模块文件

解决 Vite 5.4.x worker.format bug（Worker 强制 IIFE 格式，不支持 code-splitting）。
*/

import esbuild from 'esbuild'
import { resolve } from 'path'
import { mkdirSync, writeFileSync } from 'fs'

const entry = resolve('src/workers/render-worker.ts')
const outdir = 'src/workers'
const outfile = resolve(outdir, 'render-worker-bundled.js')

async function main() {
    await esbuild.build({
        entryPoints: [entry],
        bundle: true,
        format: 'esm',
        platform: 'browser',
        target: 'es2020',
        outfile,
        external: [], // 不 external，全部打包进单个文件
        splitting: false, // 禁止 code-splitting
        treeShaking: true,
        minify: false, // 保留源码映射以便调试
        sourcemap: false,
        banner: {
            js: '/* Pre-bundled render-worker - do not edit */\n',
        },
    })
    console.log(`✓ Worker bundled: ${outfile}`)
}

main().catch(err => {
    console.error('✗ Worker bundle failed:', err)
    process.exit(1)
})
