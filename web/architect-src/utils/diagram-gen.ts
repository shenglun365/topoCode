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
