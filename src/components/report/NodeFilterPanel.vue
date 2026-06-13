<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, ArrowDownTrayIcon, ArrowsPointingInIcon } from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'

interface FilterNode {
  id: string
  label: string
  nodeCount?: number
  type?: 'community' | 'external'
  qualityScore?: number | null
  inDegree?: number
  outDegree?: number
}

const props = defineProps<{
  nodes: FilterNode[]
  hiddenIds: Set<string>
  visible: boolean
  clickX?: number
  clickY?: number
}>()

const emit = defineEmits<{
  'update:hiddenIds': [ids: Set<string>]
  'update:visible': [visible: boolean]
  'close': []
  'connect-complete': []
}>()

const { t } = useI18n()
const panelStore = usePanelStore()

const search = ref('')
const pinned = ref(false)
const panelX = ref(0)
const panelY = ref(0)
const dragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const dragStartPX = ref(0)
const dragStartPY = ref(0)
const PW = 280

function safeArea() {
  const leftMargin = panelStore.leftCollapsed ? 0 : panelStore.leftWidth
  const rightMargin = panelStore.rightCollapsed ? 0 : panelStore.rightWidth
  return {
    left: leftMargin + 8,
    right: window.innerWidth - rightMargin - PW - 8,
    top: 56,
    bottom: window.innerHeight - 8,
  }
}

function calcPosition() {
  const area = safeArea()
  let cx = props.clickX ?? area.right
  let cy = props.clickY ?? window.innerHeight / 2
  const ph = Math.min(480, window.innerHeight * 0.65)
  let top = cy - ph / 2
  let left = cx + 12
  if (left + PW > area.right) left = cx - PW - 12
  if (left < area.left) left = area.left
  if (top < area.top) top = area.top
  if (top + ph > area.bottom) top = area.bottom - ph
  panelX.value = Math.round(left)
  panelY.value = Math.round(top)
}

function onHeaderMouseDown(e: MouseEvent) {
  dragging.value = true
  dragStartX.value = e.clientX
  dragStartY.value = e.clientY
  dragStartPX.value = panelX.value
  dragStartPY.value = panelY.value
  e.preventDefault()
}

function onMouseMove(e: MouseEvent) {
  if (!dragging.value) return
  const area = safeArea()
  panelX.value = Math.max(area.left, Math.min(area.right, dragStartPX.value + e.clientX - dragStartX.value))
  panelY.value = Math.max(area.top, Math.min(area.bottom - 480, dragStartPY.value + e.clientY - dragStartY.value))
}

function onMouseUp() { dragging.value = false }

watch(() => props.visible, (v) => {
  if (v) calcPosition()
  if (!v) pinned.value = false
})

onMounted(() => {
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
})
onUnmounted(() => {
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
})

/* ---- 搜索过滤 ---- */
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return props.nodes
  return props.nodes.filter(n =>
    n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q)
  )
})

function pct(sorted: number[], q: number): number {
  if (sorted.length === 0) return 0
  const idx = (sorted.length - 1) * q
  const lo = Math.floor(idx)
  const hi = Math.ceil(idx)
  if (lo === hi) return sorted[lo]
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo)
}

/* ---- 动态百分位分组 ---- */
const sizePcts = computed(() => {
  const vals = props.nodes.map(n => n.nodeCount || 0).sort((a, b) => a - b)
  return { p25: pct(vals, 0.25), p75: pct(vals, 0.75) }
})

const qualityPcts = computed(() => {
  const vals = props.nodes.filter(n => n.qualityScore != null).map(n => n.qualityScore!).sort((a, b) => a - b)
  return { p25: pct(vals, 0.25), p75: pct(vals, 0.75) }
})

const smallNodes = computed(() => {
  const { p25, p75 } = sizePcts.value
  return props.nodes.filter(n => (n.nodeCount || 0) <= p25 + 1e-9)
})
const mediumNodes = computed(() => {
  const { p25, p75 } = sizePcts.value
  return props.nodes.filter(n => (n.nodeCount || 0) > p25 + 1e-9 && (n.nodeCount || 0) < p75 - 1e-9)
})
const largeNodes = computed(() => {
  const { p75 } = sizePcts.value
  return props.nodes.filter(n => (n.nodeCount || 0) >= p75 - 1e-9)
})

const poorQuality = computed(() => {
  const { p25, p75 } = qualityPcts.value
  return props.nodes.filter(n => n.qualityScore != null && n.qualityScore <= p25 + 1e-9)
})
const midQuality = computed(() => {
  const { p25, p75 } = qualityPcts.value
  return props.nodes.filter(n => n.qualityScore != null && n.qualityScore > p25 + 1e-9 && n.qualityScore < p75 - 1e-9)
})
const goodQuality = computed(() => {
  const { p75 } = qualityPcts.value
  return props.nodes.filter(n => n.qualityScore != null && n.qualityScore >= p75 - 1e-9)
})

/* ---- 基础分组 ---- */
const communityNodes = computed(() => props.nodes.filter(n => n.type !== 'external'))
const externalNodes = computed(() => props.nodes.filter(n => n.type === 'external'))
const totalCount = computed(() => props.nodes.length)

type SortKey = 'name' | 'inDeg' | 'outDeg' | 'count'
const sortKey = ref<SortKey>('name')
const sortDir = ref<1 | -1>(1)

const communitySortKeys: { key: SortKey; label: string }[] = [
  { key: 'name', label: '名称' },
  { key: 'inDeg', label: '入度' },
  { key: 'outDeg', label: '出度' },
  { key: 'count', label: '成员' },
]

const sortedCommunityNodes = computed(() => {
  const list = [...communityNodes.value]
  const k = sortKey.value
  const d = sortDir.value
  list.sort((a, b) => {
    let va: number, vb: number
    if (k === 'inDeg') { va = a.inDegree ?? 0; vb = b.inDegree ?? 0 }
    else if (k === 'outDeg') { va = a.outDegree ?? 0; vb = b.outDegree ?? 0 }
    else if (k === 'count') { va = a.nodeCount ?? 0; vb = b.nodeCount ?? 0 }
    else { return d * a.label.localeCompare(b.label) }
    return d * (vb - va)
  })
  return list
})

function toggleSort(key: SortKey) {
  if (sortKey.value === key) { sortDir.value = sortDir.value === 1 ? -1 : 1 }
  else { sortKey.value = key; sortDir.value = 1 }
}

/* ---- 操作 ---- */
function toggle(id: string) {
  const next = new Set(props.hiddenIds)
  if (next.has(id)) { next.delete(id) } else { next.add(id) }
  emit('update:hiddenIds', next)
}

function hideAll(type: 'community' | 'external') {
  const next = new Set(props.hiddenIds)
  const list = type === 'community' ? communityNodes.value : externalNodes.value
  list.forEach(n => next.add(n.id))
  emit('update:hiddenIds', next)
}

function showAll(type: 'community' | 'external') {
  const next = new Set(props.hiddenIds)
  const list = type === 'community' ? communityNodes.value : externalNodes.value
  list.forEach(n => next.delete(n.id))
  emit('update:hiddenIds', next)
}

function hideByComputed(list: FilterNode[]) {
  const ids = new Set(list.map(n => n.id))
  const next = new Set(props.hiddenIds)
  ids.forEach(id => next.add(id))
  emit('update:hiddenIds', next)
}

function showByComputed(list: FilterNode[]) {
  const ids = new Set(list.map(n => n.id))
  const next = new Set(props.hiddenIds)
  ids.forEach(id => next.delete(id))
  emit('update:hiddenIds', next)
}

function selectAll() { emit('update:hiddenIds', new Set()) }
function resetHidden() { emit('update:hiddenIds', new Set()) }

function sortByInDegree(nodes: FilterNode[]): FilterNode[] {
  return [...nodes].sort((a, b) => (b.nodeCount || 0) - (a.nodeCount || 0))
}
</script>

<template>
  <teleport to="body">
    <div v-if="visible && !pinned" class="nfp-backdrop" @click="emit('close')" />
    <div v-if="visible" class="nfp-overlay" :style="{ left: panelX + 'px', top: panelY + 'px' }" :class="{ dragging }">
      <div class="nfp-panel">
        <div class="nfp-header" @mousedown="onHeaderMouseDown">
          <span class="nfp-title">{{ t('report.nodeFilter', '筛选') }} ({{ totalCount - hiddenCount }}/{{ totalCount }})</span>
          <div class="nfp-header-actions">
            <button class="nfp-icon-btn" :class="{ active: pinned }" :title="t('report.pinPanel', '常驻')" @click="pinned = !pinned">
              <ArrowDownTrayIcon class="w-3 h-3" />
            </button>
            <button class="nfp-icon-btn" @click="emit('close')">
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div class="nfp-search">
          <input v-model="search" type="text" :placeholder="t('report.searchCommunity', '搜索...')" class="nfp-search-input">
        </div>

        <!-- 按类型分组 -->
        <div class="nfp-group">
          <div class="nfp-group-title">类型</div>
          <div class="nfp-group-row">
            <button class="nfp-chip" @click="selectAll">{{ t('report.showAll', '全部') }}</button>
            <button v-if="communityNodes.length" class="nfp-chip" @click="showAll('community')">社区 {{ communityNodes.length - communityNodes.filter(n => props.hiddenIds.has(n.id)).length }}/{{ communityNodes.length }}</button>
            <button v-if="communityNodes.length" class="nfp-chip nfp-chip-off" @click="hideAll('community')">隐藏社区</button>
            <button v-if="externalNodes.length" class="nfp-chip" @click="showAll('external')">外部 {{ externalNodes.length - externalNodes.filter(n => props.hiddenIds.has(n.id)).length }}/{{ externalNodes.length }}</button>
            <button v-if="externalNodes.length" class="nfp-chip nfp-chip-off" @click="hideAll('external')">隐藏外部</button>
          </div>
        </div>

        <!-- 按大小分组 -->
        <div class="nfp-group">
          <div class="nfp-group-title">大小</div>
          <div class="nfp-group-row">
            <button class="nfp-chip" @click="hideByComputed(smallNodes)" :title="'≤25%分位(' + ((sizePcts.p25 || 0) > 1 ? Math.round(sizePcts.p25) : (sizePcts.p25 || 0).toFixed(1)) + ')'">小 ≤25% {{ smallNodes.length }}</button>
            <button class="nfp-chip" @click="hideByComputed(mediumNodes)" :title="'25%-75%分位'">中 25-75% {{ mediumNodes.length }}</button>
            <button v-if="largeNodes.length" class="nfp-chip" @click="hideByComputed(largeNodes)" :title="'≥75%分位(' + ((sizePcts.p75 || 0) > 1 ? Math.round(sizePcts.p75) : (sizePcts.p75 || 0).toFixed(1)) + ')'">大 ≥75% {{ largeNodes.length }}</button>
            <button class="nfp-chip nfp-chip-off" @click="selectAll">恢复全部</button>
          </div>
        </div>

        <!-- 按质量分组（仅社区） -->
        <div v-if="poorQuality.length || midQuality.length || goodQuality.length" class="nfp-group">
          <div class="nfp-group-title">质量</div>
          <div class="nfp-group-row">
            <button v-if="poorQuality.length" class="nfp-chip" @click="hideByComputed(poorQuality)" :title="'≤25%分位(' + (qualityPcts.p25 || 0).toFixed(2) + ')'">差 ≤25% {{ poorQuality.length }}</button>
            <button v-if="midQuality.length" class="nfp-chip" @click="hideByComputed(midQuality)" :title="'25%-75%分位'">中 25-75% {{ midQuality.length }}</button>
            <button v-if="goodQuality.length" class="nfp-chip" @click="hideByComputed(goodQuality)" :title="'≥75%分位(' + (qualityPcts.p75 || 0).toFixed(2) + ')'">优 ≥75% {{ goodQuality.length }}</button>
          </div>
        </div>

        <!-- 社区节点列表 -->
        <div v-if="communityNodes.length > 0" class="nfp-group">
          <div class="nfp-group-title">社区 ({{ communityNodes.length - communityNodes.filter(n => props.hiddenIds.has(n.id)).length }}/{{ communityNodes.length }})</div>
          <div class="nfp-sort-row">
            <button v-for="sk in communitySortKeys" :key="sk.key" class="nfp-sort-btn" :class="{ active: sortKey === sk.key }" @click="toggleSort(sk.key)">{{ sk.label }}{{ sortKey === sk.key ? (sortDir === 1 ? '↓' : '↑') : '' }}</button>
          </div>
          <div class="nfp-ext-list">
            <label v-for="n in sortedCommunityNodes.slice(0, 20)" :key="n.id" class="nfp-ext-item" :class="{ hidden: props.hiddenIds.has(n.id) }">
              <input type="checkbox" :checked="!props.hiddenIds.has(n.id)" @change="toggle(n.id)">
              <span class="nfp-ext-label" :title="n.label">{{ n.label.length > 16 ? n.label.slice(0, 16) + '\u2026' : n.label }}</span>
              <span class="nfp-ext-stat">I{{ n.inDegree ?? 0 }}</span>
              <span class="nfp-ext-stat">O{{ n.outDegree ?? 0 }}</span>
              <span class="nfp-ext-stat nfp-ext-stat-strong">{{ n.nodeCount ?? 0 }}</span>
            </label>
            <div v-if="communityNodes.length > 20" class="nfp-ext-more">还有 {{ communityNodes.length - 20 }} 个...</div>
          </div>
        </div>

        <!-- 外部节点列表 -->
        <div v-if="externalNodes.length > 0" class="nfp-group">
          <div class="nfp-group-title">外部包 (引用数降序)</div>
          <div class="nfp-ext-list">
            <label v-for="n in sortByInDegree(externalNodes).slice(0, 15)" :key="n.id" class="nfp-ext-item" :class="{ hidden: props.hiddenIds.has(n.id) }">
              <input type="checkbox" :checked="!props.hiddenIds.has(n.id)" @change="toggle(n.id)">
              <span class="nfp-ext-label">{{ n.label.length > 18 ? n.label.slice(0, 18) + '\u2026' : n.label }}</span>
              <span class="nfp-ext-count">{{ n.nodeCount || 0 }}</span>
            </label>
          </div>
        </div>

        <!-- 搜索匹配列表 -->
        <div v-if="search && filtered.length" class="nfp-group">
          <div class="nfp-group-title">搜索匹配 ({{ filtered.length }})</div>
          <div class="nfp-ext-list">
            <label v-for="n in filtered.slice(0, 30)" :key="n.id" class="nfp-ext-item" :class="{ hidden: props.hiddenIds.has(n.id) }">
              <input type="checkbox" :checked="!props.hiddenIds.has(n.id)" @change="toggle(n.id)">
              <span class="nfp-ext-label">{{ n.label.length > 22 ? n.label.slice(0, 22) + '\u2026' : n.label }}</span>
            </label>
          </div>
        </div>
        <div v-if="search && filtered.length === 0" class="nfp-empty">{{ t('report.noSearchResults', '无匹配') }}</div>

        <!-- 底部操作栏 -->
        <div class="nfp-footer">
          <span class="nfp-footer-info">{{ hiddenCount }} 隐藏</span>
          <button class="nfp-footer-btn" @click="resetHidden">{{ t('report.resetFilter', '重置') }}</button>
          <button class="nfp-footer-btn nfp-footer-btn-primary" @click="emit('connect-complete')">{{ t('report.connectComplete', '补全连接') }}</button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.nfp-backdrop { position: fixed; inset: 0; z-index: 499; }
.nfp-overlay { position: fixed; z-index: 500; user-select: none; pointer-events: auto; }
.nfp-overlay.dragging { cursor: grabbing; }
.nfp-panel {
  width: 280px; max-height: 480px; display: flex; flex-direction: column;
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: 0.5rem; box-shadow: 0 4px 16px rgba(0,0,0,0.35); overflow: hidden;
}
.nfp-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.35rem 0.6rem; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border); flex-shrink: 0; cursor: grab; user-select: none;
}
.nfp-header:active { cursor: grabbing; }
.nfp-title { font-size: 0.75rem; font-weight: 600; color: var(--text-primary); }
.nfp-header-actions { display: flex; align-items: center; gap: 0.15rem; }
.nfp-icon-btn { display: flex; align-items: center; padding: 0.12rem; background: none; border: 1px solid transparent; color: var(--text-muted); cursor: pointer; border-radius: 0.2rem; }
.nfp-icon-btn:hover { color: var(--text-primary); background: var(--bg-tertiary); border-color: var(--border); }
.nfp-icon-btn.active { color: var(--accent, #7c3aed); background: var(--bg-accent-subtle, #2d1f5e); border-color: var(--accent, #7c3aed); }
.nfp-search { padding: 0.3rem 0.5rem; flex-shrink: 0; }
.nfp-search-input { width: 100%; padding: 0.18rem 0.4rem; font-size: 0.7rem; box-sizing: border-box; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 0.25rem; color: var(--text-primary); outline: none; }
.nfp-search-input:focus { border-color: var(--accent); }
.nfp-group { padding: 0.2rem 0.5rem; border-bottom: 1px solid var(--border); flex-shrink: 0; }
.nfp-group-title { font-size: 0.62rem; color: var(--text-muted); margin-bottom: 0.15rem; text-transform: uppercase; letter-spacing: 0.03em; }
.nfp-group-row { display: flex; flex-wrap: wrap; gap: 0.2rem; }
.nfp-chip {
  padding: 0.08rem 0.35rem; font-size: 0.65rem; color: var(--text-muted);
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.2rem; cursor: pointer; transition: all 0.1s;
}
.nfp-chip:hover { border-color: var(--accent); color: var(--text-primary); }
.nfp-chip-off { opacity: 0.7; }
.nfp-chip-off:hover { opacity: 1; }
.nfp-ext-list { max-height: 120px; overflow-y: auto; }
.nfp-ext-item { display: flex; align-items: center; gap: 0.3rem; padding: 0.1rem 0; cursor: pointer; }
.nfp-ext-item:hover { background: var(--bg-secondary); }
.nfp-ext-item.hidden { opacity: 0.35; }
.nfp-ext-item input[type="checkbox"] { width: 11px; height: 11px; margin: 0; cursor: pointer; accent-color: var(--accent, #7c3aed); }
.nfp-ext-label { font-size: 0.65rem; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nfp-ext-count { font-size: 0.58rem; color: var(--text-muted); font-family: var(--font-mono); flex-shrink: 0; }
.nfp-ext-stat { font-size: 0.55rem; color: var(--text-muted); font-family: var(--font-mono); flex-shrink: 0; min-width: 18px; text-align: right; }
.nfp-ext-stat-strong { color: var(--text-primary); font-weight: 600; }
.nfp-sort-row { display: flex; gap: 0.15rem; margin-bottom: 0.2rem; }
.nfp-sort-btn { padding: 0.06rem 0.3rem; font-size: 0.58rem; color: var(--text-muted); background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 0.2rem; cursor: pointer; transition: all 0.1s; }
.nfp-sort-btn:hover { border-color: var(--accent); color: var(--text-primary); }
.nfp-sort-btn.active { border-color: var(--accent); color: var(--accent); }
.nfp-empty { font-size: 0.7rem; color: var(--text-muted); text-align: center; padding: 0.4rem; font-style: italic; }
.nfp-ext-more { font-size: 0.58rem; color: var(--text-muted); text-align: center; padding: 0.15rem 0; }
.nfp-footer {
  display: flex; align-items: center; gap: 0.35rem;
  padding: 0.3rem 0.5rem; border-top: 1px solid var(--border); flex-shrink: 0;
}
.nfp-footer-info { font-size: 0.65rem; color: var(--text-muted); flex: 1; }
.nfp-footer-btn {
  padding: 0.12rem 0.4rem; font-size: 0.65rem; color: var(--text-muted);
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.2rem; cursor: pointer;
}
.nfp-footer-btn:hover { border-color: var(--accent); color: var(--text-primary); }
.nfp-footer-btn-primary { background: var(--accent, #7c3aed); color: #fff; border-color: var(--accent); }
.nfp-footer-btn-primary:hover { opacity: 0.9; }
</style>
