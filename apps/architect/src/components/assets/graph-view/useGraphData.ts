/**
 * 语义图谱 · data 域（MS6-W2 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, ref, watch } from 'vue'
import { recommendedSemanticView, supportedViewsFor, viewUnavailableReasons, SemanticGraphViewId } from '@/utils/diagram-gen'
import type { SemanticAssetLevel, SemanticAssetKind } from '@/types'
import { SemanticGraphResult, semanticAssetService } from '@/services/semantic-asset-service'

export type DiffBucket = 'changed' | 'weak' | 'new' | 'removed'
import type { WsDeps } from './graphTypes'
import { useI18n } from 'vue-i18n'




export function useGraphData(D: WsDeps) {
  const { t } = useI18n()
  const props = D.props

const FILE_BUDGET = 500
const fileIndex = computed(() => props.fileIndex ?? [])
const scopeTotal = computed(() => fileIndex.value.reduce((s, e) => s + e.n, 0))
const overLimit = computed(() => scopeTotal.value > FILE_BUDGET)
// 文件范围选择按 tab 持久化：重开 tab 不再强制圈定。
const fileScopeKey = computed(() => `arch.graph.fileScope:${props.tab.id}`)
const fileScopeSel = ref<string[]>((() => {
  try { return JSON.parse(localStorage.getItem(`arch.graph.fileScope:${props.tab.id}`) || '[]') } catch { return [] }
})())
const fileScopeOpen = ref(false)
/** 已圈定文件集合的资产数(工具栏徽标提示)。 */
const scopeAssets = computed(() => {
  const set = new Set(fileScopeSel.value)
  return fileIndex.value.reduce((s, e) => s + (set.has(e.file) ? e.n : 0), 0)
})
watch(fileScopeKey, (k) => {
  try { fileScopeSel.value = JSON.parse(localStorage.getItem(k) || '[]') } catch { fileScopeSel.value = [] }
})
function applyFileScope(files: string[]) {
  fileScopeSel.value = files
  try { localStorage.setItem(fileScopeKey.value, JSON.stringify(files)) } catch { /* ignore */ }
  fileScopeOpen.value = false
  void load(true)
}

const level = ref<SemanticAssetLevel | ''>('')
/** 类型(资产类别)过滤：空=全部。 */
const kindFilter = ref<SemanticAssetKind | ''>('')
/** 图类型视图(空=按数据区间自动推荐)。 */
const view = ref<SemanticGraphViewId | ''>('')
const graph = ref<SemanticGraphResult | null>(null)

/** 图谱视角(需求 6.3)：工作区默认；可切 head:<sha>（该视角未提取时后端底座∪视角语义=基线骨架）。
 *  baseline:<kbVersion> / 其他分支 head 锚定需先跑 extract_impl(rev=锚点) 产数据。 */
/** 图谱视角动态对齐基线对比目标：worktree→workspace；commit→裸 sha(与对比提取的行 rev 同源)。 */
const graphRev = computed(() => {
  const t = D.diff?.cmpTarget.value
  return !t || t === 'worktree' ? 'workspace' : String(t)
})
/** 视角资产更新：走基线对比提取通道(extract-impl rev=视角)，完成后重载图谱。 */
const revSyncing = ref(false)
async function updateRevAssets() {
  if (revSyncing.value) return
  revSyncing.value = true
  try {
    const r = await semanticAssetService.startExtractImpl({ rev: graphRev.value })
    const jobId = r?.job?.id
    if (jobId && (r.started || r.reason === 'already_running')) {
      const done = await D.diff.waitForJob(jobId)
      if (!done.ok) console.warn('[graph] rev extract failed:', done.error)
    }
    await load(true)
  } finally {
    revSyncing.value = false
  }
}
/** 基线 diff：节点(任一锚点文件 ∈ diffFiles)集合 + 计数，供图例/详情徽标。 */
const diffNodeIds = computed<Set<string>>(() => {
  const s = new Set<string>()
  const df = props.diffFiles
  if (!df || !df.size) return s
  for (const a of graph.value?.anchors ?? []) {
    if (df.has(a.file)) s.add(a.assetId)
  }
  return s
})
const diffNodeCount = computed(() => diffNodeIds.value.size)
function isDiffNode(id: string): boolean {
  return props.diffFiles ? diffNodeIds.value.has(id) : false
}

// ---- 对比口径(任意 head 对)资产级变化：存在时优先于文件级 diff 徽标 ----
/** 资产 id → 变化桶(后端 asset-compare 符号级判定)：
 *  changed=强关联(符号代码段有变更,黄底) / weak=弱关联(仅同文件其他位置变更,灰底)
 *  / new=目标侧新增(绿底) / removed=目标侧移除(红虚线)。
 *  ⚠️ strong 缺失(旧后端未重启)视为强。 */
const diffKindById = computed<Map<string, DiffBucket>>(() => {
  const m = new Map<string, DiffBucket>()
  const c = props.compareData
  if (!c) return m
  for (const a of c.assets.changed) m.set(a.id, a.strong === false ? 'weak' : 'changed')
  for (const a of c.assets.new) m.set(a.id, 'new')
  for (const a of c.assets.removed) m.set(a.id, 'removed')
  return m
})
const diffBucketCounts = computed(() => {
  const counts: Record<DiffBucket, number> = { changed: 0, weak: 0, new: 0, removed: 0 }
  for (const k of diffKindById.value.values()) counts[k] += 1
  return counts
})
/** 仅看变化：图谱只渲染参与本次对比的资产(缓解大图下找变化节点)。 */
const diffOnly = ref(false)
/** 弱关联计数(仅同文件变更；不标色，仅提示)。 */
const weakCount = computed(() => props.compareData?.assets.changedWeak ?? 0)
const loading = ref(false)
/** 类型(资产类别)过滤后的节点集。 */
const kindNodes = computed(() => (graph.value?.nodes ?? []).filter((n) =>
  !kindFilter.value || n.kind === kindFilter.value))

/** 当前(类型过滤下)实际有数据的粒度层级(业务→逻辑→实现)，避免无数据选项。 */
const availableLevels = computed<SemanticAssetLevel[]>(() => {
  const present = new Set(kindNodes.value.map((n) => n.level).filter(Boolean))
  return (['business', 'logic', 'implementation'] as SemanticAssetLevel[]).filter((l) => present.has(l))
})

/** 粒度下拉选项：全部 + 有数据的层级。 */
const levelOptions = computed(() => {
  const labels: Record<string, string> = {
    business: t('assetMgmt.graph.business'),
    logic: t('assetMgmt.graph.logic'),
    implementation: t('assetMgmt.graph.implementation'),
  }
  return availableLevels.value.map((l) => ({ value: l, label: labels[l] ?? l }))
})

/** 类型下拉选项(资产类别)。 */
const kindOptions = computed(() =>
  (['entity', 'contract', 'state', 'rule', 'process', 'decision'] as SemanticAssetKind[])
    .map((k) => ({ value: k, label: t(`assetMgmt.kind.${k}`) })))

/** 生效粒度(粒度下拉选择；空=全部)。 */
const effectiveLevel = computed<SemanticAssetLevel | ''>(() => level.value)

/** 生效节点集：按类型 + 粒度过滤；「仅看变化」开启时只留对比命中资产。
 *  ⚠️ 焦点资产(单资产 tab)永不被过滤——新提取/未入对比缓存的资产曾被 diffOnly
 *  滤成空图，误报「暂无语义资产」。 */
const scopedNodes = computed(() => kindNodes.value.filter((n) =>
  (!effectiveLevel.value || n.level === effectiveLevel.value) &&
  (!diffOnly.value || !diffKindById.value.size || diffKindById.value.has(n.id)
   || (props.tab.kind === 'asset' && n.id === props.tab.assetId))))

const scopedEdges = computed(() => {
  const ids = new Set(scopedNodes.value.map((n) => n.id))
  return (graph.value?.edges ?? []).filter((e) =>
    ids.has(e.from) && ids.has(e.to) && !edgeTypeOff.value.has(e.type || ''))
})

/** 间接边开关(默认关：1 跳中转关系虚线补充，变更后重查)。 */
const includeIndirect = ref(false)
watch(includeIndirect, () => load())
/** 关闭显示的边类型集合(图例点击切换；空=全显示)。 */
const edgeTypeOff = ref<Set<string>>(new Set())
function toggleEdgeType(k: string) {
  const next = new Set(edgeTypeOff.value)
  if (next.has(k)) next.delete(k)
  else next.add(k)
  edgeTypeOff.value = next
}
/** 当前图谱内边类型 → 数量(图例)。 */
const edgeTypeCounts = computed(() => {
  const ids = new Set(scopedNodes.value.map((n) => n.id))
  const cnt = new Map<string, number>()
  for (const e of graph.value?.edges ?? []) {
    if (!ids.has(e.from) || !ids.has(e.to)) continue
    const k = e.type || ''
    cnt.set(k, (cnt.get(k) || 0) + 1)
  }
  return [...cnt.entries()].sort((a, b) => b[1] - a[1])
})
const EDGE_TYPE_TEXT = computed<Record<string, string>>(() => ({
  calls: t('assetMgmt.graph.edgeType.calls'), references: t('assetMgmt.graph.edgeType.references'),
  imports: t('assetMgmt.graph.edgeType.imports'), contains: t('assetMgmt.graph.edgeType.contains'),
  extends: t('assetMgmt.graph.edgeType.extends'), implements: t('assetMgmt.graph.edgeType.implements'),
  instantiates: t('assetMgmt.graph.edgeType.instantiates'),
  assigns: t('assetMgmt.graph.edgeType.assigns'), passes: t('assetMgmt.graph.edgeType.passes'),
  type_of: t('assetMgmt.graph.edgeType.type_of'), returns: t('assetMgmt.graph.edgeType.returns'),
  overrides: t('assetMgmt.graph.edgeType.overrides'), decorates: t('assetMgmt.graph.edgeType.decorates'),
  callback: t('assetMgmt.graph.edgeType.callback'),
}))
function edgeTypeLabel(k: string) {
  return EDGE_TYPE_TEXT.value[k] || k || t('assetMgmt.graph.edgeTypeFallback')
}
const EDGE_TYPE_COLOR: Record<string, string> = {
  calls: 'text-ctp-red', references: 'text-ctp-blue', imports: 'text-ctp-yellow',
  contains: 'text-ctp-green', extends: 'text-ctp-mauve', implements: 'text-ctp-mauve',
  instantiates: 'text-ctp-peach', assigns: 'text-ctp-teal', passes: 'text-ctp-sky',
  type_of: 'text-ctp-lavender', returns: 'text-ctp-flamingo', overrides: 'text-ctp-mauve',
  decorates: 'text-ctp-pink', callback: 'text-ctp-rosewater',
}
function edgeTypeColor(k: string) {
  return EDGE_TYPE_COLOR[k] || 'text-ctp-overlay1'
}

/** 图类型：手动选择优先，否则按数据区间自动推荐第一个支持的。 */
const viewOptions = computed<{ value: SemanticGraphViewId; label: string }[]>(() => {
  const supported = supportedViewsFor(effectiveLevel.value, scopedNodes.value)
  const labels: Record<SemanticGraphViewId, string> = {
    flow: t('assetMgmt.graph.viewFlow'),
    class: t('assetMgmt.graph.viewClass'),
    er: t('assetMgmt.graph.viewEr'),
    seq: t('assetMgmt.graph.viewSeq'),
    state: t('assetMgmt.graph.viewState'),
    activity: t('assetMgmt.graph.viewActivity'),
    mindmap: t('assetMgmt.graph.viewMindmap'),
  }
  return supported.map((v) => ({ value: v, label: labels[v] }))
})

/** 因数据不适合而被隐藏的视图及其原因(工具提示说明「为何不可选」)。 */
const hiddenViewHints = computed<string[]>(() => {
  const reasons = viewUnavailableReasons(effectiveLevel.value, scopedNodes.value)
  const labels: Record<SemanticGraphViewId, string> = {
    flow: t('assetMgmt.graph.viewFlow'),
    class: t('assetMgmt.graph.viewClass'),
    er: t('assetMgmt.graph.viewEr'),
    seq: t('assetMgmt.graph.viewSeq'),
    state: t('assetMgmt.graph.viewState'),
    activity: t('assetMgmt.graph.viewActivity'),
    mindmap: t('assetMgmt.graph.viewMindmap'),
  }
  return (Object.keys(reasons) as SemanticGraphViewId[]).map((v) => `${labels[v]}：${reasons[v]}`)
})

const effectiveView = computed<SemanticGraphViewId>(() => {
  if (view.value && viewOptions.value.some((o) => o.value === view.value)) return view.value
  // 未手动选择 → 按资产类别×粒度取推荐默认(如 entity+implementation → 类图)；不可用再退首个支持的
  const kind = D.detail.sel.value?.kind ?? (kindFilter.value || undefined)
  const rec = recommendedSemanticView(kind, effectiveLevel.value || undefined)
  if (viewOptions.value.some((o) => o.value === rec)) return rec
  return viewOptions.value[0]?.value ?? 'flow'
})

/** 下拉绑定：未手动选择时显示当前生效(推荐)默认，选择后为手动值。 */
async function load(reset = false) {
  // 规模闸门：范围资产 >500 且未圈定文件范围 → 不自动渲染，强制打开文件索引。
  if (overLimit.value && !fileScopeSel.value.length) {
    graph.value = null
    fileScopeOpen.value = true
    return
  }
  loading.value = true
  D.code.expandedTabs.value = []   // 图谱重查(刷新/切视图/聚焦切换) → 拓展沉淀 tab 重置
  // 访问历史 tab 不在此清空：图谱 tab 切换经 :key 重建组件自然重置；
  // 聚焦模式/切视图触发的 load() 属同上下文重查，历史应保留(常驻)。
  try {
    const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
    // 文件范围：仅锚定该文件的资产子图(文件级图谱入口)
    const file = props.tab.kind === 'file' ? props.tab.fileId : undefined
    // 多文件范围：超限 tab 经文件索引圈定后的选取
    const files = overLimit.value && fileScopeSel.value.length ? fileScopeSel.value : undefined
    // 逻辑视图：节点=成员实现资产集合(边=其间 relations+派生调用/依赖)
    const assets = props.tab.kind === 'logic' && props.tab.members?.length
      ? props.tab.members.join(',') : undefined
    // 邻域聚焦：聚焦模式开启且有选中 → 以选中资产为中心 D.detail.focusHops 跳子图；
    // 范围锁定时以锁定锚点为中心(切换选中不跟随)；否则单资产 tab 聚焦该资产(1 跳)、组件 tab 全量。
    let focus: string | undefined
    let hops = 1
    // 默认锁定(LS 偏好)且锚点未定 → 固化首个中心为锚点，此后切换选中不跟随
    if (D.detail.focusMode.value && D.detail.focusLock.value && !D.detail.lockAnchor.value && D.detail.selId.value) {
      D.detail.lockAnchor.value = D.detail.selId.value
    }
    if (D.detail.focusMode.value && (D.detail.focusLock.value ? D.detail.lockAnchor.value : D.detail.selId.value)) {
      focus = D.detail.focusLock.value ? D.detail.lockAnchor.value : D.detail.selId.value
      hops = D.detail.focusHops.value
    } else if (props.tab.kind === 'asset') {
      focus = props.tab.assetId
    }
    graph.value = await semanticAssetService.graph(undefined, scope, undefined, { focus, hops, includeIndirect: includeIndirect.value, file, files, assets, rev: graphRev.value })
    if (reset) {
      // 打开/切换 tab：类型重置为全部；粒度默认=组件级取该组件最高可用层级，其余取全部。
      kindFilter.value = ''
      view.value = ''
      level.value = props.tab.kind === 'comp' ? (availableLevels.value[0] ?? '') : ''
    } else if (D.detail.selId.value && !(graph.value?.nodes ?? []).some((n) => n.id === D.detail.selId.value)) {
      D.detail.selId.value = ''
      D.detail.selDetail.value = null
    }
    // 单资产视图：聚焦目标资产。
    if (props.tab.kind === 'asset' && props.tab.assetId && !D.detail.selId.value) {
      D.detail.selId.value = props.tab.assetId
    }
  } catch {
    graph.value = null
  } finally {
    loading.value = false
  }
}

watch(() => props.tab, () => {
  D.detail.selId.value = props.tab.kind === 'asset' ? (props.tab.assetId ?? '') : ''
  D.detail.selDetail.value = null
  load(true)
})

// 类型切换导致当前粒度无数据时，回退到全部(避免空图)。
watch(availableLevels, (vals) => {
  if (level.value && !vals.includes(level.value)) level.value = ''
})

// 邻域聚焦：开关/跳数变化 → 重查(聚焦态需有选中，否则回全量)。
watch(() => props.compareData, () => {
  if (!D.detail.selId.value || D.code.fullCode.value) return
  const anchors = D.detail.selAnchors.value
  if (anchors.length) void D.code.rebuildSegments(anchors)
})

// 选中变化后详情/源码异步到达 → 到位后闪烁。

  return {
    EDGE_TYPE_COLOR,
    EDGE_TYPE_TEXT,
    FILE_BUDGET,
    applyFileScope,
    availableLevels,
    diffBucketCounts,
    diffKindById,
    diffNodeCount,
    diffNodeIds,
    diffOnly,
    edgeTypeColor,
    edgeTypeCounts,
    edgeTypeLabel,
    edgeTypeOff,
    effectiveLevel,
    effectiveView,
    fileIndex,
    fileScopeKey,
    fileScopeOpen,
    fileScopeSel,
    graph,
    hiddenViewHints,
    includeIndirect,
    isDiffNode,
    kindFilter,
    kindNodes,
    kindOptions,
    level,
    levelOptions,
    load,
    loading,
    overLimit,
    scopeAssets,
    scopeTotal,
    scopedEdges,
    scopedNodes,
    toggleEdgeType,
    view,
    viewOptions,
    weakCount,
    graphRev,
    revSyncing,
    updateRevAssets,
  }
}
