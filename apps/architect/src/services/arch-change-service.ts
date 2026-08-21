import type { ArchitectureModel, ChangeType, DataFlow, ErTable } from '@/types'
import { callsToMermaid, componentsToMermaid, structuresToMermaid } from '@/utils/diagram-gen'
import { currentBaselineInfo } from './baseline-service'
import { useArchProjectStore } from '@/stores/project-store'

/**
 * 架构变更视图的纯计算服务：对比基线快照(v0)与当前快照(v1)，
 * 产出【累计变更影响概要】所需的数量统计、涉及的叶子组件、三类变更图，
 * 以及每类图对应的具体代码变更摘要。
 *
 * 原型阶段代码段为根据变更资产 + AST 节点合成的示意伪代码；后续接入真实
 * git diff + codegraph 后替换为真实 hunk。
 */

export type ChangeNodeKind = 'component' | 'er' | 'orm' | 'entity' | 'flow' | 'dataflow'

export interface ChangeNode {
  id: string
  name: string
  kind: ChangeNodeKind
  change: ChangeType
  file?: string
}

export interface ChangeRelation {
  id: string
  kind: 'depends' | 'calls'
  change: ChangeType
  file?: string
}

export type ChangeCategory = 'structure' | 'dependency' | 'calls'

export interface CodeChangeItem {
  id: string
  category: ChangeCategory
  file: string
  symbol: string
  change: ChangeType
  title: string
  summary: string
  before: string[]
  after: string[]
}

export interface ArchChangeReport {
  baseline: {
    version: string
    commit: string
    branch: string
    analyzedAt: number
    gitDate: number
  }
  files: { added: number; modified: number; deleted: number }
  nodes: ChangeNode[]
  relations: ChangeRelation[]
  /** 涉及到的叶子(最底层 / 无子级)组件名。 */
  leafComponents: string[]
  diagrams: { structure: string; dependency: string; calls: string }
  codeChanges: CodeChangeItem[]
}

const byId = <T extends { id: string }>(list: T[]) => new Map<string, T>(list.map((x) => [x.id, x]))

/** 找出变更的资产节点(含从基线移除的)。 */
function collectNodes(baseline: ArchitectureModel, current: ArchitectureModel): ChangeNode[] {
  const out: ChangeNode[] = []
  const keys: { key: 'components' | 'erTables' | 'ormMappings' | 'entityClasses' | 'executionFlows' | 'dataFlows'; kind: ChangeNodeKind }[] = [
    { key: 'components', kind: 'component' },
    { key: 'erTables', kind: 'er' },
    { key: 'ormMappings', kind: 'orm' },
    { key: 'entityClasses', kind: 'entity' },
    { key: 'executionFlows', kind: 'flow' },
    { key: 'dataFlows', kind: 'dataflow' },
  ]
  for (const { key, kind } of keys) {
    const baseList = baseline[key] as { id: string; name: string; change: ChangeType }[]
    const curList = current[key] as { id: string; name: string; change: ChangeType }[]
    const base = byId(baseList)
    for (const x of curList) {
      const prev = base.get(x.id)
      const change: ChangeType = prev ? x.change : 'added'
      if (change !== 'same') out.push({ id: x.id, name: x.name, kind, change })
    }
    // 基线有、当前已移除
    for (const b of baseList) {
      if (!byId(curList).has(b.id) && b.change !== 'same') {
        out.push({ id: b.id, name: b.name, kind, change: 'removed' })
      }
    }
  }
  return out
}

/** 找出新增/移除的组件依赖边(dependsOn)。 */
function collectDepends(baseline: ArchitectureModel, current: ArchitectureModel): ChangeRelation[] {
  const out: ChangeRelation[] = []
  const baseMap = byId(baseline.components)
  for (const c of current.components) {
    const prev = baseMap.get(c.id)
    const baseDeps = prev?.dependsOn ?? []
    const curDeps = c.dependsOn
    for (const d of baseDeps) {
      if (!curDeps.includes(d)) out.push({ id: `${c.id}~${d}`, kind: 'depends', change: 'removed' })
    }
    for (const d of curDeps) {
      if (!baseDeps.includes(d)) out.push({ id: `${c.id}~${d}`, kind: 'depends', change: 'added' })
    }
  }
  // 基线中存在、当前整组件移除的依赖
  for (const b of baseline.components) {
    if (!byId(current.components).has(b.id)) {
      b.dependsOn.forEach((d) => out.push({ id: `${b.id}~${d}`, kind: 'depends', change: 'removed' }))
    }
  }
  return out
}

/** 找出新增/移除的调用边(数据流 stream)。 */
function collectCalls(baseline: ArchitectureModel, current: ArchitectureModel): ChangeRelation[] {
  const out: ChangeRelation[] = []
  const baseStreamSig = new Set(baseline.dataFlows.flatMap((f) => f.streams.map((s) => `${s.from}|${s.to}|${s.name}`)))
  for (const f of current.dataFlows) {
    for (const s of f.streams) {
      const sig = `${s.from}|${s.to}|${s.name}`
      if (!baseStreamSig.has(sig) && s.change !== 'same') {
        out.push({ id: sig, kind: 'calls', change: s.change === 'removed' ? 'removed' : 'added' })
      }
    }
  }
  return out
}

/** 汇总涉及组件：变更组件 + 增量暂存标记组件，递归取其叶子(最底层)后代名。 */
function collectLeafComponents(baseline: ArchitectureModel, current: ArchitectureModel, stagingAffected: string[]): string[] {
  const all = [...baseline.components, ...current.components]
  const byIdAll = new Map(all.map((c) => [c.id, c]))
  const childrenOf = (id: string) => current.components.filter((c) => c.parentId === id)

  const affectedIds = new Set<string>()
  ;(collectNodes(baseline, current).filter((n) => n.kind === 'component') as ChangeNode[]).forEach((n) => {
    affectedIds.add(n.id)
  })
  stagingAffected.forEach((name) => {
    const c = all.find((x) => x.name === name)
    if (c) affectedIds.add(c.id)
  })

  const leaves = new Set<string>()
  const visit = (id: string) => {
    const kids = childrenOf(id)
    if (!kids.length) {
      leaves.add(byIdAll.get(id)?.name ?? id)
      return
    }
    kids.forEach((k) => visit(k.id))
  }
  affectedIds.forEach((id) => { if (byIdAll.has(id)) visit(id) })
  return [...leaves]
}

/** 根据资产生成示意代码变更段(before/after)。 */
function synthCode(item: { name: string; kind: ChangeNodeKind; change: ChangeType; id: string }): { before: string[]; after: string[] } {
  const cleanName = item.name.replace(/[^A-Za-z0-9_]/g, '')
  let before: string[] = []
  let after: string[] = []
  if (item.change === 'added') {
    before = ['// (baseline 中不存在该资产)']
    after = [
      `// ${item.name} (${item.kind}) — 迭代新增`,
      `func New${cleanName}() *${cleanName} {`,
      `  return &${cleanName}{ /* 初始化 */ }`,
      '}',
    ]
  } else if (item.change === 'removed') {
    before = [
      `func (x *${cleanName}) current() { /* ... */ }`,
      '// 该实现已被移除',
    ]
    after = ['// (当前快照中已不存在)']
  } else {
    before = [
      `func (x *${cleanName}) build() error {`,
      '  return nil',
      '}',
    ]
    after = [
      `func (x *${cleanName}) build() error {`,
      '  // 迭新后的实现',
      '  return nil',
      '}',
    ]
  }
  return { before, after }
}

/**
 * 生成架构变更报告。
 * @param baselineId 基线快照 id(默认 snap-v0)；@param currentId 当前快照 id(默认 snap-v1)
 * @param stagingAffected 增量暂存标记的受影响组件名
 */
export async function computeArchChange(
  baselineId = 'snap-v0',
  currentId = 'snap-v1',
  stagingAffected: string[] = [],
): Promise<ArchChangeReport> {
  const project = useArchProjectStore()
  const baseline = project.snapshots.find((s) => s.id === baselineId)
  const current = project.snapshots.find((s) => s.id === currentId)
  if (!baseline || !current) {
    return {
      baseline: { version: '-', commit: '-', branch: '-', analyzedAt: 0, gitDate: 0 },
      files: { added: 0, modified: 0, deleted: 0 },
      nodes: [], relations: [], leafComponents: [],
      diagrams: { structure: '', dependency: '', calls: '' },
      codeChanges: [],
    }
  }

  const b = baseline.model
  const c = current.model
  const nodes = collectNodes(b, c)
  const relations = [...collectDepends(b, c), ...collectCalls(b, c)]

  const diff = project.status?.diff
  const files = {
    added: diff?.added ?? 0,
    modified: diff?.modified ?? 0,
    deleted: diff?.deleted ?? 0,
  }

  // 代码变更摘要：为每个变更节点(排除纯移除)与每条关系生成示意项
  const codeChanges: CodeChangeItem[] = []
  nodes
    .filter((n) => n.change !== 'removed')
    .forEach((n) => {
      const seg = synthCode(n)
      codeChanges.push({
        id: `node-${n.id}`,
        category: n.kind === 'er' || n.kind === 'orm' || n.kind === 'entity' ? 'structure'
          : n.kind === 'component' ? 'dependency'
            : 'calls',
        file: n.file ?? `${n.kind}:${n.id}`,
        symbol: n.name,
        change: n.change,
        title: `${n.name} (${n.kind})`,
        summary: n.change === 'added' ? `迭代新增 ${n.name}` : `迭代修改 ${n.name}`,
        before: seg.before,
        after: seg.after,
      })
    })
  relations
    .filter((r) => r.change === 'added')
    .forEach((r, i) => {
      codeChanges.push({
        id: `rel-${r.id}-${i}`,
        category: r.kind === 'depends' ? 'dependency' : 'calls',
        file: r.kind === 'depends' ? 'component:depends' : 'dataflow:calls',
        symbol: r.id,
        change: r.change,
        title: `${r.kind === 'depends' ? '依赖' : '调用'} ${r.id}`,
        summary: `${r.kind === 'depends' ? '新增依赖边' : '新增调用边'} ${r.id}`,
        before: [],
        after: [`// ${r.kind === 'depends' ? 'dependsOn' : 'stream'} ${r.id}`],
      })
    })

  const baseInfo = currentBaselineInfo()
  const leafComponents = collectLeafComponents(b, c, stagingAffected)
  const currentDict = {
    components: c.components,
    dataFlows: c.dataFlows,
  }
  const structureTables: ErTable[] = (c.erTables as ErTable[])
    .map((t) => {
      const prev = byId(b.erTables).get(t.id)
      return { ...t, change: prev ? t.change : 'added' }
    })
    .concat(b.erTables.filter((t) => !byId(c.erTables).has(t.id)).map((t) => ({ ...t, change: 'removed' })))
  const dataFlowDict: DataFlow[] = c.dataFlows

  return {
    baseline: {
      version: baseInfo.archVersion,
      commit: baseInfo.commit,
      branch: baseInfo.branch,
      analyzedAt: baseInfo.analyzedAt,
      gitDate: baseInfo.gitDate,
    },
    files,
    nodes,
    relations,
    leafComponents,
    diagrams: {
      structure: structuresToMermaid(structureTables),
      dependency: componentsToMermaid(currentDict.components),
      calls: callsToMermaid(dataFlowDict, currentDict.components),
    },
    codeChanges,
  }
}