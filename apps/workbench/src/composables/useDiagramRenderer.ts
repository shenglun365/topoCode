/** 内联图渲染（```mermaid```/```plantuml``` 代码块 → 注入占位 div）。

统一经 topoOne 内核渲染（@topo/web-core/composables/useTopoRender）：
- mermaid  主线程 MermaidEngine
- plantuml POST {base}/plantuml/svg（gateway /api/topo）
取代旧实现（直连 mermaid + IPC render.renderPlantuml）。
*/

import { ref } from 'vue'
import i18n from '@/i18n'
import { renderDiagram } from '@topo/web-core/composables/useTopoRender'
import { normalizeMermaidCode } from '@topo/graph-kernel'

export interface DiagramBlock {
  id: string
  lang: DiagramLang
  code: string
  svg?: string
  error?: string
  loading?: boolean
}

export type DiagramLang = 'mermaid' | 'plantuml'

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
        <button class="fallback-diagram-copy" onclick="navigator.clipboard.writeText(this.parentElement.parentElement.querySelector('code').textContent)">${i18n.global.t('diagram.copyCode')}</button>
      </div>
      <pre class="fallback-code"><code>${escapedCode}</code></pre>
      <div class="diagram-error">${escapedError}</div>
    </div>`
  }
}

/** 清理规则单一源见 @topo/graph-kernel/core/diagram-normalize（MS3-U0 归口） */
function normalizeDiagramCode(lang: string, code: string): string {
  if (lang === 'mermaid') return normalizeMermaidCode(code)
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
        block.svg = await renderDiagram(block.lang, cleaned)
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
