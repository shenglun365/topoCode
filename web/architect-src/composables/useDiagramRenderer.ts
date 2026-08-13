import { apiBaseUrl } from '@/services/api-client'

export type DiagramLang = 'mermaid' | 'plantuml' | 'toposcript'

export interface DiagramBlock {
  id: string
  lang: DiagramLang
  code: string
  title?: string
  svg?: string
  url?: string
  error?: string
  loading?: boolean
}

let mermaidApi: any = null
let mermaidInit = false

async function ensureMermaid(): Promise<any> {
  if (mermaidApi) return mermaidApi
  const mod = await import('mermaid')
  mermaidApi = mod.default
  if (!mermaidInit) {
    mermaidApi.initialize({
      startOnLoad: false,
      securityLevel: 'loose',
      theme: 'dark',
      themeVariables: {
        background: '#181825',
        primaryColor: '#313244',
        primaryTextColor: '#cdd6f4',
        primaryBorderColor: '#45475a',
        secondaryColor: '#1e1e2e',
        tertiaryColor: '#181825',
        lineColor: '#7f849c',
        fontFamily: 'var(--font-sans)',
        fontSize: '13px',
      },
    })
    mermaidInit = true
  }
  return mermaidApi
}

/** mermaid 语法错误时渲染出的是「错误提示 SVG」(aria-roledescription=error)，而非抛异常。
 * 识别后转抛错，走统一的错误提示路径，避免错误 DOM 直接注入页面影响布局。 */
function isMermaidErrorSvg(svg: string): boolean {
  return /aria-roledescription=["']error["']/.test(svg)
    || /class=["'][^"']*error-(icon|text)[^"']*["']/.test(svg)
    || /Syntax error in text/.test(svg)
}

/** 清理 mermaid 遗留的临时容器：mermaid 渲染成功后会自行移除，
 * 但语法/绘制错误时(11.x)在抛异常前不会移除，错误 SVG 会挂在 document.body 尾部。 */
function cleanupMermaidTemp(uid?: string) {
  const ids = uid ? [`#d${uid}`, `#i${uid}`] : []
  ids.forEach((sel) => {
    try { document.querySelector(sel)?.remove() } catch { /* keep going */ }
  })
  document.querySelectorAll<HTMLElement>('[id^="dmd-"],[id^="imd-"]').forEach((el) => el.remove())
}

/** 每次渲染使用唯一临时容器 id，避免复用固定 id 时与在途渲染冲突。 */
async function renderMermaidOnce(code: string): Promise<string> {
  const mermaid = await ensureMermaid()
  const uid = `md-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  try {
    const result = await mermaid.render(uid, code)
    if (isMermaidErrorSvg(result.svg)) {
      const text = result.svg.match(/(?:Syntax error in text|error-text)[^<]*/) || ['Syntax error in mermaid diagram']
      throw new Error(text[0].replace(/[<>&]/g, '').trim())
    }
    return result.svg
  } finally {
    cleanupMermaidTemp(uid)
  }
}

/** 渲染队列：串行化 mermaid 渲染，避免并发触发同一内部实例导致首次冷加载互相干扰。 */
const renderQueue: (() => Promise<void>)[] = []
let rendering = false

async function processQueue() {
  if (rendering) return
  rendering = true
  while (renderQueue.length) {
    const task = renderQueue.shift()
    if (task) await task()
  }
  rendering = false
}

function enqueue<T>(fn: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    renderQueue.push(() => fn().then(resolve, reject))
    processQueue()
  })
}

export async function renderMermaid(code: string): Promise<string> {
  return enqueue(async () => {
    try {
      return await renderMermaidOnce(code)
    } catch (e) {
      // 首次冷启动渲染可能因 mermaid 模块/懒加载子分块尚未就绪而失败，稍候重试一次。
      console.warn('[diagram] mermaid first render failed, retrying:', (e as Error)?.message || e)
      await new Promise((r) => setTimeout(r, 300))
      return await renderMermaidOnce(code)
    }
  })
}

/** 渲染 PlantUML 为 SVG 文本：POST 到 architect 后端 `/diagram/plantuml`，
 * 由后端经 `plantuml_service`(PLANTUML_SERVER，本地 8300)渲染。与 KB AI chat `/api/plantuml` 同构。 */
export async function renderPlantuml(code: string): Promise<string> {
  const resp = await fetch(`${apiBaseUrl()}/diagram/plantuml`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: code,
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    let msg = text?.trim() || `PlantUML server returned ${resp.status}`
    try {
      const j = JSON.parse(text)
      if (j && j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* keep raw text */ }
    throw new Error(msg)
  }
  return resp.text()
}

export function normalizeMermaid(code: string): string {
  return code
    .replace(/\b([A-Za-z_]\w*)\s+\[/g, '$1[')
    .replace(/\[([^[\]]*?)\(([^()]*)\)([^[\]]*?)\]/g, '[$1$2$3]')
    .replace(/^\s*style\s+.*$/gm, '')
    .replace(/[ \t]+$/gm, '')
}

/** 各渲染器的关系边数上限(不扩容：仅用于超限时给出友好提示，引导缩小数据范围)。 */
export const DIAGRAM_EDGE_LIMITS: Partial<Record<DiagramLang, number>> = {
  mermaid: 500,
  plantuml: 400,
}

/** 粗略统计图源中的关系边数(用于渲染前预判规模，避免直接抛底层报错)。 */
export function countDiagramEdges(lang: DiagramLang, code: string): number {
  if (!code) return 0
  let n = 0
  for (const raw of code.split('\n')) {
    const t = raw.trim()
    if (!t) continue
    if (lang === 'mermaid') {
      // flowchart 边行: `a -->|label| b`；排除 linkStyle/classDef 等样式行。
      if (t.includes('-->') && !t.startsWith('linkStyle') && !t.startsWith('class ')) n++
    } else if (lang === 'plantuml') {
      // 关系行: `n0 --> n1` 或 `n0 -> n1`；排除 skinparam/note/component 等指令行。
      if (/^[A-Za-z_]\w*\s+--?>/.test(t)) n++
    }
  }
  return n
}

/** 判断渲染失败是否由「规模超限」引起(替换为友好提示，而非底层报错)。 */
export function isDiagramSizeError(lang: DiagramLang, message?: string): boolean {
  const m = (message || '').toLowerCase()
  if (lang === 'mermaid') {
    return m.includes('edge limit exceeded') || m.includes('maxedges') || m.includes('text limit')
  }
  if (lang === 'plantuml') {
    return m.includes('414') || m.includes('uri too long')
  }
  return false
}
