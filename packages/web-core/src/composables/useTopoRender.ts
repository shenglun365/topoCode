/** topoOne 无头渲染 composable（统一内核，主线程）。

替代各 app 自建的 mermaid/plantuml 渲染路径（worker / IPC render.* / 直连 mermaid）：
- mermaid  → MermaidEngine（内核，共享 mermaid 实例，串行队列避免并发）
- plantuml → 后端异步任务（POST /api/topo/plantuml/jobs，CLI 渲染不阻塞前端）

返回 { svg, loading, error, refresh, exportSvg, exportPng }，兼容旧 useMermaidRender
调用面。另导出 renderDiagram 供一次性渲染（块注入场景）。
*/

import { ref, watch, type Ref, onUnmounted } from 'vue'
import { MermaidEngine } from '@topo/graph-kernel/engines/mermaid/mermaid.ts'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'
import { authHeaders } from '../services/api'

export type TopoRenderLang = 'mermaid' | 'plantuml'

let mermaidEngine: MermaidEngine | null = null

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

// ── SYNC-BLOCK: async-jobs + IndexedDB 持久缓存（与 architect topo-render.ts 保持一致）──
// 用户契约: 后台异步 CLI / 支持缓存 / 不阻塞 / 页面刷新不中断。
// L1 内存 LRU → L2 IndexedDB(刷新命中) → L3 渲染(mermaid 前端 / plantuml 后端任务)。

const cache = new Map<string, string>()
const CACHE_MAX = 50

function lruPut(key: string, svg: string) {
  if (cache.size >= CACHE_MAX) {
    const first = cache.keys().next().value
    if (first !== undefined) cache.delete(first)
  }
  cache.set(key, svg)
}

const IDB_NAME = 'topo-render-cache'
const IDB_STORE = 'svg'

function idbOpen(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      if (typeof indexedDB === 'undefined') return resolve(null)
      const req = indexedDB.open(IDB_NAME, 1)
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(IDB_STORE)) req.result.createObjectStore(IDB_STORE)
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => resolve(null) // 隐私模式等 → 静默降级无 L2
    } catch {
      resolve(null)
    }
  })
}

async function idbGet(key: string): Promise<string | null> {
  const db = await idbOpen()
  if (!db) return null
  return new Promise((resolve) => {
    try {
      const req = db.transaction(IDB_STORE, 'readonly').objectStore(IDB_STORE).get(key)
      req.onsuccess = () => resolve((req.result as string) ?? null)
      req.onerror = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
}

async function idbSet(key: string, svg: string): Promise<void> {
  const db = await idbOpen()
  if (!db) return
  try {
    db.transaction(IDB_STORE, 'readwrite').objectStore(IDB_STORE).put(svg, key)
  } catch { /* 忽略: 缓存写失败不影响渲染 */ }
}

/** plantuml 后端异步任务: 提交即回 → 轮询回填(幂等 key=sha256(fmt+code), 刷新后重提交命中同任务/缓存)。 */
async function renderPlantumlJobs(code: string): Promise<string> {
  const auth = authHeaders() as Record<string, string>
  const post = () => fetch('/api/topo/plantuml/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...auth },
    body: JSON.stringify({ code, format: 'svg' }),
  })
  let r = await post()
  if (!r.ok) throw new Error(`plantuml render submit failed (${r.status})`)
  let job = await r.json()
  const deadline = Date.now() + 60_000
  let delay = 200
  while (job.status !== 'done' && job.status !== 'error' && Date.now() < deadline) {
    await new Promise((res) => setTimeout(res, delay))
    delay = Math.min(1500, Math.round(delay * 1.5))
    const poll = await fetch(`/api/topo/plantuml/jobs/${encodeURIComponent(job.jobId)}`, { headers: auth })
    if (poll.status === 404) {
      // 任务表被淘汰/服务重启 → 幂等重提交(后端持久缓存大概率直接命中)
      r = await post()
      if (!r.ok) throw new Error(`plantuml render resubmit failed (${r.status})`)
      job = await r.json()
      continue
    }
    if (!poll.ok) throw new Error(`plantuml render poll failed (${poll.status})`)
    job = await poll.json()
  }
  if (job.status === 'error') throw new Error(job.error || 'plantuml render failed')
  if (job.status !== 'done' || !job.svg) throw new Error('plantuml render timeout (60s)')
  return job.svg
}

// ── SYNC-BLOCK 结束 ──

/** 一次性渲染：lang + code → svg（失败抛错）。
 *  三级缓存: L1 内存 50 条 → L2 IndexedDB(刷新不丢) → L3 渲染
 *  (mermaid 前端共享实例 / plantuml 后端异步任务——不阻塞、刷新不中断)。 */
export async function renderDiagram(
  lang: TopoRenderLang,
  code: string,
  opts?: { cache?: boolean; theme?: 'light' | 'dark' }
): Promise<string> {
  const theme = opts?.theme ?? currentTheme()
  const key = `${lang}:${theme}:${code}`
  if (opts?.cache !== false) {
    const mem = cache.get(key)
    if (mem !== undefined) return mem
    const hit = await idbGet(key)
    if (hit) {
      lruPut(key, hit)
      return hit
    }
  }

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
          : await renderPlantumlJobs(code)
        lruPut(key, svg)
        void idbSet(key, svg)
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
