<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import AppHome from './AppHome.vue'
import SettingsPage from './settings/SettingsPage.vue'
import UserCenterPage from './user/UserCenterPage.vue'

/**
 * 门户宿主（P7）：微型 hash 路由。
 * `#/` 首页模块卡片；`#/settings` 统一设置中心；`#/user` 用户中心。
 */
const route = ref(window.location.hash || '#/')

function sync() {
  route.value = window.location.hash || '#/'
}

onMounted(() => window.addEventListener('hashchange', sync))
onUnmounted(() => window.removeEventListener('hashchange', sync))
</script>

<template>
  <SettingsPage v-if="route.startsWith('#/settings')" />
  <UserCenterPage v-else-if="route.startsWith('#/user')" />
  <AppHome v-else />
</template>
