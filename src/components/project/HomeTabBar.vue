<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import {
  XMarkIcon,
  DocumentTextIcon,
  ListBulletIcon,
  PlusCircleIcon,
  ChartBarIcon,
  DocumentDuplicateIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import type { HomeTab } from '@/stores/project'
import { useFuncGroupStore } from '@/stores/funcGroup'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-007')
const props = defineProps<{
  tabs: HomeTab[]
  activeTabId: string | null
}>()

const emit = defineEmits<{
  'update:activeTabId': [tabId: string | null]
  'close': [tabId: string]
}>()

const funcGroup = useFuncGroupStore()

function getTabIcon(tab: HomeTab) {
  switch (tab.kind) {
    case 'taskList': return ListBulletIcon
    case 'taskCreate': return PlusCircleIcon
    case 'report': return ChartBarIcon
    case 'reportHome': return DocumentTextIcon
    case 'subdoc': return DocumentDuplicateIcon
    default: return DocumentTextIcon
  }
}

const scrollRef = ref<HTMLElement | null>(null)
const canScrollLeft = ref(false)
const canScrollRight = ref(false)

let resizeObserver: ResizeObserver | null = null

function updateScrollButtons() {
  const el = scrollRef.value
  if (!el) {
    canScrollLeft.value = false
    canScrollRight.value = false
    return
  }
  canScrollLeft.value = el.scrollLeft > 2
  canScrollRight.value = el.scrollLeft < el.scrollWidth - el.clientWidth - 2
}

function scrollTabs(dir: 'left' | 'right') {
  const el = scrollRef.value
  if (!el) return
  const tab = el.querySelector<HTMLElement>('.home-tab')
  const step = tab ? tab.offsetWidth : 100
  el.scrollBy({ left: dir === 'left' ? -step : step, behavior: 'smooth' })
}

function onScroll() {
  updateScrollButtons()
}

// ── 拖拽排序 ──
const dragIdx = ref(-1)
const dropTargetIdx = ref(-1)

function onDragStart(e: DragEvent, idx: number) {
  dragIdx.value = idx
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(idx))
  }
}

function onDragOver(e: DragEvent, idx: number) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  dropTargetIdx.value = idx
}

function onDragLeave() {
  dropTargetIdx.value = -1
}

function onDrop(e: DragEvent, toIdx: number) {
  e.preventDefault()
  const from = dragIdx.value
  if (from >= 0 && from !== toIdx) {
    funcGroup.moveTab('analysis', from, toIdx)
  }
  dragIdx.value = -1
  dropTargetIdx.value = -1
}

function onDragEnd() {
  dragIdx.value = -1
  dropTargetIdx.value = -1
}

// ── tab 增删时重新检测溢出 ──
watch(() => props.tabs.length, () => {
  nextTick(() => updateScrollButtons())
})

onMounted(() => {
  nextTick(() => updateScrollButtons())
  try {
    resizeObserver = new ResizeObserver(() => updateScrollButtons())
    if (scrollRef.value) resizeObserver.observe(scrollRef.value)
  } catch (_) {}
})

onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
})
</script>

<template>
  <div class="home-tab-bar-wrapper">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <button
      v-if="canScrollLeft"
      class="scroll-btn scroll-left"
      title="Scroll left"
      @click="scrollTabs('left')"
    >
      <ChevronLeftIcon class="w-4 h-4" />
    </button>

    <div
      ref="scrollRef"
      class="home-tab-bar"
      @scroll="onScroll"
    >
      <div
        v-for="(tab, idx) in tabs"
        :key="tab.id"
        class="home-tab"
        :class="{
          active: activeTabId === tab.id,
          'drag-over-left': dropTargetIdx === idx && dragIdx > idx,
          'drag-over-right': dropTargetIdx === idx && dragIdx < idx,
        }"
        draggable="true"
        @click="emit('update:activeTabId', tab.id)"
        @dragstart="onDragStart($event, idx)"
        @dragover="onDragOver($event, idx)"
        @dragleave="onDragLeave"
        @drop="onDrop($event, idx)"
        @dragend="onDragEnd"
      >
        <component
          :is="getTabIcon(tab)"
          class="w-3.5 h-3.5 tab-icon"
        />
        <span class="tab-title">{{ tab.title }}</span>
        <button
          class="tab-close-btn"
          @click.stop="emit('close', tab.id)"
        >
          <XMarkIcon class="w-3 h-3" />
        </button>
      </div>
    </div>

    <button
      v-if="canScrollRight"
      class="scroll-btn scroll-right"
      title="Scroll right"
      @click="scrollTabs('right')"
    >
      <ChevronRightIcon class="w-4 h-4" />
    </button>
  </div>
</template>

<style scoped>
.home-tab-bar-wrapper {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
  min-height: 36px;
  position: relative;
}

.scroll-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  flex-shrink: 0;
  background: var(--bg-secondary);
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  z-index: 2;
  transition: all 0.1s;
}
.scroll-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.scroll-left {
  border-right: 1px solid var(--border);
}
.scroll-right {
  border-left: 1px solid var(--border);
}

.home-tab-bar {
  display: flex;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
  flex: 1;
}
.home-tab-bar::-webkit-scrollbar {
  display: none;
}

.home-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: grab;
  border-right: 1px solid var(--border);
  white-space: nowrap;
  transition: all 0.15s;
  flex-shrink: 0;
  position: relative;
  user-select: none;
}

.home-tab:active {
  cursor: grabbing;
}

.home-tab:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.home-tab.active {
  background: var(--bg-primary);
  color: var(--text-primary);
  border-bottom: 2px solid var(--accent);
}

/* 拖拽放置指示器 */
.home-tab.drag-over-left::before,
.home-tab.drag-over-right::after {
  content: '';
  position: absolute;
  top: 4px;
  bottom: 4px;
  width: 2px;
  background: var(--accent);
  border-radius: 1px;
  z-index: 5;
}
.home-tab.drag-over-left::before {
  left: -1px;
}
.home-tab.drag-over-right::after {
  right: -1px;
}

.tab-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.home-tab.active .tab-icon {
  color: var(--accent);
}

.tab-title {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tab-close-btn {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  opacity: 0;
  transition: all 0.1s;
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
}

.home-tab:hover .tab-close-btn {
  opacity: 1;
}

.tab-close-btn:hover {
  background: var(--bg-active);
}
</style>
