<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useSettingsStore } from '@/stores/settings-store'
import { useModelConfigStore } from '@/stores/model-config-store'
import AppShell from '@/components/shell/AppShell.vue'
import { useComponentId } from '@/composables/useComponentId'

const themeStore = useThemeStore()
const settingsStore = useSettingsStore()
const modelConfigStore = useModelConfigStore()
const { showId, componentId } = useComponentId('AP-001')

// 字体大小实时生效（各页面通用）
watch(() => settingsStore.fontSize, (val) => {
  document.documentElement.style.fontSize = val + 'px'
})

onMounted(async () => {
  themeStore.init()
  await modelConfigStore.loadModels()
  document.documentElement.style.fontSize = settingsStore.fontSize + 'px'
  setTimeout(() => {
    const defaultModel = modelConfigStore.models.find(m => m.isDefault)
    if (defaultModel) {
      modelConfigStore.testModel(defaultModel.id)
    }
  }, 2000)
})
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <AppShell />
</template>

<style scoped>
</style>
