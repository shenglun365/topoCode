/**
 * 链路跟踪(深度探索模式·trace tab)：单资产上/下游处理链条的符号级 DFS。
 *
 * 形态=独立图谱 tab(kind='trace')：中心固定为打开时的资产(选中切换不重算)；
 * 图面只渲染链路相关节点(资产子图 + 未锚定符号合成节点)；侧栏可拖动。
 * 与邻域聚焦互不相关(不同 tab 形态)。方向切换/刷新=显式重算。
 */
import { computed, ref, watch } from 'vue'
import {
  semanticAssetService,
  type SemanticTraceNode,
  type SemanticTraceResult,
} from '@/services/semantic-asset-service'
import type { WsDeps } from './graphTypes'

/** 收集链树中全部已锚定资产 id(图面 assets= 收窄)。 */
export function collectAssetIds(root: SemanticTraceNode | null): string[] {
  const out = new Set<string>()
  const walk = (n: SemanticTraceNode): void => {
    if (n.assetId) out.add(n.assetId)
    for (const c of n.children ?? []) walk(c)
  }
  if (root) walk(root)
  return [...out]
}

interface SymNodeSeed {
  symbol: string
  name: string
  file: string
  kind: string
}

/** 收集链树中未锚定符号(图面合成节点注入, 去重保序)。 */
export function collectSymbolNodes(root: SemanticTraceNode | null): SymNodeSeed[] {
  const out = new Map<string, SymNodeSeed>()
  const walk = (n: SemanticTraceNode): void => {
    if (!n.assetId) {
      out.set(n.symbol, { symbol: n.symbol, name: n.name, file: n.file, kind: n.nodeKind })
    }
    for (const c of n.children ?? []) walk(c)
  }
  if (root) walk(root)
  return [...out.values()]
}

/** 链树父子边(from,to 均归一到图面节点 id)。 */
export function collectTraceEdges(root: SemanticTraceNode | null): { from: string; to: string; type: string }[] {
  const out: { from: string; to: string; type: string }[] = []
  const nid = (n: SemanticTraceNode): string => n.assetId || `sym:${n.symbol}`
  const walk = (n: SemanticTraceNode): void => {
    for (const c of n.children ?? []) {
      out.push({ from: nid(n), to: nid(c), type: c.edgeKind || 'calls' })
      walk(c)
    }
  }
  if (root) walk(root)
  return out
}

export function useGraphTrace(D: WsDeps) {
  const traceMode = computed(() => D.props.tab.kind === 'trace')
  const direction = ref<'down' | 'up'>((D.props.tab.direction ?? 'down') as 'down' | 'up')
  const traceLoading = ref(false)
  const degraded = ref(false)
  /** 整链跟踪结果(root 含逐层 children, 受限 DFS 一次到位)。 */
  const tree = ref<SemanticTraceNode | null>(null)
  const extraRoots = ref<SemanticTraceNode[]>([])
  const paths = ref<SemanticTraceNode[][]>([])
  const stats = ref<SemanticTraceResult['trace']['stats'] | null>(null)
  /** 懒加载补全的子树缓存: symbol → 子节点列表(truncated/跨分支引用深入)。 */
  const expanded = ref<Record<string, SemanticTraceNode[]>>({})
  const traceExpanding = ref<Set<string>>(new Set())
  const error = ref('')
  /** 侧栏本地高亮(hover); 点击资产节点才驱动图面选中联动。 */
  const highlightId = ref('')
  /** 折叠集合。 */
  const collapsed = ref<Set<string>>(new Set())
  /** SemanticGraphView 注入: 请求宿主打开 trace tab(工具栏入口)。 */
  const openTabRequest = ref<((assetId: string, assetName: string, direction: 'down' | 'up') => void) | null>(null)

  /** 工具栏入口: 以当前选中资产为固定中心开新 trace tab。 */
  function requestOpenTab(): void {
    const aid = D.detail.selId.value
    if (!aid) return
    const name = D.detail.selDetail.value?.name || D.detail.sel.value?.name || aid
    openTabRequest.value?.(aid, name, direction.value)
  }

  async function load(assetId: string, dir?: 'down' | 'up'): Promise<void> {
    if (!assetId) return
    traceLoading.value = true
    error.value = ''
    if (dir) direction.value = dir
    try {
      const r = await semanticAssetService.trace(assetId, direction.value)
      if (r?.error || r?.trace?.error) {
        error.value = (r.error || r.trace?.error) ?? 'trace failed'
        tree.value = null
        return
      }
      tree.value = r.trace?.root ?? null
      extraRoots.value = r.trace?.extraRoots ?? []
      paths.value = r.trace?.paths ?? []
      stats.value = r.trace?.stats ?? null
      degraded.value = !!r.trace?.stats?.degraded
      collapsed.value = new Set()
    } catch (e: unknown) {
      error.value = e instanceof Error && e.message ? e.message : String(e)
      tree.value = null
    } finally {
      traceLoading.value = false
    }
  }

  /** 被剪枝(branchLimit)/跨分支引用(seenElsewhere)的分支懒加载补全。 */
  async function expandNode(node: SemanticTraceNode): Promise<void> {
    if (traceExpanding.value.has(node.symbol) || expanded.value[node.symbol]) return
    const next = new Set(traceExpanding.value)
    next.add(node.symbol)
    traceExpanding.value = next
    try {
      const r = await semanticAssetService.trace(node.assetId || '', direction.value,
        { symbol: node.symbol })
      if (r?.error || r?.trace?.error) {
        error.value = (r.error || r.trace?.error) ?? 'expand failed'
        return
      }
      expanded.value = { ...expanded.value, [node.symbol]: r.trace?.root?.children ?? [] }
    } catch (e: unknown) {
      error.value = e instanceof Error && e.message ? e.message : String(e)
    } finally {
      const done = new Set(traceExpanding.value)
      done.delete(node.symbol)
      traceExpanding.value = done
    }
  }

  /** 方向切换 = 显式重算(中心不变)。 */
  function setDirection(d: 'down' | 'up'): void {
    if (direction.value === d) return
    void load(D.props.tab.assetId ?? '', d)
  }

  /** 图面联动: 点击侧栏资产节点 → 选中(高亮+居中+浮卡), **不重算链路**(中心固定)。 */
  function locate(node: SemanticTraceNode): void {
    if (node.assetId) D.detail.selId.value = node.assetId
  }

  /** 刷新 = 显式重算(中心不变)。 */
  function refresh(): void {
    void load(D.props.tab.assetId ?? '')
  }

  /** 侧栏折叠开关。 */
  function toggleCollapse(node: { symbol: string }): void {
    const next = new Set(collapsed.value)
    if (next.has(node.symbol)) next.delete(node.symbol)
    else next.add(node.symbol)
    collapsed.value = next
  }

  /** 侧栏 ✕ = 关闭整个 trace tab。 */
  function close(): void {
    D.emit('close', D.props.tab.id)
  }

  // tab 切换/首开 → 装载中心链(tab 打开时由 useGraphData.load 的 trace 分支触发一次;
  // 这里兜底: tab 激活且无数据时补拉——避免切 tab 回来空侧栏)
  watch(() => [D.props.tab.id, D.props.tab.kind] as const, ([, kind]) => {
    if (kind === 'trace' && !tree.value && !traceLoading.value) {
      void load(D.props.tab.assetId ?? '')
    }
  })

  const canToggle = computed(() => !!D.detail.selId.value)

  // ⚠️ 键名不得与 data 域(load/loading)/code 域(expanding)撞名——ws=Object.assign 合并,
  // 后域覆盖前域(曾致 trace.load 覆盖 data.load, 常规图谱整体失效)。
  return {
    traceMode, direction, traceLoading, degraded, tree, extraRoots, paths, stats,
    expanded, traceExpanding, error, highlightId, collapsed, canToggle, openTabRequest,
    requestOpenTab, loadTrace: load, refresh, expandNode, setDirection, locate, toggleCollapse, close,
  }
}
