<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CpuChipIcon,
  WrenchScrewdriverIcon,
  PuzzlePieceIcon,
  Cog6ToothIcon,
  InformationCircleIcon,
  ArrowPathIcon,
  PaintBrushIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings'
import { useThemeStore } from '@/stores/theme'
import ModelConfig from '@/components/settings/ModelConfig.vue'
import AgentManager from '@/components/settings/AgentManager.vue'
import SkillManager from '@/components/settings/SkillManager.vue'
import GeneralSettings from '@/components/settings/GeneralSettings.vue'
import ThemeManager from '@/components/settings/ThemeManager.vue'
import AboutPage from '@/components/settings/AboutPage.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PG-005')
const { t } = useI18n()
const settingsStore = useSettingsStore()
const themeStore = useThemeStore()

onMounted(async () => {
  await settingsStore.loadSettings()
  themeStore.init()
})

const tabs = [
  { id: 'ai' as const, key: 'settings.modelConfig', icon: CpuChipIcon },
  { id: 'agents' as const, key: 'settings.agents', icon: WrenchScrewdriverIcon },
  { id: 'skills' as const, key: 'settings.skills', icon: PuzzlePieceIcon },
  { id: 'general' as const, key: 'settings.general', icon: Cog6ToothIcon },
  { id: 'theme' as const, key: 'settings.theme', icon: PaintBrushIcon },
  { id: 'plugins' as const, key: 'settings.plugins', icon: PuzzlePieceIcon },
  { id: 'about' as const, key: 'settings.about', icon: InformationCircleIcon },
]
</script>

<template>
  <div class="page-user">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- 顶部 Tab 切换 -->
    <div style="display:flex; border-bottom:1px solid var(--border); background:var(--bg-secondary); padding:0 16px;">
      <div
        v-for="tab in tabs"
        :key="tab.id"
        class="settings-tab"
        :class="{ active: settingsStore.activeTab === tab.id }"
        @click="settingsStore.setActiveTab(tab.id)"
      >
        <component :is="tab.icon" class="w-4 h-4" />
        <span>{{ t(tab.key) }}</span>
      </div>
      <div style="flex:1;"></div>

      <div style="display:flex; align-items:center; gap:6px; font-size:10px; color:var(--text-muted);">
        <span
          class="status-dot"
          :style="{
            backgroundColor: settingsStore.backendStatus === 'connected' ? 'var(--success)' : 'var(--error)',
          }"
        ></span>
        <span>{{ t('settings.pythonBackend') }}</span>
        <button class="btn btn-ghost btn-sm" style="padding:2px 6px; font-size:10px;" @click="settingsStore.restartBackend()">
          <ArrowPathIcon class="w-3 h-3" />
          <span>{{ t('common.restart') }}</span>
        </button>
      </div>
    </div>

    <!-- 设置内容区 -->
    <div style="flex:1; overflow:auto; padding:24px;">
      <ModelConfig v-if="settingsStore.activeTab === 'ai'" />
      <AgentManager v-else-if="settingsStore.activeTab === 'agents'" />
      <SkillManager v-else-if="settingsStore.activeTab === 'skills'" />
      <GeneralSettings v-else-if="settingsStore.activeTab === 'general'" />
      <ThemeManager v-else-if="settingsStore.activeTab === 'theme'" />
      <div v-else-if="settingsStore.activeTab === 'plugins'" class="empty-state">
        <PuzzlePieceIcon class="icon" />
        <div class="title">{{ t('settings.plugins') }}</div>
        <div class="desc">{{ t('settings.pluginsComingSoon') }}</div>
      </div>
      <AboutPage v-else-if="settingsStore.activeTab === 'about'" />
    </div>
  </div>
</template>

<style scoped>
.page-user {
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

.settings-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.settings-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
</style>
