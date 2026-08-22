<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { MoonIcon, SunIcon } from '@heroicons/vue/24/outline'
import { AppToolbar, ModelSettingsDropdown, PanelToggleButton } from '@topo/web-core/shell'
import StarLogoMark from '@topo/web-core/components/StarLogoMark.vue'
import type { ModelSettingsProvider } from '@topo/web-core/shell'
import { usePanelStore } from '@/stores/panel'
import { useThemeStore } from '@/stores/theme'
import { useProjectStore } from '@/stores/project'
import { useNavigationStore } from '@/stores/navigation'
import { useSettingsStore } from '@/stores/settings-store'
import { useModelConfigStore } from '@/stores/model-config-store'

const { t } = useI18n()
const route = useRoute()
const panelStore = usePanelStore()
const themeStore = useThemeStore()
const projectStore = useProjectStore()
const navigation = useNavigationStore()
const settingsStore = useSettingsStore()
const modelConfigStore = useModelConfigStore()

/** P5：/app 模型+上下文（共享 model_configs；偏好存 localStorage `topoone-model-app`/`topoone-context-app`，
 * llmClient 每次调用读取并作为 `context_budget` 透传，服务端裁剪）。 */
const modelProvider: ModelSettingsProvider = {
  async listModels() {
    if (modelConfigStore.models.length === 0) {
      try {
        await modelConfigStore.loadModels()
      } catch (e) {
        console.warn('[TopBar] loadModels failed:', e)
      }
    }
    return modelConfigStore.models.map((m) => ({ id: m.id, name: m.name }))
  },
}

const title = computed(() => navigation.currentBreadcrumb?.label || 'TopoCode')

const showProjectBadge = computed(() =>
  ['/code', '/analysis'].includes(route.path) && !!projectStore.selectedProject)

function onFontSize(v: number) {
  settingsStore.setFontSize(v)
}

function onLocale(l: string) {
  settingsStore.setLocale(l as 'zh-CN' | 'en-US')
}

function onToggleRight(v: boolean) {
  panelStore.setRightCollapsed(!v)
}
</script>

<template>
  <AppToolbar
    app-key="app"
    :title="title"
    :font-size="settingsStore.fontSize"
    :font-targets="['root']"
    @update:font-size="onFontSize"
    @update:locale="onLocale"
  >
    <template #brand>
      <div class="menu-bar-logo">
        <StarLogoMark :size="18" />
        <span class="logo-text">TopoCode</span>
      </div>
    </template>
    <template #project>
      <div
        v-if="showProjectBadge"
        class="project-badge"
        :title="projectStore.selectedProject?.path"
      >
        {{ projectStore.selectedProject?.name }}
      </div>
    </template>
    <template #tools>
      <ModelSettingsDropdown
        app-key="app"
        :provider="modelProvider"
      />
      <PanelToggleButton
        :model-value="!panelStore.rightCollapsed"
        @update:model-value="onToggleRight"
      />
    </template>
    <template #theme>
      <button
        class="toolbar-btn"
        type="button"
        :title="t('shell.topBar.toggleTheme')"
        @click="themeStore.toggleTheme()"
      >
        <MoonIcon
          v-if="themeStore.theme === 'dark'"
          class="w-4 h-4"
        />
        <SunIcon
          v-else
          class="w-4 h-4"
        />
      </button>
    </template>
  </AppToolbar>
</template>

<style scoped>
.menu-bar-logo {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 0 4px;
}
.logo-text {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}
.project-badge {
  display: inline-flex;
  align-items: center;
  max-width: 240px;
  padding: 2px 10px;
  border-radius: var(--radius-md);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
