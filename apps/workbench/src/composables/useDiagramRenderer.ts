import { ref } from 'vue'

export interface DiagramBlock {
  id: string
  lang: DiagramLang
  code: string
  svg?: string
  error?: string
  loading?: boolean
}

export type DiagramLang = 'mermaid' | 'plantuml'

let mermaidApi: any = null

async function ensureMermaid() {
  if (mermaidApi) return
  try {
    const mod = await import('mermaid')
    mermaidApi = mod.default
    mermaidApi.initialize({
      startOnLoad: false,
      securityLevel: 'loose',
      theme: 'dark',
      fontFamily: 'var(--font-sans)',
    })
  } catch (e) {
    console.warn('[useDiagramRenderer] ensureMermaid FAILED:', e)
    throw e
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function injectDiagram(block: DiagramBlock) {
  const el = document.getElementById(`inline-${block.id}`)
  if (!el) {
    console.warn(`[useDiagramRenderer] injectDiagram: placeholder NOT FOUND id=inline-${block.id}`)
    return
  }
  if (block.svg) {
    el.innerHTML = block.svg
  } else if (block.error) {
    const escapedCode = escapeHtml(block.code)
    const escapedError = escapeHtml(block.error)
    el.innerHTML = `<div class="fallback-diagram">
      <div class="fallback-diagram-header">
        <span class="fallback-diagram-lang">${escapeHtml(block.lang.toUpperCase())}</span>
        <button class="fallback-diagram-copy" onclick="navigator.clipboard.writeText(this.parentElement.parentElement.querySelector('code').textContent)">📋 复制代码</button>
      </div>
      <pre class="fallback-code"><code>${escapedCode}</code></pre>
      <div class="diagram-error">${escapedError}</div>
    </div>`
  }
}

function normalizeDiagramCode(lang: string, code: string): string {
  if (lang === 'mermaid') {
    code = code.replace(/\b([A-Za-z_]\w*)\s+\[/g, '$1[')
    code = code.replace(/(\bsubgraph\s+\w+(?:\.\w+)*)\s+(\[)/g, '$1$2')
    code = code.replace(/\[([^\]\[]*?)\(([^()]*)\)([^\]\[]*?)\]/g, '[$1$2$3]')
    code = code.replace(/^\s*style\s+.*$/gm, '')
    code = code.replace(/<br\s*\/?>/gi, ' ')
    code = code.replace(/:::\w+/g, '')
    code = code.replace(/[ \t]+$/gm, '')
    return code
  }
  if (lang === 'plantuml') {
    return code
  }
  return code
}

function extractDiagrams(content: string): DiagramBlock[] {
  const blocks: DiagramBlock[] = []
  let idx = 0
  const re = /```(mermaid|plantuml)\n([\s\S]*?)```/g
  let m
  while ((m = re.exec(content)) !== null) {
    const code = m[2].trim()
    if (code) {
      blocks.push({ id: `diagram-${idx++}`, lang: m[1] as DiagramLang, code, loading: false })
    }
  }
  return blocks
}

export function useDiagramRenderer() {
  const diagramBlocks = ref<DiagramBlock[]>([])

  async function renderAllDiagrams() {
    if (diagramBlocks.value.length === 0) return
    for (const block of diagramBlocks.value) {
      block.loading = true
      block.error = undefined
      const cleaned = normalizeDiagramCode(block.lang, block.code)
      try {
        let svg = ''
        if (block.lang === 'mermaid') {
          await ensureMermaid()
          const id = `sd-${block.id}`
          const result = await mermaidApi.render(id, cleaned)
          svg = result.svg
        } else {
          const result = await (window as any).api.render.renderPlantuml({ code: cleaned, format: 'svg' })
          svg = atob(result.data)
        }
        block.svg = svg
        injectDiagram(block)
      } catch (e: unknown) {
        block.error = (e as Error).message || 'Render failed'
        console.warn(`[useDiagramRenderer] ${block.lang} render ERROR id=${block.id}:`, (e as Error).message)
        injectDiagram(block)
      } finally {
        block.loading = false
      }
    }
  }

  function parseAndRender(content: string) {
    diagramBlocks.value = extractDiagrams(content)
    if (diagramBlocks.value.length > 0) {
      setTimeout(() => renderAllDiagrams(), 0)
    }
  }

  return {
    diagramBlocks,
    renderAllDiagrams,
    parseAndRender,
  }
}
