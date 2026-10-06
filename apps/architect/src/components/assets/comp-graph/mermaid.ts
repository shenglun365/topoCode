/**
 * 组件图谱域 · mermaid 生成(组件图/文件图 → graph TD code)。
 * 节点 id 编码为安全短 id(n0/n1…)——点击事件经 idMap 反查真实 id。
 * 变更着色 classDef: added=绿 modified=蓝 deleted=红(与资产 diff 口径一致)。
 */

export interface MermaidResult {
  code: string
  /** mermaid 安全 id → 真实节点 id */
  idMap: Record<string, string>
}

/** mermaid 文本安全化(引号/括号/换行)。 */
function esc(text: string, cap = 40): string {
  const t = (text || '').replace(/["`<>[\]{}|\\]/g, ' ').replace(/\s+/g, ' ').trim()
  return t.length > cap ? `${t.slice(0, cap)}…` : t
}

type ChangeKey = 'added' | 'modified' | 'deleted' | ''

function changeClass(ch: { added: number; modified: number; deleted: number } | '' | string): ChangeKey {
  if (ch === 'added' || ch === 'modified' || ch === 'deleted') return ch
  const c = ch as { added: number; modified: number; deleted: number }
  if (c && (c.added || c.modified || c.deleted)) return 'modified'
  return ''
}

/** 组件级图: 节点=组件(徽标=变更计数), 边=dependsOn。 */
export function compGraphMermaid(nodes: {
  id: string; name: string; fileCount: number; level: string;
  change: { added: number; modified: number; deleted: number }
}[], edges: { from: string; to: string }[]): MermaidResult {
  const idMap: Record<string, string> = {}
  const lines: string[] = ['graph TD']
  const classLines: string[] = []
  nodes.forEach((n, i) => {
    const mid = `n${i}`
    idMap[mid] = n.id
    const badge = n.change.added || n.change.modified || n.change.deleted
      ? ` · +${n.change.added} ~${n.change.modified} -${n.change.deleted}` : ''
    lines.push(`  ${mid}["${esc(n.name)}<br/>${n.fileCount} files${badge}"]`)
    const cls = changeClass(n.change)
    if (cls) classLines.push(`  ${mid}:::${cls}`)
  })
  for (const e of edges) {
    const f = Object.keys(idMap).find((k) => idMap[k] === e.from)
    const t = Object.keys(idMap).find((k) => idMap[k] === e.to)
    if (f && t) lines.push(`  ${f} --> ${t}`)
  }
  lines.push(
    '  classDef added stroke:#a6e3a1,stroke-width:3px',
    '  classDef modified stroke:#89b4fa,stroke-width:3px',
    '  classDef deleted stroke:#f38ba8,stroke-width:3px,stroke-dasharray:4',
  )
  return { code: [...lines, ...classLines].join('\n'), idMap }
}

/** 文件级图: 节点=文件(徽标=变更态), 边=imports。 */
export function fileGraphMermaid(nodes: {
  id: string; name: string; change: string; compName?: string
}[], edges: { from: string; to: string }[]): MermaidResult {
  const idMap: Record<string, string> = {}
  const lines: string[] = ['graph LR']
  const classLines: string[] = []
  nodes.forEach((n, i) => {
    const mid = `n${i}`
    idMap[mid] = n.id
    const mark = n.change === 'added' ? ' [新增]' : n.change === 'modified' ? ' [改]' : n.change === 'deleted' ? ' [删]' : ''
    lines.push(`  ${mid}["${esc(n.name, 28)}${mark}"]`)
    if (n.change) classLines.push(`  ${mid}:::${n.change}`)
  })
  for (const e of edges) {
    const f = Object.keys(idMap).find((k) => idMap[k] === e.from)
    const t = Object.keys(idMap).find((k) => idMap[k] === e.to)
    if (f && t) lines.push(`  ${f} --> ${t}`)
  }
  lines.push(
    '  classDef added stroke:#a6e3a1,stroke-width:3px',
    '  classDef modified stroke:#89b4fa,stroke-width:3px',
    '  classDef deleted stroke:#f38ba8,stroke-width:3px,stroke-dasharray:4',
  )
  return { code: [...lines, ...classLines].join('\n'), idMap }
}
