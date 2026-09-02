/** topoOne 无头渲染 composable（统一内核，主线程）。

替代各 app 自建的 mermaid/plantuml 渲染路径（worker / IPC render.* / 直连 mermaid）：
- mermaid  → MermaidEngine（内核，共享 mermaid 实例，串行队列避免并发）
- plantuml → PlantUmlEngine（POST {baseUrl}/plantuml/svg，gateway /api/topo 同源）

返回 { svg, loading, error, refresh, exportSvg, exportPng }，兼容旧 useMermaidRender
调用面。另导出 renderDiagram 供一次性渲染（块注入场景）。
*/

import { ref, watch, type Ref, onUnmounted } from 'vue'
import { MermaidEngine } from '@topo/graph-kernel/engines/mermaid/mermaid.ts'
import { PlantUmlEngine } from '@topo/graph-kernel/engines/plantuml/plantuml.ts'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'
import { authHeaders } from '../services/api'

export type TopoRenderLang = 'mermaid' | 'plantuml'

let mermaidEngine: MermaidEngine | null = null

function getPlantuml(): PlantUmlEngine {
  return new PlantUmlEngine({ baseUrl: '/api/topo', protocol: 'post-raw', headers: authHeaders() })
}

function getMermaid(): MermaidEngine {
  if (!mermaidEngine) mermaidEngine = new MermaidEngine()
  return mermaidEngine
}

function currentTheme(): 'light' | 'dark' {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
}

// ── 串行渲染队列（mermaid 共享模块实例，不可并发） ──

let queue: (() => Promise<void>)[] = []
let running = false

async function runQueue() {
  if (running) return
  running = true
  while (queue.length) {
    const task = queue.shift()
    if (task) await task()
  }
  running = false
}

const cache = new Map<string, string>()
const CACHE_MAX = 50

/** 一次性渲染：lang + code → svg（失败抛错）。带 50 条内存缓存。 */
export async function renderDiagram(
  lang: TopoRenderLang,
  code: string,
  opts?: { cache?: boolean; theme?: 'light' | 'dark' }
): Promise<string> {
  const theme = opts?.theme ?? currentTheme()
  const key = `${lang}:${theme}:${code}`
  if (opts?.cache !== false && cache.has(key)) return cache.get(key)!

  return new Promise<string>((resolve, reject) => {
    queue.push(async () => {
      try {
        const container = document.createElement('div')
        const svg = lang === 'mermaid'
          ? (await getMermaid().render({
              container,
              code,
              theme,
              themeVariables: themeVariablesFor(theme),
              securityLevel: 'loose',
            })).svg
          : (await getPlantuml().render({ container, code })).svg
        if (cache.size >= CACHE_MAX) {
          const first = cache.keys().next().value
          if (first !== undefined) cache.delete(first)
        }
        cache.set(key, svg)
        resolve(svg)
      } catch (e) {
        reject(e)
      }
    })
    runQueue()
  })
}

export interface UseTopoRenderOptions {
  cache?: boolean
  theme?: 'light' | 'dark'
}

export function useTopoRender(
  diagram: Ref<string | null>,
  lang: Ref<TopoRenderLang> | TopoRenderLang,
  options: UseTopoRenderOptions = {}
) {
  const svg = ref<string>('')
  const loading = ref(false)
  const error = ref<string | null>(null)
  const progress = ref(0)
  let cancelled = false

  const langVal = () => (typeof lang === 'string' ? lang : lang.value)

  watch(diagram, async (newCode) => {
    if (cancelled || !newCode) {
      svg.value = ''
      error.value = null
      progress.value = 0
      return
    }
    loading.value = true
    error.value = null
    progress.value = 0
    try {
      svg.value = await renderDiagram(langVal(), newCode, { cache: options.cache, theme: options.theme })
      progress.value = 100
    } catch (e: any) {
      error.value = e.message || 'Render failed'
    } finally {
      loading.value = false
    }
  }, { immediate: true })

  /** 手动触发重新渲染（绕过缓存）。 */
  async function refresh() {
    if (!diagram.value) return
    cache.clear()
    const code = diagram.value
    diagram.value = ''
    await new Promise((r) => setTimeout(r, 0))
    diagram.value = code
  }

  function exportSvg(filename: string = 'diagram.svg'): void {
    if (!svg.value) return
    const blob = new Blob([svg.value], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  async function exportPng(filename: string = 'diagram.png', scale: number = 2): Promise<void> {
    if (!svg.value) return
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const img = new Image()
    const blob = new Blob([svg.value], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    await new Promise<void>((resolve) => {
      img.onload = () => {
        const rect = img.getBoundingClientRect()
        const w = rect.width || 800
        const h = rect.height || 600
        canvas.width = w * scale
        canvas.height = h * scale
        ctx.scale(scale, scale)
        ctx.drawImage(img, 0, 0, w, h)
        URL.revokeObjectURL(url)
        resolve()
      }
      img.src = url
    })
    canvas.toBlob((blob) => {
      if (!blob) return
      const pngUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = pngUrl
      a.download = filename
      a.click()
      URL.revokeObjectURL(pngUrl)
    })
  }

  onUnmounted(() => {
    cancelled = true
  })

  return { svg, loading, error, progress, refresh, exportSvg, exportPng }
}
