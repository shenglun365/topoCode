<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, CheckIcon, ArrowsPointingInIcon, ArrowDownTrayIcon } from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'

interface FilterNode {
  id: string
  label: string
  nodeCount?: number
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
const PW = 260

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
  const ph = Math.min(420, window.innerHeight * 0.6)

  let top = cy - ph / 2
  let left = cx + 12

  if (left + PW > area.right) {
    left = cx - PW - 12
  }
  if (left < area.left) {
    left = area.left
  }
  if (top < area.top) {
    top = area.top
  }
  if (top + ph > area.bottom) {
    top = area.bottom - ph
  }

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
  panelX.value = dragStartPX.value + e.clientX - dragStartX.value
  panelY.value = dragStartPY.value + e.clientY - dragStartY.value
}

function onMouseUp() {
  dragging.value = false
}

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

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return props.nodes
  return props.nodes.filter(n =>
    n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q)
  )
})

function isHidden(id: string): boolean {
  return props.hiddenIds.has(id)
}

function toggle(id: string) {
  const next = new Set(props.hiddenIds)
  if (next.has(id)) { next.delete(id) } else { next.add(id) }
  emit('update:hiddenIds', next)
}

function selectAll() { emit('update:hiddenIds', new Set()) }
function deselectAll() { emit('update:hiddenIds', new Set(props.nodes.map(n => n.id))) }
function invert() {
  const next = new Set<string>()
  for (const n of props.nodes) { if (!props.hiddenIds.has(n.id)) next.add(n.id) }
  emit('update:hiddenIds', next)
}
</script>

<template>
  <teleport to="body">
    <div v-if="visible && !pinned" class="nfp-backdrop" @click="emit('close')" />
    <div
      v-if="visible"
      class="nfp-overlay"
      :style="{ left: panelX + 'px', top: panelY + 'px' }"
      :class="{ dragging }"
    >
      <div class="nfp-panel">
        <div class="nfp-header" @mousedown="onHeaderMouseDown">
          <span class="nfp-title">{{ t('report.nodeFilter', '节点筛选') }} ({{ props.nodes.length - props.hiddenIds.size }}/{{ props.nodes.length }})</span>
          <div class="nfp-header-actions">
            <button
              class="nfp-icon-btn"
              :class="{ active: pinned }"
              :title="t('report.pinPanel', '常驻')"
              @click="pinned = !pinned"
            >
              <ArrowDownTrayIcon class="w-3 h-3" />
            </button>
            <button class="nfp-icon-btn" @click="emit('close')">
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        <div class="nfp-search">
          <input v-model="search" type="text" :placeholder="t('report.searchCommunity', '搜索...')" class="nfp-search-input" />
        </div>
        <div class="nfp-actions">
          <button class="nfp-action-btn" @click="selectAll"><CheckIcon class="w-3 h-3" /> {{ t('report.selectAll', '全选') }}</button>
          <button class="nfp-action-btn" @click="deselectAll">{{ t('report.invertSelect', '取消') }}</button>
          <button class="nfp-action-btn" @click="invert">{{ t('report.invert', '反选') }}</button>
          <span class="nfp-count">{{ props.hiddenIds.size }} {{ t('report.hidden', '隐藏') }}</span>
        </div>
        <div class="nfp-list">
          <label v-for="n in filtered" :key="n.id" class="nfp-item" :class="{ hidden: isHidden(n.id) }">
            <input type="checkbox" :checked="!isHidden(n.id)" @change="toggle(n.id)" />
            <span class="nfp-label">{{ n.label.length > 22 ? n.label.slice(0, 22) + '\u2026' : n.label }}</span>
            <span v-if="n.nodeCount" class="nfp-count-badge">{{ n.nodeCount }}</span>
          </label>
          <div v-if="filtered.length === 0" class="nfp-empty">{{ t('report.noSearchResults', '无匹配') }}</div>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.nfp-backdrop { position: fixed; inset: 0; z-index: 499; }
.nfp-overlay {
  position: fixed; z-index: 500; user-select: none;
  pointer-events: auto;
}
.nfp-overlay.dragging { cursor: grabbing; }
.nfp-panel {
  width: 260px; max-height: 420px; display: flex; flex-direction: column;
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: 0.5rem; box-shadow: 0 4px 16px rgba(0,0,0,0.35); overflow: hidden;
}
.nfp-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.35rem 0.6rem; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border); flex-shrink: 0; cursor: grab;
  user-select: none;
}
.nfp-header:active { cursor: grabbing; }
.nfp-title { font-size: 0.75rem; font-weight: 600; color: var(--text-primary); }
.nfp-header-actions { display: flex; align-items: center; gap: 0.15rem; }
.nfp-icon-btn {
  display: flex; align-items: center; padding: 0.12rem;
  background: none; border: 1px solid transparent; color: var(--text-muted); cursor: pointer;
  border-radius: 0.2rem;
}
.nfp-icon-btn:hover { color: var(--text-primary); background: var(--bg-tertiary); border-color: var(--border); }
.nfp-icon-btn.active { color: var(--accent, #7c3aed); background: var(--bg-accent-subtle, #2d1f5e); border-color: var(--accent, #7c3aed); }

.nfp-search { padding: 0.3rem 0.5rem; flex-shrink: 0; }
.nfp-search-input {
  width: 100%; padding: 0.18rem 0.4rem; font-size: 0.7rem; box-sizing: border-box;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.25rem; color: var(--text-primary); outline: none;
}
.nfp-search-input:focus { border-color: var(--accent); }

.nfp-actions {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.2rem 0.5rem; border-bottom: 1px solid var(--border); flex-shrink: 0; flex-wrap: wrap;
}
.nfp-action-btn {
  display: flex; align-items: center; gap: 0.12rem;
  padding: 0.1rem 0.35rem; font-size: 0.65rem; color: var(--text-muted);
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.25rem; cursor: pointer;
}
.nfp-action-btn:hover { color: var(--text-primary); border-color: var(--accent); }
.nfp-count { font-size: 0.65rem; color: var(--text-muted); margin-left: auto; }

.nfp-list { flex: 1; overflow-y: auto; padding: 0.2rem 0; }
.nfp-item {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.12rem 0.5rem; cursor: pointer;
}
.nfp-item:hover { background: var(--bg-secondary); }
.nfp-item.hidden { opacity: 0.4; }
.nfp-item input[type="checkbox"] { width: 12px; height: 12px; margin: 0; cursor: pointer; accent-color: var(--accent, #7c3aed); }
.nfp-label { font-size: 0.68rem; color: var(--text-primary); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nfp-count-badge { font-size: 0.6rem; color: var(--text-muted); font-family: var(--font-mono); background: var(--bg-tertiary); border-radius: 0.2rem; padding: 0.02rem 0.22rem; flex-shrink: 0; }
.nfp-empty { font-size: 0.7rem; color: var(--text-muted); text-align: center; padding: 0.5rem; font-style: italic; }
</style>
