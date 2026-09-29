// SYNC-WITH: packages/web-core/src/composables/useTopoRender.ts（MS3-U1 裁决①独立化）
// 差异点：① 仅保留 renderDiagram 一次性渲染（useTopoRender composable architect 未用）；
//         ② 鉴权源改为 architect 自家 services/api-client.getToken（原 web-core api.authHeaders）；
//         ③ SYNC-BLOCK 块两份须保持一致（异步任务协议 + IndexedDB 持久缓存）。
import { MermaidEngine } from '@topo/graph-kernel/engines/mermaid/mermaid.ts'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'
import { getToken } from './api-client'

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

let queue: (() => Promise<void>)[]
let running: boolean
queue = []
running = false

async function runQueue() {
  if (running) return
  running = true
  try {
    while (queue.length) {
      const task = queue.shift()
      if (task) await task()
    }
  } finally {
    running = false  // 任务异常(理论上 task 内部已兜)也不永久卡死渲染队列
  }
}

// ── SYNC-BLOCK: async-jobs + IndexedDB 持久缓存（与 web-core useTopoRender 保持一致）──
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
  const token = getToken()
  const auth = token ? { Authorization: `Bearer ${token}` } : {}
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
