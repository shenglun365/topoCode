<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CpuChipIcon,
  Cog6ToothIcon,
  InformationCircleIcon,
  ArrowPathIcon,
  PaintBrushIcon,
  DocumentTextIcon,
  FunnelIcon,
  XMarkIcon,
  CommandLineIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings-store'
import { useModelConfigStore } from '@/stores/model-config-store'
import { useThemeStore } from '@/stores/theme'
import { useStatusStore } from '@/stores/status'
import { useAnalysisStore } from '@/stores/analysis'
import ModelConfig from '@/components/settings/ModelConfig.vue'
import GeneralSettings from '@/components/settings/GeneralSettings.vue'
import ThemeManager from '@/components/settings/ThemeManager.vue'
import AboutPage from '@/components/settings/AboutPage.vue'
import TemplateManager from '@/components/settings/TemplateManager.vue'
import ImportConfig from '@/components/settings/ImportConfig.vue'
import AgentConfigManager from '@/components/settings/AgentConfigManager.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PG-008')
const { t } = useI18n()
const settingsStore = useSettingsStore()
const modelConfigStore = useModelConfigStore()
const themeStore = useThemeStore()
const statusStore = useStatusStore()
const analysisStore = useAnalysisStore()
const showRestartConfirm = ref(false)

const runningTaskCount = computed(() => analysisStore.taskStats.running + analysisStore.taskStats.pending)

async function handleRestart() {
  showRestartConfirm.value = false
  await settingsStore.restartBackend()
}

onMounted(async () => {
  if (modelConfigStore.models.length === 0) {
    await (settingsStore as any).loadSettings()
  }
  themeStore.init()
  try {
    const st = await window.api?.backend.getStatus()
    if (st) statusStore.setBackendStatus(st as any)
  } catch (_) {}
})

const tabs = [
  { id: 'ai' as const, key: 'settings.modelConfig', icon: CpuChipIcon },
  { id: 'general' as const, key: 'settings.general', icon: Cog6ToothIcon },
  { id: 'import' as const, key: 'settings.importConfig', icon: FunnelIcon },
  { id: 'theme' as const, key: 'settings.theme', icon: PaintBrushIcon },
  { id: 'templates' as const, key: 'settings.templates', icon: DocumentTextIcon },
  { id: 'agent' as const, key: 'settings.agentConfig', icon: CommandLineIcon },
  { id: 'about' as const, key: 'settings.about', icon: InformationCircleIcon },
]
</script>

<template>
  <div class="page-settings">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div style="display:flex; border-bottom:1px solid var(--border); background:var(--bg-secondary); padding:0 16px;">
      <div
        v-for="tab in tabs"
        :key="tab.id"
        class="settings-tab"
        :class="{ active: settingsStore.activeTab === tab.id }"
        @click="settingsStore.setActiveTab(tab.id)"
      >
        <component
          :is="tab.icon"
          class="w-4 h-4"
        />
        <span>{{ t(tab.key) }}</span>
      </div>
      <div style="flex:1;" />
      <div style="display:flex; align-items:center; gap:6px; font-size:10px; color:var(--text-muted);">
        <span
          class="status-dot"
          :class="'status-' + statusStore.backend.status"
        />
        <span>{{ t('settings.pythonBackend') }}</span>
        <button
          class="btn btn-ghost btn-sm"
          style="padding:2px 6px; font-size:10px;"
          @click="showRestartConfirm = true"
        >
          <ArrowPathIcon class="w-3 h-3" />
          <span>{{ t('common.restart') }}</span>
        </button>
      </div>
    </div>
    <div style="flex:1; overflow:auto; padding:24px;">
      <ModelConfig v-if="settingsStore.activeTab === 'ai'" />
      <GeneralSettings v-else-if="settingsStore.activeTab === 'general'" />
      <ImportConfig v-else-if="settingsStore.activeTab === 'import'" />
      <ThemeManager v-else-if="settingsStore.activeTab === 'theme'" />
      <TemplateManager v-else-if="settingsStore.activeTab === 'templates'" />
      <AgentConfigManager v-else-if="settingsStore.activeTab === 'agent'" />
      <AboutPage v-else-if="settingsStore.activeTab === 'about'" />
    </div>
    <Teleport to="body">
      <div
        v-if="showRestartConfirm"
        class="modal-overlay"
        @click.self="showRestartConfirm = false"
      >
        <div
          class="modal"
          style="width:380px;"
        >
          <div class="modal-header">
            <span class="modal-title">{{ t('common.restart') }}</span>
            <button
              class="btn btn-ghost btn-xs"
              @click="showRestartConfirm = false"
            >
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div class="modal-body">
            <p style="font-size:13px;color:var(--text-primary);">
              {{ t('settings.restartBackendConfirm') }}
            </p>
            <p
              v-if="runningTaskCount > 0"
              style="font-size:12px;color:var(--warning);margin-top:8px;"
            >
              {{ t('common.restartBlockedTasks', { count: runningTaskCount }) }}
            </p>
          </div>
          <div class="modal-footer">
            <button
              class="btn btn-ghost btn-sm"
              @click="showRestartConfirm = false"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              :disabled="runningTaskCount > 0"
              class="btn btn-primary btn-sm"
              @click="handleRestart"
            >
               {{ t('common.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.page-settings {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.settings-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.settings-tab:hover { color: var(--text-primary); background: var(--bg-hover); }
.settings-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status-dot.status-running { background: var(--success); box-shadow: 0 0 4px var(--success); }
.status-dot.status-stopped { background: var(--text-muted); }
.status-dot.status-error { background: var(--error); box-shadow: 0 0 4px var(--error); }
.status-dot.status-restarting { background: var(--warning); animation: status-blink 0.8s ease-in-out infinite; }
@keyframes status-blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 9999; }
.modal { background: var(--bg-primary); border: 1px solid var(--border); border-radius: var(--radius-lg,8px); max-width: 100%; overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,0.4); }
.modal-header { padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
.modal-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.modal-body { padding: 20px; overflow-y: auto; }
.modal-footer { padding: 12px 20px; border-top: 1px solid var(--border); display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
</style>