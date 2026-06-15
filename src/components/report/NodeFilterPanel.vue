<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, ArrowDownTrayIcon } from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'

/* ---- size thresholds ---- */
const SIZE_LARGE = 30
const SIZE_SMALL = 5

/* ---- quality thresholds ---- */
const QUAL_HIGH = 0.5
const QUAL_LOW = 0.2

/* ---- coreness threshold ---- */
const CORE_THRESHOLD = 3

interface FilterNode {
  id: string
  label: string
  nodeCount?: number
  type?: 'community' | 'external'
  qualityScore?: number | null
  avgCoreness?: number | null
  maxCoreness?: number | null
  inDegree?: number
  outDegree?: number
}

const props = defineProps<{
  nodes: FilterNode[]
  hiddenIds: Set<string>
  search?: string
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

const pinned = ref(false)
const panelX = ref(0)
const panelY = ref(0)
const dragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const dragStartPX = ref(0)
const dragStartPY = ref(0)
const PW = 300

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
  const ph = Math.min(520, window.innerHeight * 0.7)
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
  panelY.value = Math.max(area.top, Math.min(area.bottom - 520, dragStartPY.value + e.clientY - dragStartY.value))
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

/* ---- basic groupings ---- */
const communityNodes = computed(() => props.nodes.filter(n => n.type !== 'external'))
const externalNodes = computed(() => props.nodes.filter(n => n.type === 'external'))
const hiddenCount = computed(() => props.hiddenIds.size)

/* ---- search filtered list ---- */
const searchQ = computed(() => (props.search || '').trim().toLowerCase())
const searchFiltered = computed(() => {
  const q = searchQ.value
  if (!q) return props.nodes
  return props.nodes.filter(n =>
    n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q)
  )
})

/* ---- fixed-threshold groups ---- */
const largeNodes = computed(() => props.nodes.filter(n => (n.nodeCount || 0) > SIZE_LARGE))
const mediumNodes = computed(() => props.nodes.filter(n => (n.nodeCount || 0) > SIZE_SMALL && (n.nodeCount || 0) <= SIZE_LARGE))
const smallNodes = computed(() => props.nodes.filter(n => (n.nodeCount || 0) <= SIZE_SMALL))

const highQuality = computed(() => props.nodes.filter(n => n.qualityScore != null && n.qualityScore >= QUAL_HIGH))
const midQuality = computed(() => props.nodes.filter(n => n.qualityScore != null && n.qualityScore > QUAL_LOW && n.qualityScore < QUAL_HIGH))
const poorQuality = computed(() => props.nodes.filter(n => n.qualityScore != null && n.qualityScore <= QUAL_LOW))

const coreNodes = computed(() => props.nodes.filter(n => n.avgCoreness != null && n.avgCoreness >= CORE_THRESHOLD))
const peripheralNodes = computed(() => props.nodes.filter(n => n.avgCoreness != null && n.avgCoreness < CORE_THRESHOLD))

/* ---- diagnostic ---- */
const lowQualityComms = computed(() =>
  props.nodes.filter(n => n.type !== 'external' && n.qualityScore != null && n.qualityScore < 0.3)
)
const highCoreComms = computed(() =>
  props.nodes.filter(n => n.type !== 'external' && n.avgCoreness != null && n.avgCoreness >= 3)
)
const isolatedComms = computed(() =>
  props.nodes.filter(n => n.type !== 'external' && (n.inDegree || 0) + (n.outDegree || 0) === 0)
)
const hotDepComms = computed(() => {
  const communities = props.nodes.filter(n => n.type !== 'external' && n.inDegree != null && n.inDegree > 0)
  if (communities.length === 0) return []
  const sorted = [...communities].sort((a, b) => (b.inDegree! - a.inDegree!))
  const cutoff = Math.max(1, Math.ceil(sorted.length * 0.2))
  return sorted.slice(0, cutoff)
})

/* ---- sort ---- */
type SortKey = 'name' | 'inDeg' | 'outDeg' | 'count'
const sortKey = ref<SortKey>('name')
const sortDir = ref<1 | -1>(1)

const sortKeys: { key: SortKey; label: string }[] = [
  { key: 'name', label: '名称' },
  { key: 'inDeg', label: '入度' },
  { key: 'outDeg', label: '出度' },
  { key: 'count', label: '成员' },
]

function toggleSort(key: SortKey) {
  if (sortKey.value === key) { sortDir.value = sortDir.value === 1 ? -1 : 1 }
  else { sortKey.value = key; sortDir.value = 1 }
}

const displayList = computed(() => {
  const list = searchQ.value ? [...searchFiltered.value] : [...props.nodes]
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

/* ---- actions ---- */
function toggle(id: string) {
  const next = new Set(props.hiddenIds)
  if (next.has(id)) { next.delete(id) } else { next.add(id) }
  emit('update:hiddenIds', next)
}

function selectAll() { emit('update:hiddenIds', new Set()) }

function hideNodes(list: FilterNode[]) {
  const next = new Set(props.hiddenIds)
  for (const n of list) next.add(n.id)
  emit('update:hiddenIds', next)
}

function showNodes(list: FilterNode[]) {
  const next = new Set(props.hiddenIds)
  for (const n of list) next.delete(n.id)
  emit('update:hiddenIds', next)
}

function focusNodes(list: FilterNode[]) {
  const focusIds = new Set(list.map(n => n.id))
  const next = new Set<string>()
  for (const n of props.nodes) {
    if (!focusIds.has(n.id)) next.add(n.id)
  }
  emit('update:hiddenIds', next)
}

function hideOthers(list: FilterNode[]) {
  const keepIds = new Set(list.map(n => n.id))
  const next = new Set<string>()
  for (const n of props.nodes) {
    if (!keepIds.has(n.id)) next.add(n.id)
  }
  emit('update:hiddenIds', next)
}

/* ---- type row: radio-like ---- */
function showType(type: 'all' | 'community' | 'external') {
  if (type === 'all') { selectAll(); return }
  const toHide = type === 'community' ? externalNodes.value : communityNodes.value
  const toShow = type === 'community' ? communityNodes.value : externalNodes.value
  const next = new Set(props.hiddenIds)
  for (const n of toHide) next.add(n.id)
  for (const n of toShow) next.delete(n.id)
  emit('update:hiddenIds', next)
}

function activeType(): 'all' | 'community' | 'external' {
  const extHidden = externalNodes.value.filter(n => props.hiddenIds.has(n.id)).length
  const commHidden = communityNodes.value.filter(n => props.hiddenIds.has(n.id)).length
  if (commHidden > 0 && extHidden === 0) return 'community'
  if (extHidden > 0 && commHidden === 0) return 'external'
  return 'all'
}
</script>

<template>
  <teleport to="body">
    <div v-if="visible && !pinned" class="nfp-backdrop" @click="emit('close')" />
    <div v-if="visible" class="nfp-overlay" :style="{ left: panelX + 'px', top: panelY + 'px' }" :class="{ dragging }">
      <div class="nfp-panel">
        <div class="nfp-header" @mousedown="onHeaderMouseDown">
          <span class="nfp-title">{{ t('report.nodeFilter', '筛选') }} ({{ nodes.length - hiddenCount }}/{{ nodes.length }})</span>
          <div class="nfp-header-actions">
            <button class="nfp-icon-btn" :class="{ active: pinned }" :title="t('report.pinPanel', '常驻')" @click="pinned = !pinned">
              <ArrowDownTrayIcon class="w-3 h-3" />
            </button>
            <button class="nfp-icon-btn" @click="emit('close')">
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <!-- Zone 1: 分类过滤 -->
        <div class="nfp-body">
          <div class="nfp-section">
            <div class="nfp-section-title">分类过滤</div>

            <!-- type row -->
            <div class="nfp-chip-row">
              <button class="nfp-chip" :class="{ active: activeType() === 'all' }" @click="showType('all')">全部</button>
              <button class="nfp-chip" :class="{ active: activeType() === 'community' }" @click="showType('community')">社区 {{ communityNodes.length }}</button>
              <button class="nfp-chip" :class="{ active: activeType() === 'external' }" @click="showType('external')">外部包 {{ externalNodes.length }}</button>
            </div>

            <!-- size row -->
            <div class="nfp-chip-row">
              <button class="nfp-chip" @click="selectAll">全部</button>
              <button class="nfp-chip" @click="hideOthers(largeNodes)" :title="'节点数 > ' + SIZE_LARGE">大型&gt;{{ SIZE_LARGE }} {{ largeNodes.length }}</button>
              <button class="nfp-chip" @click="hideOthers(mediumNodes)" :title="'节点数 ' + (SIZE_SMALL + 1) + '-' + SIZE_LARGE">中型 {{ mediumNodes.length }}</button>
              <button class="nfp-chip" @click="hideOthers(smallNodes)" :title="'节点数 ≤ ' + SIZE_SMALL">小型≤{{ SIZE_SMALL }} {{ smallNodes.length }}</button>
            </div>

            <!-- quality row -->
            <div class="nfp-chip-row">
              <button class="nfp-chip" @click="selectAll">全部</button>
              <button class="nfp-chip" @click="hideOthers(highQuality)" :title="'质量分 ≥ ' + QUAL_HIGH">高质量≥{{ QUAL_HIGH }} {{ highQuality.length }}</button>
              <button class="nfp-chip" @click="hideOthers(midQuality)" :title="'质量分 ' + QUAL_LOW + '-' + QUAL_HIGH">中等 {{ midQuality.length }}</button>
              <button class="nfp-chip" @click="hideOthers(poorQuality)" :title="'质量分 ≤ ' + QUAL_LOW">差≤{{ QUAL_LOW }} {{ poorQuality.length }}</button>
            </div>

            <!-- coreness row -->
            <div class="nfp-chip-row">
              <button class="nfp-chip" @click="selectAll">全部</button>
              <button class="nfp-chip" @click="hideOthers(coreNodes)" :title="'平均核心度 ≥ ' + CORE_THRESHOLD">核心≥{{ CORE_THRESHOLD }} {{ coreNodes.length }}</button>
              <button class="nfp-chip" @click="hideOthers(peripheralNodes)" :title="'平均核心度 < ' + CORE_THRESHOLD">外围 {{ peripheralNodes.length }}</button>
            </div>

            <!-- quick actions -->
            <div class="nfp-chip-row nfp-chip-row-actions">
              <button class="nfp-chip nfp-chip-action" @click="hideNodes(externalNodes)">隐藏外部包</button>
              <button class="nfp-chip nfp-chip-action" @click="hideOthers(largeNodes)">只显示大型社区</button>
            </div>
          </div>

          <!-- Zone 2: 个体列表 -->
          <div class="nfp-section">
            <div class="nfp-section-title">节点列表</div>
            <div class="nfp-sort-row">
              <button class="nfp-chip" @click="selectAll">全部选中</button>
              <button class="nfp-chip nfp-chip-action" @click="emit('update:hiddenIds', new Set(props.nodes.map(n => n.id)))">全部隐藏</button>
              <span class="nfp-sort-spacer" />
              <button v-for="sk in sortKeys" :key="sk.key" class="nfp-sort-btn" :class="{ active: sortKey === sk.key }" @click="toggleSort(sk.key)">{{ sk.label }}{{ sortKey === sk.key ? (sortDir === 1 ? '↓' : '↑') : '' }}</button>
            </div>
            <div class="nfp-ext-list">
              <label v-for="n in displayList.slice(0, 50)" :key="n.id" class="nfp-ext-item" :class="{ hidden: props.hiddenIds.has(n.id), match: searchQ && (n.label.toLowerCase().includes(searchQ) || n.id.toLowerCase().includes(searchQ)) }">
                <input type="checkbox" :checked="!props.hiddenIds.has(n.id)" @change="toggle(n.id)">
                <span class="nfp-ext-label" :title="n.label">{{ n.label.length > 18 ? n.label.slice(0, 18) + '\u2026' : n.label }}</span>
                <span class="nfp-ext-stat">I{{ n.inDegree ?? 0 }}</span>
                <span class="nfp-ext-stat">O{{ n.outDegree ?? 0 }}</span>
                <span class="nfp-ext-stat nfp-ext-stat-strong">{{ n.nodeCount ?? 0 }}</span>
              </label>
              <div v-if="displayList.length > 50" class="nfp-ext-more">还有 {{ displayList.length - 50 }} 个...</div>
            </div>
          </div>

          <!-- Zone 3: 诊断 -->
          <div v-if="lowQualityComms.length || highCoreComms.length || isolatedComms.length || hotDepComms.length" class="nfp-section">
            <div class="nfp-section-title">诊断</div>

            <div v-if="lowQualityComms.length" class="nfp-diag-row">
              <span class="nfp-diag-label">&#x26A0; 低质量社区 ({{ lowQualityComms.length }})</span>
              <button class="nfp-chip nfp-chip-diag" @click="showNodes(lowQualityComms)">显示</button>
              <button class="nfp-chip nfp-chip-diag" @click="focusNodes(lowQualityComms)">聚焦</button>
            </div>
            <div v-if="highCoreComms.length" class="nfp-diag-row">
              <span class="nfp-diag-label">&#x26A1; 高核心节点 ({{ highCoreComms.length }})</span>
              <button class="nfp-chip nfp-chip-diag" @click="showNodes(highCoreComms)">显示</button>
              <button class="nfp-chip nfp-chip-diag" @click="focusNodes(highCoreComms)">聚焦</button>
            </div>
            <div v-if="isolatedComms.length" class="nfp-diag-row">
              <span class="nfp-diag-label">&#x1F517; 孤立社区 ({{ isolatedComms.length }})</span>
              <button class="nfp-chip nfp-chip-diag" @click="showNodes(isolatedComms)">显示</button>
              <button class="nfp-chip nfp-chip-diag" @click="focusNodes(isolatedComms)">聚焦</button>
            </div>
            <div v-if="hotDepComms.length" class="nfp-diag-row">
              <span class="nfp-diag-label">&#x1F4E6; 依赖热点 ({{ hotDepComms.length }})</span>
              <button class="nfp-chip nfp-chip-diag" @click="showNodes(hotDepComms)">显示</button>
              <button class="nfp-chip nfp-chip-diag" @click="focusNodes(hotDepComms)">聚焦</button>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="nfp-footer">
          <span class="nfp-footer-info">{{ hiddenCount }} 隐藏</span>
          <button class="nfp-footer-btn" @click="selectAll">{{ t('report.resetFilter', '重置') }}</button>
          <button class="nfp-footer-btn nfp-footer-btn-primary" @click="emit('connect-complete')">显示关联节点</button>
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
  width: 300px; max-height: 520px; display: flex; flex-direction: column;
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

.nfp-body { overflow-y: auto; flex: 1; }

.nfp-section {
  padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--border);
}
.nfp-section:last-child { border-bottom: none; }
.nfp-section-title {
  font-size: 0.62rem; color: var(--text-muted); margin-bottom: 0.2rem;
  text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600;
}

.nfp-chip-row {
  display: flex; flex-wrap: wrap; gap: 0.2rem; margin-bottom: 0.25rem;
}
.nfp-chip-row:last-child { margin-bottom: 0; }
.nfp-chip-row-actions { border-top: 1px dashed var(--border); padding-top: 0.25rem; margin-top: 0.1rem; }

.nfp-chip {
  padding: 0.08rem 0.35rem; font-size: 0.63rem; color: var(--text-muted);
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.2rem; cursor: pointer; transition: all 0.1s; white-space: nowrap;
}
.nfp-chip:hover { border-color: var(--accent); color: var(--text-primary); }
.nfp-chip.active { background: var(--bg-accent-subtle, #2d1f5e); border-color: var(--accent); color: var(--accent); }
.nfp-chip-action { opacity: 0.75; font-style: italic; }
.nfp-chip-action:hover { opacity: 1; }
.nfp-chip-diag { font-size: 0.6rem; padding: 0.06rem 0.3rem; }

.nfp-sort-spacer { flex: 1; }

.nfp-sort-row {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.15rem; margin-bottom: 0.25rem;
}
.nfp-sort-btn {
  padding: 0.06rem 0.3rem; font-size: 0.58rem; color: var(--text-muted);
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.2rem; cursor: pointer; transition: all 0.1s;
}
.nfp-sort-btn:hover { border-color: var(--accent); color: var(--text-primary); }
.nfp-sort-btn.active { border-color: var(--accent); color: var(--accent); }

.nfp-ext-list { max-height: 160px; overflow-y: auto; }
.nfp-ext-item {
  display: flex; align-items: center; gap: 0.3rem; padding: 0.1rem 0; cursor: pointer;
}
.nfp-ext-item:hover { background: var(--bg-secondary); }
.nfp-ext-item.hidden { opacity: 0.35; }
.nfp-ext-item.match { background: var(--bg-accent-subtle, #2d1f5e); border-radius: 0.15rem; }
.nfp-ext-item input[type="checkbox"] { width: 11px; height: 11px; margin: 0; cursor: pointer; accent-color: var(--accent, #7c3aed); flex-shrink: 0; }
.nfp-ext-label {
  font-size: 0.65rem; color: var(--text-primary); flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.nfp-ext-count { font-size: 0.58rem; color: var(--text-muted); font-family: var(--font-mono); flex-shrink: 0; }
.nfp-ext-stat {
  font-size: 0.55rem; color: var(--text-muted); font-family: var(--font-mono);
  flex-shrink: 0; min-width: 18px; text-align: right;
}
.nfp-ext-stat-strong { color: var(--text-primary); font-weight: 600; }
.nfp-ext-more { font-size: 0.58rem; color: var(--text-muted); text-align: center; padding: 0.15rem 0; }

.nfp-diag-row {
  display: flex; align-items: center; gap: 0.3rem; padding: 0.15rem 0;
}
.nfp-diag-label { font-size: 0.65rem; color: var(--text-muted); flex: 1; }

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
