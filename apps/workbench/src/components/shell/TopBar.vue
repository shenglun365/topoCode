<script setup lang="ts">
import { computed, onMounted } from 'vue'
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

const title = computed(() => navigation.currentBreadcrumb?.label || '项目列表')

/** 模型/右面板工具仅在 代码解析、架构分析 页显示（首页隐藏） */
const showTools = computed(() => ['/code', '/analysis'].includes(route.path))

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

/** 首页不渲染模型下拉时也要保证模型列表已加载（llmClient/isLLMConfigured 依赖） */
onMounted(() => {
  if (modelConfigStore.models.length === 0) {
    modelConfigStore.loadModels().catch((e) => {
      console.warn('[TopBar] loadModels failed:', e)
    })
  }
})
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
        <span class="logo-text">TopoCode 知识库管理</span>
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
        v-if="showTools"
        app-key="app"
        :provider="modelProvider"
      />
      <PanelToggleButton
        v-if="showTools"
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
  gap: calc(6px * var(--ui-scale, 1));
  flex-shrink: 0;
  padding: 0 calc(4px * var(--ui-scale, 1));
}
.logo-text {
  font-size: calc(13px * var(--ui-scale, 1));
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}
.project-badge {
  display: inline-flex;
  align-items: center;
  max-width: calc(240px * var(--ui-scale, 1));
  padding: calc(2px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
  border-radius: var(--radius-md);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-size: calc(12px * var(--ui-scale, 1));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
