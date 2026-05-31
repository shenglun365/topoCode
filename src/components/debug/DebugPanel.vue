<script setup lang="ts">
import { useProjectStore } from '@/stores/project'
import { useDebugStore } from '@/stores/debug'
import { useI18n } from 'vue-i18n'
import { WrenchScrewdriverIcon, TrashIcon, DocumentDuplicateIcon, CheckIcon } from '@heroicons/vue/24/outline'
import { ref } from 'vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('OT-002')
const { t } = useI18n()
const projectStore = useProjectStore()
const debugStore = useDebugStore()
const copied = ref(false)

function copyLogs() {
  const text = debugStore.logs.map(l => `[${l.time}] ${l.source}: ${l.message}`).join('\n')
  navigator.clipboard.writeText(text)
  copied.value = true
  setTimeout(() => { copied.value = false }, 2000)
}
</script>

<template>
  <div class="debug-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
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
      <div class="debug-row">
        <span class="debug-label">selectedFile</span>
        <span class="debug-value">{{ projectStore.selectedFile ? `${projectStore.selectedFile.type}:${projectStore.selectedFile.name}` : '(null)' }}</span>
      </div>
    </div>

    <div
      v-if="projectStore.selectedProject"
      class="debug-section"
    >
      <div class="debug-section-title">
        {{ t('shell.rightPanel.projectInfo') }}
      </div>
      <div class="debug-row">
        <span class="debug-label">name</span>
        <span class="debug-value">{{ projectStore.selectedProject.name }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">rootPath</span>
        <span
          class="debug-value"
          :title="projectStore.selectedProject.rootPath"
        >{{ projectStore.selectedProject.rootPath }}</span>
      </div>
      <div class="debug-row">
        <span class="debug-label">importedAt</span>
        <span class="debug-value">{{ projectStore.selectedProject.importedAt }}</span>
      </div>
    </div>

    <div class="debug-section">
      <div class="debug-section-title">
        <span>{{ t('shell.rightPanel.eventLog') }}</span>
        <div class="debug-actions">
          <button
            class="debug-action-btn"
            :title="t('shell.rightPanel.copyLogs')"
            @click="copyLogs()"
          >
            <CheckIcon
              v-if="copied"
              class="w-3 h-3"
            />
            <DocumentDuplicateIcon
              v-else
              class="w-3 h-3"
            />
          </button>
          <button
            class="debug-action-btn"
            :title="t('common.clear')"
            @click="debugStore.clear()"
          >
            <TrashIcon class="w-3 h-3" />
          </button>
        </div>
      </div>
      <div
        v-if="debugStore.logs.length === 0"
        class="debug-empty"
      >
        {{ t('shell.rightPanel.noEvents') }}
      </div>
      <div
        v-else
        class="debug-log-list"
      >
        <div
          v-for="(log, idx) in debugStore.logs"
          :key="idx"
          class="debug-log-entry"
        >
          <span class="debug-log-time">{{ log.time }}</span>
          <span class="debug-log-source">{{ log.source }}</span>
          <span class="debug-log-message">{{ log.message }}</span>
        </div>
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
  justify-content: space-between;
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

.debug-actions {
  display: flex;
  gap: 4px;
}

.debug-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-muted);
  border-radius: 3px;
}

.debug-action-btn:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.debug-action-btn.copied {
  color: var(--accent);
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

.debug-empty {
  padding: 8px;
  text-align: center;
  color: var(--text-muted);
  font-size: 10px;
}

.debug-log-list {
  max-height: 300px;
  overflow-y: auto;
}

.debug-log-entry {
  display: flex;
  flex-direction: column;
  padding: 3px 0;
  border-bottom: 1px solid var(--border);
  gap: 1px;
}

.debug-log-time {
  color: var(--text-muted);
  font-size: 9px;
}

.debug-log-source {
  color: var(--accent);
  font-size: 9px;
  font-weight: 600;
}

.debug-log-message {
  color: var(--text-primary);
  font-size: 9px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
