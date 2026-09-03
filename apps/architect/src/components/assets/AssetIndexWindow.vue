<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, MinusIcon } from '@heroicons/vue/24/outline'
import type { SemanticGraphAnchor, SemanticGraphNode } from '@/services/semantic-asset-service'
import type { SemGraphViewEdge } from '@/utils/diagram-gen'

/** 资产节点索引浮窗(与关系矩阵同款联动交互：点击行 → select 全联动)。
 *  数据 = 图谱当前口径(scopedNodes/scopedEdges)；搜索/分组/排序辅助按索引探索图谱。 */
const props = defineProps<{
  nodes: SemanticGraphNode[]
  edges: SemGraphViewEdge[]
  anchors: SemanticGraphAnchor[]
  selId: string
}>()
const emit = defineEmits<{ select: [id: string]; close: [] }>()

const { t } = useI18n()

// ---- 浮窗骨架：拖动 + 四边拉伸 + 最小化停靠(状态持久化；骨架与关系矩阵一致) ----
const MIN_KEY = 'arch.indexWin.minimized'
const SIZE_KEY = 'arch.indexWin.size'
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
    if (raw && Number(raw.w) >= 320 && Number(raw.h) >= 260) return { w: Number(raw.w), h: Number(raw.h) }
  } catch { /* ignore */ }
  return { w: 380, h: 600 }
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
type IndexResizeEdge = 'n' | 's' | 'e' | 'w'
let resizeEdge: IndexResizeEdge = 's'
let resizing = false
let rsStart = { x: 0, y: 0, w: 0, h: 0, px: 0, py: 0 }
function startResize(e: MouseEvent, edge: IndexResizeEdge) {
  if (e.button !== 0) return
  e.preventDefault()
  e.stopPropagation()
  const rect = el.value?.getBoundingClientRect()
  if (!rect) return
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
  const maxW = Math.min(1200, window.innerWidth - 16)
  const maxH = window.innerHeight - 40
  const dx = e.clientX - rsStart.x
  const dy = e.clientY - rsStart.y
  let w = rsStart.w
  let h = rsStart.h
  let px = rsStart.px
  let py = rsStart.py
  if (resizeEdge === 'e') {
    w = Math.min(maxW, Math.max(320, w + dx))
  } else if (resizeEdge === 'w') {
    w = Math.min(maxW, Math.max(320, w - dx))
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
  ...(pos.value
    ? { left: `${pos.value.x}px`, top: `${pos.value.y}px` }
    : { left: '20px', top: '64px' }),
}))

// ---- 数据准备：锚点行号 + 度数 + 搜索/分组/排序 ----
const KIND_TEXT: Record<string, string> = {
  entity: 'text-ctp-mauve', contract: 'text-ctp-yellow', state: 'text-ctp-sky',
  rule: 'text-ctp-peach', process: 'text-ctp-blue', decision: 'text-ctp-green',
}
const kindText = (k?: string) => KIND_TEXT[k ?? ''] ?? 'text-ctp-overlay1'
const anchorOf = computed(() => {
  const m = new Map<string, SemanticGraphAnchor>()
  for (const a of props.anchors) if (!m.has(a.assetId)) m.set(a.assetId, a)
  return m
})
const degree = computed(() => {
  const inn = new Map<string, number>()
  const out = new Map<string, number>()
  for (const e of props.edges) {
    out.set(e.from, (out.get(e.from) ?? 0) + 1)
    inn.set(e.to, (inn.get(e.to) ?? 0) + 1)
  }
  return { inn, out }
})
const search = ref('')
const groupBy = ref<'kind' | 'level' | 'file'>('kind')
const sortBy = ref<'name' | 'degree' | 'file'>('name')
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  const { inn, out } = degree.value
  const fileOf = (n: SemanticGraphNode) => anchorOf.value.get(n.id)?.file ?? ''
  let arr = props.nodes
  if (q) arr = arr.filter((n) => n.name.toLowerCase().includes(q) || fileOf(n).toLowerCase().includes(q))
  const key = (n: SemanticGraphNode) =>
    sortBy.value === 'degree' ? ((out.get(n.id) ?? 0) + (inn.get(n.id) ?? 0)) * -1
      : sortBy.value === 'file' ? fileOf(n)
        : n.name.toLowerCase()
  return [...arr].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0))
})
const groups = computed(() => {
  const g = new Map<string, SemanticGraphNode[]>()
  for (const n of filtered.value) {
    const k = groupBy.value === 'kind' ? (n.kind || '—')
      : groupBy.value === 'level' ? (n.level || '—')
        : (anchorOf.value.get(n.id)?.file || '—')
    if (!g.has(k)) g.set(k, [])
    g.get(k)!.push(n)
  }
  return [...g.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1))
})
function rowTitle(n: SemanticGraphNode) {
  const a = anchorOf.value.get(n.id)
  return a ? `${n.name} · ${a.file}:${a.line}${a.symbol ? ` ${a.symbol}` : ''}` : n.name
}
function selectAsset(id: string) {
  if (id) emit('select', id)
}
</script>

<template>
  <!-- 最小化停靠：图谱区左下角图标 -->
  <button
    v-if="minimized"
    class="fixed z-30 bottom-3 left-3 flex items-center justify-center w-9 h-9 rounded-full bg-ctp-mantle border border-ctp-surface1 shadow-lg hover:border-ctp-blue/50 text-ctp-subtext1 hover:text-ctp-text"
    :title="t('assetMgmt.index.title')"
    @click="setMinimized(false)"
  >
    <svg viewBox="0 0 24 24" class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M4 6h16M4 12h10M4 18h14" />
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
      <span class="text-[11px] font-semibold text-ctp-text truncate">{{ t('assetMgmt.index.title') }}</span>
      <span class="chip !text-[9px] shrink-0 bg-ctp-surface0 text-ctp-subtext0">{{ nodes.length }} · {{ edges.length }}</span>
      <span class="flex-1" />
      <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0" :title="t('assetMgmt.matrix.minimize')" @click="setMinimized(true)">
        <MinusIcon class="w-3.5 h-3.5" />
      </button>
      <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5" :title="t('assetMgmt.matrix.close')" @click="emit('close')">
        <XMarkIcon class="w-3.5 h-3.5" />
      </button>
    </div>

    <!-- 工具行：搜索 + 分组 + 排序 -->
    <div class="shrink-0 flex items-center gap-1 px-3 pb-1.5 flex-wrap">
      <input
        v-model="search"
        class="input !py-0 !px-1.5 !text-[10px] flex-1 min-w-[120px]"
        :placeholder="t('assetMgmt.index.search')"
      >
      <select v-model="groupBy" class="input !py-0 !px-1 !text-[9px] w-auto shrink-0" :title="t('assetMgmt.index.groupBy')">
        <option value="kind">{{ t('assetMgmt.index.byKind') }}</option>
        <option value="level">{{ t('assetMgmt.index.byLevel') }}</option>
        <option value="file">{{ t('assetMgmt.index.byFile') }}</option>
      </select>
      <select v-model="sortBy" class="input !py-0 !px-1 !text-[9px] w-auto shrink-0" :title="t('assetMgmt.index.sortBy')">
        <option value="name">{{ t('assetMgmt.index.byName') }}</option>
        <option value="degree">{{ t('assetMgmt.index.byDegree') }}</option>
        <option value="file">{{ t('assetMgmt.index.byFile') }}</option>
      </select>
    </div>

    <!-- 索引列表 -->
    <div class="flex-1 min-h-0 overflow-auto px-2 pb-3">
      <template v-if="filtered.length">
        <div v-for="[g, items] in groups" :key="g" class="mb-1.5">
          <div class="sticky top-0 z-10 bg-ctp-mantle/95 px-1 py-0.5 flex items-center gap-1.5">
            <span class="text-[9px] font-semibold text-ctp-overlay1 truncate">{{ g }}</span>
            <span class="chip !text-[8px] !px-1 !py-0 shrink-0 bg-ctp-surface0 text-ctp-subtext0">{{ items.length }}</span>
          </div>
          <button
            v-for="n in items" :key="n.id"
            class="w-full flex items-center gap-1.5 px-1.5 py-[3px] rounded text-left hover:bg-ctp-surface0/70"
            :class="n.id === selId ? 'ring-1 ring-ctp-peach/60 bg-ctp-surface0' : ''"
            :title="rowTitle(n)"
            @click="selectAsset(n.id)"
          >
            <span class="text-[10px] font-medium truncate shrink-0 max-w-[46%]" :class="kindText(n.kind)">{{ n.name }}</span>
            <span class="flex-1 truncate text-[9px] text-ctp-overlay0 font-mono">
              {{ anchorOf.get(n.id)?.file ? `${anchorOf.get(n.id)!.file.split('/').pop()}:${anchorOf.get(n.id)!.line}` : '—' }}
            </span>
            <span class="text-[9px] text-ctp-subtext0 shrink-0">→{{ degree.out.get(n.id) ?? 0 }} ←{{ degree.inn.get(n.id) ?? 0 }}</span>
          </button>
        </div>
      </template>
      <p v-else class="text-[10px] text-ctp-overlay0 px-1 pt-2">{{ t('assetMgmt.index.noMatch') }}</p>
    </div>

    <!-- 四边拉伸(与资产卡一致) -->
    <div class="ix-edge ix-edge-n" @mousedown="startResize($event, 'n')" @dblclick.stop />
    <div class="ix-edge ix-edge-s" @mousedown="startResize($event, 's')" @dblclick.stop />
    <div class="ix-edge ix-edge-e" @mousedown="startResize($event, 'e')" @dblclick.stop />
    <div class="ix-edge ix-edge-w" @mousedown="startResize($event, 'w')" @dblclick.stop />
  </div>
</template>

<style scoped>
.ix-edge {
  position: absolute;
  z-index: 10;
  transition: background-color 0.15s;
}
.ix-edge:hover {
  background-color: rgba(136, 137, 163, 0.35);
}
.ix-edge-n,
.ix-edge-s {
  left: 0;
  right: 0;
  height: 6px;
  cursor: ns-resize;
}
.ix-edge-n { top: 0; }
.ix-edge-s { bottom: 0; }
.ix-edge-e,
.ix-edge-w {
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
}
.ix-edge-w { left: 0; }
.ix-edge-e { right: 0; }
</style>
