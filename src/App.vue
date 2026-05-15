<script setup lang="ts">
import { onMounted } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useSettingsStore } from '@/stores/settings'
import AppShell from '@/components/shell/AppShell.vue'

const themeStore = useThemeStore()
const settingsStore = useSettingsStore()

onMounted(async () => {
  themeStore.init()
  // 应用启动时加载模型/Agent/Skill 配置
  await settingsStore.loadSettings()
})
</script>

<template>
  <AppShell />
</template>

<style scoped>
</style>
