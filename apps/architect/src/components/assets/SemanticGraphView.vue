<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, XMarkIcon, ArrowsPointingOutIcon, MinusIcon, InformationCircleIcon, SparklesIcon, DocumentTextIcon } from '@heroicons/vue/24/outline'
import TopoDiagram from '@topo/web-core/topoOne/vue/TopoDiagram.vue'
import { makeButton } from '@topo/web-core/topoOne/plugins/ui.ts'
import type { NodeClickEvent } from '@topo/web-core/topoOne/plugins/types.ts'
import { themeVariablesFor } from '@topo/web-core/topoOne/vue/themes.ts'
import { semanticGraphViewDiagrams, semanticViewClickIds, supportedViewsFor, viewUnavailableReasons } from '@/utils/diagram-gen'
import { useArchSettingsStore } from '@/stores/settings-store'
import type { SemanticGraphViewId } from '@/utils/diagram-gen'
import type { SemanticAsset, SemanticAssetLevel, SemanticAssetKind } from '@/types'
import type { SemanticGraphResult, SourceSnippet } from '@/services/semantic-asset-service'
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

const props = defineProps<{ tab: GraphTabDef }>()
const emit = defineEmits<{ close: [id: string] }>()

const level = ref<SemanticAssetLevel | ''>('')
/** 类型(资产类别)过滤：空=全部。 */
const kindFilter = ref<SemanticAssetKind | ''>('')
/** 图类型视图(空=按数据区间自动推荐)。 */
const view = ref<SemanticGraphViewId | ''>('')
const graph = ref<SemanticGraphResult | null>(null)
const loading = ref(false)
const selId = ref('')
const selDetail = ref<SemanticAsset | null>(null)
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

/** 信息卡尺寸(拖右下角拉伸；默认加宽加高，最终尺寸持久化 LS，再次拉伸覆盖)。 */
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
let resizeStart = { x: 0, y: 0, w: cardSizeInit.w, h: cardSizeInit.h }

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
function cardStartResize(e: MouseEvent) {
  if (e.button !== 0) return
  e.preventDefault()
  e.stopPropagation()
  cardResizing = true
  resizeStart = {
    x: e.clientX, y: e.clientY,
    w: cardSize.value.w,
    h: cardSize.value.h ?? (cardEl.value?.offsetHeight ?? 420),
  }
  window.addEventListener('mousemove', cardDrag)
  window.addEventListener('mouseup', cardEndDrag, { once: true })
}
function cardDrag(e: MouseEvent) {
  if (cardResizing) {
    const maxW = Math.min(1100, window.innerWidth - 16)
    const maxH = Math.floor(window.innerHeight * 0.94)
    cardSize.value = {
      w: Math.min(maxW, Math.max(360, resizeStart.w + (e.clientX - resizeStart.x))),
      h: Math.min(maxH, Math.max(240, resizeStart.h + (e.clientY - resizeStart.y))),
    }
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
  return (graph.value?.edges ?? []).filter((e) => ids.has(e.from) && ids.has(e.to))
})

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
  return viewOptions.value[0]?.value ?? 'flow'
})

/** 选中节点(单资产视图的焦点 / 节点点击)。 */
const sel = computed(() => (graph.value?.nodes ?? []).find((n) => n.id === selId.value) ?? null)

const diagrams = computed<Partial<Record<'mermaid' | 'plantuml', string>>>(() => {
  if (!graph.value) return {}
  return semanticGraphViewDiagrams(effectiveView.value, scopedNodes.value, scopedEdges.value)
})

async function load(reset = false) {
  loading.value = true
  try {
    const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
    const focus = props.tab.kind === 'asset' ? props.tab.assetId : undefined
    graph.value = await semanticAssetService.graph(undefined, scope, undefined, { focus, hops: 1 })
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

// 选中资产 → 拉取完整详情（astRefs 唯一来源）。
// 完整代码视图打开时：同文件资产切换保持视图(互斥：不重建资产卡)；跨文件 → 关闭全文并正常重建。
watch(selId, async (id) => {
  selDetail.value = null
  if (!id) return
  try {
    const d = (await semanticAssetService.detail(id)) ?? null
    if (fullCode.value && d) {
      const files = new Set((d.astRefs ?? []).map((r) => r.file))
      if (!files.has(fullCode.value.file)) fullCode.value = null
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

/** 滚动到某段首个锚点行并闪烁强调(最小化时不做，脉冲提示覆盖)。 */
function flashAnchor(segIdx = flashSeg) {
  if (cardMin.value) return
  const el = segEls[segIdx]
  if (!el || !segments.value[segIdx]?.snippet) return
  const first = el.querySelector('[data-anchor-line]')
  if (first) first.scrollIntoView({ block: 'center' })
  flashing.value = false
  void nextTick(() => {
    flashing.value = true
    if (flashTimer) clearTimeout(flashTimer)
    flashTimer = setTimeout(() => { flashing.value = false }, 1700)
  })
}

function onNodeClick(e: NodeClickEvent) {
  let assetId = clickIds.value.get(e.nodeId) ?? ''
  if (!assetId) {
    // 兜底：flow 视图节点文本为「名称 · 资产ID」，取末段。
    const tail = (e.label || '').split('·').pop()?.trim() ?? ''
    if (/^sa-/.test(tail)) assetId = tail
  }
  if (!assetId) return
  flashOnNext = true
  flashSeg = 0
  if (selId.value === assetId) {
    // 同一节点重复点击：源码已在卡内，立即闪烁。
    flashOnNext = false
    void nextTick(() => flashAnchor(0))
    return
  }
  selId.value = assetId
}

// ---- AI 逐行解读(逐段生成；结合术语/规约；手动触发，后端落库缓存) ----
const lineNotesMaps = ref<Record<number, Record<number, string>>>({})
const lineNotesLoading = ref(false)
const lineNotesDegraded = ref(false)
const lineNotesError = ref('')

/** 已解读行数(按钮上展示，让激活状态可见)。 */
const lineNotesCount = computed(() =>
  Object.values(lineNotesMaps.value).reduce((n, m) => n + Object.keys(m).length, 0)
  + Object.keys(fullCodeNotes.value).length)

async function loadLineNotes() {
  if (!sel.value || lineNotesLoading.value) return
  // 完整代码模式 → 解读全文窗口
  if (fullCode.value) {
    await loadFullCodeNotes()
    return
  }
  const targets = segments.value
    .map((seg, i) => ({ seg, i }))
    .filter(({ seg }) => seg.snippet?.lines?.length)
  if (!targets.length) return
  lineNotesLoading.value = true
  lineNotesError.value = ''
  let degraded = false
  for (const { seg, i } of targets) {
    const s = seg.snippet!
    try {
      const r = await semanticAssetService.lineNotes(
        sel.value.id, s.file, s.lines[0].line, s.lines[s.lines.length - 1].line)
      // 键归一为数字(JSON 反序列化后为字符串键)，避免任何运行时键型差异
      const norm: Record<number, string> = {}
      for (const [k, v] of Object.entries(r.notes || {})) norm[Number(k)] = String(v)
      lineNotesMaps.value = { ...lineNotesMaps.value, [i]: norm }
      if (r.error) { lineNotesError.value = r.error; break }
      if (r.degraded) degraded = true
    } catch (err: any) {
      lineNotesError.value = err?.message || 'failed'
      break
    }
  }
  // 有明确 error 时只显示失败提示(可重试)，不再叠加「降级」横幅
  lineNotesDegraded.value = degraded && !lineNotesError.value
  lineNotesLoading.value = false
}

/** 锚点导航：点击锚点 → 滚动到对应代码段并闪烁锚点行。 */
function jumpToSegment(i: number) {
  const el = segEls[i]
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  flashSeg = i
  flashAnchor(i)
}

// 最小化时信息刷新(选中资产变化) → 不自动展开浮窗；停靠图标闪动缩放 ~3s 提示。
const iconPulse = ref(false)
let iconPulseTimer: ReturnType<typeof setTimeout> | null = null
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
watch(selAnchors, async (anchors) => {
  if (fullCode.value) return
  const cap = anchors.slice(0, MAX_SEGMENTS)
  const seq = ++segSeq
  segments.value = cap.map((a) => ({ file: a.file, symbol: a.symbol, startLine: a.startLine, snippet: null, loading: true }))
  lineNotesMaps.value = {}
  lineNotesDegraded.value = false
  lineNotesError.value = ''
  await Promise.all(cap.map(async (a, i) => {
    let sn: SourceSnippet | null = null
    try {
      sn = (await semanticAssetService.sourceSnippet(a.file, a.startLine, a.symbol)) ?? null
    } catch {
      sn = null
    }
    if (seq !== segSeq) return
    const seg = segments.value[i]
    if (seg) { seg.snippet = sn; seg.loading = false }
  }))
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
const FULL_FILE_LIMIT = 2000
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
  const file = selAnchors.value[0]?.file
  if (!file || !sel.value) return
  fullCodeLoading.value = true
  try {
    fullCode.value = (await semanticAssetService.sourceSnippet(file, 1, undefined, FULL_FILE_LIMIT, FULL_FILE_LIMIT, FULL_FILE_LIMIT)) ?? null
    fullCodeNotes.value = {}
  } catch {
    fullCode.value = null
  }
  fullCodeLoading.value = false
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

// ---- 完整代码 AI 逐行解读 ----
async function loadFullCodeNotes() {
  const fc = fullCode.value
  if (!fc?.lines?.length || !sel.value || fullCodeNotesLoading.value) return
  fullCodeNotesLoading.value = true
  fullCodeError.value = ''
  try {
    const r = await semanticAssetService.lineNotes(
      sel.value.id, fc.file, fc.lines[0].line, fc.lines[fc.lines.length - 1].line)
    const norm: Record<number, string> = {}
    for (const [k, v] of Object.entries(r.notes || {})) norm[Number(k)] = String(v)
    fullCodeNotes.value = norm
    if (r.error) fullCodeError.value = r.error
  } catch (err: any) {
    fullCodeError.value = err?.message || 'failed'
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
    <div class="shrink-0 flex items-center gap-1.5 px-1 pt-1 pb-1 border-b border-ctp-surface0 overflow-x-auto">
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
        v-model="view"
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
        class="shrink-0 text-[10px] text-ctp-overlay1 cursor-help"
        :title="hiddenViewHints.join('\n')"
      >ⓘ {{ t('assetMgmt.graph.unavailableHint') }}</span>
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
      <div
        v-if="graph"
        class="flex items-center gap-0.5 shrink-0"
      >
        <button
          v-for="l in diagramLangs"
          :key="l.id"
          class="px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer"
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
        class="fixed z-40 flex flex-col max-w-[calc(100vw-1rem)] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
        :class="[
          !cardPos ? 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2' : '',
          cardDragging ? 'cursor-grabbing' : '',
          cardResizing ? 'select-none' : '',
        ]"
        :style="{
          width: cardSize.w + 'px',
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
            @click="loadLineNotes"
          >
            <SparklesIcon
              class="w-3 h-3"
              :class="(lineNotesLoading || fullCodeNotesLoading) ? 'animate-spin' : ''"
            />{{ lineNotesCount
              ? `${t('assetMgmt.graph.lineNotes')} · ${lineNotesCount}`
              : t('assetMgmt.graph.lineNotes') }}
          </button>
          <button
            class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
            :title="t('assetMgmt.graph.minimize')"
            @click="setCardMin(true)"
          >
            <MinusIcon class="w-3.5 h-3.5" />
          </button>
        </div>
        <div class="flex-1 min-h-0 overflow-auto px-3 pb-3 pt-1 space-y-2">
        <!-- 完整代码视图：单文件全文 + 文件内多资产锚点高亮(点击切资产，同文件不刷新卡) -->
        <template v-if="fullCode">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 flex items-center gap-1 truncate">
            {{ t('assetMgmt.graph.fullCode') }}
            <span class="text-ctp-overlay1 font-normal">{{ fullCode.file }}</span>
            <span class="flex-1" />
            <span
              v-if="fullCodeOwners.size"
              class="text-[9px] text-ctp-sky shrink-0"
              :title="t('assetMgmt.graph.fullCodeOwnersHint')"
            >{{ t('assetMgmt.graph.fullCodeOwners', { n: fullCodeOwners.size }) }}</span>
          </div>
          <pre
            v-if="fullCode.lines?.length"
            class="m-0 overflow-auto rounded border border-ctp-surface1 bg-ctp-surface0 p-2 font-mono leading-relaxed"
            :style="{ fontSize: codeFontSize + 'px' }"
          ><template
            v-for="l in fullCode.lines"
            :key="l.line"
><div
  class="flex flex-wrap items-baseline gap-1.5"
  :class="fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId ? 'cursor-pointer' : ''"
  :title="fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId
    ? `${ownerName(fullCodeOwners.get(l.line)!)} · ${t('assetMgmt.graph.fullCodeClickHint')}` : ''"
  @click="onFullCodeLineClick(l.line)"
><span class="select-none text-ctp-overlay0 shrink-0">{{ l.line }}</span> <span
              :class="fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId
                ? ['text-ctp-sky', 'bg-ctp-sky/15', 'font-semibold rounded-sm px-0.5', 'hover:bg-ctp-sky/25']
                : fullCodeSelfLines.has(l.line)
                  ? [kindTextClass, kindBgClass, 'font-semibold rounded-sm px-0.5']
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
        <!-- 分段视图：锚点导航 + 多代码段 -->
        <template v-else>
        <!-- 锚点导航(可点击 → 滚动到对应代码段，多锚点快速定位)；跨文件锚点以桃色+标注区分 -->
        <div v-if="selAnchors.length">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5">
            {{ t('assetMgmt.graph.anchor') }}
          </div>
          <div
            v-for="(r, ri) in selAnchors.slice(0, MAX_SEGMENTS)"
            :key="ri"
            class="pl-2 font-mono text-[10px] hover:text-ctp-text cursor-pointer transition-colors truncate flex items-center gap-1"
            :class="r.file !== selAnchors[0]?.file ? 'text-ctp-peach' : 'text-ctp-overlay0'"
            :title="r.file !== selAnchors[0]?.file
              ? `${t('assetMgmt.graph.crossFileAnchor')} · ${t('assetMgmt.graph.jumpAnchor')}`
              : t('assetMgmt.graph.jumpAnchor')"
            @click="jumpToSegment(ri)"
          >
            {{ r.file }}:L{{ r.startLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span>
            <span
              v-if="r.file !== selAnchors[0]?.file"
              class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
            >{{ t('assetMgmt.graph.crossFile') }}</span>
          </div>
        </div>
        <!-- 多代码段同时展示(每段=一个锚点的源码窗口；锚点行按类别着色) -->
        <div
          v-for="(seg, si) in segments"
          :key="`${seg.file}:${seg.startLine}:${si}`"
          :ref="(el) => { segEls[si] = el as HTMLElement | null }"
          class="space-y-1"
        >
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 truncate">
            {{ t('assetMgmt.graph.sourceCode') }}
            <span class="text-ctp-overlay1 font-normal">{{ seg.file }}:L{{ seg.startLine }}<span v-if="seg.symbol"> · {{ seg.symbol }}</span></span>
          </div>
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
        <!-- 右下角拉伸把手 -->
        <div
          class="absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize"
          style="background: linear-gradient(135deg, transparent 0 55%, rgba(136, 137, 163, 0.55) 55% 100%);"
          @mousedown="cardStartResize"
          @dblclick.stop
        />
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
</style>
