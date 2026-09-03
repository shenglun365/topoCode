<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, XMarkIcon, ArrowsPointingOutIcon, MinusIcon, InformationCircleIcon, SparklesIcon, DocumentTextIcon, ViewfinderCircleIcon, ClipboardIcon, ChevronDownIcon, CheckIcon, PlusCircleIcon, TableCellsIcon, AdjustmentsHorizontalIcon, ListBulletIcon } from '@heroicons/vue/24/outline'
import GraphMatrixWindow from './GraphMatrixWindow.vue'
import AssetIndexWindow from './AssetIndexWindow.vue'
import TopoDiagram from '@topo/graph-kernel/vue/TopoDiagram.vue'
import { makeButton } from '@topo/graph-kernel/plugins/ui.ts'
import type { NodeClickEvent } from '@topo/graph-kernel/plugins/types.ts'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'
import { semanticGraphViewDiagrams, semanticViewClickIds, recommendedSemanticView, semanticNodeLabelText, supportedViewsFor, viewUnavailableReasons } from '@/utils/diagram-gen'
import { useArchSettingsStore } from '@/stores/settings-store'
import type { SemanticGraphViewId } from '@/utils/diagram-gen'
import type { SemanticAsset, SemanticAssetLevel, SemanticAssetKind } from '@/types'
import type { SemanticGraphResult, SourceSnippet, CodegraphStatus } from '@/services/semantic-asset-service'
import { semanticAssetService } from '@/services/semantic-asset-service'

const { t } = useI18n()

/** 图谱资源 tab 定义(由外部资产列表/组件列表打开)。 */
export interface GraphTabDef {
  id: string
  kind: 'all' | 'comp' | 'asset'
  title: string
  compId?: string
  assetId?: string
}

const props = defineProps<{ tab: GraphTabDef; diffFiles?: Set<string> }>()
const emit = defineEmits<{ close: [id: string] }>()

const level = ref<SemanticAssetLevel | ''>('')
/** 类型(资产类别)过滤：空=全部。 */
const kindFilter = ref<SemanticAssetKind | ''>('')
/** 图类型视图(空=按数据区间自动推荐)。 */
const view = ref<SemanticGraphViewId | ''>('')
const graph = ref<SemanticGraphResult | null>(null)

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
const loading = ref(false)
const selId = ref('')
const selDetail = ref<SemanticAsset | null>(null)
/** 邻域聚焦：开启后图谱只渲染选中资产周围 focusHops 跳子图(缓解大图拥挤/过宽/过长)。 */
const focusMode = ref(false)
const focusHops = ref(2)
/** 关系矩阵浮窗(独立全局浮窗，数据跟随当前图谱口径)。 */
const matrixOpen = ref(false)
/** 边图例浮层开关。 */
const edgeLegendOpen = ref(false)
/** 边图例浮层：Teleport 到 body + fixed 定位，避免被工具栏 overflow 裁剪或撑开。 */
const legendBtnRef = ref<HTMLElement | null>(null)
const legendPos = ref({ top: 0, left: 0 })
const LEGEND_W = 176 // w-44
function toggleEdgeLegend() {
  if (!edgeLegendOpen.value && legendBtnRef.value) {
    const r = legendBtnRef.value.getBoundingClientRect()
    let left = r.right - LEGEND_W
    if (left < 8) left = 8
    if (left + LEGEND_W > window.innerWidth - 8) left = Math.max(8, window.innerWidth - 8 - LEGEND_W)
    legendPos.value = { top: r.bottom + 4, left }
  }
  edgeLegendOpen.value = !edgeLegendOpen.value
}
function onLegendDocClick(e: MouseEvent) {
  const t = e.target
  if (!(t instanceof Node)) return
  if (legendBtnRef.value?.contains(t)) return
  if (document.querySelector('[data-edge-legend]')?.contains(t)) return
  edgeLegendOpen.value = false
}
watch(edgeLegendOpen, (open) => {
  if (open) setTimeout(() => document.addEventListener('click', onLegendDocClick, true), 0)
  else document.removeEventListener('click', onLegendDocClick, true)
})
onBeforeUnmount(() => document.removeEventListener('click', onLegendDocClick, true))
/** 工具栏开关矩阵浮窗：打开时强制还原展开态（最小化持久化会让重开只剩停靠小图标，形同"无弹窗"）。 */
function toggleMatrix() {
  matrixOpen.value = !matrixOpen.value
  if (matrixOpen.value) {
    try { localStorage.setItem('arch.matrixWin.minimized', '0') } catch { /* ignore */ }
  }
}
/** 符号源(CodeGraph)开关弹层：状态 + 三档切换(KV 持久化)。 */
const cgOpen = ref(false)
const cgStatus = ref<CodegraphStatus | null>(null)
const cgSaving = ref(false)
function onCgDocClick(e: MouseEvent) {
  const t = e.target
  if (!(t instanceof Node)) return
  if ((t as HTMLElement).closest?.('[data-cg-pop]')) return
  cgOpen.value = false
}
watch(cgOpen, (open) => {
  if (open) setTimeout(() => document.addEventListener('click', onCgDocClick, true), 0)
  else document.removeEventListener('click', onCgDocClick, true)
})
async function loadCgStatus() {
  cgStatus.value = await semanticAssetService.codegraphStatus() ?? null
}
async function toggleCg() {
  cgOpen.value = !cgOpen.value
  if (cgOpen.value) void loadCgStatus()
}
async function setCgMode(m: 'on' | 'off' | 'auto') {
  cgSaving.value = true
  try {
    if (await semanticAssetService.setCodegraphMode(m)) {
      cgStatus.value = { ...(cgStatus.value ?? { env: '', cli: false, cliPath: '', source: 'default' }), mode: m, source: 'kv' }
    }
  } finally {
    cgSaving.value = false
  }
}

/** 资产节点索引浮窗(左停靠)：开关逻辑与矩阵同款。 */
const indexOpen = ref(false)
function toggleIndex() {
  indexOpen.value = !indexOpen.value
  if (indexOpen.value) {
    try { localStorage.setItem('arch.indexWin.minimized', '0') } catch { /* ignore */ }
  }
}
/** 矩阵(含下钻行首/列头)选资产：与图谱节点点击同轨 — 切选后锚点滚动闪烁；同资产重复点回主锚点并闪烁。 */
function onMatrixSelect(id: string) {
  if (!id) return
  if (id === selId.value) {
    const home = selAnchors.value[0]?.file
    if (home && activeFileTab.value !== home) activeFileTab.value = home
    void nextTick(() => flashAnchor(0))
    return
  }
  flashOnNext = true
  flashSeg = 0
  selId.value = id
  return
}
/** 当前渲染语言(默认 mermaid)。 */
const cardLang = ref<'mermaid' | 'plantuml'>('mermaid')
const cardSrcOpen = ref(false)
const cardFullscreen = ref(false)
const diagramLangs = computed(() => [{ id: 'mermaid' as const, label: 'mermaid' }, { id: 'plantuml' as const, label: 'plantuml' }])
function setCardLang(l: 'mermaid' | 'plantuml') {
  cardLang.value = l
}
function toggleCardSource() {
  cardSrcOpen.value = !cardSrcOpen.value
}
function openCardFullscreen() {
  cardFullscreen.value = true
}
function closeCardFullscreen() {
  cardFullscreen.value = false
}
/** 重播：默认(加载/重渲染)直接呈现最终完成图；点图内工具栏的重播按钮才按步骤播放。 */
const diagRef = ref<InstanceType<typeof TopoDiagram> | null>(null)
const replayTick = ref(0)
const animating = ref(false)
function replayGraph() {
  replayTick.value += 1
  animating.value = true
}
/** 把重播按钮注入图内浮动工具栏(.td-toolbar，与缩放/导出按钮同排，置首)。 */
function injectReplayBtn(tries = 0) {
  const host = diagRef.value?.containerRef
  if (!host) return
  if (host.querySelector('[data-td-replay]')) return
  const bar = host.querySelector('.td-toolbar')
  if (!bar) {
    if (tries < 10) setTimeout(() => injectReplayBtn(tries + 1), 100)
    return
  }
  const btn = makeButton('↻', t('assetMgmt.graph.replay'), replayGraph)
  btn.dataset.tdReplay = '1'
  bar.prepend(btn)
}
/** 播放到最后一步后关掉动画态：之后主题/语言/全屏等重渲染不再重播。 */
function onDiagramReady() {
  injectReplayBtn()
  void nextTick(() => { applySelectedNodeStyle(); applyNodeTooltips() })
  if (!animating.value) return
  const tryWatch = (tries = 0) => {
    const ctrl = diagRef.value?.getAnimation() ?? null
    if (!ctrl || ctrl.total <= 0) {
      // 不支持动画的类型(无 plan)：稍候放弃，图本身已是完整态。
      if (tries < 20) setTimeout(() => tryWatch(tries + 1), 100)
      else animating.value = false
      return
    }
    const stopWatch = ctrl.subscribe((st) => {
      if (!st.playing && st.index >= ctrl.total - 1) {
        stopWatch()
        animating.value = false
      }
    })
  }
  tryWatch()
}
/** 联动选中 → 节点居中：反查 clickIds 找 svg 节点元素，bbox 中心交 zoom-pan centerOn。 */
function centerSelectedNode() {
  void nextTick(() => {
    const svg = diagRef.value?.getSvg()
    const cmap = clickIds.value
    if (!svg || !selId.value || !cmap.size) return
    const rev = new Map<string, string>()
    cmap.forEach((aid, key) => { if (!rev.has(aid)) rev.set(aid, key) })
    const key = rev.get(selId.value)
    if (!key) return
    let el: SVGGElement | null = null
    for (const g of Array.from(svg.querySelectorAll<SVGGElement>('g.node'))) {
      const mid = g.id.match(/flowchart-(.+?)-\d+$/)?.[1] ?? g.id
      const txt = (g.textContent ?? '').trim()
      if (mid === key || txt === key) { el = g; break }
    }
    if (!el) return
    try {
      // getBBox 是元素局部坐标系(祖先 transform 会偏移)；用屏幕 rect + getScreenCTM 逆映射回根 viewBox 空间
      const r = el.getBoundingClientRect()
      const sctm = svg.getScreenCTM()
      if (!sctm || !r.width) return
      const c = new DOMPoint(r.left + r.width / 2, r.top + r.height / 2).matrixTransform(sctm.inverse())
      diagRef.value?.centerOn(c.x, c.y)
    } catch { /* 未渲染时可能抛错，忽略 */ }
  })
}
watch(selId, () => centerSelectedNode())

/** 主题跟随 data-theme(catppuccin 变量随主题切换)。 */
const themeMode = computed<'dark' | 'light'>(() =>
  (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'light') ? 'light' : 'dark')
const themeVars = computed(() => themeVariablesFor(themeMode.value))
/** 信息卡拖动位置。 */
const cardPos = ref<{ x: number; y: number } | null>(null)
const cardEl = ref<HTMLElement | null>(null)
let cardDragging = false
let cardStartX = 0
let cardStartY = 0
let cardStartPos = { x: 0, y: 0 }

/** 资产类别 → 强调色(锚点高亮/最小化图标)。 */
const KIND_TEXT: Record<string, string> = {
  entity: 'text-ctp-mauve', contract: 'text-ctp-yellow', state: 'text-ctp-sky',
  rule: 'text-ctp-peach', process: 'text-ctp-blue', decision: 'text-ctp-green',
}
const KIND_CHIP: Record<string, string> = {
  entity: 'bg-ctp-mauve/15 text-ctp-mauve border-ctp-mauve/40',
  contract: 'bg-ctp-yellow/15 text-ctp-yellow border-ctp-yellow/40',
  state: 'bg-ctp-sky/15 text-ctp-sky border-ctp-sky/40',
  rule: 'bg-ctp-peach/15 text-ctp-peach border-ctp-peach/40',
  process: 'bg-ctp-blue/15 text-ctp-blue border-ctp-blue/40',
  decision: 'bg-ctp-green/15 text-ctp-green border-ctp-green/40',
}
/** 锚点行底色(比纯文字色更醒目)。 */
const KIND_BG: Record<string, string> = {
  entity: 'bg-ctp-mauve/15', contract: 'bg-ctp-yellow/15', state: 'bg-ctp-sky/15',
  rule: 'bg-ctp-peach/15', process: 'bg-ctp-blue/15', decision: 'bg-ctp-green/15',
}
const kindTextClass = computed(() => KIND_TEXT[sel.value?.kind ?? ''] ?? 'text-ctp-yellow')
const kindBgClass = computed(() => KIND_BG[sel.value?.kind ?? ''] ?? 'bg-ctp-yellow/15')
const kindChipClass = computed(() => KIND_CHIP[sel.value?.kind ?? ''] ?? 'bg-ctp-surface0 text-ctp-subtext0 border-ctp-surface1')

// 代码字号与顶部工具栏联动：比工具栏设定小一号(字号档位向下取一档)，最小 11px。
const settings = useArchSettingsStore()
const FONT_STEPS = [13, 15, 18, 22, 26, 32]
const codeFontSize = computed(() => {
  const fs = Number(settings.fontSize) || 16
  const below = FONT_STEPS.filter((s) => s < fs)
  return Math.max(11, below.length ? below[below.length - 1] : 11)
})

/** 信息卡尺寸(上下左右四边独立拉伸；最终尺寸持久化 LS，再次拉伸覆盖)。 */
const CARD_MIN_KEY = 'arch.graphCard.minimized'
const CARD_SIZE_KEY = 'arch.graphCard.size'
const cardMin = ref((() => {
  try { return localStorage.getItem(CARD_MIN_KEY) === '1' } catch { return false }
})())
function setCardMin(v: boolean) {
  cardMin.value = v
  try { localStorage.setItem(CARD_MIN_KEY, v ? '1' : '0') } catch { /* ignore */ }
}
function loadCardSize(): { w: number; h: number | null } {
  try {
    const raw = JSON.parse(localStorage.getItem(CARD_SIZE_KEY) || '')
    if (raw && Number(raw.w) >= 360 && Number(raw.h) >= 240) return { w: Number(raw.w), h: Number(raw.h) }
  } catch { /* ignore */ }
  return { w: 560, h: 520 }
}
function saveCardSize() {
  try { localStorage.setItem(CARD_SIZE_KEY, JSON.stringify(cardSize.value)) } catch { /* ignore */ }
}
const cardSize = ref<{ w: number; h: number | null }>(loadCardSize())
const cardSizeInit = { ...cardSize.value }
let cardResizing = false
type CardResizeEdge = 'n' | 's' | 'e' | 'w'
let resizeEdge: CardResizeEdge = 's'
let resizeStart = { x: 0, y: 0, w: cardSizeInit.w, h: cardSizeInit.h, px: 0, py: 0 }

function beginCardDrag(e: MouseEvent) {
  if (e.button !== 0) return
  const el = cardEl.value
  if (!el) return
  const target = e.target as HTMLElement
  if (target.closest('button, a, input, select')) return
  cardDragging = true
  if (!cardPos.value) {
    // 初始居中(transform 定位) → 首次拖动转为显式坐标
    const r = el.getBoundingClientRect()
    cardStartPos = { x: r.left, y: r.top }
    cardPos.value = { ...cardStartPos }
  } else {
    cardStartPos = { x: el.offsetLeft, y: el.offsetTop }
  }
  cardStartX = e.clientX
  cardStartY = e.clientY
  // 监听挂 window：鼠标快速划出卡片/把手也不丢事件
  window.addEventListener('mousemove', cardDrag)
  window.addEventListener('mouseup', cardEndDrag, { once: true })
  e.preventDefault()
}
function cardStartResize(e: MouseEvent, edge: CardResizeEdge) {
  if (e.button !== 0) return
  e.preventDefault()
  e.stopPropagation()
  const el = cardEl.value
  if (!el) return
  // 初始居中(transform 定位) → 首次拉伸转为显式坐标(n/w 边拉伸需同步调整位置)
  let px = el.offsetLeft
  let py = el.offsetTop
  if (!cardPos.value) {
    const r = el.getBoundingClientRect()
    px = r.left
    py = r.top
    cardPos.value = { x: px, y: py }
  }
  resizeEdge = edge
  cardResizing = true
  resizeStart = {
    x: e.clientX, y: e.clientY,
    w: cardSize.value.w,
    h: cardSize.value.h ?? el.offsetHeight,
    px, py,
  }
  window.addEventListener('mousemove', cardDrag)
  window.addEventListener('mouseup', cardEndDrag, { once: true })
}
function cardDrag(e: MouseEvent) {
  if (cardResizing) {
    const maxW = Math.min(1100, window.innerWidth - 16)
    const maxH = Math.floor(window.innerHeight * 0.94)
    const dx = e.clientX - resizeStart.x
    const dy = e.clientY - resizeStart.y
    let w = resizeStart.w
    let h = resizeStart.h
    let px = resizeStart.px
    let py = resizeStart.py
    if (resizeEdge === 'e') {
      w = Math.min(maxW, Math.max(360, w + dx))
    } else if (resizeEdge === 'w') {
      // 左缘拉伸：宽度反向变化，左缘跟随(右缘固定)
      w = Math.min(maxW, Math.max(360, w - dx))
      px += resizeStart.w - w
    }
    if (resizeEdge === 's') {
      h = Math.min(maxH, Math.max(240, h + dy))
    } else if (resizeEdge === 'n') {
      // 上缘拉伸：高度反向变化，上缘跟随(下缘固定)
      h = Math.min(maxH, Math.max(240, h - dy))
      py += resizeStart.h - h
    }
    cardSize.value = { w, h }
    cardPos.value = { x: px, y: py }
    return
  }
  if (!cardDragging) return
  const el = cardEl.value
  if (!el) return
  // fixed 浮窗：视口内软钳制(至少留 80px 可抓握)
  cardPos.value = {
    x: Math.min(window.innerWidth - 80, Math.max(-(cardSize.value.w - 80), cardStartPos.x + (e.clientX - cardStartX))),
    y: Math.min(window.innerHeight - 48, Math.max(0, cardStartPos.y + (e.clientY - cardStartY))),
  }
}
function cardEndDrag() {
  cardDragging = false
  if (cardResizing) saveCardSize()
  cardResizing = false
  window.removeEventListener('mousemove', cardDrag)
}
function cardResetPos() { cardPos.value = null }

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

/** 生效节点集：按类型 + 粒度过滤。 */
const scopedNodes = computed(() => kindNodes.value.filter((n) =>
  !effectiveLevel.value || n.level === effectiveLevel.value))

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
const EDGE_TYPE_TEXT: Record<string, string> = {
  calls: '调用', references: '引用', imports: '导入', contains: '包含',
  extends: '继承', implements: '实现', instantiates: '实例化',
  assigns: '赋值', passes: '传参', type_of: '类型', returns: '返回',
  overrides: '重写', decorates: '装饰', callback: '回调',
}
function edgeTypeLabel(k: string) {
  return EDGE_TYPE_TEXT[k] || k || '关系'
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
  const kind = sel.value?.kind ?? (kindFilter.value || undefined)
  const rec = recommendedSemanticView(kind, effectiveLevel.value || undefined)
  if (viewOptions.value.some((o) => o.value === rec)) return rec
  return viewOptions.value[0]?.value ?? 'flow'
})

/** 下拉绑定：未手动选择时显示当前生效(推荐)默认，选择后为手动值。 */
const viewSel = computed<SemanticGraphViewId>({
  get: () => effectiveView.value,
  set: (v) => { view.value = v },
})

/** 选中节点(单资产视图的焦点 / 节点点击)。 */
const sel = computed(() => (graph.value?.nodes ?? []).find((n) => n.id === selId.value) ?? null)

const diagrams = computed<Partial<Record<'mermaid' | 'plantuml', string>>>(() => {
  if (!graph.value) return {}
  return semanticGraphViewDiagrams(effectiveView.value, scopedNodes.value, scopedEdges.value)
})

async function load(reset = false) {
  loading.value = true
  expandedTabs.value = []   // 图谱重查(刷新/切视图/聚焦切换) → 拓展沉淀 tab 重置
  // 访问历史 tab 不在此清空：图谱 tab 切换经 :key 重建组件自然重置；
  // 聚焦模式/切视图触发的 load() 属同上下文重查，历史应保留(常驻)。
  try {
    const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
    // 邻域聚焦：聚焦模式开启且有选中 → 以选中资产为中心 focusHops 跳子图；
    // 否则单资产 tab 聚焦该资产(1 跳)、组件 tab 全量。
    let focus: string | undefined
    let hops = 1
    if (focusMode.value && selId.value) {
      focus = selId.value
      hops = focusHops.value
    } else if (props.tab.kind === 'asset') {
      focus = props.tab.assetId
    }
    graph.value = await semanticAssetService.graph(undefined, scope, undefined, { focus, hops, includeIndirect: includeIndirect.value })
    if (reset) {
      // 打开/切换 tab：类型重置为全部；粒度默认=组件级取该组件最高可用层级，其余取全部。
      kindFilter.value = ''
      view.value = ''
      level.value = props.tab.kind === 'comp' ? (availableLevels.value[0] ?? '') : ''
    } else if (selId.value && !(graph.value?.nodes ?? []).some((n) => n.id === selId.value)) {
      selId.value = ''
      selDetail.value = null
    }
    // 单资产视图：聚焦目标资产。
    if (props.tab.kind === 'asset' && props.tab.assetId && !selId.value) {
      selId.value = props.tab.assetId
    }
  } catch {
    graph.value = null
  } finally {
    loading.value = false
  }
}

watch(() => props.tab, () => {
  selId.value = props.tab.kind === 'asset' ? (props.tab.assetId ?? '') : ''
  selDetail.value = null
  load(true)
})

// 类型切换导致当前粒度无数据时，回退到全部(避免空图)。
watch(availableLevels, (vals) => {
  if (level.value && !vals.includes(level.value)) level.value = ''
})

// 邻域聚焦：开关/跳数变化 → 重查(聚焦态需有选中，否则回全量)。
watch([focusMode, focusHops], () => {
  void load()
})
// 聚焦态下选中变化 → 跟随重查(以新选中为中心)。
watch(selId, (id, old) => {
  if (focusMode.value && id && id !== old) void load()
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
  return (graph.value?.anchors ?? [])
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
 *  (增强的简介/描述生效)与边描述，并并回新增节点/边/锚点。区别于 load() 整图重查(会重置拓展累积)。 */
async function softRefreshGraph() {
  const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
  let fresh: SemanticGraphResult
  try {
    fresh = await semanticAssetService.graph(
      kindFilter.value || undefined, scope, effectiveLevel.value || undefined,
      focusMode.value && selId.value ? { focus: selId.value, hops: focusHops.value } : undefined)
  } catch {
    return
  }
  const g = graph.value
  if (!g) { await load(); return }
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
  graph.value = {
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
  const nodes = graph.value?.nodes ?? []
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
      targetName: nameById.get(tid) ?? t,
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

// 选中详情到达 → 节点简介(缺失则懒生成) + 关系描述(有关系才生成)
watch(selDetail, async (d) => {
  nodeBriefText.value = ''
  edgeNotesMap.value = {}
  relTabSegs.value = {}   // 切换资产 → 关系 tab 预览缓存失效
  if (!d) return
  // 访问历史 tab：选中资产的主锚点文件沉淀为 tab(LRU 上限 6)；active tab 跟随当前资产
  const pf = selAnchors.value[0]?.file ?? ''
  if (pf) {
    activeFileTab.value = pf
    const rest = visitedTabs.value.filter((x) => x.file !== pf)
    visitedTabs.value = [...rest, { file: pf, label: pf.split('/').pop() || pf, assetId: d.id, assetName: d.name }].slice(-6)
  }
  if (d.nodeBrief) {
    nodeBriefText.value = d.nodeBrief
  } else {
    nodeBriefLoading.value = true
    try {
      const r = await semanticAssetService.nodeBrief(d.id)
      nodeBriefText.value = r.degraded ? '' : (r.brief || '')
    } catch { /* 降级显示原 desc */ } finally {
      nodeBriefLoading.value = false
    }
  }
  if ((d.detail?.relations ?? []).length) {
    edgeNotesLoading.value = true
    try {
      const r = await semanticAssetService.edgeNotes(d.id)
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

/** 单个代码段：一个锚点对应一个源码窗口(symbol 已知时后端展开整个符号体)。 */
interface CodeSegment {
  file: string
  symbol?: string
  startLine: number
  snippet: SourceSnippet | null
  loading: boolean
}
const MAX_SEGMENTS = 4
const segments = ref<CodeSegment[]>([])
const segEls: (HTMLElement | null)[] = []
let segSeq = 0

// ---- B2 多段代码手风琴(>1 段折叠，默认仅首段展开) ----
const collapsedSegs = ref<Set<number>>(new Set())
function toggleSeg(i: number) {
  const s = new Set(collapsedSegs.value)
  if (s.has(i)) s.delete(i); else s.add(i)
  collapsedSegs.value = s
}
// 重置折叠态：除首段外全部折叠(单段不折叠)。
function resetSegCollapse(n: number) {
  collapsedSegs.value = new Set(Array.from({ length: n }, (_, i) => i).filter((i) => i > 0))
}

// ---- 多文件 tab：访问历史(按文件沉淀，点击回跳资产) + 关系资产文件(预览) ----
const activeFileTab = ref('')
/** 当前资产锚点涉及的文件(去重；锚点上限 MAX_SEGMENTS 内)。 */
const anchorFiles = computed<{ file: string; label: string }[]>(() => {
  const files: string[] = []
  for (const a of selAnchors.value.slice(0, MAX_SEGMENTS)) {
    if (!files.includes(a.file)) files.push(a.file)
  }
  return files.map((f) => ({ file: f, label: f.split('/').pop() || f }))
})
/** 访问过的文件(LRU 上限 6)：每项记住该文件最近看过的资产，点击回跳(全联动)。 */
const visitedTabs = ref<{ file: string; label: string; assetId: string; assetName: string }[]>([])
/** 当前 tab 文件可见的段(携带原索引：segEls/lineNotesMaps 均按原始 si 寻址)。 */
const activeTabSegs = computed(() =>
  segments.value
    .map((seg, si) => ({ seg, si }))
    .filter(({ seg }) => anchorFiles.value.length <= 1 || seg.file === activeFileTab.value))
/** 切换文件 tab：关系 tab 预览相关资产代码(全文模式下先退出全文)；自身文件 tab 聚焦首个代码段；
 *  全文模式切自身文件 tab → 连带切换全文文件。 */
function switchFileTab(file: string) {
  if (activeFileTab.value === file) return
  activeFileTab.value = file
  const rel = relTabs.value.find((t) => t.file === file)
    ?? expandedTabs.value.find((t) => t.file === file)
  if (rel) {
    if (fullCode.value) { fullCode.value = null; fullCodeNotes.value = {} }
    void ensureRelTab(rel).then(() => focusRelTab(rel.file))
    return
  }
  if (fullCode.value && fullCode.value.file !== file) {
    void loadFullCodeFor(file)
    return
  }
  const i = segments.value.findIndex((s) => s.file === file)
  if (i >= 0) jumpToSegment(i)
}

// ---- 关系延伸 tab：直接关系资产所在的其它文件也纳入 tab(预览相关代码，可跳转选中) ----
interface RelTab { file: string; label: string; line: number; symbol: string; targetId: string; targetName: string; relText: string }
/** tab 列表 = 自身锚点文件(self) + 关系资产文件(rel，去重、上限 3)。 */
const relTabs = computed<RelTab[]>(() => {
  const seenFile = new Set<string>(anchorFiles.value.map((f) => f.file))
  const out: RelTab[] = []
  for (const r of selRelations.value) {
    const a = (graph.value?.anchors ?? []).find((x) => x.assetId === r.targetId)
    if (!a || seenFile.has(a.file)) continue
    seenFile.add(a.file)
    out.push({
      file: a.file, label: a.file.split('/').pop() || a.file,
      line: a.line, symbol: a.symbol ?? '',
      targetId: r.targetId, targetName: r.targetName, relText: r.desc || r.type,
    })
    if (out.length >= 3) break
  }
  return out
})
/** 拓展关联沉淀 tab(基于选中节点扩展出的关联节点所在文件；点击仅预览，不切换选中)。 */
const expandedTabs = ref<RelTab[]>([])
const fileTabs = computed(() => [
  ...visitedTabs.value.map((v) => ({ file: v.file, label: v.label, kind: 'visit' as const, assetId: v.assetId, assetName: v.assetName, rel: null as RelTab | null })),
  ...expandedTabs.value
    .filter((t) => !visitedTabs.value.some((v) => v.file === t.file))
    .map((t) => ({ file: t.file, label: t.label, kind: 'expand' as const, assetId: '', assetName: '', rel: t as RelTab | null })),
  ...relTabs.value
    .filter((t) => !visitedTabs.value.some((v) => v.file === t.file) && !expandedTabs.value.some((x) => x.file === t.file))
    .map((t) => ({ file: t.file, label: t.label, kind: 'rel' as const, assetId: '', assetName: '', rel: t as RelTab | null })),
])
/** tab 点击：访问历史 → 选中对应资产(图谱/卡/焦点全联动)；关系/拓展 tab → 仅预览相关代码。 */
function tabClick(t: { kind: 'visit' | 'rel' | 'expand'; file: string; assetId: string }) {
  if (t.kind === 'visit' && t.assetId && t.assetId !== selId.value) {
    selId.value = t.assetId
    return
  }
  switchFileTab(t.file)
}
const activeRelTab = computed(() =>
  relTabs.value.find((x) => x.file === activeFileTab.value)
  ?? expandedTabs.value.find((x) => x.file === activeFileTab.value)
  ?? null)
/** 关系 tab 代码窗口(按文件懒拉取)。 */
const relTabSegs = ref<Record<string, SourceSnippet | null>>({})
const relTabLoading = ref('')
const relTabEl = ref<HTMLElement | null>(null)
async function ensureRelTab(t: RelTab) {
  if (relTabSegs.value[t.file] || relTabLoading.value === t.file) return
  relTabLoading.value = t.file
  try {
    const sn = (await semanticAssetService.sourceSnippet(t.file, t.line, t.symbol || undefined, 10, 10, SEG_SNIPPET_LIMIT)) ?? null
    relTabSegs.value = { ...relTabSegs.value, [t.file]: sn }
  } catch {
    relTabSegs.value = { ...relTabSegs.value, [t.file]: null }
  } finally {
    relTabLoading.value = ''
  }
}
/** 关系 tab 聚焦：滚动到其锚点行并闪烁。 */
function focusRelTab(file: string) {
  void nextTick(() => {
    if (activeFileTab.value !== file) return
    const first = relTabEl.value?.querySelector('[data-anchor-line]')
    if (first) first.scrollIntoView({ block: 'center' })
    triggerFlash()
  })
}

// ---- 拓展关联：基于选中节点扩展 1 跳关联节点(增量合并，可累积)；相关文件沉淀为源码 tab ----
const expanding = ref(false)
const expandFeedback = ref('')
let expandFeedbackTimer: ReturnType<typeof setTimeout> | null = null

/** 拓展预判断：预取选中节点 1 跳子图(与拓展同源，含派生边)，以「不在图内的节点数」精确判定。
 *  预取失败视为未知 → 仍可点击(由点击后的「无新增」反馈兜底)，避免误置灰。 */
const pendingExpand = ref<{ selId: string; sub: SemanticGraphResult; added: number } | null>(null)
const expandUnknown = ref(false)
const expandable = computed(() =>
  expandUnknown.value || (!!pendingExpand.value
    && pendingExpand.value.selId === selId.value
    && pendingExpand.value.added > 0))

async function prefetchExpand() {
  const id = selId.value
  if (!id || loading.value) { pendingExpand.value = null; return }
  expandUnknown.value = false
  try {
    const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
    const sub = await semanticAssetService.graph(
      kindFilter.value || undefined, scope, effectiveLevel.value || undefined,
      { focus: id, hops: 1 })
    if (selId.value !== id) return   // 选中已切换 → 丢弃过期结果
    const ids = new Set((graph.value?.nodes ?? []).map((n) => n.id))
    pendingExpand.value = { selId: id, sub, added: sub.nodes.filter((n) => !ids.has(n.id)).length }
  } catch {
    if (selId.value === id) {
      pendingExpand.value = null
      expandUnknown.value = true   // 预取失败不误伤：允许点击，点击后再按实际结果反馈
    }
  }
}
watch(selId, () => { pendingExpand.value = null; void prefetchExpand() })
watch(graph, () => { if (selId.value) void prefetchExpand() })   // 拓展合并/重查后重算(无新增 → 置灰)

async function expandSelected() {
  if (!selId.value || loading.value || expanding.value) return
  expanding.value = true
  try {
    let sub = pendingExpand.value?.selId === selId.value ? pendingExpand.value.sub : null
    if (!sub) {
      const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
      sub = await semanticAssetService.graph(
        kindFilter.value || undefined, scope, effectiveLevel.value || undefined,
        { focus: selId.value, hops: 1 })
    }
    const g = graph.value
    if (!g) return
    // 增量合并：节点按 id、边按 from|to|type、锚点按 assetId|file|line 去重
    const nodeIds = new Set(g.nodes.map((n) => n.id))
    const added = sub.nodes.filter((n) => !nodeIds.has(n.id))
    const edgeKey = (e: { from: string; to: string; type?: string }) => `${e.from}|${e.to}|${e.type ?? ''}`
    const edgeKeys = new Set(g.edges.map(edgeKey))
    const newEdges = sub.edges.filter((e) => !edgeKeys.has(edgeKey(e)))
    const anchorKey = (a: { assetId: string; file: string; line: number }) => `${a.assetId}|${a.file}|${a.line}`
    const anchorKeys = new Set((g.anchors ?? []).map(anchorKey))
    const newAnchors = (sub.anchors ?? []).filter((a) => !anchorKeys.has(anchorKey(a)))
    if (added.length) {
      graph.value = {
        ...g,
        nodes: [...g.nodes, ...added],
        edges: [...g.edges, ...newEdges],
        anchors: [...(g.anchors ?? []), ...newAnchors],
        count: g.nodes.length + added.length,
      }
      // 卡片联动：新增节点的主锚点文件沉淀为拓展源码 tab(点击仅预览，不切换选中)
      const seen = new Set<string>([
        ...expandedTabs.value.map((x) => x.file),
        ...visitedTabs.value.map((v) => v.file),
        ...anchorFiles.value.map((f) => f.file),
      ])
      for (const n of added) {
        const a = newAnchors.find((x) => x.assetId === n.id)
        if (!a || seen.has(a.file)) continue
        seen.add(a.file)
        expandedTabs.value = [...expandedTabs.value, {
          file: a.file, label: a.file.split('/').pop() || a.file,
          line: a.line, symbol: a.symbol ?? '',
          targetId: n.id, targetName: n.name, relText: t('assetMgmt.graph.expandLabel'),
        }]
      }
    }
    expandFeedback.value = added.length
      ? t('assetMgmt.graph.expandAdded', { n: added.length })
      : t('assetMgmt.graph.expandNone')
    if (expandFeedbackTimer) clearTimeout(expandFeedbackTimer)
    expandFeedbackTimer = setTimeout(() => { expandFeedback.value = '' }, 2200)
  } finally {
    expanding.value = false
  }
}

// ---- C2 复制代码位置(file:Lx-Ly symbol) ----
const copiedSeg = ref(-1)
async function copySegLoc(seg: CodeSegment, si: number) {
  const s = seg.snippet
  if (!s?.lines?.length) return
  const start = s.lines[0].line
  const end = s.lines[s.lines.length - 1].line
  const loc = `${seg.file}:L${start}${end !== start ? `-L${end}` : ''}${seg.symbol ? ' ' + seg.symbol : ''}`
  try {
    await navigator.clipboard.writeText(loc)
    copiedSeg.value = si
    setTimeout(() => { if (copiedSeg.value === si) copiedSeg.value = -1 }, 1500)
  } catch { /* 剪贴板不可用则忽略 */ }
}

// ---- C1 按类别结构化 detail(有数据时)：entity/contract→字段 · process/decision→步骤 · state→状态 ----
const detailBlock = computed<{ title: string; rows: { text: string; title: string }[] } | null>(() => {
  const d = selDetail.value?.detail
  if (!d) return null
  const kind = sel.value?.kind
  if ((kind === 'entity' || kind === 'contract') && d.fields?.length) {
    return {
      title: t('assetMgmt.graph.fields'),
      rows: d.fields.map((f) => {
        const text = `${f.name}${f.type ? `: ${f.type}` : ''}`
        return { text, title: f.semantic ? `${f.name}: ${f.type ?? ''} — ${f.semantic}` : text }
      }),
    }
  }
  if ((kind === 'process' || kind === 'decision') && d.steps?.length) {
    return {
      title: t('assetMgmt.graph.steps'),
      rows: d.steps.map((s, i) => {
        const n = s.order ?? i + 1
        const syms = s.symbols?.length ? ` · ${s.symbols.join(', ')}` : ''
        return { text: `${n}. ${s.semantic}`, title: `${s.semantic}${syms}` }
      }),
    }
  }
  if (kind === 'state' && d.states?.length) {
    return {
      title: t('assetMgmt.graph.states'),
      rows: d.states.map((s) => {
        const marks = [s.initial ? '●' : '', s.final ? '◉' : ''].filter(Boolean).join('')
        const text = `${s.name}${s.desc ? ` — ${s.desc}` : ''}${marks ? `  ${marks}` : ''}`
        return { text, title: text }
      }),
    }
  }
  return null
})

// 选中资产 → 拉取完整详情（astRefs 唯一来源）。
// 完整代码视图打开时：同文件资产切换保持视图(互斥：不重建资产卡)；跨文件 → 关闭全文并正常重建。
watch(selId, async (id) => {
  selDetail.value = null
  if (!id) return
  try {
    const d = (await semanticAssetService.detail(id)) ?? null
    if (fullCode.value && d) {
      const files = new Set((d.astRefs ?? []).map((r) => r.file))
      if (!files.has(fullCode.value.file)) {
        // 跨文件切资产：全文视图跟随切到新资产主锚点文件(拉取失败 → 回退分段重建)
        const target = (d.astRefs ?? [])[0]?.file ?? ''
        if (target) {
          activeFileTab.value = target
          void (async () => {
            const ok = await loadFullCodeFor(target)
            if (!ok) void rebuildSegments(selAnchors.value)
          })()
        } else {
          fullCode.value = null
        }
      }
    }
    selDetail.value = d
  } catch {
    selDetail.value = null
  }
})

// ---- 节点点击 → 选中资产 + 锚点代码闪烁突出 ----
const clickIds = computed(() => semanticViewClickIds(effectiveView.value, scopedNodes.value))
let flashOnNext = false
let flashSeg = 0
const flashing = ref(false)
let flashTimer: ReturnType<typeof setTimeout> | null = null

/** 段内高亮行判定：highlight 非空用之，否则退回锚点行，保证至少一行高亮。 */
function segHighlighted(seg: CodeSegment, line: number): boolean {
  const s = seg.snippet
  if (!s) return false
  const hl = (s.highlight ?? []).map(Number).filter((n) => n > 0)
  if (hl.length) return hl.includes(line)
  return Number(s.anchorLine || 0) === line
}

/** 闪烁脉冲(分段/全文共用)：一个脉冲周期内高亮行加 anchor-flash 类。 */
function triggerFlash() {
  flashing.value = false
  void nextTick(() => {
    flashing.value = true
    if (flashTimer) clearTimeout(flashTimer)
    flashTimer = setTimeout(() => { flashing.value = false }, 1700)
  })
}

/** 滚动到某段首个锚点行并闪烁强调(最小化时不做，脉冲提示覆盖)。 */
function flashAnchor(segIdx = flashSeg) {
  if (cardMin.value) return
  const el = segEls[segIdx]
  if (!el || !segments.value[segIdx]?.snippet) return
  const first = el.querySelector('[data-anchor-line]')
  if (first) first.scrollIntoView({ block: 'center' })
  triggerFlash()
}

function onNodeClick(e: NodeClickEvent) {
  // ① 稳定 id(nodeId)；② 文本兜底/别名(label 反查)；③ flow 文本「名称 · 资产ID」尾段
  let assetId = clickIds.value.get(e.nodeId) ?? clickIds.value.get(e.label ?? '') ?? ''
  if (!assetId) {
    const tail = (e.label || '').split('·').pop()?.trim() ?? ''
    if (/^sa-/.test(tail)) assetId = tail
  }
  if (!assetId && e.nodeId.startsWith('txt:')) {
    // 点中文本未映射(如 UML 构造型 «process»、ER 字段行) → 半径 80px 内就近搜索可映射文本
    assetId = nearestMappedAsset(e) ?? ''
  }
  if (!assetId) return
  flashOnNext = true
  flashSeg = 0
  if (selId.value === assetId) {
    // 同一节点重复点击：回到其主锚点文件 tab，立即闪烁。
    const home = selAnchors.value[0]?.file
    if (home && activeFileTab.value !== home) activeFileTab.value = home
    flashOnNext = false
    void nextTick(() => flashAnchor(0))
    return
  }
  selId.value = assetId
}

/** 就近搜索可映射文本(节点整体点击：构造型/字段行等未映射文本落在可映射文本附近)。 */
function nearestMappedAsset(e: NodeClickEvent): string | null {
  const host: HTMLElement | null = diagRef.value?.containerRef ?? null
  const svg = host?.querySelector('svg')
  if (!svg) return null
  const hostRect = host.getBoundingClientRect()
  // 事件 x/y 为 container 相对坐标 → 还原视口坐标(与 text rect 同空间)
  const px = hostRect.left + (e.x || 0)
  const py = hostRect.top + (e.y || 0)
  let best: string | null = null
  let bestD = 80 * 80
  svg.querySelectorAll('text').forEach((t) => {
    const label = t.textContent?.trim() ?? ''
    let aid = clickIds.value.get(label) ?? ''
    if (!aid) {
      const tail = label.split('·').pop()?.trim() ?? ''
      if (/^sa-/.test(tail)) aid = tail
    }
    if (!aid) return
    let r: DOMRect
    try { r = t.getBoundingClientRect() } catch { return }
    if (!r || (!r.width && !r.height)) return
    const dx = r.left + r.width / 2 - px
    const dy = r.top + r.height / 2 - py
    const d = dx * dx + dy * dy
    if (d < bestD) { bestD = d; best = aid }
  })
  return best
}

// ---- 图节点选中样式：绑定节点 DOM(每次选中切换：旧节点移除样式、新节点加样式) ----
let selectedNodeEl: Element | null = null

/** 与 node-click 插件同口径：从节点 DOM 剥出逻辑 id(mermaid id 模式 / plantuml uid)。
 *  mermaid 11 会把渲染实例 id(如 topo-one-mmd-3) 作前缀，先剥离再匹配。 */
function resolveNodeIdFromEl(el: Element, rootPrefix = ''): string | null {
  const raw = rootPrefix && el.id?.startsWith(rootPrefix) ? el.id.slice(rootPrefix.length) : (el.id || '')
  const m = /^([a-zA-Z][a-zA-Z0-9]*)-([A-Za-z][\w-]*?)-\d+$/.exec(raw)
  if (m) return m[2]
  return el.getAttribute?.('data-entity-uid') ?? null
}

/** 当前选中资产 → 图内节点 DOM；id 寻址失败(plantuml 各视图)按节点文本兜底：
 *  候选=名称截断口径 + clickIds 反查标签(名称·ID/净化id 等各视图文本口径) + 内嵌资产 id 文本。 */
function applySelectedNodeStyle() {
  const host: HTMLElement | null = diagRef.value?.containerRef ?? null
  const svg = host?.querySelector('svg')
  if (!svg) return
  selectedNodeEl?.classList.remove('td-node-selected')
  selectedNodeEl = null
  const targetId = selId.value
  if (!targetId) return
  const rootPrefix = svg.id ? `${svg.id}-` : ''
  let wantNodeId: string | undefined
  for (const [nid, aid] of clickIds.value) {   // 反查：assetId → 主键 nodeId
    if (aid === targetId) { wantNodeId = nid; break }
  }
  if (wantNodeId) {
    for (const el of svg.querySelectorAll('[id], [data-entity-uid]')) {
      if (resolveNodeIdFromEl(el, rootPrefix) === wantNodeId) { selectedNodeEl = el; break }
    }
  }
  if (!selectedNodeEl) {
    const name = sel.value?.name ?? ''
    const candidates = new Set<string>([name, ...[30, 40, 26, 18].map((m) => semanticNodeLabelText(name, m))])
    for (const [label, aid] of clickIds.value) {   // plantuml 各视图节点文本口径都登记在 clickIds
      if (aid === targetId && label) candidates.add(label)
    }
    for (const t of svg.querySelectorAll('text')) {
      const txt = (t.textContent || '').trim()
      if (!txt) continue
      if (candidates.has(txt) || txt.includes(targetId)) {   // plantuml flow 标签内嵌「· 资产ID」
        // 爬升到含形状的最近组(plantuml 文本与形状可能不同层)，保证描边样式落在节点整体上
        let el: Element | null = t
        while (el && el !== svg) {
          if (el.querySelector('rect, polygon, ellipse, circle')) { selectedNodeEl = el; break }
          el = el.parentElement
        }
        if (!selectedNodeEl) selectedNodeEl = (t.closest('g') as Element | null) ?? t.parentElement
        break
      }
    }
  }
  selectedNodeEl?.classList.add('td-node-selected')
}

/** 节点多行 tooltip：名称 / 类别·粒度 / 简介 / 锚点 / 关系(出·入)。数据现成，双引擎通用；
 *  单资产(孤立节点)hover 亦可见真实信息，避免「只有一个 ID」。 */
function nodeTooltipText(n: { id: string; kind: string; level?: string; name: string; desc: string; nodeBrief?: string }): string {
  const lines: string[] = [n.name]
  const kindLabel = t(`assetMgmt.kind.${n.kind}`)
  const levelMap: Record<string, string> = {
    business: t('assetMgmt.graph.business'),
    logic: t('assetMgmt.graph.logic'),
    implementation: t('assetMgmt.graph.implementation'),
  }
  const meta = [kindLabel, n.level ? levelMap[n.level] : ''].filter(Boolean).join(' · ')
  if (meta) lines.push(meta)
  const brief = n.nodeBrief || n.desc
  if (brief) lines.push(brief)
  const anchors = (graph.value?.anchors ?? []).filter((a) => a.assetId === n.id)
  if (anchors.length) {
    const a = anchors[0]
    const more = anchors.length > 1 ? ` (+${anchors.length - 1})` : ''
    lines.push(`${t('assetMgmt.graph.anchor')}: ${shortPath(a.file)}:L${a.line}${a.symbol ? ' · ' + a.symbol : ''}${more}`)
  }
  const out = (scopedEdges.value ?? []).filter((e) => e.from === n.id).length
  const inn = (scopedEdges.value ?? []).filter((e) => e.to === n.id).length
  if (out || inn) lines.push(`${t('assetMgmt.relations')} ${out} · ${t('assetMgmt.graph.inEdges')} ${inn}`)
  return lines.join('\n')
}

/** 节点 hover tooltip(多行)。原生 SVG <title> 实现，双引擎通用。 */
/** 图谱悬停提示(双引擎统一)：节点=多行信息(名称/类别/简介/锚点/关系)，边=完整增强描述。
 *  mermaid 节点按 id 寻址；plantuml 节点/全部边按渲染文本匹配(SVG <text> 插 <title>，
 *  mermaid foreignObject HTML 标签设 title 属性)。 */
function applyNodeTooltips() {
  const host: HTMLElement | null = diagRef.value?.containerRef ?? null
  const svg = host?.querySelector('svg')
  if (!svg) return
  const rootPrefix = svg.id ? `${svg.id}-` : ''
  const NS = 'http://www.w3.org/2000/svg'
  const titled = new Set<Element>()

  // ① 节点：mermaid id 寻址(组粒度，最准)
  for (const [nid, aid] of clickIds.value) {
    for (const el of svg.querySelectorAll('[id], [data-entity-uid]')) {
      if (resolveNodeIdFromEl(el, rootPrefix) !== nid) continue
      for (const old of el.querySelectorAll('title')) old.remove()
      const n = scopedNodes.value.find((x) => x.id === aid)
      if (n) {
        const tip = document.createElementNS(NS, 'title')
        tip.textContent = nodeTooltipText(n)
        el.insertBefore(tip, el.firstChild)
        titled.add(el)
      }
      break
    }
  }

  // ② 节点文本兜底(plantuml 全部节点)：渲染文本口径(name·id/名称截断/净化id)都登记在 clickIds
  const labelToNode = new Map<string, { id: string; kind: string; level?: string; name: string; desc: string; nodeBrief?: string }>()
  for (const [label, aid] of clickIds.value) {
    if (!label || labelToNode.has(label)) continue
    const n = scopedNodes.value.find((x) => x.id === aid)
    if (n) labelToNode.set(label, n)
  }
  for (const n of scopedNodes.value) {
    for (const v of [n.name, ...[18, 26, 30, 40].map((m) => semanticNodeLabelText(n.name, m))]) {
      if (!labelToNode.has(v)) labelToNode.set(v, n)
    }
  }
  for (const t of svg.querySelectorAll('text')) {
    const txt = (t.textContent || '').trim()
    if (!txt || titled.size && [...titled].some((g) => g.contains(t))) continue
    const n = labelToNode.get(txt)
    if (!n) continue
    let el: Element | null = t
    while (el && el !== svg) {
      if (el.querySelector('rect, polygon, ellipse, circle')) break
      el = el.parentElement
    }
    const group = (el && el !== svg ? el : (t.closest('g') ?? t.parentElement)) as Element | null
    if (group && !titled.has(group)) {
      for (const old of group.querySelectorAll('title')) old.remove()
      const tip = document.createElementNS(NS, 'title')
      tip.textContent = nodeTooltipText(n)
      group.insertBefore(tip, group.firstChild)
      titled.add(group)
    }
  }

  // ③ 边：标签截断变体 → 完整描述(增强 desc 优先)。与生成器同口径(_semLabel 清洗+截断+…)。
  const labelToDesc = new Map<string, string>()
  const puText = (s: string) => (s || '').replace(/[;|\r\n]+/g, ' ').replace(/-->/g, '->').trim()
  for (const e of scopedEdges.value) {
    // 悬停 = 关系描述 + 证据(文件:行/解析方式/置信度/间接中转)
    const ev: string[] = []
    if (e.indirect && e.via) ev.push(`间接 ⇝ ${e.via}`)
    if (e.file) ev.push(`${e.file}${e.line ? `:${e.line}` : ''}`)
    if (e.resolvedBy) ev.push(e.resolvedBy + (e.confidence ? ` (${e.confidence})` : ''))
    const tip = [(e.desc || e.semantic || e.type || '').trim(), ...ev].filter(Boolean).join('\n')
    if (!tip) continue
    const bases = new Set<string>([
      (e.desc || e.type || e.semantic || '').trim(),
      (e.desc || e.type || '').trim(),
      (e.type || '').trim(),
      (e.semantic || '').trim(),
      // 间接边标签含 ⇝via 后缀(_semEdgeLabel 口径)
      ...((e.indirect && e.via)
        ? [(e.desc || e.type || e.semantic || 'rel').trim(), (e.desc || e.type || '').trim()]
            .filter(Boolean).map((b) => `${b}⇝${e.via!.slice(0, 10)}`)
        : []),
    ].filter(Boolean))
    for (const b of bases) {
      for (const len of [10, 12, 14, 16, 20, 24, 26]) {
        const v = semanticNodeLabelText(b, len)
        if (!labelToDesc.has(v)) labelToDesc.set(v, tip)
        const pv = puText(v)
        if (!labelToDesc.has(pv)) labelToDesc.set(pv, tip)
      }
      if (!labelToDesc.has(b)) labelToDesc.set(b, tip)
    }
  }
  for (const el of svg.querySelectorAll('text, foreignObject span, foreignObject div')) {
    const txt = (el.textContent || '').trim()
    if (!txt) continue
    const full = labelToDesc.get(txt)
    if (!full || full === txt) continue   // 未截断 → 悬停无增量
    if (el.namespaceURI === NS) {
      for (const old of el.querySelectorAll('title')) old.remove()
      const tip = document.createElementNS(NS, 'title')
      tip.textContent = full
      el.insertBefore(tip, el.firstChild)
    } else {
      el.setAttribute('title', full)   // mermaid foreignObject 内是 HTML 元素
    }
  }
}

// ---- AI 逐行解读(逐段生成；结合术语/规约；手动触发，后端落库缓存) ----
const lineNotesMaps = ref<Record<number, Record<number, string>>>({})
const lineNotesLoading = ref(false)
const lineNotesDegraded = ref(false)
const lineNotesError = ref('')
/** 最近一次结果是否全部来自缓存(失效缓存后端等同无缓存，不会误标)。 */
const lineNotesFromCache = ref(false)

/** 已解读行数(按钮上展示，让激活状态可见)。 */
const lineNotesCount = computed(() =>
  Object.values(lineNotesMaps.value).reduce((n, m) => n + Object.keys(m).length, 0)
  + Object.keys(fullCodeNotes.value).length)

async function loadLineNotes(force = false) {
  if (!sel.value || lineNotesLoading.value) return
  // 完整代码模式 → 解读全文窗口
  if (fullCode.value) {
    await loadFullCodeNotes(force)
    return
  }
  const targets = segments.value
    .map((seg, i) => ({ seg, i }))
    .filter(({ seg }) => seg.snippet?.lines?.length)
  if (!targets.length) return
  lineNotesLoading.value = true
  lineNotesError.value = ''
  let degraded = false
  let anyCached = false
  let allCached = true
  for (const { seg, i } of targets) {
    const s = seg.snippet!
    try {
      const r = await semanticAssetService.lineNotes(
        sel.value.id, s.file, s.lines[0].line, s.lines[s.lines.length - 1].line, { force })
      // 键归一为数字(JSON 反序列化后为字符串键)，避免任何运行时键型差异
      const norm: Record<number, string> = {}
      for (const [k, v] of Object.entries(r.notes || {})) norm[Number(k)] = String(v)
      lineNotesMaps.value = { ...lineNotesMaps.value, [i]: norm }
      if (r.error) { lineNotesError.value = r.error; break }
      if (r.degraded) degraded = true
      if (r.cached) anyCached = true; else allCached = false
    } catch (err: any) {
      lineNotesError.value = err?.message || 'failed'
      break
    }
  }
  // 有明确 error 时只显示失败提示(可重试)，不再叠加「降级」横幅
  lineNotesDegraded.value = degraded && !lineNotesError.value
  lineNotesFromCache.value = anyCached && allCached
  lineNotesLoading.value = false
}

/** 清除缓存重新生成(后端 force=true：视同无缓存，重新生成并覆盖)。 */
function regenerateLineNotes() {
  void loadLineNotes(true)
}

/** 锚点导航：点击锚点 → (跨文件时切到对应 tab)展开对应代码段并滚动、闪烁锚点行。 */
function jumpToSegment(i: number) {
  const seg = segments.value[i]
  if (seg && activeFileTab.value !== seg.file) activeFileTab.value = seg.file
  if (collapsedSegs.value.has(i)) toggleSeg(i)   // 先展开目标段(折叠时锚点行未渲染)
  void nextTick(() => {
    const el = segEls[i]
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    flashSeg = i
    flashAnchor(i)
  })
}

// 最小化时信息刷新(选中资产变化) → 不自动展开浮窗；停靠图标闪动缩放 ~3s 提示。
// 同时：未手动选图类型时，点击节点切换选中 → 钉住「用户正在看的视图」，
// 防止推荐随新资产类别/粒度变化而偶发跳图(如 关系图→ER)。首次点击(sel null→资产)同样覆盖。
const iconPulse = ref(false)
let iconPulseTimer: ReturnType<typeof setTimeout> | null = null
let lastShownView: SemanticGraphViewId | '' = ''
watch(effectiveView, (_v, ov) => { lastShownView = ov ?? _v })   // 记录变更前的显示视图(供选中切换时钉住)
watch(sel, (n) => {
  void nextTick(applySelectedNodeStyle)   // 选中样式绑定到节点 DOM：新节点加样式、旧节点移除
  if (view.value || !n) return
  // 选中后的将显示视图(与 effectiveView 同口径)
  const rec = recommendedSemanticView(n.kind, effectiveLevel.value || undefined)
  const newEff = viewOptions.value.some((x) => x.value === rec) ? rec : (viewOptions.value[0]?.value ?? '')
  const shown = lastShownView
  if (shown && shown !== newEff && viewOptions.value.some((x) => x.value === shown)) {
    view.value = shown   // 钉住正在看的视图(新数据下仍支持时)
  }
})
watch(selId, (id, old) => {
  if (!id || id === old || !cardMin.value) return
  iconPulse.value = false
  void nextTick(() => {
    iconPulse.value = true
    if (iconPulseTimer) clearTimeout(iconPulseTimer)
    iconPulseTimer = setTimeout(() => { iconPulse.value = false }, 3000)
  })
})

// 锚点变化 → 重建代码段并逐段拉取源码窗口；注解失效(后端落库缓存，重击按钮秒回)。
// 完整代码视图打开时跳过重建(同文件资产切换不刷新资产卡)；关闭后下次锚点变化正常重建。
async function rebuildSegments(anchors: { file: string; startLine: number; symbol: string }[]) {
  const cap = anchors.slice(0, MAX_SEGMENTS)
  activeFileTab.value = cap[0]?.file ?? ''   // 跟随图节点切换 → 文件 tab 焦点落在主锚点文件
  const seq = ++segSeq
  segments.value = cap.map((a) => ({ file: a.file, symbol: a.symbol, startLine: a.startLine, snippet: null, loading: true }))
  resetSegCollapse(cap.length)   // B2: 除首段外全部折叠
  lineNotesMaps.value = {}
  lineNotesDegraded.value = false
  lineNotesError.value = ''
  await Promise.all(cap.map(async (a, i) => {
    let sn: SourceSnippet | null = null
    try {
      sn = (await semanticAssetService.sourceSnippet(a.file, a.startLine, a.symbol, 10, 10, SEG_SNIPPET_LIMIT)) ?? null
    } catch {
      sn = null
    }
    if (seq !== segSeq) return
    const seg = segments.value[i]
    if (seg) { seg.snippet = sn; seg.loading = false }
  }))
}
watch(selAnchors, (anchors) => {
  if (fullCode.value) return
  void rebuildSegments(anchors)
})

// 选中变化后详情/源码异步到达 → 到位后闪烁。
watch(segments, (segs) => {
  if (flashOnNext && segs.some((s) => s.snippet)) {
    flashOnNext = false
    void nextTick(() => flashAnchor(flashSeg))
  }
}, { deep: true })

// ---- 完整代码视图(单文件全文；文件内多资产锚点全部高亮，点击锚点切资产) ----
// 互斥约定：全文视图内点击同文件资产锚点 → 仅切换图谱选中，不重建资产卡；
// 跨文件(新资产锚点不在当前全文文件) → 关闭全文并按常规刷新图谱+资产卡。
/** 分段源码窗口上限(行)：整符号体优先全量展示/解读(旧默认 60 行截断是「长函数只解读头部」的成因)。 */
const SEG_SNIPPET_LIMIT = 2000
/** 完整代码窗口上限(行)：优先全量提供；逐行解读超限由后端 1/2→1/4→1/8 分批降级兜住。 */
const FULL_FILE_LIMIT = 8000
const fullCode = ref<SourceSnippet | null>(null)
const fullCodeLoading = ref(false)
const fullCodeNotes = ref<Record<number, string>>({})
const fullCodeNotesLoading = ref(false)
const fullCodeError = ref('')

async function toggleFullCode() {
  fullCodeError.value = ''
  if (fullCode.value) {
    fullCode.value = null
    fullCodeNotes.value = {}
    return
  }
  const file = activeFileTab.value || selAnchors.value[0]?.file
  if (!file || !sel.value) return
  await loadFullCodeFor(file)
}

/** 拉取指定文件全文(窗口上限 FULL_FILE_LIMIT)；返回是否成功，供调用方兜底回退。 */
async function loadFullCodeFor(file: string): Promise<boolean> {
  fullCodeLoading.value = true
  try {
    fullCode.value = (await semanticAssetService.sourceSnippet(file, 1, undefined, FULL_FILE_LIMIT, FULL_FILE_LIMIT, FULL_FILE_LIMIT)) ?? null
    fullCodeNotes.value = {}
    return !!fullCode.value
  } catch {
    fullCode.value = null
    return false
  } finally {
    fullCodeLoading.value = false
  }
}

/** 全文内 行号 → 所属资产 id(仅图谱范围内已知锚点；严谨起见只标注确知行，不猜测区间)。 */
const fullCodeOwners = computed<Map<number, string>>(() => {
  const m = new Map<number, string>()
  if (!fullCode.value) return m
  for (const a of graph.value?.anchors ?? []) {
    if (a.file !== fullCode.value!.file || !a.assetId) continue
    if (!m.has(a.line)) m.set(a.line, a.assetId)
  }
  return m
})

/** 当前资产在全文文件内的锚点行集合(精确 astRefs 区间)。 */
const fullCodeSelfLines = computed<Set<number>>(() => {
  const s = new Set<number>()
  if (!fullCode.value) return s
  const file = fullCode.value.file
  for (const r of selDetail.value?.astRefs ?? []) {
    if ((r.file || '') !== file) continue
    const a = Number(r.startLine || 0)
    const b = Number(r.endLine || 0) || a
    for (let ln = a; ln <= b; ln++) s.add(ln)
  }
  return s
})

// 全文视图可视焦点跟随：图节点点击/行点击切换资产(同文件不重建卡) → 滚动到
// 当前资产首个锚点行并闪烁；打开全文时同样定位到首锚点行。
const fullCodePreRef = ref<HTMLPreElement | null>(null)
watch(fullCodeSelfLines, (lines) => {
  if (!fullCode.value || cardMin.value || !lines.size) return
  void nextTick(() => {
    if (!fullCode.value) return
    const first = Math.min(...lines)
    const el = fullCodePreRef.value?.querySelector(`[data-full-line="${first}"]`)
    if (el) el.scrollIntoView({ block: 'center' })
    triggerFlash()
  })
})

/** 全文行点击：命中其它资产锚点 → 切换选中(同文件 → 资产卡保持全文视图)。 */
function onFullCodeLineClick(line: number) {
  const ownerId = fullCodeOwners.value.get(line)
  if (!ownerId || ownerId === selId.value) return
  selId.value = ownerId
}

/** 锚点所属资产显示名(全文 tooltip 用)。 */
function ownerName(assetId: string): string {
  return graph.value?.nodes.find((n) => n.id === assetId)?.name ?? assetId
}

/** 源码路径展示：项目相对路径(去开头 ./ /)；过长时从头省略目录段(保尾部)，完整路径用 title 悬停展示。 */
function shortPath(p: string, max = 42): string {
  const norm = (p || '').replace(/\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, '')
  if (norm.length <= max) return norm
  const parts = norm.split('/')
  while (parts.length > 1 && parts.join('/').length > max) parts.shift()
  const out = parts.join('/')
  return (out.length < norm.length ? '…/' : '') + out
}

// ---- 完整代码 AI 逐行解读 ----
async function loadFullCodeNotes(force = false) {
  const fc = fullCode.value
  if (!fc?.lines?.length || !sel.value || fullCodeNotesLoading.value) return
  fullCodeNotesLoading.value = true
  fullCodeError.value = ''
  try {
    const r = await semanticAssetService.lineNotes(
      sel.value.id, fc.file, fc.lines[0].line, fc.lines[fc.lines.length - 1].line, { force })
    const norm: Record<number, string> = {}
    for (const [k, v] of Object.entries(r.notes || {})) norm[Number(k)] = String(v)
    fullCodeNotes.value = norm
    lineNotesFromCache.value = !!r.cached && !r.error
    if (r.error) fullCodeError.value = r.error
  } catch (err: any) {
    fullCodeError.value = err?.message || 'failed'
    lineNotesFromCache.value = false
  } finally {
    fullCodeNotesLoading.value = false
  }
}

onMounted(async () => {
  await load()
})
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <!-- 工具栏(单行)：粒度 + 图类型 + 视图上下文(单资产焦点/关联级别) + 统计 + 操作 -->
    <div class="shrink-0 flex items-center gap-1 px-1 pt-1 pb-1 border-b border-ctp-surface0 overflow-x-auto">
      <select
        v-model="kindFilter"
        class="input !py-0.5 !px-2 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.kindHint')"
      >
        <option value="">{{ t('assetMgmt.graph.allKinds') }}</option>
        <option v-for="o in kindOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <select
        v-model="level"
        class="input !py-0.5 !px-2 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.levelHint')"
      >
        <option value="">{{ t('assetMgmt.graph.allLevels') }}</option>
        <option v-for="o in levelOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <div class="w-px h-4 bg-ctp-surface1 shrink-0" />
      <select
        v-model="viewSel"
        class="input !py-0.5 !px-2 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.viewHint')"
      >
        <option
          v-for="o in viewOptions"
          :key="o.value"
          :value="o.value"
        >
          {{ o.label }}
        </option>
      </select>
      <span
        v-if="hiddenViewHints.length"
        class="shrink-0 text-[11px] text-ctp-overlay1 cursor-help px-0.5"
        :title="hiddenViewHints.join('\n')"
      >ⓘ</span>
      <!-- 邻域聚焦：只渲染选中资产周围 N 跳子图(缓解大图拥挤/过宽/过长) -->
      <div class="w-px h-4 bg-ctp-surface1 shrink-0" />
      <button
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="focusMode ? 'btn-primary' : ''"
        :title="t('assetMgmt.graph.focusHint')"
        @click="focusMode = !focusMode"
      >
        <ViewfinderCircleIcon class="w-3.5 h-3.5" />
      </button>
      <select
        v-if="focusMode"
        v-model.number="focusHops"
        class="input !py-0.5 !px-1.5 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.focusHops')"
      >
        <option v-for="h in [1, 2, 3]" :key="h" :value="h">{{ h }} {{ t('assetMgmt.graph.hop') }}</option>
      </select>
      <!-- 拓展关联：基于选中节点扩展 1 跳关联(增量合并，可累积)；无未拓展关联时置灰 -->
      <button
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="expandable ? '' : 'opacity-50 cursor-not-allowed'"
        :disabled="!expandable || expanding"
        :title="expandable ? t('assetMgmt.graph.expandHint') : t('assetMgmt.graph.expandDisabledHint')"
        @click="expandSelected"
      >
        <PlusCircleIcon class="w-3.5 h-3.5" />
      </button>
      <span
        v-if="expandFeedback"
        class="shrink-0 text-[10px] text-ctp-teal font-medium cursor-default"
      >{{ expandFeedback }}</span>
      <!-- 关系矩阵浮窗：文件×文件密度 + 节点级非对称全矩阵，数据跟随当前图谱口径 -->
      <button
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="matrixOpen ? 'btn-primary' : ''"
        :title="t('assetMgmt.matrix.title')"
        @click="toggleMatrix"
      >
        <TableCellsIcon class="w-3.5 h-3.5" />
      </button>
      <button
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="indexOpen ? 'btn-primary' : ''"
        :title="t('assetMgmt.index.title')"
        @click="toggleIndex"
      >
        <ListBulletIcon class="w-3.5 h-3.5" />
      </button>
      <!-- 符号源(CodeGraph)开关：三档 + 状态行 -->
      <div class="relative shrink-0" data-cg-pop>
        <button
          class="btn btn-ghost !py-0.5 !text-[11px] flex items-center"
          :class="cgOpen ? 'btn-primary' : ''"
          :title="t('assetMgmt.codegraph.title')"
          @click="toggleCg"
        >
          <AdjustmentsHorizontalIcon class="w-3.5 h-3.5" />
        </button>
        <div
          v-if="cgOpen"
          class="absolute right-0 top-8 z-30 w-72 rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-2.5 text-left"
          @click.stop
        >
          <div class="text-[11px] font-semibold text-ctp-text mb-1.5">{{ t('assetMgmt.codegraph.title') }}</div>
          <div class="flex gap-1 mb-2">
            <button
              v-for="m in (['on', 'auto', 'off'] as const)" :key="m"
              class="btn !py-0.5 !px-2 !text-[10px] flex-1"
              :class="cgStatus?.mode === m ? 'btn-primary' : 'btn-ghost'"
              :disabled="cgSaving"
              @click="setCgMode(m)"
            >{{ t(`assetMgmt.codegraph.mode${m[0].toUpperCase()}${m.slice(1)}`) }}</button>
          </div>
          <div class="text-[9px] text-ctp-overlay0 leading-relaxed">
            <div v-if="cgStatus">
              <span :class="cgStatus.cli ? 'text-ctp-green' : 'text-ctp-peach'">{{ cgStatus.cli ? t('assetMgmt.codegraph.cliOk') : t('assetMgmt.codegraph.cliMissing') }}</span>
              <span v-if="cgStatus.cliPath" class="font-mono truncate inline-block max-w-full align-bottom" :title="cgStatus.cliPath"> · {{ cgStatus.cliPath.split('/').slice(-1)[0] }}</span>
              <span class="mx-1">·</span>{{ { env: t('assetMgmt.codegraph.srcEnv'), kv: t('assetMgmt.codegraph.srcKv'), default: t('assetMgmt.codegraph.srcDefault') }[cgStatus.source] }}
              <div v-if="cgStatus.native?.nodes">· {{ t('assetMgmt.codegraph.nativeNodes') }}: {{ cgStatus.native.nodes.toLocaleString() }}</div>
            </div>
            <div class="mt-1 text-ctp-subtext0">
              {{ cgStatus?.mode === 'off' ? t('assetMgmt.codegraph.hintOff') : cgStatus?.mode === 'on' ? t('assetMgmt.codegraph.hintOn') : t('assetMgmt.codegraph.hintAuto') }}
            </div>
          </div>
        </div>
      </div>
      <!-- 边类型图例 + 显隐过滤；间接边开关(浮层 Teleport 到 body，不撑开工具栏) -->
      <button
        ref="legendBtnRef"
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="edgeTypeOff.size ? 'btn-primary' : ''"
        :title="t('assetMgmt.graph.edgeLegend')"
        @click="toggleEdgeLegend"
      >
        <AdjustmentsHorizontalIcon class="w-3.5 h-3.5" />
      </button>
      <Teleport to="body">
        <div
          v-if="edgeLegendOpen"
          data-edge-legend
          class="fixed z-50 w-44 rounded-lg border border-ctp-surface1 bg-ctp-mantle shadow-lg p-2 space-y-0.5"
          :style="{ top: legendPos.top + 'px', left: legendPos.left + 'px' }"
        >
          <label
            v-for="[k, n] in edgeTypeCounts"
            :key="k"
            class="flex items-center gap-1.5 px-1 py-0.5 rounded cursor-pointer hover:bg-ctp-surface0 text-[11px]"
          >
            <input
              type="checkbox"
              class="accent-ctp-mauve"
              :checked="!edgeTypeOff.has(k)"
              @change="toggleEdgeType(k)"
            >
            <span :class="edgeTypeColor(k)">{{ edgeTypeLabel(k) }}</span>
            <span class="ml-auto text-ctp-overlay0">{{ n }}</span>
          </label>
          <label class="flex items-center gap-1.5 px-1 py-0.5 rounded cursor-pointer hover:bg-ctp-surface0 text-[11px] border-t border-ctp-surface0 mt-1 pt-1.5">
            <input
              v-model="includeIndirect"
              type="checkbox"
              class="accent-ctp-teal"
            >
            <span class="text-ctp-subtext0">{{ t('assetMgmt.graph.indirectEdges') }}</span>
          </label>
        </div>
      </Teleport>
      <!-- 单资产视图上下文：聚焦资产(1 跳) -->
      <template v-if="props.tab.kind === 'asset' && sel">
        <div class="w-px h-4 bg-ctp-surface1 shrink-0" />
        <button
          class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
          :title="t('assetMgmt.graph.clearFocus')"
          @click="clearSel"
        >
          <XMarkIcon class="w-3 h-3" />
        </button>
      </template>
      <span class="flex-1" />
      <span
        v-if="graph"
        class="text-[10px] text-ctp-overlay0 font-mono shrink-0"
      >{{ scopedNodes.length }} {{ t('assetMgmt.graph.nodes') }} · {{ scopedEdges.length }} {{ t('assetMgmt.graph.edges') }}</span>
      <span
        v-if="graph && props.diffFiles && diffNodeCount"
        class="chip bg-ctp-yellow/15 text-ctp-yellow font-mono text-[9px] shrink-0"
        :title="t('assetMgmt.diff.hint')"
      >{{ diffNodeCount }} {{ t('assetMgmt.graph.nodes') }} · diff</span>
      <div
        v-if="graph"
        class="flex items-center gap-0.5 shrink-0"
      >
        <button
          v-for="l in diagramLangs"
          :key="l.id"
          class="px-1.5 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer"
          :class="cardLang === l.id
            ? 'bg-ctp-blue/15 text-ctp-blue ring-1 ring-ctp-blue/30'
            : 'text-ctp-subtext0 hover:bg-ctp-surface0'"
          :title="l.label"
          @click="setCardLang(l.id)"
        >
          {{ l.label }}
        </button>
        <button
          class="btn btn-ghost !py-0.5 text-[11px]"
          :title="t('assetMgmt.graph.source')"
          @click="toggleCardSource"
        >
          {{ cardSrcOpen ? t('assetMgmt.graph.diagram') : 'src' }}
        </button>
        <button
          class="btn btn-ghost !py-0.5 text-[11px]"
          :title="t('assetMgmt.graph.fullscreen')"
          @click="openCardFullscreen"
        >
          <ArrowsPointingOutIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <button
        class="btn btn-xs"
        :class="enhanceRunning ? 'btn-primary' : 'btn-ghost'"
        :disabled="enhanceRunning || loading"
        :title="enhanceRunning
          ? t('assetMgmt.graph.enhanceRunning', { d: enhanceProgress.done, t: enhanceProgress.total })
          : t('assetMgmt.graph.enhanceDesc')"
        @click="startEnhanceDesc"
      >
        <SparklesIcon
          class="w-3 h-3"
          :class="enhanceRunning ? 'animate-spin' : ''"
        />{{ enhanceRunning ? `${enhanceProgress.done}/${enhanceProgress.total}` : '' }}
      </button>
      <button
        class="btn btn-xs btn-ghost"
        :disabled="loading"
        :title="t('assetMgmt.graph.reload')"
        @click="load()"
      >
        <ArrowPathIcon
          class="w-3 h-3"
          :class="loading ? 'animate-spin' : ''"
        />
      </button>
      <button
        class="btn btn-xs btn-ghost"
        :title="t('assetMgmt.graph.closeTab')"
        @click="emit('close', props.tab.id)"
      >
        <XMarkIcon class="w-3 h-3" />
      </button>
    </div>

    <div class="flex-1 min-h-0 relative">
      <div
        v-if="loading"
        class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0"
      >
        {{ t('assetMgmt.graph.loading') }}
      </div>
      <div
        v-else-if="!graph || !scopedNodes.length"
        class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0"
      >
        {{ t('assetMgmt.graph.empty') }}
      </div>

      <div
        v-else
        class="h-full relative"
        :class="cardFullscreen ? 'fixed inset-0 z-50 bg-ctp-mantle p-2' : ''"
      >
        <pre
          v-if="cardSrcOpen"
          class="h-full m-0 overflow-auto rounded-lg bg-ctp-mantle border border-ctp-surface1 p-3 font-mono text-[11px] leading-relaxed whitespace-pre text-ctp-subtext0"
        >{{ diagrams[cardLang] }}</pre>
        <TopoDiagram
          v-else
          ref="diagRef"
          class="h-full"
          :key="`${cardFullscreen ? 'fs' : 'inline'}-${replayTick}`"
          :code="diagrams[cardLang]"
          :engine="cardLang"
          :theme="themeMode"
          :theme-variables="themeVars"
          security-level="loose"
          :zoom-fit-min-scale="0.3"
          :zoom-max-scale="24"
          :auto-play="animating"
          @ready="onDiagramReady"
          @node-click="onNodeClick"
        />
        <button
          v-if="cardFullscreen"
          class="btn btn-ghost btn-xs absolute top-2 right-2 z-10"
          :title="t('assetMgmt.graph.closeFullscreen')"
          @click="closeCardFullscreen"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>

      <!-- 选中节点详情：网页全局浮窗(可拖动/可拉伸/可最小化；最小化图标停靠图谱区右下) -->
      <div
        v-if="sel && !cardMin"
        ref="cardEl"
        class="card-root fixed z-40 flex flex-col max-w-[calc(100vw-1rem)] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
        :class="[
          !cardPos ? 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2' : '',
          cardDragging ? 'cursor-grabbing' : '',
          cardResizing ? 'select-none' : '',
        ]"
        :style="{
          width: cardSize.w + 'px',
          // 卡片非代码文字随全局 UI 字号等比(--card-scale = 全局字号/16，与 --ui-scale 同步缩放)，
          // 基准字号在 scoped .card-root 覆盖中已整体放大两号；代码(pre/code)仍用 codeFontSize。
          '--card-scale': String((Number(settings.fontSize) || 16) / 16),
          ...(cardSize.h ? { height: cardSize.h + 'px' } : {}),
          ...(cardPos ? { left: cardPos.x + 'px', top: cardPos.y + 'px' } : {}),
        }"
        :title="t('assetMgmt.graph.cardResetPos')"
      >
        <div
          class="flex items-center gap-1.5 cursor-move shrink-0 px-3 pt-2.5 pb-1"
          @mousedown="beginCardDrag"
          @dblclick="cardResetPos"
        >
          <span class="text-[11px] font-semibold text-ctp-text truncate">{{ sel.name }}</span>
          <span
            class="chip !text-[9px] shrink-0"
            :class="{
              'bg-ctp-mauve/15 text-ctp-mauve': sel.kind === 'entity',
              'bg-ctp-yellow/15 text-ctp-yellow': sel.kind === 'contract',
              'bg-ctp-sky/15 text-ctp-sky': sel.kind === 'state',
              'bg-ctp-peach/15 text-ctp-peach': sel.kind === 'rule',
              'bg-ctp-blue/15 text-ctp-blue': sel.kind === 'process',
              'bg-ctp-green/15 text-ctp-green': sel.kind === 'decision',
            }"
           >{{ t(`assetMgmt.kind.${sel.kind}`) }}</span>
           <span
             v-if="isDiffNode(sel.id)"
             class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
             :title="t('assetMgmt.diff.hint')"
           >{{ t('assetMgmt.diff.modified') }}</span>
           <span class="flex-1" />
           <button
             class="btn btn-ghost !py-0 !px-1.5 !text-[9px] shrink-0"
             :class="fullCode ? '!text-ctp-sky' : ''"
            :disabled="fullCodeLoading"
            :title="t('assetMgmt.graph.fullCode')"
            @click="toggleFullCode"
          >
            <DocumentTextIcon
              class="w-3 h-3"
              :class="fullCodeLoading ? 'animate-pulse' : ''"
            />{{ t('assetMgmt.graph.fullCode') }}
          </button>
          <button
            class="btn btn-ghost !py-0 !px-1.5 !text-[9px] shrink-0"
            :class="lineNotesCount || fullCodeNotesLoading || lineNotesLoading ? '!text-ctp-mauve' : ''"
            :disabled="lineNotesLoading || fullCodeNotesLoading"
            :title="lineNotesError ? t('assetMgmt.graph.lineNotesFailed') : t('assetMgmt.graph.lineNotes')"
            @click="loadLineNotes()"
          >
            <SparklesIcon
              class="w-3 h-3"
              :class="(lineNotesLoading || fullCodeNotesLoading) ? 'animate-spin' : ''"
            />{{ lineNotesCount
              ? `${t('assetMgmt.graph.lineNotes')} · ${lineNotesCount}`
              : t('assetMgmt.graph.lineNotes') }}
          </button>
          <template v-if="lineNotesCount">
            <span
              v-if="lineNotesFromCache"
              class="chip !text-[8px] bg-ctp-surface0 text-ctp-subtext0 shrink-0"
              :title="t('assetMgmt.graph.lineNotesCachedTip')"
            >{{ t('assetMgmt.graph.lineNotesCached') }}</span>
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0"
              :disabled="lineNotesLoading || fullCodeNotesLoading"
              :title="t('assetMgmt.graph.lineNotesForce')"
              @click="regenerateLineNotes"
            >
              <ArrowPathIcon
                class="w-3 h-3"
                :class="(lineNotesLoading || fullCodeNotesLoading) ? 'animate-spin' : ''"
              />
            </button>
          </template>
          <button
            class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
            :title="t('assetMgmt.graph.minimize')"
            @click="setCardMin(true)"
          >
            <MinusIcon class="w-3.5 h-3.5" />
          </button>
        </div>
        <!-- 文件 tab(常驻)：固定标题栏下方，不随代码滚动；访问历史 + 关系资产文件 -->
        <div v-if="fileTabs.length" class="shrink-0 flex items-center gap-1 flex-wrap px-3 pt-0.5 pb-1">
          <button
            v-for="f in fileTabs"
            :key="f.kind + f.file"
            class="chip !text-[9px] font-mono max-w-[45%] truncate cursor-pointer"
            :class="activeFileTab === f.file
              ? (f.kind === 'rel' ? '!bg-ctp-peach/15 !text-ctp-peach' : '!bg-ctp-mauve/15 !text-ctp-mauve')
              : 'bg-ctp-surface0 !text-ctp-subtext0 hover:!text-ctp-text'"
            :title="f.kind === 'rel' && f.rel ? `${f.rel.targetName} · ${f.rel.relText} · ${f.file}` : `${f.assetName} · ${f.file}`"
            @click="tabClick(f)"
          >{{ f.label }}</button>
        </div>
        <div class="flex-1 min-h-0 overflow-auto px-3 pb-3 pt-1 space-y-2">
        <!-- 完整代码视图：单文件全文 + 文件内多资产锚点高亮(点击切资产，同文件不刷新卡) -->
        <template v-if="fullCode">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 flex items-center gap-1 truncate">
            {{ t('assetMgmt.graph.fullCode') }}
            <span
              class="text-ctp-overlay1 font-normal truncate"
              :title="fullCode.file"
            >{{ shortPath(fullCode.file) }}</span>
            <span class="flex-1" />
            <span
              v-if="fullCodeOwners.size"
              class="text-[9px] text-ctp-sky shrink-0"
              :title="t('assetMgmt.graph.fullCodeOwnersHint')"
            >{{ t('assetMgmt.graph.fullCodeOwners', { n: fullCodeOwners.size }) }}</span>
          </div>
          <pre
            v-if="fullCode.lines?.length"
            ref="fullCodePreRef"
            class="m-0 overflow-auto rounded border border-ctp-surface1 bg-ctp-surface0 p-2 font-mono leading-relaxed"
            :style="{ fontSize: codeFontSize + 'px' }"
          ><template
            v-for="l in fullCode.lines"
            :key="l.line"
><div
  :data-full-line="l.line"
  class="flex flex-wrap items-baseline gap-1.5"
  :class="fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId ? 'cursor-pointer' : ''"
  :title="fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId
    ? `${ownerName(fullCodeOwners.get(l.line)!)} · ${t('assetMgmt.graph.fullCodeClickHint')}` : ''"
  @click="onFullCodeLineClick(l.line)"
><span class="select-none text-ctp-overlay0 shrink-0">{{ l.line }}</span> <span
              :class="fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId
                ? ['text-ctp-sky', 'bg-ctp-sky/15', 'font-semibold rounded-sm px-0.5', 'hover:bg-ctp-sky/25']
                : fullCodeSelfLines.has(l.line)
                  ? [kindTextClass, kindBgClass, 'font-semibold rounded-sm px-0.5', flashing ? 'anchor-flash' : '']
                  : 'text-ctp-subtext0'"
            >{{ l.code }}</span><span
              v-if="fullCodeNotes[l.line]"
              class="ml-auto shrink-0 max-w-[48%] truncate text-right italic"
              :class="fullCodeSelfLines.has(l.line) ? kindTextClass : 'text-ctp-overlay1'"
              :title="fullCodeNotes[l.line]"
            >{{ fullCodeNotes[l.line] }}</span></div></template></pre>
          <div
            v-else
            class="text-[10px] text-ctp-overlay0"
          >
            {{ t('common.loading') }}
          </div>
          <div
            v-if="fullCodeError"
            class="text-[9px] text-ctp-peach pt-0.5"
          >
            {{ t('assetMgmt.graph.lineNotesFailed') }}
          </div>
        </template>
        <!-- 分段视图：简介 → 结构化 detail → 代码段(手风琴+复制) → 锚点导航 → 关系 -->
        <template v-else>
        <!-- 节点简介(代码级、grounded；生成中回退原 desc) -->
        <p class="text-[10px] leading-relaxed text-ctp-subtext0 whitespace-pre-wrap">
          <SparklesIcon
            v-if="nodeBriefText || nodeBriefLoading"
            class="w-3 h-3 inline text-ctp-mauve mr-0.5 -mt-0.5"
          />
          {{ (nodeBriefLoading && !nodeBriefText) ? (selDetail?.desc || sel.desc) : (nodeBriefText || selDetail?.desc || sel.desc) }}
          <button
            v-if="nodeBriefText"
            class="inline text-ctp-overlay0 hover:text-ctp-text align-middle"
            :title="t('assetMgmt.graph.briefForce')"
            :disabled="nodeBriefLoading"
            @click="regenerateNodeBrief"
          >
            <ArrowPathIcon
              class="w-2.5 h-2.5 inline"
              :class="nodeBriefLoading ? 'animate-spin' : ''"
            />
          </button>
        </p>
        <!-- C1 结构化 detail(按类别：字段/步骤/状态) -->
        <div v-if="detailBlock" class="space-y-0.5">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5">{{ detailBlock.title }}</div>
          <div
            v-for="(row, ri) in detailBlock.rows"
            :key="ri"
            class="pl-2 font-mono text-[10px] text-ctp-subtext0 truncate"
            :title="row.title"
          >{{ row.text }}</div>
        </div>
        <!-- 关系延伸 tab 内容：相关资产锚点代码预览(点击名称跳转选中该资产) -->
        <div v-if="activeRelTab" ref="relTabEl" class="space-y-1">
          <div class="flex items-center gap-1 mb-0.5">
            <span
              class="font-medium text-[10px] text-ctp-peach truncate cursor-pointer hover:underline"
              :title="t('assetMgmt.graph.jumpAnchor')"
              @click="jumpToRelation(activeRelTab)"
            >{{ activeRelTab.targetName }}</span>
            <span class="text-[9px] text-ctp-overlay1 truncate">
              {{ activeRelTab.relText }} · {{ shortPath(activeRelTab.file) }}:L{{ activeRelTab.line }}
            </span>
            <span class="flex-1" />
          </div>
          <pre
            v-if="relTabSegs[activeRelTab.file]?.lines?.length"
            class="m-0 overflow-auto rounded border border-ctp-surface1 bg-ctp-surface0 p-2 font-mono leading-relaxed max-h-52"
            :style="{ fontSize: codeFontSize + 'px' }"
          ><template
            v-for="l in (relTabSegs[activeRelTab.file] as SourceSnippet)!.lines"
            :key="l.line"
  ><div class="flex flex-wrap items-baseline gap-1.5"><span class="select-none text-ctp-overlay0 shrink-0">{{ l.line }}</span> <span
            :data-anchor-line="((relTabSegs[activeRelTab.file] as SourceSnippet)!.highlight ?? []).map(Number).includes(l.line)
              || Number((relTabSegs[activeRelTab.file] as SourceSnippet)!.anchorLine || 0) === l.line ? '1' : null"
            :class="((relTabSegs[activeRelTab.file] as SourceSnippet)!.highlight ?? []).map(Number).includes(l.line)
              || Number((relTabSegs[activeRelTab.file] as SourceSnippet)!.anchorLine || 0) === l.line
              ? [kindTextClass, kindBgClass, 'font-semibold rounded-sm px-0.5', flashing ? 'anchor-flash' : '']
              : 'text-ctp-subtext0'"
          >{{ l.code }}</span></div></template></pre>
          <div v-else class="text-[10px] text-ctp-overlay0">{{ t('common.loading') }}</div>
        </div>
        <!-- 多代码段(主体；>1 段时手风琴折叠，默认仅首段展开；跨文件时仅显示当前 tab 文件) -->
        <div
          v-for="{ seg, si } in activeTabSegs"
          :key="`${seg.file}:${seg.startLine}:${si}`"
          :ref="(el) => { segEls[si] = el as HTMLElement | null }"
          class="space-y-1"
        >
          <!-- 段头：可点击折叠(>1 段) + 复制位置(C2) -->
          <div
            class="flex items-center gap-1 mb-0.5"
            :class="segments.length > 1 ? 'cursor-pointer select-none' : ''"
            :title="segments.length > 1 ? t('assetMgmt.graph.jumpAnchor') : ''"
            @click="segments.length > 1 && toggleSeg(si)"
          >
            <ChevronDownIcon
              v-if="segments.length > 1"
              class="w-3 h-3 shrink-0 transition-transform"
              :class="collapsedSegs.has(si) ? '-rotate-90' : ''"
            />
            <span class="font-medium text-[10px] text-ctp-mauve truncate" :title="`${seg.file}:${seg.startLine}${seg.symbol ? ' · ' + seg.symbol : ''}`">
              {{ t('assetMgmt.graph.sourceCode') }}
              <span class="text-ctp-overlay1 font-normal">{{ shortPath(seg.file) }}:L{{ seg.startLine }}<span v-if="seg.symbol"> · {{ seg.symbol }}</span></span>
            </span>
            <span class="flex-1" />
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0"
              :title="t('assetMgmt.graph.copyLoc')"
              :disabled="!seg.snippet"
              @click.stop="copySegLoc(seg, si)"
            >
              <CheckIcon v-if="copiedSeg === si" class="w-3 h-3 text-ctp-green" />
              <ClipboardIcon v-else class="w-3 h-3" />
            </button>
          </div>
          <!-- 代码体(折叠时隐藏) -->
          <template v-if="!collapsedSegs.has(si)">
          <pre
            v-if="seg.snippet?.lines?.length"
            class="m-0 overflow-auto rounded border border-ctp-surface1 bg-ctp-surface0 p-2 font-mono leading-relaxed"
            :class="cardSize.h ? '' : 'max-h-52'"
            :style="{ fontSize: codeFontSize + 'px' }"
          ><template
            v-for="l in seg.snippet.lines"
            :key="l.line"
  ><div class="flex flex-wrap items-baseline gap-1.5"><span class="select-none text-ctp-overlay0 shrink-0">{{ l.line }}</span> <span
              :data-anchor-line="segHighlighted(seg, l.line) ? '1' : null"
              :class="segHighlighted(seg, l.line)
                ? [kindTextClass, kindBgClass, 'font-semibold rounded-sm px-0.5', flashing ? 'anchor-flash' : '']
                : 'text-ctp-subtext0'"
            >{{ l.code }}</span><span
              v-if="lineNotesMaps[si]?.[l.line]"
              class="ml-auto shrink-0 max-w-[48%] truncate text-right italic"
              :class="segHighlighted(seg, l.line) ? kindTextClass : 'text-ctp-overlay1'"
              :title="lineNotesMaps[si]?.[l.line]"
            >{{ lineNotesMaps[si]?.[l.line] }}</span></div></template></pre>
          <div
            v-else-if="seg.loading"
            class="text-[10px] text-ctp-overlay0"
          >
            {{ t('common.loading') }}
          </div>
          </template>
        </div>
        <!-- 锚点导航(>1 段时快速定位)；跨文件锚点以桃色+标注区分 -->
        <div v-if="selAnchors.length && segments.length > 1">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 pt-1">
            {{ t('assetMgmt.graph.anchor') }}
          </div>
          <div
            v-for="(r, ri) in selAnchors.slice(0, MAX_SEGMENTS)"
            :key="ri"
            class="pl-2 font-mono text-[10px] hover:text-ctp-text cursor-pointer transition-colors truncate flex items-center gap-1"
            :class="r.file !== selAnchors[0]?.file ? 'text-ctp-peach' : 'text-ctp-overlay0'"
            :title="`${r.file} · ${r.file !== selAnchors[0]?.file
              ? `${t('assetMgmt.graph.crossFileAnchor')} · ${t('assetMgmt.graph.jumpAnchor')}`
              : t('assetMgmt.graph.jumpAnchor')}`"
            @click="jumpToSegment(ri)"
          >
            {{ shortPath(r.file) }}:L{{ r.startLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span>
            <span
              v-if="r.file !== selAnchors[0]?.file"
              class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
            >{{ t('assetMgmt.graph.crossFile') }}</span>
          </div>
        </div>
        <!-- 关系(证据式描述；点击跳转对方资产) -->
        <div v-if="selRelations.length || edgeNotesLoading">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 flex items-center gap-1">
            {{ t('assetMgmt.relations') }}
            <ArrowPathIcon
              v-if="edgeNotesLoading"
              class="w-2.5 h-2.5 animate-spin text-ctp-overlay0"
            />
          </div>
          <div
            v-for="r in selRelations"
            :key="r.key"
            class="pl-2 text-[10px] text-ctp-overlay0 hover:text-ctp-text cursor-pointer transition-colors"
            :title="t('assetMgmt.graph.jumpAnchor')"
            @click="jumpToRelation(r)"
          >
            <span class="text-ctp-subtext0">{{ r.targetName }}</span>
            <span class="text-ctp-overlay1"> · {{ r.desc || r.type }}</span>
          </div>
          <!-- 入边(被谁引用) -->
          <template v-if="inEdges.length">
            <div class="text-[9px] text-ctp-overlay1 pt-1">
              {{ t('assetMgmt.graph.inEdges') }}
            </div>
            <div
              v-for="r in inEdges"
              :key="r.fromId"
              class="pl-2 text-[10px] text-ctp-overlay0 hover:text-ctp-text cursor-pointer transition-colors"
              :title="r.desc || ''"
              @click="jumpToRelation({ targetId: r.fromId })"
            >
              <span class="text-ctp-subtext0">{{ r.fromName }}</span>
              <span class="text-ctp-overlay1"> · {{ r.desc || r.type || t('assetMgmt.graph.usesMe') }}</span>
            </div>
          </template>
        </div>
        </template>
        <div
          v-if="lineNotesDegraded"
          class="text-[9px] text-ctp-overlay0 pt-0.5"
        >
          {{ t('assetMgmt.graph.lineNotesDegraded') }}
        </div>
        <div
          v-if="lineNotesError"
          class="text-[9px] text-ctp-peach pt-0.5"
        >
          {{ t('assetMgmt.graph.lineNotesFailed') }}
        </div>
        </div>
        <!-- 四边独立拉伸把手(上下左右；hover 显隐提示) -->
        <div class="card-edge card-edge-n" @mousedown="cardStartResize($event, 'n')" @dblclick.stop />
        <div class="card-edge card-edge-s" @mousedown="cardStartResize($event, 's')" @dblclick.stop />
        <div class="card-edge card-edge-w" @mousedown="cardStartResize($event, 'w')" @dblclick.stop />
        <div class="card-edge card-edge-e" @mousedown="cardStartResize($event, 'e')" @dblclick.stop />
      </div>

      <!-- 最小化态：停靠图谱区右下；信息刷新时闪动缩放 ~3s 提示(不自动展开) -->
      <button
        v-if="sel && cardMin"
        class="absolute z-10 right-2 bottom-2 w-9 h-9 rounded-full border shadow-lg flex items-center justify-center transition-transform hover:scale-110"
        :class="[kindChipClass, iconPulse ? 'icon-pulse' : '']"
        :title="`${sel.name} · ${t('assetMgmt.graph.restore')}`"
        @click="setCardMin(false)"
      >
        <InformationCircleIcon class="w-5 h-5" />
      </button>
      <!-- 关系矩阵浮窗：数据实时跟随当前图谱口径(聚焦/拓展/过滤)；点节点头回写选中全联动 -->
      <GraphMatrixWindow
        v-if="matrixOpen"
        :nodes="scopedNodes"
        :edges="scopedEdges"
        :anchors="graph?.anchors ?? []"
        :sel-id="selId"
        @select="onMatrixSelect"
        @close="matrixOpen = false"
      />
      <!-- 资产节点索引浮窗：按索引探索图谱，点击行与图谱/资产卡/锚点全联动 -->
      <AssetIndexWindow
        v-if="indexOpen"
        :nodes="scopedNodes"
        :edges="scopedEdges"
        :anchors="graph?.anchors ?? []"
        :sel-id="selId"
        @select="onMatrixSelect"
        @close="indexOpen = false"
      />
    </div>
  </div>
</template>

<style scoped>
@keyframes anchor-flash-kf {
  0%, 55% { background-color: rgba(250, 179, 135, 0.28); }
  100% { background-color: transparent; }
}
.anchor-flash {
  animation: anchor-flash-kf 1.7s ease-out 1;
  border-radius: 2px;
}
@keyframes icon-pulse-kf {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(250, 179, 135, 0); }
  50% { transform: scale(1.22); box-shadow: 0 0 0 8px rgba(250, 179, 135, 0.28); }
}
.icon-pulse {
  animation: icon-pulse-kf 1s ease-in-out 3;
}
/* 图节点选中态：桃色光晕描边，绑定节点 DOM 切换 */
:deep(.td-node-selected) {
  filter: drop-shadow(0 0 4px rgba(250, 179, 135, 0.95)) drop-shadow(0 0 10px rgba(250, 179, 135, 0.45));
}
:deep(.td-node-selected) path,
:deep(.td-node-selected) rect,
:deep(.td-node-selected) polygon,
:deep(.td-node-selected) circle,
:deep(.td-node-selected) ellipse {
  stroke: #fab387 !important;
  stroke-width: 2px !important;
}
:deep(.td-node-selected) text {
  fill: #fab387 !important;
  font-weight: 600;
}
/* 资产卡四边独立拉伸把手(上下左右)：透明热区，hover 显提示条 */
.card-edge {
  position: absolute;
  z-index: 10;
  transition: background-color 0.15s;
}
.card-edge:hover {
  background-color: rgba(136, 137, 163, 0.35);
}
.card-edge-n,
.card-edge-s {
  left: 0;
  right: 0;
  height: 6px;
  cursor: ns-resize;
}
.card-edge-n { top: 0; }
.card-edge-s { bottom: 0; }
.card-edge-e,
.card-edge-w {
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
}
.card-edge-w { left: 0; }
.card-edge-e { right: 0; }
/* 资产卡：非代码文字在基准上整体放大两号(8→10 / 9→11 / 10→12 / 11→13)，
   并随全局 UI 字号等比(--card-scale = 全局字号/16，与 --ui-scale 同步缩放)；
   代码(pre/code)仍用 codeFontSize，不在此列。特异性高于 global.css 的 --ui-scale 覆盖，卡片内优先生效。 */
.card-root .text-\[8px\],  .card-root .\!text-\[8px\]  { font-size: calc(10px * var(--card-scale, 1)) !important; }
.card-root .text-\[9px\],  .card-root .\!text-\[9px\]  { font-size: calc(11px * var(--card-scale, 1)) !important; }
.card-root .text-\[10px\], .card-root .\!text-\[10px\] { font-size: calc(12px * var(--card-scale, 1)) !important; }
.card-root .text-\[11px\], .card-root .\!text-\[11px\] { font-size: calc(13px * var(--card-scale, 1)) !important; }
</style>
