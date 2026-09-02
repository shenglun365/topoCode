/** 预编译 topoOne 内核为单个 IIFE bundle（服务端无头渲染池 worker 页内联用）。

产出 dist-topoone/topo-one.js，暴露全局 `topoOne`（渲染池 worker 页内
`window.__topo = window.topoOne` 消费）。零 HTTP 依赖、无动态分块。
*/

import esbuild from 'esbuild'
import { resolve } from 'path'
import { mkdirSync } from 'fs'

const entry = resolve('../graph-kernel/src/index.ts')
const outfile = resolve('dist-topoone/topo-one.js')

async function main() {
    mkdirSync(resolve('dist-topoone'), { recursive: true })
    await esbuild.build({
        entryPoints: [entry],
        bundle: true,
        format: 'iife',
        globalName: 'topoOne',
        platform: 'browser',
        target: 'es2020',
        outfile,
        splitting: false,
        minify: false,
        sourcemap: false,
        treeShaking: true,
        define: { 'process.env.NODE_ENV': '"production"' },
        logLevel: 'info',
    })
    console.log(`✓ topoOne IIFE bundle: ${outfile}`)
}

main().catch((err) => {
    console.error('✗ topoOne bundle failed:', err)
    process.exit(1)
})
