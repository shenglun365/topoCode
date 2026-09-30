/**
 * 资产图谱 → 统一图 JSON 适配（批4-2）：SemanticGraphResult → GraphFrameInput。
 *
 * 映射：资产节点=canonical.nodes(key=资产id)；relations 边=canonical.edges；
 * 组件=containers(scopeKey 命中的组件，owns 文件不可入图——容器按成员节点圈定)；
 * rev 双帧=基线底座帧 → 指定视角帧(演化播放/着色的数据源)。
 */
import type { GraphFrameDataInput } from '@topo/engine'
import type { SemanticGraphResult } from '@/services/semantic-asset-service'

export interface ComponentLite { id: string; name: string }

/** 单视图帧构建：给定资产 id 集合 → 存在性帧。 */
function frameOf(ids: Iterable<string>, id: string, label: string,
                 changedIds?: Set<string>) {
  const nodes = [...ids]
  return { id, label, nodes, edges: [] as string[], modified: changedIds ? [...changedIds] : [] }
}

/** 边随两端存活：帧的边 = canonical 边 ∩ 两端同帧。 */
function edgesIn(canonical: GraphFrameDataInput['canonical'],
                 nodeSet: Set<string>): string[] {
  return (canonical.edges || [])
    .filter((e) => nodeSet.has(e.from) && nodeSet.has(e.to))
    .map((e) => e.key || `${e.from}->${e.to}`)
}

export function assetsToGraphFrames(
  g: SemanticGraphResult,
  opts: { rev?: string; changedIds?: Set<string>; components?: ComponentLite[] } = {},
): GraphFrameDataInput {
  const nodes = (g.nodes || []).map((n) => ({
    key: n.id,
    label: n.name || n.id,
    kind: n.kind || 'entity',
  }))
  const keyOf = new Set(nodes.map((n) => n.key))
  const edges = (g.edges || [])
    .filter((e) => keyOf.has(e.from) && keyOf.has(e.to))
    .map((e, i) => ({ key: `e${i}-${e.from}~${e.to}`, from: e.from, to: e.to }))
  // 组件容器：scopeKey(comm-xxx) 命中的成员节点
  const compMembers = new Map<string, string[]>()
  for (const n of g.nodes || []) {
    const cid = (n.scopeKey || '').startsWith('comm-') ? n.scopeKey.slice(5) : ''
    if (!cid) continue
    const list = compMembers.get(cid)
    if (list) list.push(n.id)
    else compMembers.set(cid, [n.id])
  }
  const compById = new Map((opts.components || []).map((c) => [c.id, c]))
  const containers = [...compMembers.keys()].map((cid) => ({
    key: cid,
    label: compById.get(cid)?.name || cid,
    children: compMembers.get(cid) || [],
  }))
  const canonical = { nodes, edges, containers }
  const allIds = nodes.map((n) => n.key)
  const baseIds = opts.changedIds
    ? allIds.filter((id) => !opts.changedIds!.has(id))
    : allIds
  const frames = [
    frameOf(baseIds, 'base', '基线'),
    frameOf(allIds, 'view', opts.rev === 'workspace' ? '工作区' : (opts.rev || '视角'),
            opts.changedIds),
  ]
  // 单帧模式(无变化集)：两帧等价 → 视角帧即全量
  if (!opts.changedIds) frames.splice(0, 1)
  for (const f of frames) {
    const nodeSet = new Set(f.nodes)
    f.edges = edgesIn(canonical, nodeSet)
  }
  return { canonical, frames }
}

/** 静态单帧（kernelMode 默认视图）。 */
export function assetsToStaticSpec(g: SemanticGraphResult,
                                   components?: ComponentLite[]) {
  const gi = assetsToGraphFrames(g, { components })
  return gi
}
