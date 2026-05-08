<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useStatusStore } from '@/stores/status'

const { t } = useI18n()
const status = useStatusStore()
</script>

<template>
  <footer class="status-bar">
    <div class="status-item">
      <span
        class="status-dot"
        :class="{
          'error': status.backend.status === 'error',
          'warning': status.backend.status === 'stopped',
        }"
      ></span>
      <span>
        {{ status.backend.status === 'running' ? t('shell.statusBar.pythonBackend') : t('shell.statusBar.backendDisconnected') }}
      </span>
    </div>

    <div v-if="status.astStatus" class="status-item">
      <span>{{ status.astStatus }}</span>
    </div>

    <div v-if="status.gitBranch" class="status-item">
      <span>{{ t('shell.statusBar.branch') }}: {{ status.gitBranch }}</span>
    </div>

    <div class="status-spacer"></div>

    <div v-if="status.aiModel" class="status-item">
      <span>AI: {{ status.aiModel }}</span>
    </div>

    <div class="status-item">
      <span>{{ status.encoding }}</span>
    </div>

    <div class="status-item">
      <span>Zoom: {{ status.zoom }}%</span>
    </div>
  </footer>
</template>

<style scoped>
.status-bar {
  height: var(--status-bar-height);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  padding: 0 12px;
  gap: 16px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-muted);
}

.status-item {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: default;
}

.status-item:hover {
  color: var(--text-primary);
}

.status-spacer {
  flex: 1;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--success);
}

.status-dot.error {
  background: var(--error);
}

.status-dot.warning {
  background: var(--warning);
}
</style>
