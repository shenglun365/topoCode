<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useSettingsStore } from '@/stores/settings'
import AppShell from '@/components/shell/AppShell.vue'

const themeStore = useThemeStore()
const settingsStore = useSettingsStore()

// 字体大小实时生效（各页面通用）
watch(() => settingsStore.fontSize, (val) => {
  document.documentElement.style.fontSize = val + 'px'
})

onMounted(async () => {
  themeStore.init()
  // 应用启动时加载模型/Agent/Skill 配置
  await settingsStore.loadSettings()
  // 初始化字体大小
  document.documentElement.style.fontSize = settingsStore.fontSize + 'px'
  // 延迟 2 秒后自动测试默认模型连接（等待后端就绪）
  setTimeout(() => {
    const defaultModel = settingsStore.models.find(m => m.isDefault)
    if (defaultModel) {
      settingsStore.testModel(defaultModel.id)
    }
  }, 2000)
})
</script>

<template>
  <AppShell />
</template>

<style scoped>
</style>
