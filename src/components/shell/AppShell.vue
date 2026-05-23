<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import TopBar from './TopBar.vue'
import ActivityBar from './ActivityBar.vue'
import LeftPanel from './LeftPanel.vue'
import RightPanel from './RightPanel.vue'
import StatusBar from './StatusBar.vue'
import OnboardingTour from '@/components/onboarding/OnboardingTour.vue'
import { useNavigationStore } from '@/stores/navigation'
import { useFuncGroupStore, type FuncGroupId } from '@/stores/funcGroup'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-001')
const route = useRoute()
const navigation = useNavigationStore()
const funcGroup = useFuncGroupStore()

// 路由 path 到功能组 ID 的映射
const routeToFuncGroupMap: { [key: string]: FuncGroupId } = {
    '/home': 'home',
    '/analysis': 'analysis',
    '/knowledge': 'knowledge',
    '/coder': 'coder',
    '/user': 'home',
}

// 当前功能组
const currentFuncGroup = computed(() => {
    return routeToFuncGroupMap[route.path] || 'home';
})

// 同步路由切换和功能组切换
watch(
    () => route.path,
    (newPath) => {
        const group = routeToFuncGroupMap[newPath];
        if (group) {
            funcGroup.switchFuncGroup(group);
        }
    }
);
</script>

<template>
  <div class="app-shell">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- 顶部菜单栏 -->
    <TopBar />

    <!-- 主内容行 -->
    <div class="app-row2">
      <!-- 活动栏 -->
      <ActivityBar />

      <!-- 左侧面板 -->
      <LeftPanel />

      <!-- 主内容区 -->
      <main class="content-area">
        <div class="content-body">
          <router-view v-slot="{ Component }">
            <keep-alive :include="['CoderPage']">
              <component :is="Component" :key="route.name" />
            </keep-alive>
          </router-view>
        </div>
      </main>

      <!-- 右侧面板 -->
      <RightPanel />
    </div>

    <!-- 底部状态栏 -->
    <StatusBar />

    <!-- 新手引导 -->
    <OnboardingTour />
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
}

.app-row2 {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.content-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-primary);
}

.content-body {
  flex: 1;
  overflow: auto;
  position: relative;
}
</style>
