<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, ChatBubbleLeftIcon, ListBulletIcon } from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useNavigationStore } from '@/stores/navigation'
import { useProjectStore } from '@/stores/project'
import DebugPanel from '@/components/debug/DebugPanel.vue'
import CodeIndexPanel from '@/components/report/CodeIndexPanel.vue'
import AIAssistantPanel from '@/components/ai/AIAssistantPanel.vue'
import ReportTaskListPanel from '@/components/report/ReportTaskListPanel.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-004')
const { t } = useI18n()
const panelStore = usePanelStore()
const navigation = useNavigationStore()
const projectStore = useProjectStore()

const codeIndexRef = ref<InstanceType<typeof CodeIndexPanel> | null>(null)

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

const title = computed(() => {
  if (showCodeIndex.value) {
    return t('report.codeIndex')
  }
  if (isAnalysisReport.value) {
    return panelStore.rightTab === 'ai' ? t('ai.assistantTitle') : t('report.sidebar.taskList')
  }
  if (showAIAssistant.value) {
    return t('ai.assistantTitle')
  }
  if (projectStore.viewMode === 'project' && projectStore.activeTab) {
    return t('ai.assistantTitle')
  }
  return t(panelTitleKeys[navigation.currentPage] || 'common.detail')
})

defineExpose({
  codeIndexRef,
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
        <ListBulletIcon class="w-3.5 h-3.5" />
        <span>{{ t('report.sidebar.taskList') }}</span>
      </button>
    </div>
    <div class="panel-body">
      <!-- DEBUG 面板 -->
      <DebugPanel v-if="panelStore.debugMode" />

      <!-- 代码索引面板（旧报告 tab） -->
      <CodeIndexPanel
        v-else-if="showCodeIndex"
        ref="codeIndexRef"
      />

      <!-- 任务列表面板（分析报告首页 detail tab） -->
      <ReportTaskListPanel
        v-else-if="showTaskList"
        :task-id="projectStore.activeTab?.taskId || ''"
        :task-name="projectStore.activeTab?.title"
      />

      <!-- AI 助手面板 -->
      <AIAssistantPanel v-else-if="showAIAssistant || (projectStore.viewMode === 'project' && projectStore.activeTab)" />

      <!-- 动态内容插槽 -->
      <template v-else>
        <slot :page="navigation.currentPage">
          <div class="empty-state">
            <div class="icon">
              📌
            </div>
            <div class="title">
              {{ t('shell.rightPanel.nodeDetail') }}
            </div>
            <div class="desc">
              {{ t('shell.rightPanel.clickNodeToView') }}
            </div>
          </div>
        </slot>
      </template>
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
