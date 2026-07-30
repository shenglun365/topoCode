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
  return result.replace(
    /<pre><code(?: class="[^"]*")?>([\s\S]*?)<\/code><\/pre>/g,
    (_, codeContent) => {
      return `<div class="code-block-wrap"><button class="code-fs-btn" title="全屏查看"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg></button><pre><code>${codeContent}</code></pre></div>`
    }
  )
}

export function codeFullscreen(codeText: string) {
  const ov = document.createElement('div')
  ov.className = 'diag-fullscreen-overlay'
  const fc = document.createElement('div')
  fc.className = 'code-fs-content'
  const pre = document.createElement('pre')
  const codeEl = document.createElement('code')
  codeEl.textContent = codeText
  pre.appendChild(codeEl)
  fc.appendChild(pre)
  const closeBtn = document.createElement('button')
  closeBtn.className = 'diag-fs-close'
  closeBtn.textContent = '\u00D7'
  ov.appendChild(closeBtn)
  ov.appendChild(fc)
  document.body.appendChild(ov)

  let scale = 1, dx = 0, dy = 0, dragging = false, startX = 0, startY = 0, sx = 0, sy = 0
  function update() { fc.style.transform = `translate(${dx}px,${dy}px) scale(${scale})` }

  ov.addEventListener('wheel', (e) => {
    e.preventDefault()
    const old = scale
    scale = Math.max(0.25, Math.min(5, scale + (e.deltaY > 0 ? -0.2 : 0.2)))
    const rect = fc.getBoundingClientRect()
    const mx = e.clientX - rect.left, my = e.clientY - rect.top
    dx = dx + mx * (1 - scale / old)
    dy = dy + my * (1 - scale / old)
    update()
  }, { passive: false })

  fc.onmousedown = (e) => {
    if ((e.target as HTMLElement).closest('button')) return
    dragging = true; startX = e.clientX; startY = e.clientY; sx = dx; sy = dy; fc.style.cursor = 'grabbing'
  }
  const mm = (e: MouseEvent) => { if (!dragging) return; dx = sx + (e.clientX - startX); dy = sy + (e.clientY - startY); update() }
  const mu = () => { dragging = false; fc.style.cursor = '' }
  window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu)
  const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { cleanup(); ov.remove() } }
  window.addEventListener('keydown', onKey)
  closeBtn.onclick = () => { cleanup(); ov.remove() }
  function cleanup() { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); window.removeEventListener('keydown', onKey) }
}

export function fitScale(
  elW: number, elH: number,
  cw: number, ch: number,
  minScale = 0.2
): number | null {
  if (elW <= cw && elH <= ch) return null
  const s = Math.min(cw / elW, ch / elH) * 0.95
  if (s < minScale || s >= 1) return null
  return s
}

export function autoFitCodeBlock(wrap: HTMLElement) {
  const pre = wrap.querySelector('pre')
  if (!pre) return
  pre.style.transform = ''
  pre.style.transformOrigin = '0 0'
  wrap.style.overflow = ''
  void pre.offsetWidth
  const s = fitScale(pre.scrollWidth, pre.scrollHeight, wrap.clientWidth, 99999)
  if (s !== null) {
    pre.style.transform = `scale(${s})`
    wrap.style.overflow = 'hidden'
  }
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

  // 解码 HTML 实体 (&lt; → <, &#xxxx; → Unicode)
  const textarea = document.createElement('textarea')
  textarea.innerHTML = s
  s = textarea.value
  textarea.remove()

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
    // plantuml 相关修复已在后端统一处理
  }

  return { code: s, errors }
}

// ── 共享 mermaid 实例（所有组件共用） ──
let mermaidApi: any = null

export async function ensureMermaid() {
  if (mermaidApi) return mermaidApi
  const mod = await import('mermaid')
  mermaidApi = mod.default
  mermaidApi.initialize({ startOnLoad: false, securityLevel: 'antiscript', theme: 'default' })
  return mermaidApi
}

// ── 渲染队列（串行化避免并发卡顿） ──
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

export function enqueueRender(fn: () => Promise<void>) {
  renderQueue.push(fn)
  processQueue()
}
