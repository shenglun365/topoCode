<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useNavigationStore } from '@/stores/navigation'
import { useProjectStore } from '@/stores/project'
import DebugPanel from '@/components/debug/DebugPanel.vue'
import CodeIndexPanel from '@/components/report/CodeIndexPanel.vue'
import AIAssistantPanel from '@/components/ai/AIAssistantPanel.vue'

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

// 是否显示代码索引面板（分析页面 + 报告 tab）
const showCodeIndex = computed(() => {
  return navigation.currentPage === 'analysis' &&
    projectStore.activeTab?.kind === 'report'
})

// 是否显示 AI 助手面板（首页）
const showAIAssistant = computed(() => {
  return navigation.currentPage === 'home'
})

const title = computed(() => {
  if (showCodeIndex.value) {
    return t('report.codeIndex')
  }
  if (showAIAssistant.value) {
    return t('ai.assistantTitle')
  }
  if (projectStore.viewMode === 'project' && projectStore.activeTab) {
    return t('ai.assistantTitle')
  }
  return t(panelTitleKeys[navigation.currentPage] || 'common.detail')
})

// 暴露给父组件调用
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
    <div class="panel-header">
      <span>{{ title }}</span>
      <div class="panel-header-actions">
        <div class="icon-btn" @click="panelStore.toggleRight()" :title="t('common.close')">
          <XMarkIcon class="w-3.5 h-3.5" />
        </div>
      </div>
    </div>
    <div class="panel-body">
      <!-- DEBUG 面板 -->
      <DebugPanel v-if="panelStore.debugMode" />

      <!-- 代码索引面板 -->
      <CodeIndexPanel
        v-else-if="showCodeIndex"
        ref="codeIndexRef"
      />

      <!-- 符号索引（预留） -->
      <div v-else-if="projectStore.viewMode === 'project' && projectStore.activeTab" class="symbols-panel">
        <div class="symbols-empty">
          <div class="icon">🔍</div>
          <div class="title">{{ t('shell.rightPanel.symbols') }}</div>
          <div class="desc">{{ t('shell.rightPanel.symbolsPending') }}</div>
        </div>
      </div>

      <!-- AI 助手面板（首页 / 项目视图） -->
      <AIAssistantPanel v-else-if="showAIAssistant || (projectStore.viewMode === 'project' && projectStore.activeTab)" />

      <!-- 动态内容插槽 -->
      <template v-else>
        <slot :page="navigation.currentPage">
          <!-- 默认空状态 -->
          <div class="empty-state">
            <div class="icon">📌</div>
            <div class="title">{{ t('shell.rightPanel.nodeDetail') }}</div>
            <div class="desc">{{ t('shell.rightPanel.clickNodeToView') }}</div>
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
