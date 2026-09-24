// SYNC-WITH: packages/web-core/src/composables/useTopoRender.ts（MS3-U1 裁决①独立化）
// 差异点：① 仅保留 renderDiagram 一次性渲染（useTopoRender composable architect 未用）；
//         ② 鉴权源改为 architect 自家 services/api-client.getToken（原 web-core api.authHeaders）。
import { MermaidEngine } from '@topo/graph-kernel/engines/mermaid/mermaid.ts'
import { PlantUmlEngine } from '@topo/graph-kernel/engines/plantuml/plantuml.ts'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'
import { getToken } from './api-client'

export type TopoRenderLang = 'mermaid' | 'plantuml'

let mermaidEngine: MermaidEngine | null = null

function getPlantuml(): PlantUmlEngine {
  const token = getToken()
  return new PlantUmlEngine({
    baseUrl: '/api/topo',
    protocol: 'post-raw',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
}

function getMermaid(): MermaidEngine {
  if (!mermaidEngine) mermaidEngine = new MermaidEngine()
  return mermaidEngine
}

function currentTheme(): 'light' | 'dark' {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
}

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
