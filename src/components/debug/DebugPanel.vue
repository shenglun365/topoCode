<script setup lang="ts">
import { useProjectStore } from '@/stores/project'
import { useI18n } from 'vue-i18n'
import { WrenchScrewdriverIcon } from '@heroicons/vue/24/outline'

const { t } = useI18n()
const projectStore = useProjectStore()
</script>

<template>
  <div class="debug-panel">
    <div class="debug-section">
      <div class="debug-section-title">
        <WrenchScrewdriverIcon class="w-3.5 h-3.5" />
        {{ t('shell.rightPanel.debug') }}
      </div>
      <div class="debug-row">
        <span class="debug-label">selectedProjectId</span>
        <span class="debug-value">{{ projectStore.selectedProjectId || '(null)' }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">viewMode</span>
        <span class="debug-value">{{ projectStore.viewMode }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">activeTabId</span>
        <span class="debug-value">{{ projectStore.activeTabId || '(null)' }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">activeTab.type</span>
        <span class="debug-value">{{ projectStore.activeTab?.type || '(null)' }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">projects.length</span>
        <span class="debug-value">{{ projectStore.projects.length }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">tabs.length</span>
        <span class="debug-value">{{ projectStore.tabs.length }}</span>
      </div>
    </div>

    <div class="debug-section" v-if="projectStore.selectedProject">
      <div class="debug-section-title">{{ t('shell.rightPanel.projectInfo') }}</div>
      <div class="debug-row">
        <span class="debug-label">name</span>
        <span class="debug-value">{{ projectStore.selectedProject.name }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">rootPath</span>
        <span class="debug-value" :title="projectStore.selectedProject.rootPath">{{ projectStore.selectedProject.rootPath }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">importedAt</span>
        <span class="debug-value">{{ projectStore.selectedProject.importedAt }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.debug-panel {
  padding: 8px;
  font-family: 'Courier New', monospace;
  font-size: 10px;
  color: var(--text-secondary);
  overflow: auto;
}

.debug-section {
  margin-bottom: 12px;
}

.debug-section-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  margin-bottom: 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}

.debug-row {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
  gap: 8px;
}

.debug-label {
  color: var(--text-muted);
  flex-shrink: 0;
}

.debug-value {
  color: var(--text-primary);
  text-align: right;
  word-break: break-all;
}
</style>
