<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, ChatBubbleLeftIcon, ListBulletIcon, CommandLineIcon, ClockIcon } from '@heroicons/vue/24/outline'
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
  navigation.currentPage === 'analysis' && ['reportHome', 'componentAnalysis'].includes(projectStore.activeTab?.kind || '')
)

// 是否显示代码索引面板（分析页面 + 旧报告 tab）
const showCodeIndex = computed(() => {
  return navigation.currentPage === 'analysis' &&
    projectStore.activeTab?.kind === 'report'
})

// 是否显示 AI 助手面板（首页 或 分析页面报告首页 AI tab）
const showAIAssistant = computed(() => {
  return navigation.currentPage === 'home' || (isAnalysisReport.value && panelStore.rightTab === 'ai')
})

// 是否显示任务列表面板（分析页面报告首页 detail tab）
const showTaskList = computed(() => {
  return isAnalysisReport.value && panelStore.rightTab === 'detail'
})

// 是否显示 Agent 任务列表面板
const showAgentTasks = computed(() => {
  return isAnalysisReport.value && panelStore.rightTab === 'tasks'
})

const title = computed(() => {
  if (showCodeIndex.value) {
    return t('report.codeIndex')
  }
  if (showAgentTasks.value) {
    return t('report.agentTasks', 'Agent 任务')
  }
  if (isAnalysisReport.value) {
    if (panelStore.rightTab === 'detail') return t('report.sidebar.analysisHistory', '分析历史')
    if (panelStore.rightTab === 'tasks') return t('report.agentTasks', 'Agent')
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
  if (showTaskList.value) return { component: RIGHT_PANEL_COMPONENTS.taskList, props: { taskId: projectStore.activeTab?.taskId || '', taskName: projectStore.activeTab?.title } }
  if (showAIAssistant.value || (projectStore.viewMode === 'project' && projectStore.activeTab)) return { component: RIGHT_PANEL_COMPONENTS.ai }
  return null
})
</script>

<template>
  <aside
    class="panel-right"
    :class="{ collapsed: panelStore.rightCollapsed }"
    :style="{ width: panelStore.rightCollapsed ? 0 : `${panelStore.rightWidth}px` }"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="panel-header">
      <span>{{ title }}</span>
      <div class="panel-header-actions">
        <div
          class="icon-btn"
          :title="t('common.close')"
          @click="panelStore.toggleRight()"
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
        <span>{{ t('ai.assistantTitle') }}</span>
      </button>
      <button
        :class="['right-tab', { active: panelStore.rightTab === 'detail' }]"
        @click="panelStore.setRightTab('detail')"
      >
        <ClockIcon class="w-3.5 h-3.5" />
        <span>{{ t('report.sidebar.analysisHistory', '分析历史') }}</span>
      </button>
      <button
        :class="['right-tab', { active: panelStore.rightTab === 'tasks' }]"
        @click="panelStore.setRightTab('tasks')"
      >
        <CommandLineIcon class="w-3.5 h-3.5" />
        <span>{{ t('report.agentTasks', 'Agent') }}</span>
      </button>
    </div>
    <div class="panel-body">
      <component
        :is="activePanelComponent?.component"
        v-bind="activePanelComponent?.props || {}"
      />
    </div>
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
}

.panel-right.collapsed {
  width: 0 !important;
  border-left: none;
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
