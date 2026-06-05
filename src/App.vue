<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useSettingsStore } from '@/stores/settings-store'
import { useModelConfigStore } from '@/stores/model-config-store'
import AppShell from '@/components/shell/AppShell.vue'

const themeStore = useThemeStore()
const settingsStore = useSettingsStore()
const modelConfigStore = useModelConfigStore()

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
  <AppShell />
</template>

<style scoped>
</style>
