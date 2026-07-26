import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

const style = document.createElement('style')
style.textContent = `
.diagram-container{border:1px solid var(--border,#e4e4e7);border-radius:var(--radius-lg,12px);overflow:hidden;margin:8px 0}
.diag-toolbar{display:flex;align-items:center;justify-content:space-between;padding:4px 8px;background:var(--bg-hover,#f0f0f2);border-bottom:1px solid var(--border,#e4e4e7);gap:4px}
.diag-tabs{display:flex;gap:2px}
.diag-tab{background:none;border:none;padding:3px 10px;border-radius:var(--radius-sm,6px);cursor:pointer;font-size:12px;color:var(--text-muted,#888);transition:all .15s}
.diag-tab:hover{color:var(--text-secondary,#666);background:var(--bg-tertiary,#e8e8e8)}
.diag-tab-active{background:var(--accent,#4d6bfe);color:#fff}
.diag-tab-active:hover{background:var(--accent-hover,#3a56d4);color:#fff}
.diag-actions{display:flex;align-items:center;gap:2px}
.diag-actions button{background:none;border:none;color:var(--text-muted,#888);cursor:pointer;padding:2px 6px;border-radius:4px;font-size:13px;line-height:1}
.diag-actions button:hover{background:var(--bg-tertiary,#e8e8e8);color:var(--text-primary,#1a1a1a)}
.diag-zoom-pct{font-size:11px;color:var(--text-muted,#888);min-width:30px;text-align:center}
.diag-view{padding:12px;overflow:auto;background:var(--bg,#fff)}
.diag-svg-wrap{transform-origin:top left;transition:transform .15s}
.diag-svg-wrap svg{max-width:none!important}
.diag-code{padding:0}
.diag-textarea{width:100%;min-height:120px;border:none;padding:12px;font-family:var(--font-mono,monospace);font-size:13px;background:var(--bg-code,#f4f4f5);color:var(--code-text,#1a1a1a);resize:vertical;outline:none;box-sizing:border-box;tab-size:2}
.diag-render-btn{display:block;width:100%;padding:8px;background:var(--accent,#4d6bfe);color:#fff;border:none;cursor:pointer;font-size:13px}
.diag-render-btn:hover{background:var(--accent-hover,#3a56d4)}
.diagram-error{padding:16px;color:var(--error,#ef4444);font-size:13px;text-align:center}
.diag-fullscreen-overlay{position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99999;display:flex;align-items:center;justify-content:center;padding:40px}
.diag-fullscreen-overlay .diag-fs-close{position:absolute;top:16px;right:16px;background:rgba(255,255,255,.15);border:none;color:#fff;font-size:24px;width:40px;height:40px;border-radius:50%;cursor:pointer;z-index:1}
.diag-fullscreen-overlay .diag-fs-close:hover{background:rgba(255,255,255,.3)}
.diag-fullscreen-overlay .diag-fs-content{max-width:95%;max-height:90vh;overflow:auto;transform-origin:center center;transition:transform .1s}
.diag-fullscreen-overlay .diag-fs-content svg{max-width:none!important}
.diagram-placeholder .diagram-loading{padding:32px;color:var(--text-muted,#888);font-size:var(--ui-font-size,14px);text-align:center}
`
document.head.appendChild(style)

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
  const processed = text.replace(/```(mermaid|plantuml)\n([\s\S]*?)```/g, (_m, lang: string, code: string) => {
    const trimmed = code.trim()
    if (!trimmed) return _m
    return `<div class="diagram-placeholder" data-lang="${lang}"><pre style="display:none">${escapeHtml(trimmed)}</pre><div class="diagram-loading">${lang === 'mermaid' ? 'Mermaid' : 'PlantUML'} rendering...</div></div>`
  })
  const result = marked.parse(processed) as string
  if (text.includes('```mermaid')) console.log(`[renderMarkdown] textLen=${text.length} hasMermaid=true resultLen=${result.length} hasPlaceholder=${result.includes('diagram-placeholder')} resultStart=${result.slice(0,120)}`)
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

let mermaidApi: any = null

async function ensureMermaid() {
  if (mermaidApi) return
  try {
    const mod = await import('mermaid')
    mermaidApi = mod.default
    mermaidApi.initialize({
      startOnLoad: false,
      securityLevel: 'antiscript',
      theme: 'default',
    })
  } catch (e) {
    console.warn('[render] mermaid import failed:', e)
    throw e
  }
}

function makeBtn(tag: string, cls: string, text: string, title?: string): HTMLElement {
  const el = document.createElement(tag)
  el.className = cls
  el.textContent = text
  if (title) el.setAttribute('title', title)
  return el
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function getDiagramCode(el: HTMLElement): string {
  const pre = el.querySelector('pre')
  if (pre) return pre.textContent?.trim() || ''
  return ''
}

function buildDiagramContainer(code: string, lang: string, svg: string): HTMLElement {
  const container = document.createElement('div')
  container.className = 'diagram-container'

  // toolbar
  const toolbar = document.createElement('div')
  toolbar.className = 'diag-toolbar'
  const tabsDiv = document.createElement('div')
  tabsDiv.className = 'diag-tabs'
  const tabChart = makeBtn('button', 'diag-tab diag-tab-active', '\u56FE\u8868')
  tabChart.setAttribute('data-tab', 'chart')
  const tabCode = makeBtn('button', 'diag-tab', '\u4EE3\u7801')
  tabCode.setAttribute('data-tab', 'code')
  tabsDiv.appendChild(tabChart)
  tabsDiv.appendChild(tabCode)

  const actionsDiv = document.createElement('div')
  actionsDiv.className = 'diag-actions'
  const zoomOut = makeBtn('button', 'diag-zoom-out', '\u2212', '\u7F29\u5C0F')
  const zoomPct = makeBtn('span', 'diag-zoom-pct', '100%')
  const zoomIn = makeBtn('button', 'diag-zoom-in', '+', '\u653E\u5927')
  const downloadBtn = makeBtn('button', 'diag-download', '\u2B07', '\u4E0B\u8F7D')
  const fullscreenBtn = makeBtn('button', 'diag-fullscreen', '\u26F6', '\u5168\u5C4F')
  actionsDiv.appendChild(zoomOut)
  actionsDiv.appendChild(zoomPct)
  actionsDiv.appendChild(zoomIn)
  actionsDiv.appendChild(downloadBtn)
  actionsDiv.appendChild(fullscreenBtn)
  toolbar.appendChild(tabsDiv)
  toolbar.appendChild(actionsDiv)
  container.appendChild(toolbar)

  // chart view
  const diagView = document.createElement('div')
  diagView.className = 'diag-view'
  const svgWrap = document.createElement('div')
  svgWrap.className = 'diag-svg-wrap'
  svgWrap.style.transform = 'scale(1)'
  svgWrap.innerHTML = svg
  diagView.appendChild(svgWrap)
  container.appendChild(diagView)

  // code view
  const diagCode = document.createElement('div')
  diagCode.className = 'diag-code'
  diagCode.style.display = 'none'
  const pre = document.createElement('pre')
  const ccode = document.createElement('code')
  ccode.className = 'language-' + lang
  ccode.textContent = code
  pre.appendChild(ccode)
  const ta = document.createElement('textarea')
  ta.className = 'diag-textarea'
  ta.spellcheck = false
  ta.value = code
  const renderBtn = makeBtn('button', 'diag-render-btn', '\u91CD\u65B0\u6E32\u67D3')
  diagCode.appendChild(pre)
  diagCode.appendChild(ta)
  diagCode.appendChild(renderBtn)
  container.appendChild(diagCode)

  // tab switching
  tabChart.onclick = () => {
    tabChart.classList.add('diag-tab-active')
    tabCode.classList.remove('diag-tab-active')
    diagView.style.display = ''
    diagCode.style.display = 'none'
  }
  tabCode.onclick = () => {
    tabCode.classList.add('diag-tab-active')
    tabChart.classList.remove('diag-tab-active')
    diagView.style.display = 'none'
    diagCode.style.display = ''
  }

  // zoom
  let zs = 1
  zoomOut.onclick = () => {
    zs = Math.max(0.25, zs - 0.25)
    svgWrap.style.transform = 'scale(' + zs + ')'
    zoomPct.textContent = Math.round(zs * 100) + '%'
  }
  zoomIn.onclick = () => {
    zs = Math.min(3, zs + 0.25)
    svgWrap.style.transform = 'scale(' + zs + ')'
    zoomPct.textContent = Math.round(zs * 100) + '%'
  }

  // download
  downloadBtn.onclick = () => {
    const se = svgWrap.querySelector('svg')
    if (!se) return
    const xml = new XMLSerializer().serializeToString(se.cloneNode(true))
    const blob = new Blob(['<?xml version="1.0"?>' + xml], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'diagram.svg'
    a.click()
    URL.revokeObjectURL(url)
  }

  // fullscreen
  fullscreenBtn.onclick = () => {
    const ov = document.createElement('div')
    ov.className = 'diag-fullscreen-overlay'
    const fc = document.createElement('div')
    fc.className = 'diag-fs-content'
    fc.innerHTML = svgWrap.innerHTML
    const closeBtn = document.createElement('button')
    closeBtn.className = 'diag-fs-close'
    closeBtn.textContent = '\u00D7'
    ov.appendChild(closeBtn)
    ov.appendChild(fc)
    document.body.appendChild(ov)
    let fsScale = 1, fsDx = 0, fsDy = 0, fsDragging = false, fsStartX = 0, fsStartY = 0, fsSx = 0, fsSy = 0
    function fsUpdate() { fc.style.transform = 'translate(' + fsDx + 'px,' + fsDy + 'px) scale(' + fsScale + ')' }
    ov.addEventListener('wheel', (e) => {
      e.preventDefault()
      const old = fsScale
      fsScale = Math.max(0.25, Math.min(5, fsScale + (e.deltaY > 0 ? -0.2 : 0.2)))
      const rect = fc.getBoundingClientRect()
      const mx = e.clientX - rect.left, my = e.clientY - rect.top
      fsDx = mx - (mx - fsDx) * (fsScale / old)
      fsDy = my - (my - fsDy) * (fsScale / old)
      fsUpdate()
    }, { passive: false })
    fc.onmousedown = (e) => {
      fsDragging = true; fsStartX = e.clientX; fsStartY = e.clientY; fsSx = fsDx; fsSy = fsDy; fc.style.cursor = 'grabbing'
    }
    const onMouseMove = (e: MouseEvent) => {
      if (!fsDragging) return; fsDx = fsSx + (e.clientX - fsStartX); fsDy = fsSy + (e.clientY - fsStartY); fsUpdate()
    }
    const onMouseUp = () => {
      if (!fsDragging) return; fsDragging = false; fc.style.cursor = ''
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    closeBtn.onclick = () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      ov.remove()
    }
  }

  return container
}

async function renderSingle(el: HTMLElement): Promise<void> {
  const lang = el.getAttribute('data-lang') || ''
  const code = getDiagramCode(el)
  if (!code) {
    console.log(`[renderSingle] no code for lang=${lang} el=${el.className}`)
    return
  }

  try {
    let svg = ''
    if (lang === 'mermaid') {
      await ensureMermaid()
      let clean = code
        .replace(/^\s*style\s+.*$/gm, '')
        .replace(/<br\s*\/?>/gi, ' ')
        .replace(/:::\w+/g, '')
        .replace(/[ \t]+$/gm, '')
        .trim()
      const uid = 'm-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6)
      const valid = await mermaidApi.parse(clean, { suppressErrors: true })
      if (!valid) {
        throw new Error('\u56FE\u89E3\u8BED\u6CD5\u9519\u8BEF\uFF0C\u5DF2\u663E\u793A\u539F\u59CB\u4EE3\u7801')
      }
      const result = await mermaidApi.render(uid, clean)
      svg = result.svg
    } else if (lang === 'plantuml') {
      const resp = await fetch('/api/plantuml?code=' + encodeURIComponent(code))
      if (!resp.ok) throw new Error('PlantUML server returned ' + resp.status)
      svg = await resp.text()
    }
    const container = buildDiagramContainer(code, lang, svg)
    el.parentNode?.replaceChild(container, el)
  } catch (e: any) {
    // show code pre + error message instead of wiping everything
    const pre = el.querySelector('pre')
    if (pre) {
      pre.style.display = 'block'
      pre.style.background = '#1e1e1e'
      pre.style.color = '#d4d4d4'
      pre.style.padding = '12px'
      pre.style.borderRadius = '8px'
      pre.style.fontSize = '13px'
      pre.style.whiteSpace = 'pre-wrap'
      pre.style.wordBreak = 'break-all'
    }
    const loading = el.querySelector('.diagram-loading')
    if (loading) {
      loading.innerHTML = '<span style="color:#e06c75;font-weight:600">\u2716 ' + escapeHtml(e.message || '\u6E32\u67D3\u5931\u8D25') + '</span>'
    } else {
      const err = document.createElement('div')
      err.className = 'diagram-loading'
      err.style.color = '#e06c75'
      err.style.fontWeight = '600'
      err.textContent = '\u2716 ' + (e.message || '\u6E32\u67D3\u5931\u8D25')
      el.insertBefore(err, el.firstChild)
    }
  }
}

export function renderDiagrams(container: HTMLElement): void {
  const placeholders = container.querySelectorAll<HTMLElement>('.diagram-placeholder')
  const codeblocks = container.querySelectorAll<HTMLElement>('code.language-mermaid, code.language-plantuml')
  const bubbles = container.querySelectorAll<HTMLElement>('.bubble')
  let hasMermaidText = 0
  bubbles.forEach(b => { if (b.textContent?.includes('```mermaid') || b.innerHTML.includes('data-code')) hasMermaidText++ })
  console.log(`[renderDiagrams] container=${container.className} placeholders=${placeholders.length} codeblocks=${codeblocks.length} bubbles=${bubbles.length} hasMermaid=${hasMermaidText}`)
  if (bubbles.length) {
    console.log(`[renderDiagrams] firstBubbleHTML=${(bubbles[0].innerHTML||'').slice(0,100)}`)
  }
  placeholders.forEach((el) => {
    if (el.getAttribute('data-rendered')) {
      console.log(`[renderDiagrams] skip already rendered`)
      return
    }
    el.setAttribute('data-rendered', '1')
    renderSingle(el)
  })
}
