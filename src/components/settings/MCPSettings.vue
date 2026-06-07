<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'
import { useMCPStore } from '@/stores/mcp-store'
import { useSettingsStore } from '@/stores/settings-store'
import {
  PlayIcon,
  StopIcon,
  ArrowPathIcon,
  ServerIcon,
} from '@heroicons/vue/24/outline'

const { showId, componentId } = useComponentId('ST-008')
const { t } = useI18n()
const mcp = useMCPStore()
const settings = useSettingsStore()

const zmqPort = ref(5671)
const logLevel = ref('WARN')
const projectRoot = ref('')
const starting = ref(false)

let unsubscribe: (() => void) | null = null

onMounted(async () => {
  if ((window as any).api?.mcp?.onStatusChange) {
    unsubscribe = (window as any).api.mcp.onStatusChange((s: any) => {
      mcp.setStatus(s)
      starting.value = false
    })
  }
})

onUnmounted(() => {
  unsubscribe?.()
})

async function startMCP() {
  starting.value = true
  try {
    const root = projectRoot.value || ''
    await (window as any).api?.mcp?.start(root, zmqPort.value, logLevel.value)
  } catch (e: unknown) {
    console.warn('Failed to start MCP Server', e)
    starting.value = false
  }
}

async function stopMCP() {
  try {
    await (window as any).api?.mcp?.stop()
    mcp.reset()
  } catch (e: unknown) {
    console.warn('Failed to stop MCP Server', e)
  }
}

async function restartMCP() {
  await stopMCP()
  setTimeout(startMCP, 500)
}
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div
    :class="['setting-section', componentId]"
    :data-component-id="showId ? componentId : null"
  >
    <div class="section-header">
      <ServerIcon class="h-5 w-5" />
      <span>{{ t('settings.mcpServer') }}</span>
    </div>

    <div class="mcp-status-bar">
      <span
        class="status-dot"
        :class="mcp.state"
      />
      <span class="status-text">{{ mcp.statusText }}</span>
      <span
        v-if="mcp.pid"
        class="status-pid"
      >PID: {{ mcp.pid }}</span>
      <span
        v-if="mcp.error"
        class="status-error"
      >{{ mcp.error }}</span>
    </div>

    <div class="form-row">
      <label>{{ t('settings.projectRoot') }}</label>
      <input
        v-model="projectRoot"
        type="text"
        class="input"
        placeholder="/path/to/project"
        :disabled="mcp.isRunning"
      >
    </div>

    <div class="form-row">
      <label>{{ t('settings.zmqDealerPort') }}</label>
      <input
        v-model.number="zmqPort"
        type="number"
        min="1024"
        max="65535"
        class="input"
        :disabled="mcp.isRunning"
      >
    </div>

    <div class="form-row">
      <label>{{ t('settings.logLevel') }}</label>
      <select
        v-model="logLevel"
        class="input"
        :disabled="mcp.isRunning"
      >
        <option value="DEBUG">
          DEBUG
        </option>
        <option value="INFO">
          INFO
        </option>
        <option value="WARN">
          WARN
        </option>
        <option value="ERROR">
          ERROR
        </option>
      </select>
    </div>

    <div class="action-row">
      <button
        v-if="!mcp.isRunning"
        class="btn btn-primary btn-sm"
        :disabled="starting"
        @click="startMCP"
      >
        <PlayIcon class="h-4 w-4" />
        {{ starting ? t('common.starting') : t('common.start') }}
      </button>
      <button
        v-if="mcp.isRunning"
        class="btn btn-danger btn-sm"
        @click="stopMCP"
      >
        <StopIcon class="h-4 w-4" />
        {{ t('common.stop') }}
      </button>
      <button
        class="btn btn-ghost btn-sm"
        @click="restartMCP"
      >
        <ArrowPathIcon class="h-4 w-4" />
        {{ t('common.restart') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.setting-section {
  padding: 16px;
  border-bottom: 1px solid var(--border);
}
.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 12px;
  color: var(--text);
}
.mcp-status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status-dot.running { background: var(--success); }
.status-dot.starting { background: var(--warning); animation: pulse 1s infinite; }
.status-dot.stopped { background: var(--text-muted); }
.status-dot.error { background: var(--error); }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.status-text { color: var(--text); }
.status-pid { color: var(--text-muted); font-size: 12px; }
.status-error { color: var(--error); font-size: 12px; }
.form-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.form-row label {
  width: 100px;
  font-size: 13px;
  color: var(--text);
  flex-shrink: 0;
}
.input {
  flex: 1;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.action-row {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
