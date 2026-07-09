<script setup lang="ts">
import { onMounted, watch, computed } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useSettingsStore } from '@/stores/settings-store'
import { useModelConfigStore } from '@/stores/model-config-store'
import { useProjectStore } from '@/stores/project'
import AppShell from '@/components/shell/AppShell.vue'
import { useComponentId } from '@/composables/useComponentId'

const themeStore = useThemeStore()
const settingsStore = useSettingsStore()
const modelConfigStore = useModelConfigStore()
const projectStore = useProjectStore()
const { showId, componentId } = useComponentId('AP-001')

const importPhaseLabel = computed(() => {
  switch (projectStore.importStatus) {
    case 'scan': return '正在扫描文件...'
    case 'write': return '正在写入数据...'
    default: return '正在导入...'
  }
})

// 字体大小实时生效（各页面通用）
watch(() => settingsStore.fontSize, (val) => {
  document.documentElement.style.fontSize = val + 'px'
})

onMounted(async () => {
  themeStore.init()
  await modelConfigStore.loadModels()
  document.documentElement.style.fontSize = settingsStore.fontSize + 'px'
})
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <AppShell />

  <!-- 项目导入全局遮罩：阻止所有交互操作 -->
  <Teleport to="body">
    <div
      v-if="projectStore.importing"
      class="import-block-overlay"
    >
      <div class="import-block-card">
        <div class="import-block-spinner" />
        <span class="import-block-title">项目导入中，请稍候...</span>
        <span class="import-block-phase">{{ importPhaseLabel }}</span>
        <div class="import-block-bar">
          <div
            class="import-block-fill"
            :style="{ width: (projectStore.importProgress || 0) + '%' }"
          />
        </div>
        <span class="import-block-pct">{{ projectStore.importProgress || 0 }}%</span>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* 无 scoped 样式在此，使用全局样式确保遮罩层级 */
</style>

<style>
.import-block-overlay {
  position: fixed;
  inset: 0;
  z-index: 99999;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: all;
  cursor: not-allowed;
}
.import-block-card {
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 32px 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  min-width: 280px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}
.import-block-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border);
  border-top-color: var(--accent, #7c3aed);
  border-radius: 50%;
  animation: import-spin 0.8s linear infinite;
}
@keyframes import-spin {
  to { transform: rotate(360deg); }
}
.import-block-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.import-block-phase {
  font-size: 12px;
  color: var(--text-muted);
}
.import-block-bar {
  width: 100%;
  height: 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
}
.import-block-fill {
  height: 100%;
  background: var(--accent, #7c3aed);
  border-radius: 3px;
  transition: width 0.3s;
}
.import-block-pct {
  font-size: 11px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
</style>
