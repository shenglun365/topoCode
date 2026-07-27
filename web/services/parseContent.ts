import { renderMarkdown } from '@web/services/render'
import { diagramStateStore } from '@web/services/diagramStateStore'
import type { DiagramViewState } from '@web/services/diagramStateStore'

export interface ParsedBlock {
  type: 'text' | 'mermaid' | 'plantuml'
  html?: string
  code?: string
  diagId?: string
  initialState?: DiagramViewState
}

/** 确定性 diagId: diag_{msgId}_{index}，保证跨页面加载一致 */
function diagIdFor(id: string | undefined, prefix: string, index: number): string {
  if (id) return `diag_${prefix}_${id}_${index}`
  return `diag_anon_${Date.now().toString(16).slice(-4)}_${index}`
}

function parseBlocks(text: string, id: string | undefined, prefix: string): ParsedBlock[] {
  if (!text) return []
  const blocks: ParsedBlock[] = []
  const headerStates = diagramStateStore.extractFromContent(text)
  const headerEntries = Object.entries(headerStates)
  let remaining = text.replace(/<!--\s*diagram:\S+\s*\{[^}]*\}\s*-->\n?/g, '')

  const codeBlockRe = /```(mermaid|plantuml)\n([\s\S]*?)```/g
  let lastIndex = 0
  let m: RegExpExecArray | null
  let diagIndex = 0

  while ((m = codeBlockRe.exec(remaining)) !== null) {
    const before = remaining.slice(lastIndex, m.index)
    if (before.trim()) {
      blocks.push({ type: 'text', html: renderMarkdown(before) })
    }
    const code = m[2].trim()
    if (code) {
      const diagId = diagIdFor(id, prefix, diagIndex)
      const headerEntry = headerEntries[diagIndex]
      const initialState = headerEntry ? headerEntry[1] : diagramStateStore.load(diagId, id || '')
      blocks.push({ type: m[1] as 'mermaid' | 'plantuml', code, diagId, initialState: initialState || undefined })
      diagIndex++
    }
    lastIndex = m.index + m[0].length
  }

  const after = remaining.slice(lastIndex)
  if (after.trim()) {
    blocks.push({ type: 'text', html: renderMarkdown(after) })
  }
  if (!blocks.length) {
    blocks.push({ type: 'text', html: renderMarkdown(text) })
  }
  return blocks
}

export function parseMessageContent(text: string, msgId?: string): ParsedBlock[] {
  return parseBlocks(text, msgId, 'msg')
}

export function parseDocContent(text: string, docId?: string): ParsedBlock[] {
  return parseBlocks(text, docId, 'doc')
}
