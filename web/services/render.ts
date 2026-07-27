import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

const marked = new Marked(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code: string, lang: string) {
      if (lang === 'mermaid' || lang === 'plantuml') return code
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value
      }
      return code
    },
  })
)

marked.setOptions({
  gfm: true,
  breaks: true,
})

export function renderMarkdown(text: string): string {
  if (!text) return ''
  const result = marked.parse(text) as string
  return result
}

export function renderDocMarkdown(text: string): string {
  if (!text) return ''
  let html = renderMarkdown(text)
  html = html.replace(
    /<a href="##community:(\w+):([\w-]+)">/g,
    '<a href="#" class="comm-link" data-et="$1" data-cid="$2">'
  )
  return html
}

export function normalizeDiagram(
  code: string,
  lang: 'mermaid' | 'plantuml'
): { code: string; errors: string[] } {
  const errors: string[] = []
  let s = code

  const before = s
  s = s.replace(/\r\n/g, '\n')
  if (s !== before) errors.push('[error] 将 CRLF 统一为 LF')

  const fullwidthPairs: [RegExp, string, string][] = [
    [/，/g, ',', '全角逗号'],
    [/（/g, '(', '全角左括号'],
    [/）/g, ')', '全角右括号'],
    [/：/g, ':', '全角冒号'],
    [/“|”/g, '"', '全角双引号'],
    [/‘|’/g, "'", '全角单引号'],
    [/\u3000/g, ' ', '中文空格'],
  ]
  for (const [re, repl, label] of fullwidthPairs) {
    let n = 0
    s = s.replace(re, (m) => { n++; return repl })
    if (n) errors.push(`[warning] 替换 ${label} 为半角 (${n} 处)`)
  }

  let arrowCount = 0
  s = s.replace(/→/g, () => { arrowCount++; return '-->' })
  s = s.replace(/←/g, () => { arrowCount++; return '<--' })
  if (arrowCount) errors.push(`[warning] 替换全角箭头为半角 (${arrowCount} 处)`)

  let tabCount = 0
  s = s.replace(/\t/g, () => { tabCount++; return '  ' })
  if (tabCount) errors.push(`[error] 转换制表符为空格 (${tabCount} 处)`)

  let trailCount = 0
  s = s.replace(/[ \t]+$/gm, (m) => { trailCount++; return '' })
  if (trailCount) errors.push(`[warning] 移除行尾多余空白 (${trailCount} 行)`)

  let blankBefore = s
  s = s.replace(/\n{3,}/g, '\n\n')
  if (s !== blankBefore) errors.push(`[warning] 压缩连续空行`)

  const trimmed = s.trim()
  if (trimmed !== s) errors.push(`[warning] 清除首尾空白`)
  s = trimmed

  if (lang === 'mermaid') {
    let brCount = 0
    s = s.replace(/<br\s*\/?>/gi, () => { brCount++; return ' ' })
    if (brCount) errors.push(`[error] 替换 <br> 为空格 (${brCount} 处)`)

    let styleCount = 0
    s = s.replace(/^\s*style\s+.*$/gm, () => { styleCount++; return '' })
    if (styleCount) errors.push(`[error] 移除 style 指令行 (${styleCount} 行)`)

    let colonsCount = 0
    s = s.replace(/:::\w+/g, () => { colonsCount++; return '' })
    if (colonsCount) errors.push(`[error] 移除 ::: 标记 (${colonsCount} 处)`)

    let spaceCount = 0
    s = s.replace(/(\w+)\s+\[/g, (_, name) => { spaceCount++; return name + '[' })
    if (spaceCount) errors.push(`[warning] 移除节点名与 [ 间多余空格 (${spaceCount} 处)`)

    s = s.replace(/subgraph\s+\S+(?!\n)/g, (m) => m + '\n')

  } else if (lang === 'plantuml') {
    if (!/^\s*@startuml\b/m.test(s)) {
      s = '@startuml\n' + s
      errors.push('[error] 补全缺失的 @startuml')
    }
    if (!/@enduml\b\s*$/.test(s)) {
      s = s + '\n@enduml'
      errors.push('[error] 补全缺失的 @enduml')
    }
    const parts = s.split(/^@startuml\b.*$/m)
    if (parts.length > 2) {
      s = parts[0] + '@startuml' + parts.slice(1).join('')
      const ep = s.split(/^@enduml\b.*$/m)
      if (ep.length > 2) s = ep[0] + '@enduml'
      errors.push('[warning] 移除重复的 @startuml/@enduml')
    }
  }

  return { code: s, errors }
}

// ── 共享 mermaid 实例（所有组件共用） ──
let mermaidApi: any = null

export async function ensureMermaid() {
  if (mermaidApi) { console.log('[render] ensureMermaid: cached'); return mermaidApi }
  console.log('[render] ensureMermaid: importing...')
  const mod = await import('mermaid')
  mermaidApi = mod.default
  mermaidApi.initialize({ startOnLoad: false, securityLevel: 'antiscript', theme: 'default' })
  return mermaidApi
}

// ── 渲染队列（串行化避免并发卡顿） ──
const renderQueue: (() => Promise<void>)[] = []
let rendering = false

async function processQueue() {
  if (rendering) { console.log('[render] processQueue: already running'); return }
  rendering = true
  console.log(`[render] processQueue: start, tasks=\${renderQueue.length}`)
  while (renderQueue.length) {
    const task = renderQueue.shift()
    if (task) {
      console.log(`[render] processQueue: run task, \${renderQueue.length} left`)
      await task()
    }
  }
  rendering = false
  console.log('[render] processQueue: all done')
}

export function enqueueRender(fn: () => Promise<void>) {
  renderQueue.push(fn)
  console.log(`[render] enqueue total=\${renderQueue.length}`)
  processQueue()
}
