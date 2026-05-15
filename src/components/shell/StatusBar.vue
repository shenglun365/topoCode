<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStatusStore } from '@/stores/status'
import { clearCache } from '@/utils/graphCache'
import { TrashIcon } from '@heroicons/vue/24/outline'

const { t } = useI18n()
const status = useStatusStore()
const clearing = ref(false)

async function handleClearCache() {
  clearing.value = true
  try {
    await clearCache()
  } finally {
    clearing.value = false
  }
}
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

    <button
      class="cache-clear-btn"
      :disabled="clearing"
      @click="handleClearCache"
      :title="t('report.clearCache')"
    >
      <TrashIcon class="w-3.5 h-3.5" />
    </button>
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

.cache-clear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 3px;
  transition: color 0.15s;
}

.cache-clear-btn:hover {
  color: var(--text-primary);
}

.cache-clear-btn:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
