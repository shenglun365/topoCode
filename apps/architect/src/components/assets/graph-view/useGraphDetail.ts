/**
 * 语义图谱 · detail 域（MS6-W2 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { semanticGraphViewDiagrams, ViewClickEntry, SemanticGraphViewId } from '@/utils/diagram-gen'
import type { SemanticAsset } from '@/types'
import { SemanticGraphResult, semanticAssetService } from '@/services/semantic-asset-service'

import type { WsDeps } from './graphTypes'

export function useGraphDetail(D: WsDeps) {
  const props = D.props

const selId = ref('')
const selDetail = ref<SemanticAsset | null>(null)
/** 行级定位请求(档2)：合成节点(决策分支)携带的代码行——detail/代码段就绪后滚动高亮。 */
const focusLine = ref(0)
/** 邻域聚焦：开启后图谱只渲染选中资产周围 focusHops 跳子图(缓解大图拥挤/过宽/过长)。 */
const focusMode = ref(false)
const focusHops = ref(2)
/** 范围锁定：锁定时切换选中节点不跟随重查(图谱视角保持)，解锁恢复漫游。
 *  默认锁定；全局共享偏好，LS 持久化(arch.graph.focusLock)。 */
const FOCUS_LOCK_KEY = 'arch.graph.focusLock'
const focusLock = ref((() => {
  try { return (localStorage.getItem(FOCUS_LOCK_KEY) ?? '1') !== '0' }
  catch { return true }
})())
watch(focusLock, (v) => {
  try { localStorage.setItem(FOCUS_LOCK_KEY, v ? '1' : '0') } catch { /* ignore */ }
})
const lockAnchor = ref('')   // 锁定瞬间的中心锚点(软刷新/重查仍以其为中心)

function toggleFocusLock() {
  if (!focusMode.value) return
  focusLock.value = !focusLock.value
  if (focusLock.value) {
    lockAnchor.value = selId.value
  } else {
    const drifted = selId.value && selId.value !== lockAnchor.value
    lockAnchor.value = ''
    // 解锁且选中已偏离锚点 → 立即对齐漫游态
    if (drifted) void D.data.load()
  }
}
const viewSel = computed<SemanticGraphViewId>({
  get: () => D.data.effectiveView.value,
  set: (v) => { D.data.view.value = v },
})

/** 选中节点(单资产视图的焦点 / 节点点击)。 */
const sel = computed(() => (D.data.graph.value?.nodes ?? []).find((n) => n.id === selId.value) ?? null)

const diagrams = computed<Partial<Record<'mermaid' | 'plantuml', string>>>(() => {
  if (!D.data.graph.value) return {}
  const r = semanticGraphViewDiagrams(D.data.effectiveView.value, D.data.scopedNodes.value, D.data.scopedEdges.value)
  viewClickMap.value = r.clickMap
  return r
})
/** 视图合成节点(步骤/分支/子状态)→宿主资产映射(含行级定位 line)；随图数据/视图重建。 */
const viewClickMap = ref<Map<string, ViewClickEntry>>(new Map())

watch([focusMode, focusHops], () => {
  void D.data.load()
})
// 聚焦开/关只管理本次锚点：锁定偏好(focusLock)是 LS 持久值，不随聚焦开关复位。
// 关闭 → 清锚点；开启且处于锁定偏好 → 以当前选中为新一轮锚点。
watch(focusMode, (on) => {
  if (!on) {
    lockAnchor.value = ''
  } else if (focusLock.value) {
    lockAnchor.value = selId.value
  }
})
// 聚焦态下选中变化 → 跟随重查(以新选中为中心)；范围锁定时不跟随(漫游暂停)。
watch(selId, (id, old) => {
  if (focusMode.value && !focusLock.value && id && id !== old) void D.data.load()
})

function clearSel() {
  selId.value = ''
  selDetail.value = null
}

/** 选中节点的代码锚点。 */
const selAnchors = computed<{ file: string; startLine: number; symbol: string }[]>(() => {
  if (!sel.value) return []
  const refs = selDetail.value?.astRefs ?? []
  if (refs.length) return refs
  return (D.data.graph.value?.anchors ?? [])
    .filter((a) => a.assetId === sel.value!.id)
    .map((a) => ({ file: a.file, startLine: a.line, symbol: a.symbol }))
})

// ---- 节点简介 + 关系描述(证据式，grounded；提取时/懒生成，stale 自动失效) ----
const nodeBriefText = ref('')
const nodeBriefLoading = ref(false)
const edgeNotesMap = ref<Record<string, string>>({})
const edgeNotesLoading = ref(false)
const inEdges = ref<{ fromId: string; fromName: string; type?: string; desc?: string }[]>([])
const inEdgesLoading = ref(false)

/** 重新生成当前选中资产的简介(force)。 */
async function regenerateNodeBrief() {
  const d = selDetail.value
  if (!d || nodeBriefLoading.value) return
  nodeBriefLoading.value = true
  try {
    const r = await semanticAssetService.nodeBrief(d.id, true)
    nodeBriefText.value = r.degraded ? (d.desc || '') : (r.brief || d.desc || '')
  } catch { /* 保留现状 */ } finally {
    nodeBriefLoading.value = false
  }
}

/** 图谱软刷新：保留当前节点集(拓展合并结果不丢、聚焦层级不动)，就地更新节点字段
 *  (增强的简介/描述生效)与边描述，并并回新增节点/边/锚点。区别于 D.data.load() 整图重查(会重置拓展累积)。 */
async function softRefreshGraph() {
  const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
  let fresh: SemanticGraphResult
  try {
    fresh = await semanticAssetService.graph(
      D.data.kindFilter.value || undefined, scope, D.data.effectiveLevel.value || undefined,
      focusMode.value && (focusLock.value ? lockAnchor.value : selId.value)
        ? { focus: focusLock.value ? lockAnchor.value : selId.value, hops: focusHops.value }
        : undefined)
  } catch {
    return
  }
  const g = D.data.graph.value
  if (!g) { await D.data.load(); return }
  const freshById = new Map(fresh.nodes.map((n) => [n.id, n]))
  // 就地更新已有节点字段(名称/描述/简介/详情/状态——增强结果生效)；拓展并回的节点保留
  const nodes = g.nodes.map((n) => {
    const f = freshById.get(n.id)
    return f ? { ...n, name: f.name, desc: f.desc, nodeBrief: f.nodeBrief, detail: f.detail, needsUpdate: f.needsUpdate, status: f.status, change: f.change } : n
  })
  const eKey = (e: { from: string; to: string; type?: string }) => `${e.from}|${e.to}|${e.type ?? ''}`
  const freshEdge = new Map(fresh.edges.map((e) => [eKey(e), e]))
  const edges = g.edges.map((e) => {
    const f = freshEdge.get(eKey(e))
    return f ? { ...e, desc: f.desc, semantic: f.semantic } : e
  })
  const eKeys = new Set(edges.map(eKey))
  const aKey = (a: { assetId: string; file: string; line: number }) => `${a.assetId}|${a.file}|${a.line}`
  const aKeys = new Set((g.anchors ?? []).map(aKey))
  D.data.graph.value = {
    ...g,
    nodes,
    edges: [...edges, ...fresh.edges.filter((e) => !eKeys.has(eKey(e)))],
    anchors: [...(g.anchors ?? []), ...(fresh.anchors ?? []).filter((a) => !aKeys.has(aKey(a)))],
  }
}

/** 存量资产描述批量增强(后台)：启动后轮询进度，完成后软刷新图谱数据。 */
const enhanceRunning = ref(false)
const enhanceProgress = ref({ done: 0, total: 0 })
let enhancePoll: ReturnType<typeof setInterval> | null = null
async function startEnhanceDesc() {
  if (enhanceRunning.value) return
  try {
    const r = await semanticAssetService.enhanceDesc(false)
    enhanceRunning.value = !!r.running
    enhanceProgress.value = { done: r.done, total: r.total }
    if (enhancePoll) clearInterval(enhancePoll)
    if (enhanceRunning.value) {
      enhancePoll = setInterval(async () => {
        try {
          const s = await semanticAssetService.enhanceDescStatus()
          enhanceProgress.value = { done: s.done, total: s.total }
          if (!s.running) {
            clearInterval(enhancePoll!)
            enhancePoll = null
            enhanceRunning.value = false
            await softRefreshGraph()   // 完成 → 软刷新(简介/边描述生效；拓展合并与拓展 tab 保留)
          }
        } catch { /* 忽略单次轮询失败 */ }
      }, 2000)
    }
  } catch (err: any) {
    console.warn('[semantic] enhance desc 启动失败:', err?.message)
  }
}

/** 选中资产的可展示关系(已解析到真实资产；成员归属不进列表)。 */
const selRelations = computed(() => {
  const d = selDetail.value
  if (!d) return []
  const nodes = D.data.graph.value?.nodes ?? []
  const nameById = new Map(nodes.map((n) => [n.id, n.name]))
  const idByName = new Map(nodes.map((n) => [n.name, n.id]))
  const out: { key: string; targetId: string; targetName: string; type: string; desc: string }[] = []
  const seen = new Set<string>()
  for (const r of (d.detail?.relations ?? [])) {
    const t = String((r as { target?: string }).target ?? '')
    if (!t) continue
    const tid = nodes.find((x) => x.id === t)?.id ?? idByName.get(t) ?? ''
    if (!tid || tid === d.id) continue
    const key = `${tid}|${r.type ?? ''}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push({
      key,
      targetId: tid,
      targetName: (nameById.get(tid) as string | undefined) ?? t,
      type: (r as { type?: string }).type ?? '',
      desc: edgeNotesMap.value[tid] ?? (r as { semantic?: string }).semantic ?? (r as { type?: string }).type ?? '',
    })
  }
  return out
})

/** 点击关系行 → 跳转到对方资产(图谱选中 + 卡联动)。 */
function jumpToRelation(r: { targetId: string }) {
  if (!r.targetId || r.targetId === selId.value) return
  selId.value = r.targetId
}

// per-asset 取消器：切换资产时中止未决的 LLM 解析请求(nodeBrief/edgeNotes)
// ——连点下不再白烧配额/加剧闸门排队(B2)。
let detailAbort: AbortController | null = null

// 选中详情到达 → 节点简介(缺失则懒生成) + 关系描述(有关系才生成)
watch(selDetail, async (d) => {
  detailAbort?.abort()
  detailAbort = new AbortController()
  const sig = detailAbort.signal
  nodeBriefText.value = ''
  edgeNotesMap.value = {}
  D.code.relTabSegs.value = {}   // 切换资产 → 关系 tab 预览缓存失效
  if (!d) return
  // 访问历史 tab：选中资产的主锚点文件沉淀为 tab(LRU 上限 6)；active tab 跟随当前资产
  const pf = selAnchors.value[0]?.file ?? ''
  if (pf) {
    D.code.activeFileTab.value = pf
    const rest = D.code.visitedTabs.value.filter((x) => x.file !== pf)
    D.code.visitedTabs.value = [...rest, { file: pf, label: pf.split('/').pop() || pf, assetId: d.id, assetName: d.name }].slice(-6)
  }
  if (d.nodeBrief) {
    nodeBriefText.value = d.nodeBrief
  } else {
    nodeBriefLoading.value = true
    try {
      const r = await semanticAssetService.nodeBrief(d.id, false, sig).catch(() => null)
      if (!r) return   // 已切换资产(abort) → 丢弃
      nodeBriefText.value = r.degraded ? '' : (r.brief || '')
    } catch { /* 降级显示原 desc */ } finally {
      nodeBriefLoading.value = false
    }
  }
  if ((d.detail?.relations ?? []).length) {
    edgeNotesLoading.value = true
    try {
      const r = await semanticAssetService.edgeNotes(d.id, false, sig).catch(() => null)
      if (!r) return   // 已切换资产(abort) → 丢弃
      edgeNotesMap.value = r.notes || {}
    } catch { /* 关系描述降级显示 semantic/type */ } finally {
      edgeNotesLoading.value = false
    }
  }
  // 入边(被谁引用)
  inEdgesLoading.value = true
  try {
    const r = await semanticAssetService.inEdges(d.id)
    inEdges.value = r.inEdges || []
  } catch { inEdges.value = [] } finally {
    inEdgesLoading.value = false
  }
})

// ---- 代码段(多锚点多段展示) + 节点点击联动 + AI 逐行解读 ----

watch(selId, async (id) => {
  selDetail.value = null
  if (!id) return
  try {
    const d = (await semanticAssetService.detail(id)) ?? null
    if (D.code.fullCode.value && d) {
      const files = new Set((d.astRefs ?? []).map((r) => r.file))
      if (!files.has(D.code.fullCode.value.file)) {
        // 跨文件切资产：全文视图跟随切到新资产主锚点文件(拉取失败 → 回退分段重建)
        const target = (d.astRefs ?? [])[0]?.file ?? ''
        if (target) {
          D.code.activeFileTab.value = target
          void (async () => {
            const ok = await D.code.loadFullCodeFor(target)
            if (!ok) void D.code.rebuildSegments(selAnchors.value)
          })()
        } else {
          D.code.fullCode.value = null
        }
      }
    }
    selDetail.value = d
  } catch {
    selDetail.value = null
  }
})

// ---- 节点点击 → 选中资产 + 锚点代码闪烁突出 ----
watch(selId, (id, old) => {
  if (!id || id === old || !D.render.cardMin.value) return
  D.code.iconPulse.value = false
  void nextTick(() => {
    D.code.iconPulse.value = true
    if (D.render.iconPulseTimer) clearTimeout(D.render.iconPulseTimer)
    D.render.iconPulseTimer = setTimeout(() => { D.code.iconPulse.value = false }, 3000)
  })
})

// 锚点变化 → 重建代码段并逐段拉取源码窗口；注解失效(后端落库缓存，重击按钮秒回)。
// 完整代码视图打开时跳过重建(同文件资产切换不刷新资产卡)；关闭后下次锚点变化正常重建。

  return {
    FOCUS_LOCK_KEY,
    clearSel,
    diagrams,
    edgeNotesLoading,
    edgeNotesMap,
    enhancePoll,
    enhanceProgress,
    enhanceRunning,
    focusHops,
    focusLock,
    focusMode,
    inEdges,
    inEdgesLoading,
    jumpToRelation,
    lockAnchor,
    nodeBriefLoading,
    nodeBriefText,
    regenerateNodeBrief,
    sel,
    selAnchors,
    selDetail,
    selId,
    selRelations,
    softRefreshGraph,
    startEnhanceDesc,
    toggleFocusLock,
    viewSel,
    viewClickMap,
    focusLine,
  }
}
