/**
 * 链路跟踪(深度探索模式)：单资产上/下游处理链条的符号级 DFS。
 *
 * 与邻域聚焦(focus+hops, BFS 广度)互补不交叉——聚焦在图内圈定子图，
 * 跟踪在侧栏按层展开链树(整链一次到位; 被剪枝/跨分支引用的节点可懒加载
 * expand 补全)并与图面选中联动。开启跟踪与聚焦互斥(状态机独立)。
 */
import { computed, ref, watch } from 'vue'
import { semanticAssetService, type SemanticTraceNode } from '@/services/semantic-asset-service'
import type { WsDeps } from './graphTypes'

export function useGraphTrace(D: WsDeps) {
  const traceMode = ref(false)
  const direction = ref<'down' | 'up'>('down')
  const loading = ref(false)
  const degraded = ref(false)
  /** 整链跟踪结果(root 含逐层 children, 受限 DFS 一次到位)。 */
  const tree = ref<SemanticTraceNode | null>(null)
  const extraRoots = ref<SemanticTraceNode[]>([])
  /** 懒加载补全的子树缓存: symbol → 子节点列表(truncated/跨分支引用深入)。 */
  const expanded = ref<Record<string, SemanticTraceNode[]>>({})
  const expanding = ref<Set<string>>(new Set())
  const error = ref('')
  /** 侧栏本地高亮(hover); 点击资产节点才驱动图面选中联动。 */
  const highlightId = ref('')
  /** 折叠集合(默认全展开, 受限树体积可控)。 */
  const collapsed = ref<Set<string>>(new Set())

  async function load(assetId: string): Promise<void> {
    if (!assetId) return
    loading.value = true
    error.value = ''
    try {
      const r = await semanticAssetService.trace(assetId, direction.value)
      if (r?.error || r?.trace?.error) {
        error.value = (r.error || r.trace?.error) ?? 'trace failed'
        tree.value = null
        return
      }
      tree.value = r.trace?.root ?? null
      extraRoots.value = r.trace?.extraRoots ?? []
      degraded.value = !!r.trace?.stats?.degraded
      collapsed.value = new Set()
    } catch (e: unknown) {
      error.value = e instanceof Error && e.message ? e.message : String(e)
      tree.value = null
    } finally {
      loading.value = false
    }
  }

  /** 被剪枝(branchLimit)/跨分支引用(seenElsewhere)的分支懒加载补全。 */
  async function expandNode(node: SemanticTraceNode): Promise<void> {
    if (expanding.value.has(node.symbol) || expanded.value[node.symbol]) return
    const next = new Set(expanding.value)
    next.add(node.symbol)
    expanding.value = next
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
      const done = new Set(expanding.value)
      done.delete(node.symbol)
      expanding.value = done
    }
  }

  function toggle(): void {
    if (traceMode.value) {
      close()
      return
    }
    const aid = D.detail.selId.value
    if (!aid) return                     // 需先选中资产(工具栏按钮已 disable)
    D.detail.focusMode.value = false     // 与邻域聚焦互斥
    traceMode.value = true
    void load(aid)
  }

  function close(): void {
    traceMode.value = false
    tree.value = null
    extraRoots.value = []
    expanded.value = {}
    highlightId.value = ''
    collapsed.value = new Set()
  }

  /** 侧栏折叠开关。 */
  function toggleCollapse(node: { symbol: string }): void {
    const next = new Set(collapsed.value)
    if (next.has(node.symbol)) next.delete(node.symbol)
    else next.add(node.symbol)
    collapsed.value = next
  }

  function setDirection(d: 'down' | 'up'): void {
    if (direction.value === d) return
    direction.value = d
    const aid = D.detail.selId.value
    if (aid) void load(aid)
  }

  /** 图面联动: 点击侧栏资产节点 → 选中(高亮+视口居中, 复用既有联动)。 */
  function locate(node: SemanticTraceNode): void {
    if (node.assetId) D.detail.selId.value = node.assetId
  }

  // 跟踪开启时选中切换 → 跟随整链重查(以新选中为中心)
  watch(() => D.detail.selId.value, (id) => {
    if (traceMode.value && id) void load(id)
  })

  const canToggle = computed(() => !!D.detail.selId.value)

  return {
    traceMode, direction, loading, degraded, tree, extraRoots, expanded,
    expanding, error, highlightId, collapsed, canToggle,
    toggle, traceToggle: toggle, toggleCollapse, close, setDirection, expandNode, locate,
  }
}
