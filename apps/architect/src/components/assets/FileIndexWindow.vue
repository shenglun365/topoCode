<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, MinusIcon } from '@heroicons/vue/24/outline'
import type { GraphFileEntry } from '@/types'

/** 文件范围索引浮窗(资产索引同款骨架：拖动/拉伸/最小化停靠)。
 *
 * 大项目语义资产 >500 时强制手动圈定图谱文件范围：
 * - 两级分组：所属组件 → 源码目录(组内排序)；
 * - 多选 + 整组选取，总资产预算 ≤ budget(超出预算的加入被拒绝并提示)；
 * - 关键字搜索覆盖 组件名/文件名/目录。
 */
const props = defineProps<{
  entries: GraphFileEntry[]
  selected: string[]
  budget: number
  /** 范围资产总数(超限提示用)。 */
  total: number
  /** 组件 id → 名称(分组展示)。 */
  compNames?: Record<string, string>
  forced?: boolean
}>()
const emit = defineEmits<{ apply: [files: string[]]; close: [] }>()

const { t } = useI18n()

// ---- 浮窗骨架(与 AssetIndexWindow 一致) ----
const SIZE_KEY = 'arch.fileIdxWin.size'
const MIN_KEY = 'arch.fileIdxWin.minimized'
const minimized = ref(false)
function setMinimized(v: boolean) {
  minimized.value = v
  try { localStorage.setItem(MIN_KEY, v ? '1' : '0') } catch { /* ignore */ }
}
function loadSize(): { w: number; h: number | null } {
  try {
    const raw = JSON.parse(localStorage.getItem(SIZE_KEY) || '')
    if (raw && Number(raw.w) >= 340 && Number(raw.h) >= 260) return { w: Number(raw.w), h: Number(raw.h) }
  } catch { /* ignore */ }
  return { w: 400, h: 620 }
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
type IdxResizeEdge = 'n' | 's' | 'e' | 'w'
let resizeEdge: IdxResizeEdge = 's'
let resizing = false
let rsStart = { x: 0, y: 0, w: 0, h: 0, px: 0, py: 0 }
function startResize(e: MouseEvent, edge: IdxResizeEdge) {
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
    w = Math.min(maxW, Math.max(340, w + dx))
  } else if (resizeEdge === 'w') {
    w = Math.min(maxW, Math.max(340, w - dx))
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
}
const winStyle = computed(() => ({
  width: `${size.value.w}px`,
  height: size.value.h ? `${size.value.h}px` : undefined,
  ...(pos.value
    ? { left: `${pos.value.x}px`, top: `${pos.value.y}px` }
    : { left: '20px', top: '64px' }),
}))

// ---- 选择状态(本地副本，应用时上抛) ----
const sel = ref<Set<string>>(new Set(props.selected))
watch(() => props.selected, (v) => { sel.value = new Set(v) })

/** 预算占用 = 已选文件的资产数合计(文件可能多组件共享，按文件去重计数)。 */
const selAssets = computed(() => {
  let n = 0
  for (const e of props.entries) if (sel.value.has(e.file)) n += e.n
  return n
})
/** 单次操作实际落选提示(整组/单选超预算时短暂显示)。 */
const denyMsg = ref('')
let denyTimer: ReturnType<typeof setTimeout> | null = null
function deny(msg: string) {
  denyMsg.value = msg
  if (denyTimer) clearTimeout(denyTimer)
  denyTimer = setTimeout(() => { denyMsg.value = '' }, 2200)
}
function toggle(f: GraphFileEntry) {
  const s = new Set(sel.value)
  if (s.has(f.file)) {
    s.delete(f.file)
  } else {
    if (selAssets.value + f.n > props.budget) {
      deny(t('assetMgmt.fileIndex.budgetDeny', { budget: props.budget }))
      return
    }
    s.add(f.file)
  }
  sel.value = s
}
function groupFiles(g: Group): GraphFileEntry[] {
  return g.dirs.flatMap((d) => d.files)
}
function toggleGroup(g: Group) {
  const files = groupFiles(g)
  const allSel = files.every((f) => sel.value.has(f.file))
  const s = new Set(sel.value)
  if (allSel) {
    for (const f of files) s.delete(f.file)
    sel.value = s
    return
  }
  let cap = props.budget - selAssets.value
  let full = true
  for (const f of files) {
    if (s.has(f.file)) continue
    if (f.n <= cap) {
      s.add(f.file)
      cap -= f.n
    } else {
      full = false
    }
  }
  sel.value = s
  if (!full) deny(t('assetMgmt.fileIndex.budgetDeny', { budget: props.budget }))
}
function clearAll() {
  sel.value = new Set()
}
function apply() {
  emit('apply', props.entries.filter((e) => sel.value.has(e.file)).map((e) => e.file))
}

// ---- 搜索 + 组件→目录两级分组 ----
const q = ref('')
const OTHER_KEY = '__other__'
interface Group {
  key: string
  name: string
  dirs: { dir: string; files: GraphFileEntry[] }[]
  files: number
  assets: number
}
const compNameOf = (cid: string) => props.compNames?.[cid] ?? cid
const groups = computed<Group[]>(() => {
  const kw = q.value.trim().toLowerCase()
  const hit = (e: GraphFileEntry) => {
    if (!kw) return true
    if (e.file.toLowerCase().includes(kw) || e.dir.toLowerCase().includes(kw)) return true
    return e.comps.some((c) => compNameOf(c).toLowerCase().includes(kw))
  }
  const byComp = new Map<string, { n: number; byDir: Map<string, GraphFileEntry[]> }>()
  for (const e of props.entries) {
    if (!hit(e)) continue
    const key = e.comps[0] ?? OTHER_KEY
    const g = byComp.get(key) ?? { n: 0, byDir: new Map() }
    const dir = e.dir || '/'
    const arr = g.byDir.get(dir) ?? []
    arr.push(e)
    g.byDir.set(dir, arr)
    g.n += e.n
    byComp.set(key, g)
  }
  const out: Group[] = []
  for (const [key, g] of byComp) {
    const dirs = [...g.byDir.entries()]
      .map(([dir, files]) => ({ dir, files: files.sort((a, b) => a.file.localeCompare(b.file)) }))
      .sort((a, b) => a.dir.localeCompare(b.dir))
    out.push({
      key,
      name: key === OTHER_KEY ? t('assetMgmt.unownedFiles') : compNameOf(key),
      dirs,
      files: dirs.reduce((s, d) => s + d.files.length, 0),
      assets: g.n,
    })
  }
  return out.sort((a, b) => a.name.localeCompare(b.name))
})
const shownAssets = computed(() => groups.value.reduce((s, g) => s + g.assets, 0))
const dirTail = (dir: string) => {
  if (!dir || dir === '/') return dir
  const parts = dir.split('/')
  return parts.length > 2 ? '…/' + parts.slice(-2).join('/') : dir
}
</script>

<template>
  <!-- 最小化停靠：图谱区左下角图标(与资产索引同位风格) -->
  <button
    v-if="minimized"
    class="fixed z-30 bottom-3 left-14 flex items-center justify-center w-9 h-9 rounded-full bg-ctp-mantle border shadow-lg hover:border-ctp-blue/50"
    :class="props.selected.length ? 'border-ctp-mauve/60 text-ctp-mauve' : 'border-ctp-surface1 text-ctp-subtext1 hover:text-ctp-text'"
    :title="t('assetMgmt.fileIndex.title')"
    @click="setMinimized(false)"
  >
    <svg viewBox="0 0 24 24" class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-8l-2-2H5a2 2 0 0 0-2 2Z" />
    </svg>
  </button>

  <div
    v-else
    ref="el"
    class="fixed z-30 flex flex-col rounded-lg bg-ctp-mantle border shadow-xl overflow-hidden"
    :class="forced ? 'border-ctp-peach/50' : 'border-ctp-surface1'"
    :style="winStyle"
  >
    <!-- 标题栏(拖动) -->
    <div class="flex items-center gap-1.5 cursor-move shrink-0 px-3 pt-2.5 pb-1" @mousedown="beginDrag" @dblclick="pos = null">
      <span class="text-[11px] font-semibold text-ctp-text truncate">{{ t('assetMgmt.fileIndex.title') }}</span>
      <span class="chip !text-[9px] shrink-0 bg-ctp-surface0 text-ctp-subtext0">{{ t('assetMgmt.fileIndex.totalChip', { n: total }) }}</span>
      <span class="flex-1" />
      <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0" :title="t('assetMgmt.matrix.minimize')" @click="setMinimized(true)">
        <MinusIcon class="w-3.5 h-3.5" />
      </button>
      <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5" :title="t('assetMgmt.matrix.close')" @click="emit('close')">
        <XMarkIcon class="w-3.5 h-3.5" />
      </button>
    </div>

    <p
      v-if="forced"
      class="shrink-0 mx-3 mb-1.5 px-2 py-1 rounded bg-ctp-peach/10 text-[10px] text-ctp-peach"
    >{{ t('assetMgmt.fileIndex.forcedHint', { budget: props.budget, total: props.total }) }}</p>

    <!-- 工具行：关键字搜索(组件名/文件名/目录) -->
    <div class="shrink-0 flex items-center gap-1 px-3 pb-1.5">
      <input
        v-model="q"
        class="input !py-0 !px-1.5 !text-[10px] flex-1 min-w-[120px]"
        :placeholder="t('assetMgmt.fileIndex.search')"
      >
    </div>

    <!-- 索引列表：组件 → 目录 → 文件 -->
    <div class="flex-1 min-h-0 overflow-auto px-2 pb-2">
      <template v-if="groups.length">
        <div v-for="g in groups" :key="g.key" class="mb-1.5">
          <div class="sticky top-0 z-10 bg-ctp-mantle/95 px-1 py-0.5 flex items-center gap-1.5">
            <button
              class="text-[9px] font-semibold text-ctp-blue hover:text-ctp-mauve shrink-0"
              :title="t('assetMgmt.fileIndex.toggleGroup')"
              @click="toggleGroup(g)"
            >{{ groupFiles(g).every((f) => sel.has(f.file)) ? t('assetMgmt.fileIndex.deselectAll') : t('assetMgmt.fileIndex.selectAll') }}</button>
            <span class="text-[9px] font-semibold text-ctp-overlay1 truncate" :title="g.name">{{ g.name }}</span>
            <span class="chip !text-[8px] !px-1 !py-0 shrink-0 bg-ctp-surface0 text-ctp-subtext0">{{ g.files }} · {{ g.assets }}</span>
          </div>
          <template v-for="d in g.dirs" :key="g.key + d.dir">
            <div class="px-1.5 pt-1 text-[8px] text-ctp-overlay0 font-mono truncate" :title="d.dir">{{ dirTail(d.dir) }}</div>
            <button
              v-for="f in d.files" :key="f.file"
              class="w-full flex items-center gap-1.5 px-1.5 py-[3px] rounded text-left hover:bg-ctp-surface0/70"
              :class="sel.has(f.file) ? 'bg-ctp-mauve/10 ring-1 ring-ctp-mauve/40' : ''"
              :title="f.file"
              @click="toggle(f)"
            >
              <input type="checkbox" class="accent-ctp-mauve pointer-events-none" :checked="sel.has(f.file)" tabindex="-1">
              <span class="text-[10px] font-medium truncate shrink-0 max-w-[46%] text-ctp-subtext1">{{ f.file.split('/').pop() }}</span>
              <span class="flex-1 truncate text-[9px] text-ctp-overlay0 font-mono">{{ dirTail(f.dir) }}</span>
              <span
                v-if="f.comps.length > 1"
                class="chip !text-[8px] !px-1 !py-0 shrink-0 bg-ctp-teal/10 text-ctp-teal"
                :title="f.comps.map(compNameOf).join(' · ')"
              >+{{ f.comps.length - 1 }}</span>
              <span class="chip !text-[8px] !px-1 !py-0 shrink-0 bg-ctp-surface0 text-ctp-subtext0 font-mono">{{ f.n }}</span>
            </button>
          </template>
        </div>
      </template>
      <p v-else class="text-[10px] text-ctp-overlay0 px-1 pt-2">{{ t('assetMgmt.fileIndex.noMatch') }}</p>
    </div>

    <!-- 底栏：预算 + 清空/应用 -->
    <div class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 border-t border-ctp-surface0">
      <span class="text-[10px] text-ctp-overlay0 font-mono truncate">
        {{ t('assetMgmt.fileIndex.selectedFiles', { files: sel.size, n: selAssets, budget: props.budget }) }}
        <template v-if="q"> · {{ t('assetMgmt.fileIndex.shown', { n: shownAssets }) }}</template>
      </span>
      <span v-if="denyMsg" class="text-[9px] text-ctp-peach truncate">{{ denyMsg }}</span>
      <span class="flex-1" />
      <button class="btn btn-ghost btn-xs" :disabled="!sel.size" @click="clearAll">{{ t('assetMgmt.fileIndex.clear') }}</button>
      <button class="btn btn-primary btn-xs" :disabled="!sel.size" @click="apply">{{ t('assetMgmt.fileIndex.apply') }}</button>
    </div>
  </div>
</template>
