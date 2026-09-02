import type { ArchComponent, DataFlow, EntityClass, ErTable, ExecutionFlow, OrmMapping } from '@/types'

/** 当前主题的图表调色板（跟随 <html data-theme>）。 */
export function currentDiagramPalette(): Record<string, string> {
  const light = document.documentElement.getAttribute('data-theme') === 'light'
  if (light) {
    return {
      fill: '#ccd0da', border: '#acb0be', border2: '#9ca0b0',
      text: '#4c4f69', bg: '#e6e9ef', bgDeep: '#eff1f5', line: '#5c5f77',
      staleFill: '#f2d3d0', staleText: '#ea76cb',
    }
  }
  return {
    fill: '#313244', border: '#45475a', border2: '#585b70',
    text: '#cdd6f4', bg: '#181825', bgDeep: '#1e1e2e', line: '#a6adc8',
    staleFill: '#3a2a2a', staleText: '#f5c2e7',
  }
}

// ============ ER 表视图 ============

export function erToMermaid(er: ErTable): string {
  const lines = ['erDiagram']
  for (const t of [er]) {
    lines.push(`  ${t.id} {`)
    for (const c of t.columns) lines.push(`    ${c.pk ? 'string' : c.type} ${c.name} ${c.nullable ? '|' : ''}`)
    lines.push('  }')
  }
  const relMap: Record<string, string> = { '1:1': '||--||', '1:N': '||--o{', 'N:M': '}o--o{' }
  const seen = new Set<string>()
  for (const r of er.relations) {
    if (seen.has(`${r.from}${r.to}${r.type}`)) continue
    seen.add(`${r.from}${r.to}${r.type}`)
    lines.push(`  ${r.from} ${relMap[r.type] ?? '||--o{'} ${r.to} : "${r.key}"`)
  }
  return lines.join('\n')
}

export function erToPlantUml(er: ErTable): string {
  const lines = ['@startuml']
  lines.push(`entity "${er.name}" as ${er.id} {`)
  for (const c of er.columns) {
    const pk = c.pk ? ' <<PK>>' : ''
    lines.push(`  * ${c.name} : ${c.type}${pk}`)
  }
  lines.push('}')
  er.relations.forEach((r) => {
    lines.push(`${r.from} ${r.type === 'N:M' ? '}o--o{' : r.type === '1:1' ? '||--||' : '||--o{'} ${r.to} : ${r.key}`)
  })
  lines.push('@enduml')
  return lines.join('\n')
}

// ============ ORM 映射视图 ============

export function ormToMermaid(orm: OrmMapping): string {
  const lines = ['classDiagram']
  lines.push(`  class ${orm.entity} {`)
  for (const f of orm.fields) lines.push(`    +${f.type} ${f.entityField}`)
  lines.push('  }')
  lines.push(`  class ${orm.table} {`)
  for (const f of orm.fields) lines.push(`    +${f.type} ${f.column}`)
  lines.push('  }')
  lines.push(`  ${orm.entity} --> ${orm.table} : maps`)
  return lines.join('\n')
}

export function ormToPlantUml(orm: OrmMapping): string {
  const lines = ['@startuml']
  lines.push(`class "${orm.entity}" as ${orm.entity} {`)
  for (const f of orm.fields) lines.push(`  +${f.type} ${f.entityField} : ${f.desc}`)
  lines.push('}')
  lines.push(`class "${orm.table}" as ${orm.table} {`)
  for (const f of orm.fields) lines.push(`  +${f.type} ${f.column}`)
  lines.push('}')
  lines.push(`${orm.entity} --> ${orm.table} : ORM 映射`)
  lines.push('@enduml')
  return lines.join('\n')
}

// ============ 程序内实体类视图 ============

export function entityToMermaid(cls: EntityClass): string {
  const lines = ['classDiagram']
  lines.push(`  class ${cls.name} {`)
  for (const f of cls.fields) lines.push(`    +${f.type} ${f.name}`)
  for (const m of cls.methods) lines.push(`    +${m.signature}`)
  lines.push('  }')
  return lines.join('\n')
}

export function entityToPlantUml(cls: EntityClass): string {
  const lines = ['@startuml', `class "${cls.name}" {`]
  for (const f of cls.fields) lines.push(`  ${f.type} ${f.name} : ${f.desc}`)
  for (const m of cls.methods) lines.push(`  ${m.returnType} ${m.signature}`)
  lines.push('}')
  lines.push('@enduml')
  return lines.join('\n')
}

// ============ 处理流程 ============

export function flowToMermaid(flow: ExecutionFlow): string {
  const lines = ['flowchart LR']
  for (const s of flow.steps) {
    const label = JSON.stringify(s.label)
    lines.push(s.type === 'decision' ? `  ${s.id}{${label}}` : `  ${s.id}[${label}]`)
  }
  for (let i = 0; i < flow.steps.length - 1; i++) {
    const a = flow.steps[i].id
    const b = flow.steps[i + 1].id
    lines.push(`  ${a} -->|${flow.steps[i].owner}| ${b}`)
  }
  return lines.join('\n')
}

export function flowToPlantUml(flow: ExecutionFlow): string {
  const lines = ['@startuml', 'start']
  for (const s of flow.steps) {
    if (s.type === 'decision') {
      lines.push(`if (${s.label}?) then (yes)`)
    } else if (s.type === 'io') {
      lines.push(`:${s.label};\nnote right\n  ${s.owner}\nend note`)
    } else {
      lines.push(`:${s.label};`)
    }
  }
  lines.push('stop', '@enduml')
  return lines.join('\n')
}

/** 时序图视图(≤5 实体，表示处理过程)。 */
export function flowToSequenceMermaid(flow: ExecutionFlow): string {
  const seq = flow.sequence
  if (!seq || !seq.entities.length) return ''
  const lines = ['sequenceDiagram']
  seq.entities.forEach((e) => lines.push(`  participant ${e.id} as ${e.name}`))
  for (const m of seq.messages) {
    lines.push(`  ${m.from}->>${m.to}: ${m.label}`)
  }
  return lines.join('\n')
}

export function flowToSequencePlantUml(flow: ExecutionFlow): string {
  const seq = flow.sequence
  if (!seq || !seq.entities.length) return ''
  const lines = ['@startuml']
  seq.entities.forEach((e) => lines.push(`participant "${e.name}" as ${e.id}`))
  for (const m of seq.messages) {
    lines.push(`${m.from} -> ${m.to} : ${m.label}`)
  }
  lines.push('@enduml')
  return lines.join('\n')
}

export function dataflowToMermaid(df: DataFlow, components: ArchComponent[]): string {
  const lines = ['flowchart LR']
  const compIds = new Set<string>()
  df.streams.forEach((s) => { compIds.add(s.from); compIds.add(s.to) })
  const comp = components.filter((c) => compIds.has(c.id))
  comp.forEach((c) => lines.push(`  ${c.id}[${JSON.stringify(c.name)}]`))
  df.streams.forEach((s) => lines.push(`  ${s.from} -->|${JSON.stringify(s.name)}: ${s.payload}| ${s.to}`))
  return lines.join('\n')
}

export function componentsToMermaid(components: ArchComponent[]): string {
  const P = currentDiagramPalette()
  const lines = ['flowchart LR']
  lines.push(`  classDef green fill:${P.fill},stroke:#a6e3a1,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef red fill:${P.fill},stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:${P.text}`)
  lines.push(`  classDef peach fill:${P.fill},stroke:#fab387,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef gray fill:${P.fill},stroke:${P.border2},color:${P.text}`)
  for (const c of components) {
    lines.push(`  ${c.id}[${JSON.stringify(c.name)}]`)
    lines.push(`  class ${c.id} ${c.change === 'same' ? 'gray' : c.change}`)
  }
  const seen = new Set<string>()
  for (const c of components) {
    for (const dep of c.dependsOn) {
      if (components.some((x) => x.id === dep) && !seen.has(`${c.id}->${dep}`)) {
        lines.push(`  ${c.id} --> ${dep}`)
        seen.add(`${c.id}->${dep}`)
      }
    }
  }
  return lines.join('\n')
}

const CHANGE_CLASS_DEF = (P: Record<string, string>) => ({
  added: `fill:${P.fill},stroke:#a6e3a1,stroke-width:2px,color:${P.text}`,
  removed: `fill:${P.fill},stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:${P.text}`,
  modified: `fill:${P.fill},stroke:#fab387,stroke-width:2px,color:${P.text}`,
  same: `fill:${P.fill},stroke:${P.border2},color:${P.text}`,
})

/**
 * 数据结构变更图：当前快照的全部 ER 表(classDiagram)，按 change 着色，含表间关系。
 */
export function structuresToMermaid(tables: ErTable[]): string {
  const P = currentDiagramPalette()
  const lines = ['classDiagram']
  lines.push('  direction LR')
  const classDefs: string[] = []
  ;(['added', 'removed', 'modified', 'same'] as const).forEach((k) => {
    classDefs.push(`  classDef ${k} ${CHANGE_CLASS_DEF(P)[k]}`)
  })
  lines.push(...classDefs)
  const seenTable = new Set<string>()
  for (const t of tables) {
    if (seenTable.has(t.id)) continue
    seenTable.add(t.id)
    lines.push(`  class ${t.id} {`)
    for (const c of t.columns) {
      const pk = c.pk ? ' <<PK>>' : ''
      const fk = c.fk ? ` <<FK→${c.fk}>>` : ''
      lines.push(`    +${c.type} ${c.name}${pk}${fk}`)
    }
    lines.push('  }')
    lines.push(`  class ${t.id} ${t.change}`)
  }
  const seenRel = new Set<string>()
  for (const t of tables) {
    for (const r of t.relations) {
      const key = `${r.from}|${r.to}`
      if (seenRel.has(key)) continue
      seenRel.add(key)
      lines.push(`  ${r.from} --> ${r.to} : ${r.key} (${r.type})`)
    }
  }
  return lines.join('\n')
}

/**
 * 调用关系变更图：数据流 stream 图(flowchart)，组件节点按 change 着色，标注调用通道。
 */
export function callsToMermaid(dataFlows: DataFlow[], components: ArchComponent[]): string {
  const P = currentDiagramPalette()
  const lines = ['flowchart LR']
  lines.push(`  classDef added fill:${P.fill},stroke:#a6e3a1,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef removed fill:${P.fill},stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:${P.text}`)
  lines.push(`  classDef modified fill:${P.fill},stroke:#fab387,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef same fill:${P.fill},stroke:${P.border2},color:${P.text}`)
  const compIds = new Set<string>()
  dataFlows.forEach((f) => f.streams.forEach((s) => { compIds.add(s.from); compIds.add(s.to) }))
  const comps = components.filter((c) => compIds.has(c.id))
  const compMap = new Map(comps.map((c) => [c.id, c]))
  const seenNode = new Set<string>()
  for (const id of compIds) {
    const c = compMap.get(id)
    if (!c || seenNode.has(id)) continue
    seenNode.add(id)
    lines.push(`  ${c.id}[${JSON.stringify(c.name)}]`)
    lines.push(`  class ${c.id} ${c.change}`)
  }
  const seenEdge = new Set<string>()
  dataFlows.forEach((f) => {
    for (const s of f.streams) {
      const key = `${s.from}|${s.to}|${s.name}`
      if (seenEdge.has(key)) continue
      seenEdge.add(key)
      const dash = s.change === 'removed' ? '-.->' : '-->'
      lines.push(`  ${s.from} ${dash}|${JSON.stringify(s.name)} · ${s.payload}| ${s.to}`)
      if (s.change !== 'same') lines.push(`  linkStyle ${seenEdge.size - 1} stroke:${s.change === 'added' ? '#a6e3a1' : '#fab387'}`)
    }
  })
  return lines.join('\n')
}

// ============ 语义资产图谱 ============

const SEMANTIC_LEVEL_ORDER = ['business', 'logic', 'implementation'] as const
const SEMANTIC_LEVEL_LABEL: Record<string, string> = {
  business: '业务', logic: '逻辑', implementation: '实现',
}

function _semLevel(n?: string): string {
  return SEMANTIC_LEVEL_ORDER.includes(n as any) ? (n as string) : 'logic'
}

/** 资产 id → 稳定序号节点标识(mermaid/plantuml 符号安全)。 */
function _semNodeId(idx: number): string {
  return `n${idx}`
}

function _semLabel(s: string, max = 26): string {
  // mermaid flowchart 边标签 |...| 遇 @ | " 等字符直接 Parse error(实测 v11)，统一置换；
  // 空白折叠防止 desc 内换行把一条边拆成两行。
  const t = (s || '').replace(/\[|\]|\{|\}|\(|\)|\||@/g, ' ').replace(/"/g, "'").replace(/\\/g, '').replace(/\s+/g, ' ').trim()
  return t.length > max ? `${t.slice(0, max)}…` : (t || '?')
}

/** 节点显示名(供外部按渲染文本定位节点 DOM，口径与各生成器一致)。 */
export function semanticNodeLabelText(s: string, max = 30): string {
  return _semLabel(s, max)
}

/** plantuml 标签净化：`;` 会提前终止 `:label;`、`|` 破坏泳道/换行、`-->` 会被解析为关系箭头。 */
function _puText(s: string): string {
  return (s || '').replace(/[;|\r\n]+/g, ' ').replace(/-->/g, '->').trim()
}

/** 语义资产节点显示文本：业务名 + 资产 ID，便于定位引用。 */
function _semNodeLabel(n: { name: string; id: string }, max = 26): string {
  return `${_semLabel(n.name, max)} · ${n.id}`
}

/** 语义资产图谱 → Mermaid flowchart(按粒度 high→medium→low 分 subgraph 表达层级)。 */
export function semanticGraphToMermaid(
  nodes: { id: string; kind: string; level?: string; name: string; status?: string; needsUpdate?: number }[],
  edges: SemGraphViewEdge[],
): string {
  const P = currentDiagramPalette()
  const lines = ['flowchart TD']
  lines.push(`  classDef asset fill:${P.fill},stroke:#cba6f7,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef process fill:${P.fill},stroke:#89b4fa,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef decision fill:${P.fill},stroke:#a6e3a1,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef contract fill:${P.fill},stroke:#f9e2af,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef stale fill:${P.staleFill},stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:${P.staleText}`)
  lines.push('  classDef needsUpdate stroke:#f9e2af')
  const byLevel = new Map<string, { id: string; kind: string; idx: number; name: string; status?: string; needsUpdate?: number }[]>()
  nodes.forEach((n, idx) => {
    const lv = _semLevel(n.level)
    if (!byLevel.has(lv)) byLevel.set(lv, [])
    byLevel.get(lv)!.push({ ...n, idx })
  })
  const idToNode = new Map(nodes.map((n, i) => [n.id, i]))
  const declared = new Set<string>()
  for (const lv of SEMANTIC_LEVEL_ORDER) {
    const group = byLevel.get(lv)
    if (!group?.length) continue
    lines.push(`  subgraph ${lv.toUpperCase()}[${SEMANTIC_LEVEL_LABEL[lv] ?? lv}]`)
    lines.push(`  style ${lv.toUpperCase()} fill:${P.bgDeep},stroke:${P.border},color:#89b4fa,font-weight:600`)
    for (const n of group) {
      const nodeId = _semNodeId(n.idx)
      const status = n.status || 'active'
      const flag = n.needsUpdate ? ' ⚠' : ''
      const style = status === 'stale' ? ':::stale' : n.needsUpdate ? ':::needsUpdate' : ''
      lines.push(`    ${nodeId}["${_semNodeLabel(n)}${flag}"]${style}`)
      lines.push(`    class ${nodeId} ${n.kind || 'asset'}`)
      declared.add(nodeId)
    }
    lines.push('  end')
  }
  const seen = new Set<string>()
  for (const e of edges) {
    if (!e.from || !e.to) continue
    const si = idToNode.get(e.from)
    const ti = idToNode.get(e.to)
    if (si === undefined || ti === undefined) continue
    const a = _semNodeId(si)
    const b = _semNodeId(ti)
    if (a === b) continue
    const key = `${a}->${b}`
    if (seen.has(key)) continue
    seen.add(key)
    const label = (e.desc || e.type || e.semantic || '').trim()
    lines.push(`  ${a} ${_mmdArrow(e)}${label || e.indirect ? `|${_semEdgeLabel(e, 14)}|` : ''} ${b}`)
  }
  // 显式加粗可见连线(深色背景下保证线/字可读，不依赖全局主题)。
  lines.push(`  linkStyle default stroke:${P.line},color:${P.text},stroke-width:1.5px`)
  return lines.join('\n')
}

/** 语义资产图谱 → PlantUML component 图(按粒度 package 分组表达层级)。 */
export function semanticGraphToPlantUml(
  nodes: { id: string; kind: string; level?: string; name: string; status?: string; needsUpdate?: number }[],
  edges: SemGraphViewEdge[],
): string {
  const P = currentDiagramPalette()
  const lines = ['@startuml', 'skinparam componentStyle rectangle', `skinparam backgroundColor ${P.bg}`,
    `skinparam ArrowColor ${P.line}`, 'skinparam ArrowThickness 1.5', `skinparam LineColor ${P.line}`,
    `skinparam componentBackgroundColor ${P.fill}`, `skinparam componentBorderColor ${P.border}`,
    `skinparam componentFontColor ${P.text}`, `skinparam defaultFontColor ${P.text}`, `skinparam packageBackgroundColor ${P.bgDeep}`,
    `skinparam packageBorderColor ${P.border2}`, 'skinparam packageFontColor #89b4fa', 'skinparam shadowing false']
  const byLevel = new Map<string, { id: string; kind: string; idx: number; name: string; status?: string; needsUpdate?: number }[]>()
  nodes.forEach((n, idx) => {
    const lv = _semLevel(n.level)
    if (!byLevel.has(lv)) byLevel.set(lv, [])
    byLevel.get(lv)!.push({ ...n, idx })
  })
  const idToNode = new Map(nodes.map((n, i) => [n.id, i]))
  for (const lv of SEMANTIC_LEVEL_ORDER) {
    const group = byLevel.get(lv)
    if (!group?.length) continue
    lines.push(`package "${SEMANTIC_LEVEL_LABEL[lv] ?? lv}" as L${lv.toUpperCase()} {`)
    for (const n of group) {
      const nodeId = _semNodeId(n.idx)
      lines.push(`  component "${_semNodeLabel(n, 18)}${n.needsUpdate ? ' ⚠' : ''}" as ${nodeId} <<${n.kind || 'asset'}>> ${P.fill}`)
    }
    lines.push('}')
  }
  const seen = new Set<string>()
  for (const e of edges) {
    if (!e.from || !e.to) continue
    const si = idToNode.get(e.from)
    const ti = idToNode.get(e.to)
    if (si === undefined || ti === undefined) continue
    const a = _semNodeId(si)
    const b = _semNodeId(ti)
    if (a === b) continue
    const key = `${a}->${b}`
    if (seen.has(key)) continue
    seen.add(key)
    const label = (e.desc || e.type || e.semantic || '').trim()
    lines.push(`${a} ${_puArrow(e)} ${b}${label || e.indirect ? ` : ${_semEdgeLabel(e, 18)}` : ''}`)
  }
  lines.push('@enduml')
  return lines.join('\n')
}

// ============ 语义图谱 · 多种图类型 ============

/** 语义图谱支持的图类型视图 id。 */
export type SemanticGraphViewId = 'flow' | 'class' | 'er' | 'seq' | 'state' | 'activity' | 'mindmap'

/** 供新图型生成器使用的节点/边形状(与 graph 接口节点含精简 detail)。 */
export interface SemGraphViewNode {
  id: string
  kind: string
  level?: string
  name: string
  status?: string
  needsUpdate?: number
  scopeKey?: string
  detail?: {
    fields?: { name?: string; type?: string; semantic?: string }[]
    steps?: { order?: number; semantic?: string; condition?: string }[]
    branches?: { condition?: string; then?: unknown; else?: unknown }[]
    trigger?: string
    relations?: { target?: string; type?: string; semantic?: string }[]
    states?: { name: string; desc?: string; initial?: boolean; final?: boolean }[]
    transitions?: { from?: string; to?: string; event?: string; condition?: string; action?: string }[]
    tags?: string[]
    aggregates?: { assetId?: string; name?: string; role?: string }[]
  }
}

export interface SemGraphViewEdge {
  from: string
  to: string
  type?: string
  semantic?: string
  /** 证据式关系描述(edge_notes 生成；优先于 type/semantic 作边标签)。 */
  desc?: string
  /** 间接边(1 跳中转)：虚线渲染 + via 中转名。 */
  indirect?: boolean
  via?: string
  /** 派生边证据(发生处文件:行)。 */
  line?: number | null
  file?: string
  confidence?: string
  resolvedBy?: string
}

type _Node = SemGraphViewNode
type _Edge = SemGraphViewEdge

/** 边标签：desc 优先，间接边附 ⇝中转 提示。 */
function _semEdgeLabel(e: _Edge, max = 14, fallback = ''): string {
  // desc 常带 @L{行}: 证据前缀(edge_notes LLM 惯例)：证据已在边悬停/矩阵详情呈现，
  // 标签里去掉以省出 14 字预算给真实内容(且 @ 会破坏 mermaid 边标签解析)。
  let base = (e.desc || e.type || e.semantic || fallback).trim()
  base = base.replace(/^@L\d+\s*[:：]\s*/, '')
  if (e.indirect && e.via) return `${_semLabel(base || 'rel', max)}⇝${_semLabel(e.via, 10)}`
  return _semLabel(base, max)
}

/** 间接边 → mermaid 虚线箭头。 */
function _mmdArrow(e: _Edge, solid = '-->'): string {
  return e.indirect ? '-.->' : solid
}

/** 间接边 → plantuml 虚线箭头。 */
function _puArrow(e: _Edge, solid = '-->'): string {
  return e.indirect ? '..>' : solid
}

/** mermaid/plantuml 安全的资产 id(去特殊字符、避免数字开头)；规避 JS 原型链同名(mermaid 按名做对象索引)。 */
function _safeSemId(id: string): string {
  const s = (id || 'x').replace(/[^A-Za-z0-9_]/g, '_').replace(/^(\d)/, '_$1')
  return _JS_PROTO.has(s) ? `${s}_` : s
}

/** JS Object 原型链属性名(同名键会命中原型而非自身，mermaid 等按名索引渲染器会崩)。 */
const _JS_PROTO = new Set(['constructor', 'toString', 'valueOf', 'hasOwnProperty', 'isPrototypeOf',
  'propertyIsEnumerable', 'toLocaleString', '__proto__', '__defineGetter__', '__defineSetter__',
  '__lookupGetter__', '__lookupSetter__'])

/** mermaid classDiagram 类名：由显示名净化而来(可读)，全局去重保证唯一。
 *  注：mermaid classDiagram 不支持 `class "显示名" as 别名`(报 got 'STR')，
 *  类名本身必须直接可读。 */
function _safeClassNames(items: { id: string; name: string }[]): Map<string, string> {
  const used = new Set<string>()
  const out = new Map<string, string>()
  for (const it of items) {
    let s = (_semLabel(it.name, 40) || 'C').replace(/[^\p{L}\p{N}_-]+/gu, '_')
    if (!s || /^_+$/.test(s)) s = 'C'
    if (/^[0-9]/.test(s)) s = `C_${s}`
    if (_JS_PROTO.has(s)) s = `${s}_`
    let unique = s
    for (let i = 2; used.has(unique); i++) unique = `${s}_${i}`
    used.add(unique)
    out.set(it.id, unique)
  }
  return out
}

/** 类/ER 字段名等简单标识符。 */
function _safeIdent(s: string, fallback = 'f'): string {
  const t = (s || '').replace(/[^A-Za-z0-9_]/g, '_')
  return t.replace(/^(\d)/, '_$1') || fallback
}

/** 推荐图类型：类别 × 粒度。 */
export function recommendedSemanticView(kind?: string, level?: string): SemanticGraphViewId {
  const lv = _semLevel(level)
  if (kind === 'entity') return lv === 'business' ? 'mindmap' : lv === 'logic' ? 'er' : 'class'
  if (kind === 'process') return lv === 'business' ? 'activity' : 'seq'
  if (kind === 'decision') return lv === 'business' ? 'mindmap' : 'state'
  if (kind === 'contract') return 'seq'
  if (kind === 'state') return 'state'
  if (kind === 'rule') return 'mindmap'
  if (lv === 'implementation') return 'flow'
  return lv === 'business' ? 'mindmap' : 'flow'
}

/** 视图可用性判定的最小节点形状(与语义图谱节点 detail 兼容)。 */
type ViewNodeShape = {
  kind?: string
  level?: string
  detail?: {
    fields?: { name?: string }[]
    steps?: unknown[]
    branches?: unknown[]
    trigger?: unknown
    states?: unknown[]
    transitions?: unknown[]
  }
}

/** 按数据区间(粒度 + 节点类别构成 + detail 内容)动态给出支持的图类型(供下拉只显示可用的)。 */
export function supportedViewsFor(
  level: string,
  nodes: ViewNodeShape[],
): SemanticGraphViewId[] {
  const lv = level || 'all'
  const kinds = new Set(nodes.map((n) => n.kind || 'entity'))
  const has = (k: string) => kinds.has(k)
  const byKind = (k: string) => nodes.filter((n) => n.kind === k)
  const hasFields = (k: string) => byKind(k).some((n) => (n.detail?.fields ?? []).length > 0)
  const hasFlowDetail = (k: string) => byKind(k).some((n) =>
    (n.detail?.steps ?? []).length > 0 || (n.detail?.branches ?? []).length > 0 || !!n.detail?.trigger)
  const hasStates = () => byKind('state').some((n) =>
    (n.detail?.states ?? []).length > 0 && (n.detail?.transitions ?? []).length > 0)
  const seqParticipants = nodes.filter((n) => n.kind === 'process' || n.kind === 'contract').length
  // 业务级优先 mindmap/activity；其余按 kind 分布。
  if (lv === 'business') {
    const out: SemanticGraphViewId[] = ['mindmap']
    if (has('process') && hasFlowDetail('process')) out.push('activity')
    if ((has('contract') || has('entity') || has('rule')) && hasFields('entity')) out.push('class')
    return [...new Set(out)]
  }
  const out: SemanticGraphViewId[] = []
  if (has('state') && hasStates()) out.push('state')
  if (has('process')) {
    out.push('flow')
    if (seqParticipants <= SEQ_PARTICIPANT_BUDGET) out.push('seq')
    if (hasFlowDetail('process')) out.push('activity')
  }
  if ((has('entity') || has('rule')) && hasFields('entity')) out.push('class', 'er')
  if (has('contract') && seqParticipants <= SEQ_PARTICIPANT_BUDGET) out.push('seq', 'class')
  if (has('decision')) out.push('state')
  out.push('flow')
  return [...new Set(out)]
}

/** 视图预算(节点数上限，超限不提供该视图)。 */
export const SEQ_PARTICIPANT_BUDGET = 30
export const MINDMAP_NODE_BUDGET = 120
export const FLOW_NODE_BUDGET = 200

/** 不适用的视图及其原因(供下拉工具提示说明「为何不可选」)。 */
export function viewUnavailableReasons(
  level: string,
  nodes: ViewNodeShape[],
): Partial<Record<SemanticGraphViewId, string>> {
  const lv = level || 'all'
  const reasons: Partial<Record<SemanticGraphViewId, string>> = {}
  const has = (k: string) => nodes.some((n) => n.kind === k)
  const byKind = (k: string) => nodes.filter((n) => n.kind === k)
  const hasFields = (k: string) => byKind(k).some((n) => (n.detail?.fields ?? []).length > 0)
  const hasFlowDetail = (k: string) => byKind(k).some((n) =>
    (n.detail?.steps ?? []).length > 0 || (n.detail?.branches ?? []).length > 0 || !!n.detail?.trigger)
  const seqParticipants = nodes.filter((n) => n.kind === 'process' || n.kind === 'contract').length
  const businessOnly = lv === 'business'
  if ((has('entity') || has('rule') || (businessOnly && has('contract'))) && !hasFields('entity')) {
    reasons.er = '无带属性的实体资产(ER 图需要实体字段)'
    reasons.class = '无带属性的实体资产(类图需要实体字段)'
  } else if (!has('entity') && !has('rule')) {
    reasons.er = '无实体/规则资产'
    reasons.class = '无实体/规则资产'
  }
  if (seqParticipants > SEQ_PARTICIPANT_BUDGET) {
    reasons.seq = `参与者过多(${seqParticipants} > ${SEQ_PARTICIPANT_BUDGET})，时序图不清晰`
  } else if (!has('process') && !has('contract')) {
    reasons.seq = '无过程/契约资产'
  }
  if (businessOnly && has('process') && !hasFlowDetail('process')) {
    reasons.activity = '过程资产缺少步骤/分支细节'
  } else if (!has('process')) {
    reasons.activity = '无过程资产'
  }
  if (has('state') && !byKind('state').some((n) => (n.detail?.states ?? []).length > 0)) {
    reasons.state = '状态资产缺少状态集定义'
  }
  if (nodes.length > MINDMAP_NODE_BUDGET) {
    reasons.mindmap = `节点过多(${nodes.length} > ${MINDMAP_NODE_BUDGET})`
  }
  return reasons
}

// ---- 类图 ----

export function semanticClassDiagramToMermaid(nodes: _Node[], edges: _Edge[]): string {
  const P = currentDiagramPalette()
  const classes = nodes.filter((n) => n.kind === 'entity' || (n.kind === 'contract' && n.level === 'implementation'))
  // 类名由业务名净化而来(声明/成员/边引用一致)；mermaid 不支持带引号的别名语法。
  const safe = _safeClassNames(nodes)
  const lines = ['classDiagram', '  direction LR']
  lines.push(`  classDef asset fill:${P.fill},stroke:#cba6f7,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef contract fill:${P.fill},stroke:#f9e2af,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef stale fill:${P.staleFill},stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:${P.staleText}`)
  for (const n of classes) {
    lines.push(`  class ${safe.get(n.id)}`)
    const fields = (n.detail?.fields ?? []).slice(0, 30)
    if (fields.length) {
      lines.push(`  class ${safe.get(n.id)} {`)
      for (const f of fields) lines.push(`    +${_safeIdent(f.name || 'f')}: ${_semLabel(f.type || '?', 24)}`)
      lines.push('  }')
    }
  }
  const seen = new Set<string>()
  for (const e of edges) {
    const a = safe.get(e.from)
    const b = safe.get(e.to)
    if (!a || !b || a === b) continue
    const t = (e.type || '').toLowerCase()
    let arrow = _mmdArrow(e)
    if (e.indirect) arrow = '..>'
    else if (t.includes('extends')) arrow = '<|--'
    else if (t.includes('implements')) arrow = '<|..'
    else if (t.includes('contains') || t.includes('instantiates')) arrow = '*--'
    const key = `${a}${arrow}${b}`
    if (seen.has(key)) continue
    seen.add(key)
    // classDiagram 边标签在首个半角冒号处截断(实测 v11)，标签内冒号置换为全角
    lines.push(`  ${a} ${arrow} ${b}${(e.desc || e.type) ? ` : ${_semEdgeLabel(e, 12).replace(/:/g, '：')}` : ''}`)
  }
  for (const n of classes) lines.push(`  class ${safe.get(n.id)} ${n.status === 'stale' ? 'stale' : n.kind}`)
  return lines.join('\n')
}

export function semanticClassDiagramToPlantUml(nodes: _Node[], edges: _Edge[]): string {
  const P = currentDiagramPalette()
  const classes = nodes.filter((n) => n.kind === 'entity' || (n.kind === 'contract' && n.level === 'implementation'))
  const safe = new Map(nodes.map((n) => [n.id, _safeSemId(n.id)]))
  const lines = ['@startuml', `skinparam classBackgroundColor ${P.fill}`, `skinparam classBorderColor ${P.border}`,
    `skinparam classFontColor ${P.text}`, `skinparam defaultFontColor ${P.text}`, `skinparam backgroundColor ${P.bg}`,
    `skinparam ArrowColor ${P.line}`, 'skinparam shadowing false']
  for (const n of classes) {
    lines.push(`class "${_semLabel(n.name, 40)}" as ${safe.get(n.id)} {`)
    for (const f of (n.detail?.fields ?? []).slice(0, 30)) {
      lines.push(`  +${_safeIdent(f.name || 'f')} : ${_semLabel(f.type || '?', 24)}`)
    }
    lines.push('}')
  }
  const seen = new Set<string>()
  for (const e of edges) {
    const a = safe.get(e.from)
    const b = safe.get(e.to)
    if (!a || !b || a === b) continue
    const t = (e.type || '').toLowerCase()
    let arrow = _puArrow(e)
    if (e.indirect) arrow = '..>'
    else if (t.includes('extends')) arrow = '<|--'
    else if (t.includes('implements')) arrow = '<|..'
    else if (t.includes('contains') || t.includes('instantiates')) arrow = '*--'
    const key = `${a}${arrow}${b}`
    if (seen.has(key)) continue
    seen.add(key)
    lines.push(`${a} ${arrow} ${b}${(e.desc || e.type) ? ` : ${_semEdgeLabel(e, 14)}` : ''}`)
  }
  lines.push('@enduml')
  return lines.join('\n')
}

// ---- ER 图 ----

function _erRelationArrow(type: string): string {
  const t = (type || '').toLowerCase()
  if (t.includes('1:1') || t === '1-1') return '||--||'
  if (t.includes('n:m') || t.includes('m:n') || t.includes('nm')) return '}o--o{'
  if (t.includes('1:n') || t.includes('1-n') || t.includes('one-to-many')) return '||--o{'
  if (t.includes('contains') || t.includes('has') || t.includes('instantiates')) return '||--o{'
  return '||--o{'
}

export function semanticErDiagramToMermaid(nodes: _Node[], edges: _Edge[]): string {
  const entities = nodes.filter((n) => n.kind === 'entity')
  // mermaid erDiagram 实体 id 需为 ASCII 标识符：用资产 id(稳定且唯一)，业务名以注释行辅助。
  const nameMap = new Map<string, string>(entities.map((n) => [n.id, _safeSemId(n.id)]))
  const lines = ['erDiagram']
  for (const n of entities) {
    lines.push(`  ${nameMap.get(n.id)} {`)
    const fields = (n.detail?.fields ?? []).slice(0, 30)
    if (fields.length) {
      for (const f of fields) lines.push(`    ${_safeIdent(f.type || 'string')} ${_safeIdent(f.name || 'f')}`)
    } else {
      lines.push('    string name')
    }
    lines.push('  }')
  }
  const seen = new Set<string>()
  for (const e of edges) {
    const a = nameMap.get(e.from)
    const b = nameMap.get(e.to)
    if (!a || !b || a === b) continue
    const key = `${a}|${b}`
    if (seen.has(key)) continue
    seen.add(key)
    lines.push(`  ${a} ${_erRelationArrow(e.type || '')} ${b} : "${_puText(_semEdgeLabel(e, 16, 'has'))}"`)
  }
  return lines.join('\n')
}

export function semanticErDiagramToPlantUml(nodes: _Node[], edges: _Edge[]): string {
  const P = currentDiagramPalette()
  const entities = nodes.filter((n) => n.kind === 'entity')
  const nameMap = new Map<string, string>(entities.map((n) => [n.id, _safeSemId(n.id)]))
  const lines = ['@startuml', `skinparam classBackgroundColor ${P.fill}`, `skinparam classBorderColor ${P.border}`,
    `skinparam classFontColor ${P.text}`, `skinparam defaultFontColor ${P.text}`, `skinparam backgroundColor ${P.bg}`,
    `skinparam ArrowColor ${P.line}`, 'skinparam shadowing false']
  for (const n of entities) {
    lines.push(`entity "${_semLabel(n.name, 40)}" as ${nameMap.get(n.id)} {`)
    for (const f of (n.detail?.fields ?? []).slice(0, 30)) {
      lines.push(`  * ${_safeIdent(f.name || 'f')} : ${_safeIdent(f.type || '?')}`)
    }
    lines.push('}')
  }
  const seen = new Set<string>()
  for (const e of edges) {
    const a = nameMap.get(e.from)
    const b = nameMap.get(e.to)
    if (!a || !b || a === b) continue
    const key = `${a}|${b}`
    if (seen.has(key)) continue
    seen.add(key)
    lines.push(`${a} ${_erRelationArrow(e.type || '')} ${b} : ${_puText(_semEdgeLabel(e, 16, 'has'))}`)
  }
  lines.push('@enduml')
  return lines.join('\n')
}

// ---- 序列图 ----

export function semanticSequenceDiagramToMermaid(nodes: _Node[], edges: _Edge[]): string {
  const parts = nodes.filter((n) => n.kind === 'process' || n.kind === 'contract')
  const safe = new Map(nodes.map((n) => [n.id, _safeSemId(n.id)]))
  const lines = ['sequenceDiagram']
  const shown = new Set<string>()
  for (const n of parts) {
    lines.push(`  participant ${safe.get(n.id)} as ${_semLabel(n.name, 26)}`)
    shown.add(n.id)
  }
  if (!parts.length) return 'sequenceDiagram'
  for (const n of parts) {
    if (n.detail?.trigger) lines.push(`  Note right of ${safe.get(n.id)}: 触发: ${_semLabel(String(n.detail.trigger), 40)}`)
    for (const s of (n.detail?.steps ?? []).slice(0, 30)) {
      lines.push(`  ${safe.get(n.id)}->>${safe.get(n.id)}: ${(s.order ?? '') ? `${s.order}. ` : ''}${_semLabel(s.semantic || '', 50)}`)
    }
  }
  const seen = new Set<string>()
  for (const e of edges) {
    if (!shown.has(e.from) || !shown.has(e.to)) continue
    const key = `${e.from}|${e.to}|${e.type}`
    if (seen.has(key)) continue
    seen.add(key)
    const t = (e.type || '').toLowerCase()
    if (t.includes('references')) continue
    lines.push(`  ${safe.get(e.from)}->>${safe.get(e.to)}: ${_semEdgeLabel(e, 24, '交互')}`)
  }
  return lines.join('\n')
}

export function semanticSequenceDiagramToPlantUml(nodes: _Node[], edges: _Edge[]): string {
  const P = currentDiagramPalette()
  const parts = nodes.filter((n) => n.kind === 'process' || n.kind === 'contract')
  const safe = new Map(nodes.map((n) => [n.id, _safeSemId(n.id)]))
  const lines = ['@startuml', `skinparam sequenceParticipantBackgroundColor ${P.fill}`,
    `skinparam sequenceParticipantBorderColor ${P.border}`, `skinparam sequenceParticipantFontColor ${P.text}`,
    `skinparam defaultFontColor ${P.text}`, `skinparam backgroundColor ${P.bg}`, `skinparam ArrowColor ${P.line}`,
    'skinparam shadowing false']
  const shown = new Set<string>()
  for (const n of parts) {
    lines.push(`participant ${safe.get(n.id)} as "${_semLabel(n.name, 26)}"`)
    shown.add(n.id)
  }
  if (!parts.length) return '@startuml\n@enduml'
  for (const n of parts) {
    if (n.detail?.trigger) lines.push(`note right of ${safe.get(n.id)}: 触发: ${_semLabel(String(n.detail.trigger), 40)}`)
    for (const s of (n.detail?.steps ?? []).slice(0, 30)) {
      lines.push(`${safe.get(n.id)} -> ${safe.get(n.id)} : ${(s.order ?? '') ? `${s.order}. ` : ''}${_semLabel(s.semantic || '', 50)}`)
    }
  }
  const seen = new Set<string>()
  for (const e of edges) {
    if (!shown.has(e.from) || !shown.has(e.to)) continue
    const key = `${e.from}|${e.to}|${e.type}`
    if (seen.has(key)) continue
    seen.add(key)
    const t = (e.type || '').toLowerCase()
    if (t.includes('references')) continue
    lines.push(`${safe.get(e.from)} -> ${safe.get(e.to)} : ${_semEdgeLabel(e, 24, '交互')}`)
  }
  lines.push('@enduml')
  return lines.join('\n')
}

// ---- 状态/决策图 ----

/** 节点状态机(真实的 state 类别：states/transitions 数据)。 */
function _stateMachines(nodes: _Node[]) {
  return nodes.filter((n) => n.kind === 'state'
    && Array.isArray(n.detail?.states) && n.detail!.states!.length)
}

export function semanticStateDiagramToMermaid(nodes: _Node[], edges: _Edge[]): string {
  const rules = nodes.filter((n) => n.kind === 'decision')
  const machines = _stateMachines(nodes)
  const safe = new Map(nodes.map((n) => [n.id, _safeSemId(n.id)]))
  const lines = ['stateDiagram-v2']
  if (!rules.length && !machines.length) return 'stateDiagram-v2'
  for (const m of machines) {
    const st = m.detail!.states!
    st.forEach((s, i) => {
      const sid = `${safe.get(m.id)}_s${i}`
      lines.push(`  state "${_semLabel(s.name, 24)}" as ${sid}`)
      if (s.initial) lines.push(`  [*] --> ${sid}`)
    })
    for (const tr of (m.detail?.transitions ?? []).slice(0, 20)) {
      const from = st.findIndex((s) => s.name === tr.from)
      const to = st.findIndex((s) => s.name === tr.to)
      if (from < 0 || to < 0 || from === to) continue
      const label = [tr.event, tr.condition].filter(Boolean).join(' && ') || '迁移'
      lines.push(`  ${safe.get(m.id)}_s${from} --> ${safe.get(m.id)}_s${to} : ${_semLabel(label, 30)}`)
    }
    const finals = st.filter((s) => s.final)
    finals.forEach((s) => {
      const idx = st.findIndex((x) => x.name === s.name)
      if (idx >= 0) lines.push(`  ${safe.get(m.id)}_s${idx} --> [*]`)
    })
  }
  for (const n of rules) lines.push(`  state "${_semLabel(n.name, 30)}" as ${safe.get(n.id)}`)
  for (const n of rules) {
    const branches = (n.detail?.branches ?? []).slice(0, 6)
    branches.forEach((b, i) => {
      const s = `${safe.get(n.id)}_b${i}`
      lines.push(`  state "${_semLabel(b.condition || `分支${i + 1}`, 24)}" as ${s}`)
      lines.push(`  ${safe.get(n.id)} --> ${s}`)
      lines.push(`  ${s} --> ${safe.get(n.id)}_t${i} : 成立`)
      lines.push(`  state "${_semLabel(String(b.then ?? 'then'), 20)}" as ${safe.get(n.id)}_t${i}`)
      lines.push(`  ${s} --> ${safe.get(n.id)}_e${i} : 不成立`)
      lines.push(`  state "${_semLabel(String(b.else ?? 'else'), 20)}" as ${safe.get(n.id)}_e${i}`)
    })
  }
  const seen = new Set<string>()
  for (const e of edges) {
    if (!rules.some((r) => r.id === e.from)) continue
    const a = safe.get(e.from)
    const b = safe.get(e.to)
    if (!a || !b || a === b) continue
    const key = `${a}|${b}`
    if (seen.has(key)) continue
    seen.add(key)
    lines.push(`  ${a} --> ${b} : ${_semEdgeLabel(e, 14, '转移')}`)
  }
  return lines.join('\n')
}

export function semanticStateDiagramToPlantUml(nodes: _Node[], edges: _Edge[]): string {
  const lbl = (t: string, max = 40) => _puText(_semLabel(t, max))
  const P = currentDiagramPalette()
  const rules = nodes.filter((n) => n.kind === 'decision')
  const machines = _stateMachines(nodes)
  const safe = new Map(nodes.map((n) => [n.id, _safeSemId(n.id)]))
  const lines = ['@startuml', `skinparam stateBackgroundColor ${P.fill}`, `skinparam stateBorderColor ${P.border}`,
    `skinparam stateFontColor ${P.text}`, `skinparam defaultFontColor ${P.text}`, `skinparam backgroundColor ${P.bg}`,
    `skinparam ArrowColor ${P.line}`, 'skinparam shadowing false']
  if (!rules.length && !machines.length) return '@startuml\n@enduml'
  for (const m of machines) {
    const st = m.detail!.states!
    st.forEach((s, i) => {
      const sid = `${safe.get(m.id)}_s${i}`
      lines.push(`state "${lbl(s.name, 24)}" as ${sid}`)
      if (s.initial) lines.push(`[*] --> ${sid}`)
    })
    for (const tr of (m.detail?.transitions ?? []).slice(0, 20)) {
      const from = st.findIndex((s) => s.name === tr.from)
      const to = st.findIndex((s) => s.name === tr.to)
      if (from < 0 || to < 0 || from === to) continue
      const label = [tr.event, tr.condition].filter(Boolean).join(' && ') || '迁移'
      lines.push(`${safe.get(m.id)}_s${from} --> ${safe.get(m.id)}_s${to} : ${lbl(label, 30)}`)
    }
    const finals = st.filter((s) => s.final)
    finals.forEach((s) => {
      const idx = st.findIndex((x) => x.name === s.name)
      if (idx >= 0) lines.push(`${safe.get(m.id)}_s${idx} --> [*]`)
    })
  }
  for (const n of rules) lines.push(`state "${lbl(n.name, 30)}" as ${safe.get(n.id)}`)
  for (const n of rules) {
    const branches = (n.detail?.branches ?? []).slice(0, 6)
    branches.forEach((b, i) => {
      const s = `${safe.get(n.id)}_b${i}`
      lines.push(`state "${lbl(b.condition || `分支${i + 1}`, 24)}" as ${s}`)
      lines.push(`${safe.get(n.id)} --> ${s}`)
      lines.push(`${s} --> ${safe.get(n.id)}_t${i} : 成立`)
      lines.push(`state "${lbl(String(b.then ?? 'then'), 20)}" as ${safe.get(n.id)}_t${i}`)
      lines.push(`${s} --> ${safe.get(n.id)}_e${i} : 不成立`)
      lines.push(`state "${lbl(String(b.else ?? 'else'), 20)}" as ${safe.get(n.id)}_e${i}`)
    })
  }
  const seen = new Set<string>()
  for (const e of edges) {
    if (!rules.some((r) => r.id === e.from)) continue
    const a = safe.get(e.from)
    const b = safe.get(e.to)
    if (!a || !b || a === b) continue
    const key = `${a}|${b}`
    if (seen.has(key)) continue
    seen.add(key)
    lines.push(`${a} --> ${b} : ${lbl(_semEdgeLabel(e, 14, '转移'), 30)}`)
  }
  lines.push('@enduml')
  return lines.join('\n')
}

// ---- 活动/泳道图(决策化：if/else 判定 + 步骤顺序 + 跨资产转移) ----

function _activityOrder(nodes: _Node[]): _Node[] {
  return [...nodes].sort((a, b) => {
    const pr = (k: string) => (k === 'process' ? 0 : k === 'decision' ? 1 : k === 'contract' ? 2 : 3)
    const lv = (l?: string) => (l === 'logic' ? 0 : l === 'implementation' ? 1 : 2)
    return pr(a.kind) - pr(b.kind) || lv(a.level) - lv(b.level) || (a.name || '').localeCompare(b.name || '')
  })
}

function _hasActivityDetail(nodes: _Node[]): boolean {
  return nodes.some((n) => (n.detail?.steps?.length ?? 0) > 0
    || (n.detail?.branches?.length ?? 0) > 0
    || !!n.detail?.trigger)
}

/** 分支 else 为空时使用「跳过/继续」占位，避免出现 '?'。 */
function _branchElseLabel(b: { else?: unknown }): string {
  return (String(b.else ?? '').trim()) || '跳过/继续'
}

export function semanticActivityDiagramToMermaid(nodes: _Node[], edges: _Edge[]): string {
  const P = currentDiagramPalette()
  const safe = new Map(nodes.map((n) => [n.id, _safeSemId(n.id)]))
  const lines = ['flowchart TD']
  lines.push(`  classDef process fill:${P.fill},stroke:#89b4fa,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef decision fill:${P.fill},stroke:#a6e3a1,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef contract fill:${P.fill},stroke:#f9e2af,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef asset fill:${P.fill},stroke:#cba6f7,stroke-width:2px,color:${P.text}`)
  lines.push(`  classDef stale fill:${P.staleFill},stroke:#f38ba8,stroke-width:2px,color:${P.staleText}`)
  // mermaid flowchart 边数硬上限 500(超出抛 "Edge limit exceeded" 整图崩溃)；
  // 预留余量，预算耗尽即停(退化为部分流程，不崩图)。
  const EDGE_BUDGET = 450
  let edgeCount = 0
  const overBudget = () => edgeCount >= EDGE_BUDGET
  if (!_hasActivityDetail(nodes)) {
    // 退化：无 steps/branches/trigger → 按 scopeKey 泳道分组展示
    const byScope = new Map<string, _Node[]>()
    for (const n of nodes) {
      const k = n.scopeKey || '其它'
      if (!byScope.has(k)) byScope.set(k, [])
      byScope.get(k)!.push(n)
    }
    for (const [k, group] of byScope) {
      const sid = `sw_${_safeIdent(k)}`
      lines.push(`  subgraph ${sid}["${_semLabel(k, 30)}"]`)
      lines.push(`  style ${sid} fill:${P.bgDeep},stroke:${P.border},color:#89b4fa,font-weight:600`)
      for (const n of group) {
        lines.push(`    ${safe.get(n.id)}["${_semNodeLabel(n, 30)}"]`)
        lines.push(`    class ${safe.get(n.id)} ${n.kind || 'process'}`)
      }
      lines.push('  end')
    }
    const seen = new Set<string>()
    for (const e of edges) {
      if (overBudget()) break
      const a = safe.get(e.from)
      const b = safe.get(e.to)
      if (!a || !b || a === b) continue
      const key = `${a}->${b}`
      if (seen.has(key)) continue
      seen.add(key)
      edgeCount++
      lines.push(`  ${a} ${_mmdArrow(e)}${(e.desc || e.type || e.indirect) ? `|${_semEdgeLabel(e, 12)}|` : ''} ${b}`)
    }
    lines.push(`  linkStyle default stroke:${P.line},color:${P.text},stroke-width:1.5px`)
    return lines.join('\n')
  }
  const kindStyle = (k: string) => ({ process: 'process', decision: 'decision', contract: 'contract', asset: 'asset', state: 'state' })[k] || undefined
  let seq = 0
  const nid = () => `n${seq++}`
  const addNode = (label: string, style?: string): string => {
    const id = nid()
    lines.push(`  ${id}["${_semLabel(label, 30)}"]${style ? `:::${style}` : ''}`)
    return id
  }
  const link = (a?: string, b?: string) => { if (a && b && a !== b && !overBudget()) { edgeCount++; lines.push(`  ${a} --> ${b}`) } }
  const labeledLink = (a: string, b: string, text: string) => { if (!overBudget()) { edgeCount++; lines.push(`  ${a} -- ${text} --> ${b}`) } }
  const entry = new Map<string, string>()
  const exit = new Map<string, string>()
  for (const n of _activityOrder(nodes)) {
    if (overBudget()) break   // 预算耗尽：后续资产不再展开(其跨资产边也因 entry/exit 缺失自动跳过)
    const style = kindStyle(n.kind)
    let first: string | undefined
    let last: string | undefined
    if (n.detail?.trigger) {
      first = addNode(`⚡ ${String(n.detail.trigger)}`, 'process')
      last = first
    }
    const branches = (n.detail?.branches ?? []).filter((b) => (b.condition || '').trim())
    if (n.kind === 'decision' && branches.length) {
      const join = addNode(`${_semLabel(n.name, 20)} 合并`, style)
      for (const b of branches.slice(0, 6)) {
        const cond = addNode(String(b.condition).trim(), 'decision')
        const t = addNode(String(b.then ?? 'then'), style)
        const e = addNode(_branchElseLabel(b), style)
        if (!first) first = cond
        if (last) link(last, cond)
        last = cond
        labeledLink(cond, t, '成立')
        labeledLink(cond, e, '不成立')
        link(t, join)
        link(e, join)
      }
      if (last) link(last, join)
      last = join
      if (!first) first = join
    } else if ((n.detail?.steps ?? []).length) {
      for (const s of (n.detail!.steps ?? []).slice(0, 30)) {
        const txt = (s.semantic || '').trim() || _semLabel(n.name, 20)
        const cond = (s.condition || '').trim()
        if (cond) {
          const c = addNode(cond, 'decision')
          const act = addNode(txt, style)
          if (!first) first = c
          if (last) link(last, c)
          last = c
          labeledLink(c, act, '成立')
          last = act
        } else {
          const act = addNode(txt, style)
          if (!first) first = act
          if (last) link(last, act)
          last = act
        }
      }
    } else {
      const node = addNode(`${_semNodeLabel(n, 24)}`, style)
      if (!first) first = node
      if (last) link(last, node)
      last = node
    }
    if (first) entry.set(n.id, first)
    if (last) exit.set(n.id, last)
  }
  const seen = new Set<string>()
  for (const e of edges) {
    if (overBudget()) break
    const a = exit.get(e.from)
    const b = entry.get(e.to)
    if (!a || !b || a === b) continue
    const key = `${a}|${b}`
    if (seen.has(key)) continue
    seen.add(key)
    edgeCount++
    lines.push(`  ${a} -->|${_semLabel(e.type || '', 12)}| ${b}`)
  }
  lines.push(`  linkStyle default stroke:${P.line},color:${P.text},stroke-width:1.5px`)
  return lines.join('\n')
}

export function semanticActivityDiagramToPlantUml(nodes: _Node[], edges: _Edge[]): string {
  const lbl = (t: string, max = 40) => _puText(_semLabel(t, max))
  const P = currentDiagramPalette()
  const lines = ['@startuml', `skinparam activityBackgroundColor ${P.fill}`, `skinparam activityBorderColor ${P.border}`,
    `skinparam activityFontColor ${P.text}`, `skinparam defaultFontColor ${P.text}`, `skinparam backgroundColor ${P.bg}`,
    `skinparam ArrowColor ${P.line}`, 'skinparam shadowing false']
  if (!_hasActivityDetail(nodes)) {
    // 退化：无 detail → 按 scopeKey 泳道 partition。
    // PlantUML 要求泳道在图起始处先声明(否则 400: swimlane must be defined at the start)；
    // 故先集中声明全部泳道，start 后再按组切换。
    const byScope = new Map<string, _Node[]>()
    for (const n of nodes) {
      const k = n.scopeKey || '其它'
      if (!byScope.has(k)) byScope.set(k, [])
      byScope.get(k)!.push(n)
    }
    const lane = (k: string) => lbl(k, 20).replace(/[|;:]/g, ' ')
    const lanes = [...byScope.keys()].map(lane)
    for (const ln of lanes) lines.push(`|${ln}|`)   // 声明必须带尾竖线(无尾竖线 400)
    lines.push('start')
    for (const [k, group] of byScope) {
      lines.push(`|${lane(k)}|`)
      for (const n of group) lines.push(`:${lbl(n.name, 40)};`)
    }
    lines.push('stop', '@enduml')
    return lines.join('\n')
  }
  // ── DAG(仅节点集内边) + 拓扑序 ──────────────────────────────
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const succ = new Map<string, string[]>()
  const pred = new Map<string, string[]>()
  for (const n of nodes) { succ.set(n.id, []); pred.set(n.id, []) }
  for (const e of edges) {
    if (!e.from || !e.to || e.from === e.to) continue
    if (!byId.has(e.from) || !byId.has(e.to)) continue
    if (!succ.get(e.from)!.includes(e.to)) succ.get(e.from)!.push(e.to)
    if (!pred.get(e.to)!.includes(e.from)) pred.get(e.to)!.push(e.from)
  }
  const order = _activityOrder(nodes).map((n) => n.id)
  const idx = new Map(order.map((id, i) => [id, i]))
  const done = new Set<string>()
  const topo: string[] = []
  while (done.size < order.length) {
    const ready = order.filter((id) => !done.has(id) && (pred.get(id) ?? []).every((p) => done.has(p)))
    if (!ready.length) break // 环(防御) → 剩余兜底
    ready.sort((a, b) => idx.get(a)! - idx.get(b)!)
    for (const id of ready) { done.add(id); topo.push(id) }
  }
  for (const id of order) if (!done.has(id)) { done.add(id); topo.push(id) }
  const topoIdx = new Map(topo.map((id, i) => [id, i]))

  /** 可达后代(排除自身，环安全)。 */
  const descendants = (start: string): Set<string> => {
    const out = new Set<string>()
    const stack = [...(succ.get(start) ?? [])]
    while (stack.length) {
      const s = stack.pop()!
      if (out.has(s)) continue
      out.add(s)
      for (const t of succ.get(s) ?? []) if (!out.has(t)) stack.push(t)
    }
    return out
  }
  const isJoin = (id: string) => (pred.get(id) ?? []).length >= 2

  /** 汇聚点：被 >=2 个分支可达、且为 join 节点、拓扑序最靠前者。 */
  const commonJoin = (branchIds: string[]): string | undefined => {
    const counts = new Map<string, number>()
    for (const b of branchIds) {
      for (const id of descendants(b)) {
        if (!isJoin(id)) continue
        counts.set(id, (counts.get(id) ?? 0) + 1)
      }
    }
    let best: string | undefined
    let bestN = 0
    for (const [id, c] of counts) {
      if (c < 2) continue
      if (c > bestN || (c === bestN && best && topoIdx.get(id)! < topoIdx.get(best)!)) {
        bestN = c; best = id
      }
    }
    return best
  }

  const emitNode = (n: _Node) => {
    if (n.detail?.trigger) lines.push(`:${lbl(String(n.detail.trigger), 50)};`)
    const branches = (n.detail?.branches ?? []).filter((b) => (b.condition || '').trim())
    if (n.kind === 'decision' && branches.length) {
      for (const b of branches.slice(0, 6)) {
        lines.push(`if (${lbl(String(b.condition).trim(), 40)}) then (成立)`)
        lines.push(`  :${lbl(String(b.then ?? 'then'), 40)};`)
        lines.push(`else (不成立)`)
        lines.push(`  :${lbl(_branchElseLabel(b), 40)};`)
        lines.push('endif')
      }
      return
    }
    const steps = n.detail?.steps ?? []
    if (steps.length) {
      for (const s of steps.slice(0, 30)) {
        const txt = lbl((s.semantic || '').trim() || n.name, 40)
        const cond = (s.condition || '').trim()
        if (cond) {
          lines.push(`if (${lbl(cond, 40)}) then`)
          lines.push(`  :${txt};`)
          lines.push('endif')
        } else {
          lines.push(`:${txt};`)
        }
      }
      return
    }
    lines.push(`:${lbl(n.name, 40)};`)
  }

  // ── 结构化发射：分叉→fork，汇聚→end fork 后发射共享 join 节点 ──
  const emitted = new Set<string>()
  const onPath = new Set<string>()

  const emitSubtree = (id: string, skipJoin?: string) => {
    if (emitted.has(id) || id === skipJoin || onPath.has(id)) return
    onPath.add(id)
    emitted.add(id)
    const node = byId.get(id)
    if (node) emitNode(node)
    const next = (succ.get(id) ?? []).filter((s) => !emitted.has(s) && s !== skipJoin)
    let join: string | undefined
    if (next.length >= 2) join = commonJoin(next)
    const effective = next.filter((s) => s !== join && !emitted.has(s))
    const CAP = 8
    const branches = effective.slice(0, CAP)
    if (branches.length === 1) {
      emitSubtree(branches[0], join ?? skipJoin)
      if (join && join !== skipJoin) emitSubtree(join, skipJoin)
    } else if (branches.length >= 2) {
      lines.push('fork')
      branches.forEach((s, i) => {
        if (i) lines.push('fork again')
        emitSubtree(s, join ?? skipJoin)
      })
      lines.push('end fork')
      if (join && join !== skipJoin) emitSubtree(join, skipJoin)
    } else if (join && join !== skipJoin) {
      emitSubtree(join, skipJoin)
    }
    onPath.delete(id)
  }

  const roots = topo.filter((id) => (pred.get(id) ?? []).length === 0)
  lines.push('start')
  if (roots.length === 0) {
    // 孤立/环：顺序兜底
    for (const id of topo) {
      if (!emitted.has(id)) { emitted.add(id); const n = byId.get(id); if (n) emitNode(n) }
    }
  } else if (roots.length === 1) {
    emitSubtree(roots[0])
  } else {
    const join = commonJoin(roots)
    const effectiveRoots = roots.filter((r) => r !== join && !emitted.has(r)).slice(0, 8)
    if (effectiveRoots.length === 1) {
      emitSubtree(effectiveRoots[0], join)
      if (join) emitSubtree(join)
    } else if (effectiveRoots.length >= 2) {
      lines.push('fork')
      effectiveRoots.forEach((r, i) => {
        if (i) lines.push('fork again')
        emitSubtree(r, join)
      })
      lines.push('end fork')
      if (join) emitSubtree(join)
    } else if (join) {
      emitSubtree(join)
    }
  }
  // 兜底：未发出的节点(孤立点/防御遗漏)顺序补发
  for (const id of topo) {
    if (!emitted.has(id)) { emitted.add(id); const n = byId.get(id); if (n) emitNode(n) }
  }
  lines.push('stop', '@enduml')
  return lines.join('\n')
}

// ---- 聚合/分层图 ----

export function semanticMindmapToMermaid(nodes: _Node[]): string {
  if (!nodes.length) return 'mindmap\n  root((空))'
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const lines = ['mindmap', '  root((语义资产))']
  const high = nodes.filter((n) => n.level === 'business')
  const shownHigh = new Set<string>()
  if (high.length) {
    for (const n of high.slice(0, 40)) {
      if (shownHigh.has(n.id)) continue
      shownHigh.add(n.id)
      lines.push(`    ${_semLabel(n.name, 30)}`)
      for (const a of (n.detail?.aggregates ?? []).slice(0, 30)) {
        if (a.assetId && byId.has(a.assetId) && !shownHigh.has(a.assetId)) {
          shownHigh.add(a.assetId)
          lines.push(`      ${_semLabel(a.name || byId.get(a.assetId)?.name || a.assetId, 30)}`)
        }
      }
    }
  } else {
    // 无 high 资产：按 aggregates 构建两到三层树
    const roots = nodes.filter((n) => !nodes.some((o) => o.id !== n.id && o.detail?.aggregates?.some((a) => a.assetId === n.id)))
    for (const n of roots.slice(0, 40)) {
      if (shownHigh.has(n.id)) continue
      shownHigh.add(n.id)
      lines.push(`    ${_semLabel(n.name, 30)}`)
      const kids = nodes.filter((o) => o.id !== n.id && o.detail?.aggregates?.some((a) => a.assetId === n.id))
      for (const k of kids.slice(0, 20)) {
        if (shownHigh.has(k.id)) continue
        shownHigh.add(k.id)
        lines.push(`      ${_semLabel(k.name, 30)}`)
      }
    }
  }
  return lines.join('\n')
}

export function semanticMindmapToPlantUml(nodes: _Node[]): string {
  if (!nodes.length) return '@startmindmap\n* 空\n@endmindmap'
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const lines = ['@startmindmap', '* 语义资产']
  const shown = new Set<string>()
  const high = nodes.filter((n) => n.level === 'business')
  const seed = high.length ? high : nodes.filter((n) => !nodes.some((o) => o.id !== n.id && o.detail?.aggregates?.some((a) => a.assetId === n.id)))
  for (const n of seed.slice(0, 40)) {
    if (shown.has(n.id)) continue
    shown.add(n.id)
    lines.push(`** ${_semLabel(n.name, 30)}`)
    for (const a of (n.detail?.aggregates ?? []).slice(0, 30)) {
      if (!a.assetId || !byId.has(a.assetId)) continue
      lines.push(`*** ${_semLabel(a.name || byId.get(a.assetId)?.name || a.assetId, 30)}`)
      shown.add(a.assetId)
    }
  }
  lines.push('@endmindmap')
  return lines.join('\n')
}

// ---- 视图分发表 ----

export const SEMANTIC_VIEW_GENERATORS: Record<SemanticGraphViewId, {
  mermaid: (nodes: _Node[], edges: _Edge[]) => string
  plantuml: (nodes: _Node[], edges: _Edge[]) => string
}> = {
  flow: { mermaid: semanticGraphToMermaid, plantuml: semanticGraphToPlantUml },
  class: { mermaid: semanticClassDiagramToMermaid, plantuml: semanticClassDiagramToPlantUml },
  er: { mermaid: semanticErDiagramToMermaid, plantuml: semanticErDiagramToPlantUml },
  seq: { mermaid: semanticSequenceDiagramToMermaid, plantuml: semanticSequenceDiagramToPlantUml },
  state: { mermaid: semanticStateDiagramToMermaid, plantuml: semanticStateDiagramToPlantUml },
  activity: { mermaid: semanticActivityDiagramToMermaid, plantuml: semanticActivityDiagramToPlantUml },
  mindmap: { mermaid: semanticMindmapToMermaid, plantuml: semanticMindmapToPlantUml },
}

/** 生成某视图的 mermaid+plantuml 两版源码。 */
export function semanticGraphViewDiagrams(
  view: SemanticGraphViewId,
  nodes: _Node[],
  edges: _Edge[],
): { mermaid: string; plantuml: string } {
  const g = SEMANTIC_VIEW_GENERATORS[view] ?? SEMANTIC_VIEW_GENERATORS.flow
  return { mermaid: g.mermaid(nodes, edges), plantuml: g.plantuml(nodes, edges) }
}

/** 图内点击节点 id(node-click 插件剥壳后) → 资产 id 映射；未渲染的合成节点不在表内。
 *  同时含 label 反查副映射(口径=各引擎渲染的节点显示名，经 _semLabel 截断)：
 *  plantuml class/er/state/activity/mindmap 与 mermaid mindmap 无可寻址 id，
 *  由 node-click 文本兜底(txt:显示名)命中。先到先得，主键(稳定 id)不覆盖。 */
export function semanticViewClickIds(
  view: SemanticGraphViewId,
  nodes: { id: string; name: string }[],
): Map<string, string> {
  const out = new Map<string, string>()
  const put = (k: string, id: string) => { if (k && !out.has(k)) out.set(k, id) }
  if (view === 'flow') {
    nodes.forEach((n, i) => out.set(`n${i}`, n.id))
    // plantuml component 文本为「名称 · 资产ID」(18 字截断)；label 兜底另由 onNodeClick 尾段解析
    for (const n of nodes) put(_semNodeLabel(n, 18), n.id)
  } else if (view === 'class') {
    for (const [id, name] of _safeClassNames(nodes)) put(name, id)
    for (const n of nodes) put(_semLabel(n.name, 40), n.id)   // plantuml class 文本=显示名
  } else if (view === 'seq') {
    for (const n of nodes) { put(_safeSemId(n.id), n.id); put(_semLabel(n.name, 26), n.id) }
  } else if (view === 'state') {
    for (const n of nodes) { put(_safeSemId(n.id), n.id); put(_semLabel(n.name, 30), n.id) }
  } else if (view === 'er') {
    for (const n of nodes) put(_safeSemId(n.id), n.id)   // plantuml/mermaid er 文本=净化 id
  } else if (view === 'mindmap') {
    for (const n of nodes) put(_semLabel(n.name, 30), n.id)
  } else {
    // activity：退化分支(按资产)=safeSemId；detail 分支为步骤文本，不映射到资产
    for (const n of nodes) {
      put(_safeSemId(n.id), n.id)
      put(_semLabel(n.name, 40), n.id)
    }
  }
  // 通用文本兜底：裸显示名(各引擎文本兜底点击的常见口径)，不覆盖主键/口径键
  for (const n of nodes) put(n.name, n.id)
  return out
}
