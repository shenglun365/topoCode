<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useStatusStore } from '@/stores/status'
import { useSettingsStore } from '@/stores/settings'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-006')
const { t } = useI18n()
const status = useStatusStore()
const settings = useSettingsStore()
const testing = ref(false)

const defaultModel = computed(() => settings.models.find(m => m.isDefault) || settings.models[0] || null)
const modelStatusClass = computed(() => {
  const m = defaultModel.value
  if (!m) return 'status-stopped'
  if (m.status === 'connected') return 'status-running'
  if (m.status === 'error') return 'status-error'
  return 'status-stopped'
})

async function testModelStatus() {
  const m = defaultModel.value
  if (!m || m.status === 'connected' || testing.value) return
  testing.value = true
  try {
    await settings.testModel(m.id)
  } catch (_) {}
  testing.value = false
}
</script>

<template>
  <footer class="status-bar">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="status-item">
      <span
        class="status-dot"
        :class="'status-' + status.backend.status"
      />
      <span>
        {{ status.backend.status === 'running' ? t('shell.statusBar.pythonBackend') : status.backend.status === 'restarting' ? t('shell.statusBar.backendRestarting') : t('shell.statusBar.backendDisconnected') }}
      </span>
    </div>

    <div
      v-if="defaultModel"
      class="status-item status-model"
      :class="{ clickable: defaultModel.status !== 'connected', testing }"
      :title="defaultModel.status !== 'connected' ? t('shell.statusBar.testModel') : ''"
      @click="testModelStatus"
    >
      <span
        class="status-dot"
        :class="modelStatusClass"
      />
      <span>{{ testing ? t('shell.statusBar.testing') : defaultModel.name }}</span>
    </div>

    <div
      v-if="status.astStatus"
      class="status-item"
    >
      <span>{{ status.astStatus }}</span>
    </div>

    <div
      v-if="status.gitBranch"
      class="status-item"
    >
      <span>{{ t('shell.statusBar.branch') }}: {{ status.gitBranch }}</span>
    </div>

    <div class="status-spacer" />

    <div
      v-if="status.aiModel"
      class="status-item"
    >
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
.status-item.status-model.clickable {
  cursor: pointer;
}
.status-item.status-model.clickable:hover {
  color: var(--accent);
}
.status-item.status-model.testing {
  opacity: 0.6;
  pointer-events: none;
}

.status-spacer {
  flex: 1;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.status-dot.status-running {
  background: var(--success);
  box-shadow: 0 0 4px var(--success);
}
.status-dot.status-stopped {
  background: var(--text-muted);
}
.status-dot.status-error {
  background: var(--error);
  box-shadow: 0 0 4px var(--error);
}
.status-dot.status-restarting {
  background: var(--warning);
  animation: status-blink 0.8s ease-in-out infinite;
}
@keyframes status-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

</style>
