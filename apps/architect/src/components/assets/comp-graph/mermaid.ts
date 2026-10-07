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
  if (!c || (!c.added && !c.modified && !c.deleted)) return ''
  if (c.added && !c.modified && !c.deleted) return 'added'     // 纯新增 → 绿
  if (c.deleted && !c.added && !c.modified) return 'deleted'   // 纯删除 → 红
  return 'modified'                                            // 混合/仅修改 → 蓝
}

export interface CompMermaidNode {
  id: string; name: string; fileCount: number; level: string; parentId?: string
  change: { added: number; modified: number; deleted: number }
}

/** 组件级图: 节点=组件(徽标=变更计数), 边=dependsOn; parentId → subgraph 层级分组
 *  (子组件收进父组件 cluster, 父不在目录或悬挂时平铺)。 */
export function compGraphMermaid(nodes: CompMermaidNode[],
                                 edges: { from: string; to: string }[]): MermaidResult {
  const idMap: Record<string, string> = {}
  const nodeOf = new Map(nodes.map((n) => [n.id, n]))
  const classLines: string[] = []
  const midOf = new Map<string, string>()
  const label = (n: CompMermaidNode) => {
    const badge = n.change.added || n.change.modified || n.change.deleted
      ? ` · +${n.change.added} ~${n.change.modified} -${n.change.deleted}` : ''
    return `["${esc(n.name)}<br/>${n.fileCount} files${badge}"]`
  }
  // 分组: 父也在目录中的组件按父聚合(两轮: 父先于子)
  const groups = new Map<string, CompMermaidNode[]>()   // parentId → 子组件
  const loose: CompMermaidNode[] = []
  for (const n of nodes) {
    if (n.parentId && nodeOf.has(n.parentId) && n.parentId !== n.id) {
      if (!groups.has(n.parentId)) groups.set(n.parentId, [])
      groups.get(n.parentId)!.push(n)
    } else {
      loose.push(n)
    }
  }
  const emitNode = (n: CompMermaidNode, out: string[]) => {
    const mid = `n${midOf.size}`
    midOf.set(n.id, mid)
    idMap[mid] = n.id
    out.push(`  ${mid}${label(n)}`)
    const cls = changeClass(n.change)
    // 默认配色对齐语义图谱(catppuccin, 非黑); 变更态整类替换——
    // ⚠️ mermaid ::: 语法只支持单个 class 名, `:::a,b` 解析失败回退 default
    classLines.push(`  ${mid}:::${cls || 'comp'}`)
  }
  const lines: string[] = ['graph TD']
  for (const n of loose) {
    const kids = groups.get(n.id) || []
    if (kids.length) {
      const sg = `sg${midOf.size}`
      lines.push(`  subgraph ${sg}["${esc(n.name)}"]`)
      emitNode(n, lines)
      for (const k of kids.sort((a, b) => a.name.localeCompare(b.name))) emitNode(k, lines)
      lines.push('  end')
    } else {
      emitNode(n, lines)
    }
  }
  // 悬挂子(父不在目录)兜底平铺
  for (const [pid, kids] of groups) {
    if (!nodeOf.has(pid)) for (const k of kids) emitNode(k, lines)
  }
  for (const e of edges) {
    const f = midOf.get(e.from)
    const t = midOf.get(e.to)
    if (f && t) lines.push(`  ${f} --> ${t}`)
  }
  lines.push(
    '  classDef comp fill:#2a2b3d,stroke:#cba6f7,color:#cdd6f4',
    '  classDef added fill:#24382e,stroke:#a6e3a1,stroke-width:2.5px,color:#cdd6f4',
    '  classDef modified fill:#26304a,stroke:#89b4fa,stroke-width:2.5px,color:#cdd6f4',
    '  classDef deleted fill:#3a2b34,stroke:#f38ba8,stroke-width:2.5px,stroke-dasharray:4,color:#cdd6f4',
  )
  const code = [...lines, ...classLines].join('\n')
  console.info('[comp-graph] compGraphMermaid', {
    nodes: nodes.length, edges: edges.length, classed: classLines.length,
    changeDist: nodes.reduce((m, n) => { const k = changeClass(n.change) || 'none'; m[k] = (m[k] || 0) + 1; return m }, {} as Record<string, number>),
  })
  console.info('[comp-graph] comp mermaid code:\n' + code)
  return { code, idMap }
}

/** 文件级图: 节点=文件(徽标=变更态), 边=imports。 */
export function fileGraphMermaid(nodes: {
  id: string; name: string; change: string; compName?: string
}[], edges: { from: string; to: string }[]): MermaidResult {
  const idMap: Record<string, string> = {}
  const lines: string[] = ['graph LR']
  const classLines: string[] = []
  const midOf = new Map<string, string>()
  nodes.forEach((n, i) => {
    const mid = `n${i}`
    midOf.set(n.id, mid)
    idMap[mid] = n.id
    const mark = n.change === 'added' ? ' [新增]' : n.change === 'modified' ? ' [改]' : n.change === 'deleted' ? ' [删]' : ''
    lines.push(`  ${mid}["${esc(n.name, 28)}${mark}"]`)
    classLines.push(`  ${mid}:::${n.change || 'file'}`)
  })
  for (const e of edges) {
    const f = midOf.get(e.from)
    const t = midOf.get(e.to)
    if (f && t) lines.push(`  ${f} --> ${t}`)
  }
  lines.push(
    '  classDef file fill:#2a2b3d,stroke:#74c7ec,color:#cdd6f4',
    '  classDef added fill:#24382e,stroke:#a6e3a1,stroke-width:2.5px,color:#cdd6f4',
    '  classDef modified fill:#26304a,stroke:#89b4fa,stroke-width:2.5px,color:#cdd6f4',
    '  classDef deleted fill:#3a2b34,stroke:#f38ba8,stroke-width:2.5px,stroke-dasharray:4,color:#cdd6f4',
  )
  const code = [...lines, ...classLines].join('\n')
  console.info('[comp-graph] fileGraphMermaid', {
    nodes: nodes.length, edges: edges.length, classed: classLines.length,
    changeDist: nodes.reduce((m, n) => { const k = n.change || 'none'; m[k] = (m[k] || 0) + 1; return m }, {} as Record<string, number>),
  })
  console.info('[comp-graph] file mermaid code:\n' + code)
  return { code, idMap }
}
