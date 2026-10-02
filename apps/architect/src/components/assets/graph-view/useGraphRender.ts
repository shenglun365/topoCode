/**
 * 语义图谱 · render 域（MS6-W2 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { KIND_CARD_CLASS } from '@/services/semantic-kind-style'
import { makeButton } from '@topo/graph-kernel/plugins/ui.ts'
import type { NodeClickEvent } from '@topo/graph-kernel/plugins/types.ts'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'
import { semanticViewClickIds, recommendedSemanticView, semanticNodeLabelText, SemanticGraphViewId } from '@/utils/diagram-gen'
import { useArchSettingsStore } from '@/stores/settings-store'

import type { WsDeps } from './graphTypes'
import TopoDiagram from '@topo/graph-kernel/vue/TopoDiagram.vue'
import type { DiffBucket } from './useGraphData'
import { useI18n } from 'vue-i18n'

type CardResizeEdge = 'n' | 's' | 'e' | 'w'


export function useGraphRender(D: WsDeps) {
  const { t } = useI18n()

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
  if (id === D.detail.selId.value) {
    const home = D.detail.selAnchors.value[0]?.file
    if (home && D.code.activeFileTab.value !== home) D.code.activeFileTab.value = home
    void nextTick(() => D.code.flashAnchor(0))
    return
  }
  flashOnNext = true
  D.code.flashSeg = 0
  D.detail.selId.value = id
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
/** 旧「逐批加载/重播」动画机制已删除(2026-09-29 裁决：未完成的验证性效果，
 *  架构感知图谱直接呈现最终完成图；帧间过渡由演化时间轴的补间承担)。 */
const diagRef = ref<InstanceType<typeof TopoDiagram> | null>(null)
function onDiagramReady() {
  void nextTick(() => { applyPlantumlNodeAddressing(); applySelectedNodeStyle(); applyNodeTooltips(); applyDiffNodeStyles() })
}
/** 节点是否已在可视区域内：节点屏幕 bbox 外扩 margin 逆映射到根用户空间后
 *  完全落在 svg 元素可视范围内(对 zoom-pan 的 transform/viewBox 实现均成立)。
 *  在视口内则跳过居中，避免点选时图谱频繁跳动(用户反馈)。 */
function nodeVisibleInViewport(svg: SVGSVGElement, el: SVGGElement): boolean {
  try {
    const sctm = svg.getScreenCTM()
    const svgRect = svg.getBoundingClientRect()
    if (!sctm || !svgRect.width || !svgRect.height) return false
    const inv = sctm.inverse()
    const p1 = new DOMPoint(svgRect.left, svgRect.top).matrixTransform(inv)
    const p2 = new DOMPoint(svgRect.right, svgRect.bottom).matrixTransform(inv)
    const vx = Math.min(p1.x, p2.x)
    const vy = Math.min(p1.y, p2.y)
    const vw = Math.abs(p2.x - p1.x)
    const vh = Math.abs(p2.y - p1.y)
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return false
    const a = new DOMPoint(r.left, r.top).matrixTransform(inv)
    const b = new DOMPoint(r.right, r.bottom).matrixTransform(inv)
    const M = 24 // 外扩余量：贴边节点也算完整可见
    const nx = Math.min(a.x, b.x) - M
    const ny = Math.min(a.y, b.y) - M
    const nw = Math.abs(b.x - a.x) + 2 * M
    const nh = Math.abs(b.y - a.y) + 2 * M
    return nx >= vx && ny >= vy && nx + nw <= vx + vw && ny + nh <= vy + vh
  } catch {
    return false
  }
}
/** 联动选中 → 节点居中：反查 clickIds 找 svg 节点元素，bbox 中心交 zoom-pan centerOn。
 *  节点已在可视区域内时不平移(避免频繁跳动)；仅视口外节点才居中。 */
function centerSelectedNode() {
  void nextTick(() => {
    const svg = diagRef.value?.getSvg() as SVGSVGElement | null | undefined
    const cmap = clickIds.value
    if (!svg || !D.detail.selId.value || !cmap.size) return
    const rev = new Map<string, string>()
    cmap.forEach((aid, key) => { if (!rev.has(aid)) rev.set(aid, key) })
    const key = rev.get(D.detail.selId.value)
    if (!key) return
    let el: SVGGElement | null = null
    for (const g of Array.from(svg.querySelectorAll<SVGGElement>('g.node'))) {
      const mid = g.id.match(/flowchart-(.+?)-\d+$/)?.[1] ?? g.id
      const txt = (g.textContent ?? '').trim()
      if (mid === key || txt === key) { el = g; break }
    }
    if (!el) return
    try {
      if (nodeVisibleInViewport(svg, el)) return
      // getBBox 是元素局部坐标系(祖先 transform 会偏移)；用屏幕 rect + getScreenCTM 逆映射回根 viewBox 空间
      const r = el.getBoundingClientRect()
      const sctm = svg.getScreenCTM()
      if (!sctm || !r.width) return
      const c = new DOMPoint(r.left + r.width / 2, r.top + r.height / 2).matrixTransform(sctm.inverse())
      diagRef.value?.centerOn(c.x, c.y)
    } catch { /* 未渲染时可能抛错，忽略 */ }
  })
}
watch(D.detail.selId, () => centerSelectedNode())

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
const KIND_CHIP: Record<string, string> = KIND_CARD_CLASS
/** 锚点行底色(比纯文字色更醒目)。 */
const KIND_BG: Record<string, string> = {
  entity: 'bg-ctp-mauve/15', contract: 'bg-ctp-yellow/15', state: 'bg-ctp-sky/15',
  rule: 'bg-ctp-peach/15', process: 'bg-ctp-blue/15', decision: 'bg-ctp-green/15',
}
const kindTextClass = computed(() => KIND_TEXT[D.detail.sel.value?.kind ?? ''] ?? 'text-ctp-yellow')
const kindBgClass = computed(() => KIND_BG[D.detail.sel.value?.kind ?? ''] ?? 'bg-ctp-yellow/15')
const kindChipClass = computed(() => KIND_CHIP[D.detail.sel.value?.kind ?? ''] ?? 'bg-ctp-surface0 text-ctp-subtext0 border-ctp-surface1')

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

const clickIds = computed(() => {
  const m = semanticViewClickIds(D.data.effectiveView.value, D.data.scopedNodes.value)
  // 合成节点(步骤/分支/子状态)映射合并：id 键(mermaid 寻址) + 文本键(plantuml 兜底)。
  // 先到先得——资产主键优先(clickMap 不覆盖)，合成节点让点击/选中全节点可寻址。
  for (const [k, ent] of (D.detail.viewClickMap?.value ?? new Map())) {
    if (!m.has(k)) m.set(k, ent.assetId)
  }
  return m
})
let flashOnNext = false
const flashing = ref(false)
let flashTimer: ReturnType<typeof setTimeout> | null = null

/** 闪烁脉冲(分段/全文共用)：一个脉冲周期内高亮行加 anchor-flash 类。 */
function triggerFlash() {
  flashing.value = false
  void nextTick(() => {
    flashing.value = true
    if (flashTimer) clearTimeout(flashTimer)
    flashTimer = setTimeout(() => { flashing.value = false }, 1700)
  })
}

function onNodeClick(e: NodeClickEvent) {
  // ① 稳定 id(nodeId)；② 文本兜底/别名(label 反查)；③ flow 文本「名称 · 资产ID」尾段
  let assetId = clickIds.value.get(e.nodeId) ?? clickIds.value.get(e.label ?? '') ?? ''
  if (!assetId) {
    const tail = (e.label || '').split('·').pop()?.trim() ?? ''
    if (/^sa-/.test(tail)) assetId = tail
  }
  // 合成节点行级定位(档2)：决策分支携带 branches[].line → 代码段就绪后滚到该行
  const clickEnt = D.detail.viewClickMap?.value?.get(e.nodeId) ?? D.detail.viewClickMap?.value?.get(e.label ?? '')
  if (clickEnt) {
    assetId = clickEnt.assetId
    D.detail.focusLine.value = clickEnt.line || 0
  } else {
    D.detail.focusLine.value = 0
  }
  if (!assetId && e.nodeId.startsWith('txt:')) {
    // 点中文本未映射(如 UML 构造型 «process»、ER 字段行) → 半径 80px 内就近搜索可映射文本
    assetId = nearestMappedAsset(e) ?? ''
  }
  if (!assetId) return
  flashOnNext = true
  D.code.flashSeg = 0
  if (D.detail.selId.value === assetId) {
    // 同一节点重复点击：回到其主锚点文件 tab，立即闪烁。
    const home = D.detail.selAnchors.value[0]?.file
    if (home && D.code.activeFileTab.value !== home) D.code.activeFileTab.value = home
    flashOnNext = false
    void nextTick(() => D.code.flashAnchor(0))
    return
  }
  D.detail.selId.value = assetId
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
  const targetId = D.detail.selId.value
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
    const name = D.detail.sel.value?.name ?? ''
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

/** 对比变化节点视觉(统一浅橘黄底+右上信号点)：
 *  变更/新增/移除统一「需更新」浅橘黄；弱关联(符号段未变)更浅一档；
 *  信号点=节点包含的具体代码变化——绿点(含新增行)/红点(含删除行)/双点(有增有删)。
 *  形状内联样式兜底(setProperty important，免疫 mermaid 主题样式优先级)。
 *  寻址与选中态/tooltip 同款：mermaid id 主口径 + plantuml 文本兜底(标签→<text>→爬升到含形状组)。 */
const DIFF_FILL: Record<DiffBucket, string> = {
  changed: 'rgba(249, 226, 175, 0.30)',   // 浅橘黄：变更(符号段有变化)
  weak: 'rgba(249, 226, 175, 0.14)',      // 更浅一档：弱关联(段未变,可能受影响)
  new: 'rgba(249, 226, 175, 0.30)',       // 统一浅橘黄：新增信号由绿点表达
  removed: 'rgba(249, 226, 175, 0.30)',   // 统一浅橘黄：移除信号由红点表达
}
const DIFF_STROKE: Record<DiffBucket, string> = {
  changed: 'rgba(249, 226, 175, 0.8)',
  weak: 'rgba(249, 226, 175, 0.4)',
  new: 'rgba(249, 226, 175, 0.8)',
  removed: 'rgba(249, 226, 175, 0.8)',
}
// 信号点走全局 ctp 变量：随 data-theme 联动(浅色主题=饱和绿/红)，与 UI 色调恒一致
const SIGNAL_GREEN = 'rgb(var(--ctp-green))'
const SIGNAL_RED = 'rgb(var(--ctp-red))'
function applyDiffNodeStyles() {
  const host: HTMLElement | null = diagRef.value?.containerRef ?? null
  const svg = host?.querySelector('svg')
  if (!svg) return
  svg.querySelectorAll('[class*="td-node-diff"]').forEach((el) =>
    el.classList.remove('td-node-diff-changed', 'td-node-diff-weak', 'td-node-diff-new', 'td-node-diff-removed'))
  svg.querySelectorAll('.td-node-signal').forEach((el) => el.remove())
  if (!D.data.diffKindById.value.size) return
  const rootPrefix = svg.id ? `${svg.id}-` : ''
  // 桶样式+信号点落组：统一浅橘黄底(weak 更浅) + 左上内侧纯色信号点(绿=含新增/红=含删除)。
  const applyNodeSignal = (el: Element, bucket: DiffBucket,
                           sigIn?: { hasAdded: boolean; hasDeleted: boolean }): void => {
    // weak(符号段未变,可能受影响)不画信号点——不确定的关联画增删点会误导为确有变化
    const sig = bucket === 'weak' ? undefined : sigIn
    el.classList.add(`td-node-diff-${bucket}`)
    // 内联样式兜底：mermaid 主题样式(SVG 内 <style> 带 id 选择器)特异性高于类规则，
    // 类规则虽有 !important 但部分引擎渲染路径会被内联呈现覆盖——双保险。
    for (const shape of el.querySelectorAll<SVGElement>('rect, polygon, ellipse, circle')) {
      shape.style.setProperty('fill', DIFF_FILL[bucket], 'important')
      shape.style.setProperty('stroke', DIFF_STROKE[bucket], 'important')
      shape.style.removeProperty('stroke-dasharray')
    }
    if (!sig || (!sig.hasAdded && !sig.hasDeleted)) return
    el.querySelectorAll('.td-node-signal').forEach((d) => d.remove())   // 幂等
    // 左上信号点：组 bbox 左上区域内缩注入纯色圆点(左/顶留隙；双信号绿左红右横排)
    try {
      const bb = (el as SVGGElement).getBBox()
      const NS = 'http://www.w3.org/2000/svg'
      const mkDot = (cx: number, cy: number, fill: string): SVGCircleElement => {
        const c = document.createElementNS(NS, 'circle')
        c.setAttribute('cx', String(cx))
        c.setAttribute('cy', String(cy))
        c.setAttribute('r', '4')
        c.style.setProperty('fill', fill, 'important')   // 免疫主题 CSS 覆盖(SVG 属性特异性最低)
        c.style.setProperty('stroke', 'none', 'important')   // 描边全免疫(桶类/主题 CSS 均不命中)
        c.style.setProperty('stroke-width', '0', 'important')
        c.setAttribute('class', 'td-node-signal')
        c.setAttribute('pointer-events', 'none')
        return c
      }
      const y = bb.y + 10          // 左上区域内缩：左/顶各留 6 单位间隙(r=4)
      if (sig.hasAdded && sig.hasDeleted) {
        el.appendChild(mkDot(bb.x + 10, y, SIGNAL_GREEN))
        el.appendChild(mkDot(bb.x + 18, y, SIGNAL_RED))
      } else if (sig.hasAdded) {
        el.appendChild(mkDot(bb.x + 10, y, SIGNAL_GREEN))
      } else {
        el.appendChild(mkDot(bb.x + 10, y, SIGNAL_RED))
      }
    } catch { /* bbox 不可得时静默跳过信号点 */ }
  }
  // ① mermaid id 主口径(plantuml SVG 无此类 id，恒不命中)
  const styled = new Set<string>()
  const signalOf = (aid: string) => D.data.diffSignalsById?.value?.get(aid)
  for (const [nid, aid] of clickIds.value) {
    if (styled.has(aid)) continue          // clickIds 多键(名称变体)可映同一资产，防重复
    const bucket = D.data.diffKindById.value.get(aid)
    if (!bucket) continue
    for (const el of svg.querySelectorAll('[id], [data-entity-uid]')) {
      if (resolveNodeIdFromEl(el, rootPrefix) !== nid) continue
      applyNodeSignal(el, bucket, signalOf(aid))
      styled.add(aid)
      break
    }
  }
  // ② plantuml 文本兜底：渲染文本口径(name·id/名称截断/净化id)都登记在 clickIds 的 label 键
  const pending = new Map<string, DiffBucket>()
  for (const [, aid] of clickIds.value) {
    if (styled.has(aid) || pending.has(aid)) continue
    const bucket = D.data.diffKindById.value.get(aid)
    if (bucket) pending.set(aid, bucket)
  }
  if (!pending.size) return
  const labelBucket = new Map<string, { bucket: DiffBucket; aid: string }>()
  for (const [label, aid] of clickIds.value) {
    const bucket = pending.get(aid)
    if (!label || !bucket || labelBucket.has(label)) continue
    labelBucket.set(label, { bucket, aid })
  }
  for (const n of D.data.scopedNodes.value) {   // 名称截断口径(与 tooltip ② 同款)
    const bucket = pending.get(n.id)
    if (!bucket) continue
    for (const v of [n.name, ...[18, 26, 30, 40].map((m) => semanticNodeLabelText(n.name, m))]) {
      if (!labelBucket.has(v)) labelBucket.set(v, { bucket, aid: n.id })
    }
  }
  const seenGroups = new Set<Element>()
  for (const t of svg.querySelectorAll('text')) {
    const txt = (t.textContent || '').trim()
    if (!txt) continue
    let hit = labelBucket.get(txt)
    if (!hit) {   // plantuml flow 标签内嵌「· 资产ID」
      for (const [aid, b] of pending) {
        if (txt.includes(aid)) { hit = { bucket: b, aid }; break }
      }
    }
    const bucket = hit?.bucket
    if (!bucket) continue
    // 爬升到含形状的最近组(plantuml 文本与形状可能不同层)，样式落在节点整体上
    let el: Element | null = t
    while (el && el !== svg) {
      if (el.querySelector('rect, polygon, ellipse, circle')) break
      el = el.parentElement
    }
    const group = (el && el !== svg ? el : (t.closest('g') ?? t.parentElement)) as Element | null
    if (group && !seenGroups.has(group)) {
      seenGroups.add(group)
      applyNodeSignal(group, bucket, hit ? signalOf(hit.aid) : undefined)
    }
  }
}
/** plantuml 节点寻址注入：CLI 渲染的 SVG 无任何 id/class/data-*(实测)——kernel
 *  resolvePlantuml 主路径恒空，点击全靠"最近文本"兜底(点框边缘易误中邻节点)。
 *  渲染后按 clickIds 文本口径(safeSemId/显示名/「名称 · ID」截断变体)匹配 <text>，
 *  爬升含形状组注入 data-entity-uid → 节点框任意位置可点(kernel 主路径直命中)。
 *  幂等：注入前清除既有标记。mermaid 引擎(有 id 寻址)不处理。 */
function applyPlantumlNodeAddressing() {
  if (cardLang.value !== 'plantuml') return
  const host: HTMLElement | null = diagRef.value?.containerRef ?? null
  const svg = host?.querySelector('svg')
  if (!svg) return
  svg.querySelectorAll('g[data-entity-uid]').forEach((g) => {
    g.removeAttribute('data-entity-uid')
    g.removeAttribute('data-qualified-name')
  })
  // 文本 → 资产 id：clickIds 各视图口径 + 名称截断变体(与着色文本兜底同源) + 「· sa-x」尾段
  const byText = new Map<string, string>()
  for (const [k, aid] of clickIds.value) {
    if (!/^n\d+$/.test(k)) byText.set(k, aid)
  }
  for (const [k, ent] of (D.detail.viewClickMap?.value ?? new Map())) {
    if (!byText.has(k)) byText.set(k, ent.assetId)   // 合成节点文本(步骤/分支)注入寻址
  }
  for (const n of D.data.scopedNodes.value) {
    for (const v of [n.name, ...[18, 26, 30, 40].map((m) => semanticNodeLabelText(n.name, m))]) {
      if (!byText.has(v)) byText.set(v, n.id)
    }
  }
  if (!byText.size) return
  for (const t of svg.querySelectorAll('text')) {
    const txt = (t.textContent || '').trim()
    if (!txt) continue
    let aid = byText.get(txt)
    if (!aid) {   // 「名称 · 资产ID」尾段兜底(component 口径截断后 ID 仍完整)
      const tail = txt.split('·').pop()?.trim() ?? ''
      if (/^sa-[A-Za-z0-9_-]+$/.test(tail)) aid = tail
    }
    if (!aid) continue
    let el: Element | null = t
    while (el && el !== svg) {
      if (el.querySelector('rect, polygon, ellipse, circle')) break
      el = el.parentElement
    }
    const g = (el && el !== svg ? el : (t.closest('g') ?? t.parentElement)) as Element | null
    if (g && !g.hasAttribute('data-entity-uid')) {
      g.setAttribute('data-entity-uid', aid)
      g.setAttribute('data-qualified-name', txt)
    }
  }
}
watch(D.data.diffKindById, () => void nextTick(applyDiffNodeStyles))

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
  const anchors = (D.data.graph.value?.anchors ?? []).filter((a) => a.assetId === n.id)
  if (anchors.length) {
    const a = anchors[0]
    const more = anchors.length > 1 ? ` (+${anchors.length - 1})` : ''
    lines.push(`${t('assetMgmt.graph.anchor')}: ${D.code.shortPath(a.file)}:L${a.line}${a.symbol ? ' · ' + a.symbol : ''}${more}`)
  }
  const out = (D.data.scopedEdges.value ?? []).filter((e) => e.from === n.id).length
  const inn = (D.data.scopedEdges.value ?? []).filter((e) => e.to === n.id).length
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
      const n = D.data.scopedNodes.value.find((x) => x.id === aid)
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
    const n = D.data.scopedNodes.value.find((x) => x.id === aid)
    if (n) labelToNode.set(label, n)
  }
  for (const n of D.data.scopedNodes.value) {
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
  for (const e of D.data.scopedEdges.value) {
    // 悬停 = 关系描述 + 证据(文件:行/解析方式/置信度/间接中转)
    const ev: string[] = []
    if (e.indirect && e.via) ev.push(t('assetMgmt.graph.indirectVia', { via: e.via }))
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
let iconPulseTimer: ReturnType<typeof setTimeout> | null = null
let lastShownView: SemanticGraphViewId | '' = ''
watch(D.data.effectiveView, (_v, ov) => { lastShownView = ov ?? _v })   // 记录变更前的显示视图(供选中切换时钉住)
watch(D.detail.sel, (n) => {
  void nextTick(applySelectedNodeStyle)   // 选中样式绑定到节点 DOM：新节点加样式、旧节点移除
  if (D.data.view.value || !n) return
  // 选中后的将显示视图(与 D.data.effectiveView 同口径)
  const rec = recommendedSemanticView(n.kind, D.data.effectiveLevel.value || undefined)
  const newEff = D.data.viewOptions.value.some((x) => x.value === rec) ? rec : (D.data.viewOptions.value[0]?.value ?? '')
  const shown = lastShownView
  if (shown && shown !== newEff && D.data.viewOptions.value.some((x) => x.value === shown)) {
    D.data.view.value = shown   // 钉住正在看的视图(新数据下仍支持时)
  }
})

  return {
    CARD_MIN_KEY,
    CARD_SIZE_KEY,
    DIFF_FILL,
    DIFF_STROKE,
    FONT_STEPS,
    KIND_BG,
    KIND_CHIP,
    KIND_TEXT,
    LEGEND_W,
    applyDiffNodeStyles,
    applyNodeTooltips,
    applySelectedNodeStyle,
    beginCardDrag,
    cardDrag,
    cardDragging,
    cardEl,
    cardEndDrag,
    cardFullscreen,
    cardLang,
    cardMin,
    cardPos,
    cardResetPos,
    cardResizing,
    cardSize,
    cardSizeInit,
    cardSrcOpen,
    cardStartPos,
    cardStartResize,
    cardStartX,
    cardStartY,
    centerSelectedNode,
    clickIds,
    closeCardFullscreen,
    codeFontSize,
    diagRef,
    diagramLangs,
    edgeLegendOpen,
    flashOnNext,
    flashTimer,
    flashing,
    iconPulseTimer,
    indexOpen,
    kindBgClass,
    kindChipClass,
    kindTextClass,
    lastShownView,
    legendBtnRef,
    legendPos,
    loadCardSize,
    matrixOpen,
    nearestMappedAsset,
    nodeTooltipText,
    nodeVisibleInViewport,
    onDiagramReady,
    onLegendDocClick,
    onMatrixSelect,
    onNodeClick,
    openCardFullscreen,
    resizeEdge,
    resizeStart,
    resolveNodeIdFromEl,
    saveCardSize,
    selectedNodeEl,
    setCardLang,
    setCardMin,
    settings,
    themeMode,
    themeVars,
    toggleCardSource,
    toggleEdgeLegend,
    toggleIndex,
    toggleMatrix,
    triggerFlash,
  }
}
