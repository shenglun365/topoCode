<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, MinusIcon, ArrowLeftIcon } from '@heroicons/vue/24/outline'
import type { SemanticGraphAnchor, SemanticGraphNode } from '@/services/semantic-asset-service'
import type { SemGraphViewEdge } from '@/utils/diagram-gen'

/** 关系矩阵浮窗(与资产卡同级交互：拖动/右下拉伸/最小化停靠)。
 *  双层钻取：文件×文件密度矩阵 → 文件对的节点级非对称全矩阵(行=from，列=to)。
 *  数据 = 图谱当前口径(scopedNodes/scopedEdges，跟随聚焦/拓展/过滤)；点击节点头回传 select 联动。 */
const props = defineProps<{
  nodes: SemanticGraphNode[]
  edges: SemGraphViewEdge[]
  anchors: SemanticGraphAnchor[]
  selId: string
}>()
const emit = defineEmits<{ select: [id: string]; close: [] }>()

const { t } = useI18n()

// ---- 浮窗骨架：拖动 + 右下拉伸 + 最小化停靠(状态持久化) ----
const MIN_KEY = 'arch.matrixWin.minimized'
const SIZE_KEY = 'arch.matrixWin.size'
const minimized = ref((() => {
  try { return localStorage.getItem(MIN_KEY) === '1' } catch { return false }
})())
function setMinimized(v: boolean) {
  minimized.value = v
  try { localStorage.setItem(MIN_KEY, v ? '1' : '0') } catch { /* ignore */ }
}
function loadSize(): { w: number; h: number | null } {
  try {
    const raw = JSON.parse(localStorage.getItem(SIZE_KEY) || '')
    if (raw && Number(raw.w) >= 420 && Number(raw.h) >= 260) return { w: Number(raw.w), h: Number(raw.h) }
  } catch { /* ignore */ }
  return { w: 880, h: 600 }
}
function saveSize() {
  try { localStorage.setItem(SIZE_KEY, JSON.stringify(size.value)) } catch { /* ignore */ }
}
const size = ref(loadSize())
const pos = ref<{ x: number; y: number } | null>(null)
const el = ref<HTMLElement | null>(null)
let dragging = false
let dragX = 0
let dragY = 0
let dragPos = { x: 0, y: 0 }
function beginDrag(e: MouseEvent) {
  if (e.button !== 0) return
  if (!pos.value) {
    const rect = el.value?.getBoundingClientRect()
    if (!rect) return
    pos.value = { x: rect.left, y: rect.top }
  }
  dragging = true
  dragX = e.clientX
  dragY = e.clientY
  dragPos = { ...pos.value }
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', endDrag, { once: true })
}
function onDrag(e: MouseEvent) {
  if (!dragging) return
  pos.value = {
    x: Math.min(window.innerWidth - 80, Math.max(-(size.value.w - 80), dragPos.x + (e.clientX - dragX))),
    y: Math.min(window.innerHeight - 48, Math.max(0, dragPos.y + (e.clientY - dragY))),
  }
}
function endDrag() {
  dragging = false
  window.removeEventListener('mousemove', onDrag)
}
// 四边拉伸(与资产卡一致)：n/s/e/w 边缘拖拽；n/w 边反向改变宽高并同步移动位置
type MatrixResizeEdge = 'n' | 's' | 'e' | 'w'
let resizeEdge: MatrixResizeEdge = 's'
let resizing = false
let rsStart = { x: 0, y: 0, w: 0, h: 0, px: 0, py: 0 }
function startResize(e: MouseEvent, edge: MatrixResizeEdge) {
  if (e.button !== 0) return
  e.preventDefault()
  e.stopPropagation()
  const rect = el.value?.getBoundingClientRect()
  if (!rect) return
  // 隐式定位(right/top 锚定) → 首次拉伸转为显式坐标
  const px = pos.value?.x ?? rect.left
  const py = pos.value?.y ?? rect.top
  if (!pos.value) pos.value = { x: px, y: py }
  resizeEdge = edge
  resizing = true
  rsStart = { x: e.clientX, y: e.clientY, w: rect.width, h: rect.height, px, py }
  window.addEventListener('mousemove', onResize)
  window.addEventListener('mouseup', endResize, { once: true })
}
function onResize(e: MouseEvent) {
  if (!resizing) return
  const maxW = Math.min(1600, window.innerWidth - 16)
  const maxH = window.innerHeight - 40
  const dx = e.clientX - rsStart.x
  const dy = e.clientY - rsStart.y
  let w = rsStart.w
  let h = rsStart.h
  let px = rsStart.px
  let py = rsStart.py
  if (resizeEdge === 'e') {
    w = Math.min(maxW, Math.max(420, w + dx))
  } else if (resizeEdge === 'w') {
    w = Math.min(maxW, Math.max(420, w - dx))
    px += rsStart.w - w
  }
  if (resizeEdge === 's') {
    h = Math.min(maxH, Math.max(260, h + dy))
  } else if (resizeEdge === 'n') {
    h = Math.min(maxH, Math.max(260, h - dy))
    py += rsStart.h - h
  }
  size.value = { w, h }
  pos.value = { x: px, y: py }
}
function endResize() {
  resizing = false
  saveSize()
  window.removeEventListener('mousemove', onResize)
}
const winStyle = computed(() => ({
  width: `${size.value.w}px`,
  height: size.value.h ? `${size.value.h}px` : undefined,
  left: pos.value ? `${pos.value.x}px` : undefined,
  top: pos.value ? `${pos.value.y}px` : undefined,
  right: pos.value ? undefined : '20px',
  top2: undefined,
  ...(pos.value ? {} : { top: '64px' }),
}))

// ---- 数据准备：节点 → 锚点文件；度数；文件清单 ----
const KIND_TEXT: Record<string, string> = {
  entity: 'text-ctp-mauve', contract: 'text-ctp-yellow', state: 'text-ctp-sky',
  rule: 'text-ctp-peach', process: 'text-ctp-blue', decision: 'text-ctp-green',
}
const KIND_BG: Record<string, string> = {
  entity: 'bg-ctp-mauve/15', contract: 'bg-ctp-yellow/15', state: 'bg-ctp-sky/15',
  rule: 'bg-ctp-peach/15', process: 'bg-ctp-blue/15', decision: 'bg-ctp-green/15',
}
const kindText = (k?: string) => KIND_TEXT[k ?? ''] ?? 'text-ctp-overlay1'

const nodeFile = computed(() => {
  const m = new Map<string, string>()
  for (const n of props.nodes) {
    const a = props.anchors.find((x) => x.assetId === n.id)
    if (a?.file) m.set(n.id, a.file)
  }
  return m
})
const fileOf = (id: string) => nodeFile.value.get(id) ?? ''

const UNANCHORED = '__unanchored__'
const degree = computed(() => {
  const d = new Map<string, number>()
  for (const e of props.edges) {
    d.set(e.from, (d.get(e.from) ?? 0) + 1)
    d.set(e.to, (d.get(e.to) ?? 0) + 1)
  }
  return d
})
const degOf = (id: string) => degree.value.get(id) ?? 0

const files = computed(() => {
  const set = new Set<string>()
  for (const n of props.nodes) set.add(fileOf(n.id) || UNANCHORED)
  return [...set].filter((f) => f !== UNANCHORED || props.nodes.some((n) => !fileOf(n.id))).sort()
})
const fileLabel = (f: string) => (f === UNANCHORED ? t('assetMgmt.matrix.unanchored') : f.split('/').pop() || f)

const nodesByFile = computed(() => {
  const m = new Map<string, SemanticGraphNode[]>()
  for (const n of props.nodes) {
    const f = fileOf(n.id) || UNANCHORED
    if (!m.has(f)) m.set(f, [])
    m.get(f)!.push(n)
  }
  return m
})

// ---- 层 1：文件×文件密度矩阵 ----
interface FileCell { count: number; types: string[] }
const fileCells = computed(() => {
  const m = new Map<string, FileCell>()
  const get = (a: string, b: string) => {
    const k = `${a}|${b}`
    if (!m.has(k)) m.set(k, { count: 0, types: [] })
    return m.get(k)!
  }
  for (const e of props.edges) {
    const fa = fileOf(e.from)
    const fb = fileOf(e.to)
    if (!fa || !fb) continue
    const c = get(fa, fb)
    c.count += 1
    if (e.type && !c.types.includes(e.type)) c.types.push(e.type)
  }
  return m
})
const fileCell = (fa: string, fb: string) => fileCells.value.get(`${fa}|${fb}`)
const maxFileCount = computed(() => Math.max(1, ...[...fileCells.value.values()].map((c) => c.count)))
const heatStyle = (count: number) => count <= 0 ? {} : { opacity: String(0.35 + 0.65 * (count / maxFileCount.value)) }

// ---- 层 2：文件对 → 节点级非对称矩阵 ----
const drill = ref<{ fa: string; fb: string } | null>(null)
const sortMode = ref<'file' | 'kind' | 'degree'>('file')
const SOFT_LIMIT = 80
const KIND_ORDER: Record<string, number> = { entity: 0, contract: 1, state: 2, rule: 3, process: 4, decision: 5 }

const drillNodes = computed(() => {
  if (!drill.value) return []
  const { fa, fb } = drill.value
  const inPair = props.nodes.filter((n) => {
    const f = fileOf(n.id) || UNANCHORED
    return f === fa || f === fb
  })
  const capped = inPair.length > SOFT_LIMIT
    ? [...inPair].sort((a, b) => degOf(b.id) - degOf(a.id)).slice(0, SOFT_LIMIT)
    : inPair
  const cmp: Record<string, (a: SemanticGraphNode, b: SemanticGraphNode) => number> = {
    file: (a, b) => (fileOf(a.id) === fa ? 0 : 1) - (fileOf(b.id) === fa ? 0 : 1)
      || (a.name || '').localeCompare(b.name || ''),
    kind: (a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || (a.name || '').localeCompare(b.name || ''),
    degree: (a, b) => degOf(b.id) - degOf(a.id) || (a.name || '').localeCompare(b.name || ''),
  }
  return [...capped].sort(cmp[sortMode.value])
})
const drillCapped = computed(() => {
  if (!drill.value) return false
  const { fa, fb } = drill.value
  return props.nodes.filter((n) => {
    const f = fileOf(n.id) || UNANCHORED
    return f === fa || f === fb
  }).length > SOFT_LIMIT
})
const drillEdges = computed(() => {
  if (!drill.value) return []
  const ids = new Set(drillNodes.value.map((n) => n.id))
  return props.edges.filter((e) => ids.has(e.from) && ids.has(e.to))
})
const cellEdges = computed(() => {
  const m = new Map<string, SemGraphViewEdge[]>()
  for (const e of drillEdges.value) {
    const k = `${e.from}|${e.to}`
    if (!m.has(k)) m.set(k, [])
    m.get(k)!.push(e)
  }
  return m
})
const cellOf = (r: string, c: string) => cellEdges.value.get(`${r}|${c}`) ?? []
const isOrphan = (id: string) => !drillEdges.value.some((e) => e.from === id || e.to === id)

// ---- 交互：十字高亮 / 单元格详情 / 头部点击联动 ----
const hoverRow = ref('')
const hoverCol = ref('')
const detail = ref<{ from: string; to: string; edges: SemGraphViewEdge[] } | null>(null)
function openCell(from: string, to: string) {
  const es = cellOf(from, to)
  if (!es.length) return
  detail.value = { from, to, edges: es }
}
function selectAsset(id: string) {
  if (id) emit('select', id)
}
function cellTitle(from: string, to: string): string {
  const es = cellOf(from, to)
  if (!es.length) return ''
  const fromName = props.nodes.find((n) => n.id === from)?.name ?? from
  const toName = props.nodes.find((n) => n.id === to)?.name ?? to
  const lines = es.map((e) => {
    const ev = [e.indirect ? `⇝${e.via || ''}` : '', e.file ? `${e.file}${e.line ? `:${e.line}` : ''}` : '']
      .filter(Boolean).join(' · ')
    return `· ${e.type || '—'}${e.desc ? ` — ${e.desc}` : ''}${ev ? `  (${ev})` : ''}`
  })
  return `${fromName} → ${toName}\n${t('assetMgmt.matrix.edgesCount', { n: es.length })}\n${lines.join('\n')}`
}
function fileCellTitle(fa: string, fb: string): string {
  const c = fileCell(fa, fb)
  if (!c?.count) return ''
  const a = fa === UNANCHORED ? fileLabel(fa) : fa
  const b = fb === UNANCHORED ? fileLabel(fb) : fb
  return `${a} → ${b}\n${t('assetMgmt.matrix.edgesCount', { n: c.count })}\n${c.types.join(', ')}`
}
const nameOf = (id: string) => props.nodes.find((n) => n.id === id)?.name ?? id
function headTitle(n: SemanticGraphNode): string {
  const f = fileOf(n.id)
  return `${n.name} · ${n.kind}${n.level ? ` · ${n.level}` : ''}${f ? `\n${f}` : ''}\n${t('assetMgmt.matrix.degreeShort')} ${degOf(n.id)}`
}
const selName = computed(() => props.nodes.find((n) => n.id === props.selId)?.name ?? '')
</script>

<template>
  <!-- 最小化停靠：图谱区右下角图标 -->
  <button
    v-if="minimized"
    class="fixed z-30 bottom-3 flex items-center justify-center w-9 h-9 rounded-full bg-ctp-mantle border border-ctp-surface1 shadow-lg hover:border-ctp-blue/50 text-ctp-subtext1 hover:text-ctp-text"
    style="right: 76px"
    :title="t('assetMgmt.matrix.title')"
    @click="setMinimized(false)"
  >
    <svg viewBox="0 0 24 24" class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" />
    </svg>
  </button>

  <div
    v-else
    ref="el"
    class="fixed z-30 flex flex-col rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
    :style="winStyle"
  >
    <!-- 标题栏(拖动) -->
    <div class="flex items-center gap-1.5 cursor-move shrink-0 px-3 pt-2.5 pb-1" @mousedown="beginDrag" @dblclick="pos = null">
      <span class="text-[11px] font-semibold text-ctp-text truncate">{{ t('assetMgmt.matrix.title') }}</span>
      <span class="chip !text-[9px] shrink-0 bg-ctp-surface0 text-ctp-subtext0">{{ nodes.length }} · {{ edges.length }}</span>
      <span v-if="selName" class="text-[9px] text-ctp-overlay1 truncate" :title="selId">{{ selName }}</span>
      <span class="flex-1" />
      <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0" :title="t('assetMgmt.matrix.minimize')" @click="setMinimized(true)">
        <MinusIcon class="w-3.5 h-3.5" />
      </button>
      <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5" :title="t('assetMgmt.matrix.close')" @click="emit('close')">
        <XMarkIcon class="w-3.5 h-3.5" />
      </button>
    </div>

    <!-- 层 2：文件对节点级矩阵 -->
    <template v-if="drill">
      <div class="shrink-0 flex items-center gap-1.5 px-3 pb-1 flex-wrap">
        <button class="btn btn-ghost !py-0 !px-1.5 !text-[9px] shrink-0" @click="drill = null">
          <ArrowLeftIcon class="w-3 h-3" />{{ t('assetMgmt.matrix.backToFile') }}
        </button>
        <span class="text-[10px] text-ctp-subtext1 font-mono truncate">
          {{ fileLabel(drill.fa) }} ↔ {{ fileLabel(drill.fb) }}
        </span>
        <span class="flex-1" />
        <span class="text-[9px] text-ctp-overlay1 shrink-0">{{ t('assetMgmt.matrix.sortLabel') }}</span>
        <select v-model="sortMode" class="input !py-0 !px-1 !text-[9px] w-auto shrink-0">
          <option value="file">{{ t('assetMgmt.matrix.sortByFile') }}</option>
          <option value="kind">{{ t('assetMgmt.matrix.sortByKind') }}</option>
          <option value="degree">{{ t('assetMgmt.matrix.sortByDegree') }}</option>
        </select>
      </div>
      <div v-if="drillCapped" class="shrink-0 mx-3 mb-1 px-2 py-1 rounded bg-ctp-peach/10 text-[9px] text-ctp-peach">
        {{ t('assetMgmt.matrix.softLimitHint', { n: SOFT_LIMIT }) }}
      </div>
      <div class="flex-1 min-h-0 overflow-auto px-3 pb-3">
        <table v-if="drillNodes.length" class="border-separate" style="border-spacing: 0">
          <thead>
            <tr>
              <th class="sticky top-0 left-0 z-20 bg-ctp-mantle p-0" />
              <th
                v-for="c in drillNodes" :key="c.id"
                class="sticky top-0 z-10 bg-ctp-mantle p-0 align-bottom"
                :class="c.id === selId ? 'ring-1 ring-ctp-peach/60' : ''"
              >
                <div class="w-[32px] h-[112px] flex items-start justify-center pt-1" :title="headTitle(c)" @click="selectAsset(c.id)">
                  <span
                    class="text-[9px] leading-[1.2] [writing-mode:vertical-rl] max-h-[104px] overflow-hidden cursor-pointer hover:text-ctp-text"
                    :class="[kindText(c.kind), hoverCol === c.id || hoverRow === c.id ? 'font-bold' : 'text-ctp-subtext0']"
                  >{{ c.name }}</span>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in drillNodes" :key="r.id">
              <th
                class="sticky left-0 z-10 bg-ctp-mantle text-right px-1.5 h-[32px] max-w-[170px] truncate cursor-pointer hover:text-ctp-text"
                :class="[kindText(r.kind), r.id === selId ? 'ring-1 ring-ctp-peach/60 bg-ctp-mantle' : '', hoverRow === r.id ? 'font-semibold' : 'font-normal']"
                :title="headTitle(r)"
                @click="selectAsset(r.id)"
              >
                <span v-if="isOrphan(r.id)" class="text-ctp-overlay0 mr-0.5" :title="t('assetMgmt.matrix.orphanHint')">◦</span>{{ r.name }}
              </th>
              <td
                v-for="c in drillNodes" :key="c.id"
                class="w-[32px] h-[32px] p-0 border border-ctp-surface0/60 text-center align-middle"
                :class="[
                  cellOf(r.id, c.id).length ? 'cursor-pointer' : '',
                  hoverRow === r.id || hoverCol === c.id ? 'bg-ctp-surface1/70' : '',
                ]"
                :title="cellTitle(r.id, c.id)"
                @mouseenter="hoverRow = r.id; hoverCol = c.id"
                @mouseleave="hoverRow = ''; hoverCol = ''"
                @click="openCell(r.id, c.id)"
              >
                <span
                  v-if="cellOf(r.id, c.id).length"
                  class="inline-flex items-center justify-center w-[24px] h-[24px] rounded-sm text-[9px] font-semibold"
                  :class="KIND_BG[c.kind] || 'bg-ctp-mauve/15'"
                  :style="heatStyle(1)"
                >{{ cellOf(r.id, c.id).length > 1 ? '×' + cellOf(r.id, c.id).length : '→' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.matrix.noNodes') }}</p>
      </div>
    </template>

    <!-- 层 1：文件×文件密度矩阵 -->
    <template v-else>
      <div class="shrink-0 px-3 pb-1 text-[9px] text-ctp-overlay1">{{ t('assetMgmt.matrix.fileLevelHint') }}</div>
      <div class="flex-1 min-h-0 overflow-auto px-3 pb-3">
        <table class="border-separate" style="border-spacing: 0">
          <thead>
            <tr>
              <th class="sticky top-0 left-0 z-20 bg-ctp-mantle p-0" />
              <th v-for="f in files" :key="f" class="sticky top-0 z-10 bg-ctp-mantle p-0">
                <div class="w-[36px] h-[112px] flex items-start justify-center pt-1">
                  <span
                    class="text-[9px] leading-[1.2] [writing-mode:vertical-rl] max-h-[104px] overflow-hidden text-ctp-subtext1"
                    :title="f === UNANCHORED ? fileLabel(f) : f"
                  >{{ fileLabel(f) }}</span>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="rf in files" :key="rf">
              <th class="sticky left-0 z-10 bg-ctp-mantle text-right px-1.5 h-[26px] max-w-[170px] truncate font-normal text-[10px] text-ctp-subtext1"
                  :title="rf === UNANCHORED ? fileLabel(rf) : rf"
              >{{ fileLabel(rf) }}</th>
              <td
                v-for="cf in files" :key="cf"
                class="w-[36px] h-[30px] p-0 border border-ctp-surface0/60 text-center"
              >
                <!-- 对角线：文件内部边数 -->
                <div
                  v-if="rf === cf"
                  class="w-full h-full flex items-center justify-center text-[8px] text-ctp-overlay0 bg-ctp-surface0/40"
                  :title="`${fileLabel(rf)} · ${t('assetMgmt.matrix.internal')} ${fileCell(rf, cf)?.count ?? 0}`"
                >{{ fileCell(rf, cf)?.count || '' }}</div>
                <!-- 非对角：行文件 → 列文件 密度(可下钻) -->
                <button
                  v-else-if="fileCell(rf, cf)?.count"
                  class="w-full h-full flex items-center justify-center text-[9px] font-semibold text-ctp-text cursor-pointer"
                  :class="KIND_BG.process"
                  :style="heatStyle(fileCell(rf, cf)!.count)"
                  :title="fileCellTitle(rf, cf)"
                  @click="drill = { fa: rf, fb: cf }"
                >{{ fileCell(rf, cf)!.count }}</button>
                <div v-else class="w-full h-full" :title="fileCellTitle(rf, cf)" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- 单元格详情浮层(点击有向格)：方向 + 类型 + 完整增强描述 + 选中联动 -->
    <div
      v-if="detail"
      class="shrink-0 border-t border-ctp-surface1 px-3 py-2 max-h-[38%] overflow-auto bg-ctp-surface0/60"
    >
      <div class="flex items-center gap-1 mb-1">
        <span class="text-[10px] font-semibold text-ctp-subtext1 truncate">
          {{ nameOf(detail.from) }} → {{ nameOf(detail.to) }}
        </span>
        <span class="chip !text-[8px] bg-ctp-surface0 text-ctp-overlay1">{{ t('assetMgmt.matrix.edgesCount', { n: detail.edges.length }) }}</span>
        <span class="flex-1" />
        <button class="text-ctp-overlay0 hover:text-ctp-text text-[9px]" @click="detail = null">{{ t('assetMgmt.matrix.closeDetail') }}</button>
      </div>
      <div v-for="(e, i) in detail.edges" :key="i" class="pl-1 py-0.5 text-[10px] leading-relaxed">
        <span class="font-mono text-ctp-overlay1">{{ e.type || '—' }}</span>
        <span v-if="e.indirect" class="text-ctp-teal" :title="e.via"> ⇝{{ t('assetMgmt.matrix.indirect') }}</span>
        <span v-if="e.desc" class="text-ctp-subtext0"> — {{ e.desc }}</span>
        <span v-if="e.file" class="ml-1 font-mono text-[9px] text-ctp-overlay0">{{ e.file }}{{ e.line ? `:${e.line}` : '' }}</span>
        <span v-if="e.resolvedBy" class="ml-1 text-[9px] text-ctp-overlay0">{{ e.resolvedBy }}{{ e.confidence ? ` (${e.confidence})` : '' }}</span>
        <button class="ml-1 text-ctp-sky hover:underline" @click="selectAsset(detail!.from)">{{ nameOf(detail.from) }}</button>
        <span class="text-ctp-overlay0"> → </span>
        <button class="ml-1 text-ctp-sky hover:underline" @click="selectAsset(detail!.to)">{{ nameOf(detail.to) }}</button>
      </div>
    </div>

    <!-- 四边拉伸(与资产卡一致) -->
    <div class="mx-edge mx-edge-n" @mousedown="startResize($event, 'n')" @dblclick.stop />
    <div class="mx-edge mx-edge-s" @mousedown="startResize($event, 's')" @dblclick.stop />
    <div class="mx-edge mx-edge-e" @mousedown="startResize($event, 'e')" @dblclick.stop />
    <div class="mx-edge mx-edge-w" @mousedown="startResize($event, 'w')" @dblclick.stop />
  </div>
</template>

<style scoped>
.mx-edge {
  position: absolute;
  z-index: 10;
  transition: background-color 0.15s;
}
.mx-edge:hover {
  background-color: rgba(136, 137, 163, 0.35);
}
.mx-edge-n,
.mx-edge-s {
  left: 0;
  right: 0;
  height: 6px;
  cursor: ns-resize;
}
.mx-edge-n { top: 0; }
.mx-edge-s { bottom: 0; }
.mx-edge-e,
.mx-edge-w {
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
}
.mx-edge-w { left: 0; }
.mx-edge-e { right: 0; }
</style>
