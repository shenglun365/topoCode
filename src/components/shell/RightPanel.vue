<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  XMarkIcon, ChatBubbleLeftIcon, CommandLineIcon,
  ArrowTopRightOnSquareIcon,
} from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useNavigationStore } from '@/stores/navigation'
import { useProjectStore } from '@/stores/project'
import { RIGHT_PANEL_COMPONENTS } from './rightPanelRegistry'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-004')
const { t } = useI18n()
const panelStore = usePanelStore()
const navigation = useNavigationStore()
const projectStore = useProjectStore()

const panelTitleKeys: Record<string, string> = {
  home: 'ai.assistantTitle',
  analysis: 'shell.rightPanel.taskDetail',
  knowledge: 'shell.rightPanel.docDetail',
  coder: 'shell.rightPanel.context',
  user: 'shell.rightPanel.settingsDetail',
}

const isAnalysisReport = computed(() =>
  navigation.currentPage === 'analysis' && ['reportHome', 'subdoc'].includes(projectStore.activeTab?.kind || '')
)

// 当前会话上下文（项目名 › 任务名）
const projectName = computed(() => projectStore.selectedProject?.name || '')
const taskName = computed(() => projectStore.activeTab?.title || '')
const sessionHint = computed(() => {
  if (!isAnalysisReport.value) return ''
  const p = projectName.value
  const t = taskName.value
  if (!p && !t) return ''
  const hint = p ? (t ? `${p} › ${t}` : p) : t
  return hint.length > 24 ? hint.slice(0, 21) + '...' : hint
})

// 是否显示代码索引面板（分析页面 + 旧报告 tab）
const showCodeIndex = computed(() => {
  return navigation.currentPage === 'analysis' &&
    projectStore.activeTab?.kind === 'report'
})

// 是否显示 AI 助手面板（首页 或 分析页面报告首页 AI tab）
const showAIAssistant = computed(() => {
  return navigation.currentPage === 'home' || (isAnalysisReport.value && panelStore.rightTab === 'ai')
})

// 是否显示 Agent 任务列表面板（分析页面报告首页 tasks tab）
const showAgentTasks = computed(() => {
  return isAnalysisReport.value && panelStore.rightTab === 'tasks'
})

const title = computed(() => {
  if (showCodeIndex.value) {
    return t('report.codeIndex')
  }
  if (showAgentTasks.value) {
    return t('report.agentTasks', '解析任务')
  }
  if (isAnalysisReport.value) {
    return t('ai.assistantTitle')
  }
  if (showAIAssistant.value) {
    return t('ai.assistantTitle')
  }
  if (projectStore.viewMode === 'project' && projectStore.activeTab) {
    return t('ai.assistantTitle')
  }
  return t(panelTitleKeys[navigation.currentPage] || 'common.detail')
})

const activePanelComponent = computed(() => {
  if (panelStore.debugMode) return { component: RIGHT_PANEL_COMPONENTS.debug }
  if (showCodeIndex.value) return { component: RIGHT_PANEL_COMPONENTS.codeIndex }
  if (showAgentTasks.value) return { component: RIGHT_PANEL_COMPONENTS.agentTaskList }
  if (showAIAssistant.value || (projectStore.viewMode === 'project' && projectStore.activeTab)) return { component: RIGHT_PANEL_COMPONENTS.ai }
  return null
})

/* ========== 浮动窗口：拖拽 & 缩放 ========== */

const dragging = ref(false)
const dragStartX = ref(0)
const dragStartY = ref(0)
const dragStartPX = ref(0)
const dragStartPY = ref(0)

type ResizeDir = 'left' | 'right' | 'bottom' | 'br' | 'bl'
const resizeDir = ref<ResizeDir | null>(null)
const resizeStartX = ref(0)
const resizeStartY = ref(0)
const resizeStartW = ref(0)
const resizeStartH = ref(0)
const resizeStartPX = ref(0)

function onDragStart(e: MouseEvent) {
  dragging.value = true
  dragStartX.value = e.clientX
  dragStartY.value = e.clientY
  dragStartPX.value = panelStore.rightFloatingX
  dragStartPY.value = panelStore.rightFloatingY
  e.preventDefault()
}

function onDragMove(e: MouseEvent) {
  if (!dragging.value) return
  panelStore.rightFloatingX = Math.max(-200, Math.min(window.innerWidth - 60, dragStartPX.value + e.clientX - dragStartX.value))
  panelStore.rightFloatingY = Math.max(0, Math.min(window.innerHeight - 40, dragStartPY.value + e.clientY - dragStartY.value))
}

function onDragEnd() { dragging.value = false }

function onResizeStart(dir: ResizeDir, e: MouseEvent) {
  resizeDir.value = dir
  resizeStartX.value = e.clientX
  resizeStartY.value = e.clientY
  resizeStartW.value = panelStore.rightFloatingW
  resizeStartH.value = panelStore.rightFloatingH
  resizeStartPX.value = panelStore.rightFloatingX
  e.preventDefault()
  e.stopPropagation()
}

function onResizeMove(e: MouseEvent) {
  if (!resizeDir.value) return
  const maxW = Math.floor(window.innerWidth * 0.75)
  const maxH = Math.floor(window.innerHeight * 0.85)
  const dx = e.clientX - resizeStartX.value
  const dy = e.clientY - resizeStartY.value
  if (resizeDir.value === 'right' || resizeDir.value === 'br') {
    panelStore.rightFloatingW = Math.min(maxW, Math.max(260, resizeStartW.value + dx))
  }
  if (resizeDir.value === 'left' || resizeDir.value === 'bl') {
    const newW = Math.min(maxW, Math.max(260, resizeStartW.value - dx))
    const diff = resizeStartW.value - newW
    panelStore.rightFloatingX = resizeStartPX.value + diff
    panelStore.rightFloatingW = newW
  }
  if (resizeDir.value === 'bottom' || resizeDir.value === 'br' || resizeDir.value === 'bl') {
    panelStore.rightFloatingH = Math.min(maxH, Math.max(200, resizeStartH.value + dy))
  }
}

function onResizeEnd() { resizeDir.value = null }

/* ========== 全屏停靠模式：宽度拖拽 ========== */

const dockResizing = ref(false)
const dockResizeStartX = ref(0)
const dockResizeStartW = ref(0)

function onDockResizeStart(e: MouseEvent) {
  dockResizing.value = true
  dockResizeStartX.value = e.clientX
  dockResizeStartW.value = panelStore.rightWidth
  e.preventDefault()
}

function onDockResizeMove(e: MouseEvent) {
  if (!dockResizing.value) return
  const diff = dockResizeStartX.value - e.clientX
  const newW = Math.min(Math.floor(window.innerWidth * 0.5), Math.max(260, dockResizeStartW.value + diff))
  panelStore.setRightWidth(newW)
}

function onDockResizeEnd() { dockResizing.value = false }

onMounted(() => {
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
  document.addEventListener('mousemove', onDockResizeMove)
  document.addEventListener('mouseup', onDockResizeEnd)
})

onUnmounted(() => {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
  document.removeEventListener('mousemove', onDockResizeMove)
  document.removeEventListener('mouseup', onDockResizeEnd)
})

/* ========== 面板样式 ========== */

const panelStyle = computed(() => {
  if (panelStore.rightFloating) {
    return {
      position: 'fixed' as const,
      top: `${panelStore.rightFloatingY}px`,
      left: `${panelStore.rightFloatingX}px`,
      width: `${panelStore.rightFloatingW}px`,
      height: `${panelStore.rightFloatingH}px`,
      zIndex: 9999,
      borderRadius: '8px',
    }
  }
  if (panelStore.isFullscreen && !panelStore.rightCollapsed) {
    return {
      position: 'fixed' as const,
      top: '0',
      right: '0',
      bottom: '44px',
      width: `${panelStore.rightWidth}px`,
      zIndex: 250,
      borderRadius: '0',
    }
  }
  return {
    width: panelStore.rightCollapsed ? '0' : `${panelStore.rightWidth}px`,
  }
})

function handleClose() {
  if (panelStore.rightFloating) {
    panelStore.rightFloating = false
    panelStore.rightCollapsed = true
  } else {
    panelStore.toggleRight()
  }
}

function toggleFloat() {
  panelStore.toggleRightFloating()
  if (!panelStore.rightFloating) {
    panelStore.rightCollapsed = false
  }
}
</script>

<template>
  <aside
    class="panel-right"
    :class="{
      collapsed: panelStore.rightCollapsed && !panelStore.rightFloating,
      floating: panelStore.rightFloating,
      'fullscreen-docked': panelStore.isFullscreen && !panelStore.rightFloating && !panelStore.rightCollapsed,
    }"
    :style="panelStyle"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      class="panel-header"
      :class="{ 'float-drag': panelStore.rightFloating }"
      @mousedown="panelStore.rightFloating ? onDragStart($event) : undefined"
    >
      <div class="panel-title-row">
        <span>{{ title }}</span>
        <span
          v-if="sessionHint"
          class="session-hint"
          :title="[projectName, taskName].filter(Boolean).join(' › ')"
        >{{ sessionHint }}</span>
      </div>
      <div class="panel-header-actions">
        <div
          class="icon-btn"
          :title="panelStore.rightFloating ? t('shell.rightPanel.dock', '停靠') : t('shell.rightPanel.float', '弹出窗口')"
          @click="toggleFloat"
        >
          <ArrowTopRightOnSquareIcon
            v-if="!panelStore.rightFloating"
            class="w-3.5 h-3.5"
          />
          <svg
            v-else
            class="w-3.5 h-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M8 3v3a2 2 0 01-2 2H3m18 0h-3a2 2 0 01-2-2V3m0 18v-3a2 2 0 012-2h3M3 16h3a2 2 0 012 2v3" />
          </svg>
        </div>
        <div
          class="icon-btn"
          :title="t('common.close')"
          @click="handleClose"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </div>
      </div>
    </div>
    <!-- Tab 切换栏（分析报告首页） -->
    <div
      v-if="isAnalysisReport"
      class="right-tab-bar"
    >
      <button
        :class="['right-tab', { active: panelStore.rightTab === 'ai' }]"
        @click="panelStore.setRightTab('ai')"
      >
        <ChatBubbleLeftIcon class="w-3.5 h-3.5" />
        <span>{{ t('ai.chatTab', '对话') }}</span>
      </button>
      <button
        :class="['right-tab', { active: panelStore.rightTab === 'tasks' }]"
        @click="panelStore.setRightTab('tasks')"
      >
        <CommandLineIcon class="w-3.5 h-3.5" />
        <span>{{ t('report.agentTasks', '解析任务') }}</span>
      </button>
    </div>
    <div class="panel-body">
      <component
        :is="activePanelComponent?.component"
      />
    </div>

    <!-- 全屏停靠模式拖拽把手 -->
    <div
      v-if="panelStore.isFullscreen && !panelStore.rightFloating && !panelStore.rightCollapsed"
      class="dock-resize-handle"
      @mousedown="onDockResizeStart($event)"
    />

    <!-- 浮动模式缩放手柄 -->
    <template v-if="panelStore.rightFloating">
      <div class="resize-handle resize-left" @mousedown="onResizeStart('left', $event)" />
      <div class="resize-handle resize-right" @mousedown="onResizeStart('right', $event)" />
      <div class="resize-handle resize-bottom" @mousedown="onResizeStart('bottom', $event)" />
      <div class="resize-handle resize-bl" @mousedown="onResizeStart('bl', $event)" />
      <div class="resize-handle resize-br" @mousedown="onResizeStart('br', $event)" />
    </template>
  </aside>
</template>

<style scoped>
.panel-right {
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.2s ease;
  position: relative;
}

.panel-right.collapsed {
  width: 0 !important;
  border-left: none;
}

/* 全屏停靠模式 */
.panel-right.fullscreen-docked {
  flex-shrink: unset !important;
  border-left: 1px solid var(--border);
  border-right: none;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.3);
  transition: none;
  overflow: hidden;
}
.panel-right.fullscreen-docked .panel-body {
  overflow: auto;
}
.panel-right.fullscreen-docked .panel-header {
  cursor: default;
}

/* 全屏停靠拖拽把手 */
.dock-resize-handle {
  position: absolute;
  left: -3px;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  z-index: 1;
}
.dock-resize-handle::after {
  content: '';
  position: absolute;
  left: 2px;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 32px;
  background: var(--border);
  border-radius: 1px;
  transition: background 0.15s;
}
.dock-resize-handle:hover::after {
  background: var(--accent);
}

/* 浮动模式 */
.panel-right.floating {
  flex-shrink: unset !important;
  border: 1px solid var(--border);
  border-left: 1px solid var(--border);
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.45);
  transition: none;
  overflow: hidden;
  border-radius: 8px;
}

.panel-right.floating .panel-body {
  overflow: auto;
  padding-right: 8px;
  padding-bottom: 6px;
}

.panel-right.floating .panel-header.float-drag {
  cursor: move;
  user-select: none;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  min-height: 32px;
}

.panel-header-actions {
  display: flex;
  gap: 4px;
}

.panel-header-actions .icon-btn {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 12px;
}

.panel-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
}

.session-hint {
  font-size: 10px;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: default;
}

.panel-header-actions .icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.right-tab-bar {
  display: flex;
  border-bottom: 1px solid var(--border);
  background: var(--bg-tertiary);
}

.right-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 8px;
  font-size: 10px;
  font-weight: 500;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.right-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.right-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.panel-body {
  flex: 1;
  overflow: auto;
  padding: 4px 0;
}

/* 缩放手柄 */
.resize-handle {
  position: absolute;
  z-index: 20;
  pointer-events: auto;
}
.resize-handle:hover {
  background: color-mix(in srgb, var(--accent) 35%, transparent);
}
.resize-left {
  left: 0; top: 0; bottom: 0; width: 10px;
  cursor: ew-resize;
}
.resize-right {
  right: 0; top: 0; bottom: 0; width: 10px;
  cursor: ew-resize;
}
.resize-bottom {
  left: 0; right: 0; bottom: 0; height: 8px;
  cursor: ns-resize;
}
.resize-bl {
  left: 0; bottom: 0; width: 16px; height: 16px;
  cursor: nesw-resize;
}
.resize-br {
  right: 0; bottom: 0; width: 16px; height: 16px;
  cursor: nwse-resize;
}

.symbols-panel {
  padding: 12px;
}

.symbols-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px 12px;
  text-align: center;
}

.symbols-empty .icon {
  font-size: 24px;
  opacity: 0.5;
}

.symbols-empty .title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

.symbols-empty .desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
</style>
