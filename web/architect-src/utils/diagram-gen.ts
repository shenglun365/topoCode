import type { ArchComponent, DataFlow, EntityClass, ErTable, ExecutionFlow, OrmMapping } from '@/types'

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
  const lines = ['flowchart LR']
  lines.push('  classDef green fill:#313244,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4')
  lines.push('  classDef red fill:#313244,stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:#cdd6f4')
  lines.push('  classDef peach fill:#313244,stroke:#fab387,stroke-width:2px,color:#cdd6f4')
  lines.push('  classDef gray fill:#313244,stroke:#585b70,color:#cdd6f4')
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

export function dataflowToTopoScript(df: DataFlow, components: ArchComponent[]): string {
  const lines = ['graph']
  const compIds = new Set<string>()
  df.streams.forEach((s) => { compIds.add(s.from); compIds.add(s.to) })
  const comp = components.filter((c) => compIds.has(c.id))
  comp.forEach((c) => lines.push(`${c.id} [${c.name}] :: ${c.kind}`))
  df.streams.forEach((s) => lines.push(`${s.from} -> ${s.to} : ${s.name}(${s.payload})`))
  return lines.join('\n')
}

const CHANGE_CLASS_DEF = {
  added: 'fill:#313244,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4',
  removed: 'fill:#313244,stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:#cdd6f4',
  modified: 'fill:#313244,stroke:#fab387,stroke-width:2px,color:#cdd6f4',
  same: 'fill:#313244,stroke:#585b70,color:#cdd6f4',
}

/**
 * 数据结构变更图：当前快照的全部 ER 表(classDiagram)，按 change 着色，含表间关系。
 */
export function structuresToMermaid(tables: ErTable[]): string {
  const lines = ['classDiagram']
  lines.push('  direction LR')
  const classDefs: string[] = []
  ;(['added', 'removed', 'modified', 'same'] as const).forEach((k) => {
    classDefs.push(`  classDef ${k} ${CHANGE_CLASS_DEF[k]}`)
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
  const lines = ['flowchart LR']
  lines.push('  classDef added fill:#313244,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4')
  lines.push('  classDef removed fill:#313244,stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:#cdd6f4')
  lines.push('  classDef modified fill:#313244,stroke:#fab387,stroke-width:2px,color:#cdd6f4')
  lines.push('  classDef same fill:#313244,stroke:#585b70,color:#cdd6f4')
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

const SEMANTIC_LEVEL_ORDER = ['high', 'medium', 'low'] as const

const SEMANTIC_LEVEL_LABEL: Record<string, string> = {
  high: 'high · 概念级',
  medium: 'medium · 逻辑级',
  low: 'low · 实现级',
}

function _semLevel(n?: string): string {
  return SEMANTIC_LEVEL_ORDER.includes(n as any) ? (n as string) : 'medium'
}

/** 资产 id → 稳定序号节点标识(mermaid/plantuml 符号安全)。 */
function _semNodeId(idx: number): string {
  return `n${idx}`
}

function _semLabel(s: string, max = 26): string {
  const t = (s || '').replace(/[\[\]{}()]/g, ' ').trim()
  return t.length > max ? `${t.slice(0, max)}…` : (t || '?')
}

/** 语义资产图谱 → Mermaid flowchart(按粒度 high→medium→low 分 subgraph 表达层级)。 */
export function semanticGraphToMermaid(
  nodes: { id: string; kind: string; level?: string; name: string; status?: string; needsUpdate?: number }[],
  edges: { from: string; to: string; type?: string; semantic?: string }[],
): string {
  const lines = ['flowchart TD']
  lines.push('  classDef structure fill:#313244,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4')
  lines.push('  classDef behavior fill:#313244,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4')
  lines.push('  classDef rule fill:#313244,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4')
  lines.push('  classDef contract fill:#313244,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4')
  lines.push('  classDef stale fill:#3a2a2a,stroke:#f38ba8,stroke-width:2px,stroke-dasharray:4 2,color:#f5c2e7')
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
    lines.push(`  style ${lv.toUpperCase()} fill:#1e1e2e,stroke:#45475a,color:#89b4fa,font-weight:600`)
    for (const n of group) {
      const nodeId = _semNodeId(n.idx)
      const status = n.status || 'active'
      const flag = n.needsUpdate ? ' ⚠' : ''
      const style = status === 'stale' ? ':::stale' : n.needsUpdate ? ':::needsUpdate' : ''
      lines.push(`    ${nodeId}["${_semLabel(n.name)}${flag}"]${style}`)
      lines.push(`    class ${nodeId} ${n.kind || 'structure'}`)
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
    const label = (e.type || e.semantic || '').trim()
    lines.push(`  ${a} -->${label ? `|${_semLabel(label, 14)}|` : ''} ${b}`)
  }
  // 显式加粗可见连线(深色背景下保证线/字可读，不依赖全局主题)。
  lines.push('  linkStyle default stroke:#a6adc8,color:#cdd6f4,stroke-width:1.5px')
  return lines.join('\n')
}

/** 语义资产图谱 → PlantUML component 图(按粒度 package 分组表达层级)。 */
export function semanticGraphToPlantUml(
  nodes: { id: string; kind: string; level?: string; name: string; status?: string; needsUpdate?: number }[],
  edges: { from: string; to: string; type?: string; semantic?: string }[],
): string {
  const lines = ['@startuml', 'skinparam componentStyle rectangle', 'skinparam backgroundColor #181825',
    'skinparam ArrowColor #a6adc8', 'skinparam ArrowThickness 1.5', 'skinparam LineColor #a6adc8',
    'skinparam componentBackgroundColor #313244', 'skinparam componentBorderColor #45475a',
    'skinparam componentFontColor #cdd6f4', 'skinparam defaultFontColor #cdd6f4', 'skinparam packageBackgroundColor #1e1e2e',
    'skinparam packageBorderColor #585b70', 'skinparam packageFontColor #89b4fa', 'skinparam shadowing false']
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
      lines.push(`  component "${_semLabel(n.name)}${n.needsUpdate ? ' ⚠' : ''}" as ${nodeId} <<${n.kind || 'structure'}>> #313244`)
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
    const label = (e.type || e.semantic || '').trim()
    lines.push(`${a} --> ${b}${label ? ` : ${_semLabel(label, 18)}` : ''}`)
  }
  lines.push('@enduml')
  return lines.join('\n')
}
