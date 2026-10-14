<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import AppHome from './AppHome.vue'
import UserCenterPage from './user/UserCenterPage.vue'

/**
 * 门户宿主（P7）：微型 hash 路由。
 * `#/` 首页模块卡片；`#/user` 用户中心。
 * (MS3-U6 案A: `#/settings` 设置中心随工作台域迁 apps/workbench/src/components/settings, portal 独立构建不再含设置面)
 */
const route = ref(window.location.hash || '#/')

function sync() {
  route.value = window.location.hash || '#/'
}

onMounted(() => window.addEventListener('hashchange', sync))
onUnmounted(() => window.removeEventListener('hashchange', sync))
</script>

<template>
  <UserCenterPage v-if="route.startsWith('#/user')" />
  <AppHome v-else />
</template>
