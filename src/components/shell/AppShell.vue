<script setup lang="ts">
import { onMounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import TopBar from './TopBar.vue'
import ActivityBar from './ActivityBar.vue'
import LeftPanel from './LeftPanel.vue'
import RightPanel from './RightPanel.vue'
import StatusBar from './StatusBar.vue'
import OnboardingTour from '@/components/onboarding/OnboardingTour.vue'
import { useNavigationStore } from '@/stores/navigation'
import { useFuncGroupStore, type FuncGroupId } from '@/stores/funcGroup'
import { useStatusStore } from '@/stores/status'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-001')
const route = useRoute()
const navigation = useNavigationStore()
const funcGroup = useFuncGroupStore()
const statusStore = useStatusStore()

// 路由 path 到功能组 ID 的映射
const routeToFuncGroupMap: { [key: string]: FuncGroupId } = {
    '/home': 'home',
    '/code': 'home',
    '/analysis': 'analysis',
    '/knowledge': 'knowledge',
    '/coder': 'coder',
    '/user': 'home',
}

// 当前功能组
const currentFuncGroup = computed(() => {
    return routeToFuncGroupMap[route.path] || 'home';
})

// 是否隐藏左右侧栏（首页、设置页）
const isSettingsPage = computed(() => route.path === '/home' || route.path === '/user')

// 初始化后端状态监听
onMounted(async () => {
  try {
    const st = await window.api.backend.getStatus()
    if (st) statusStore.setBackendStatus(st)
  } catch (_) {}
  // 每 5 秒轮询本地 PythonBridge 状态（不经过 ZMQ，避免挂死）
  setInterval(async () => {
    try {
      const st = await window.api.backend.getStatus()
      if (st) statusStore.setBackendStatus(st, true)
    } catch (_) {}
  }, 5000)
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
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <!-- 后端状态提示条 -->
    <div
      v-if="statusStore.backend.status === 'error' || (statusStore.backend.status === 'starting' && Date.now() > 15000)"
      class="backend-error-banner"
      :class="{ 'banner-warning': statusStore.backend.status === 'starting' }"
    >
      <template v-if="statusStore.backend.status === 'error'">
        <span>⚠ 后端服务异常</span>
        <span class="backend-error-msg">{{ statusStore.backend.error }}</span>
      </template>
      <template v-else>
        <span>⏳ 尚未检测到后端服务，请等待 3~5 秒</span>
        <span class="backend-error-msg">如长时间未响应，请查看日志：%APPDATA%/topoone-ui/logs/ （Win） / ~/Library/Application Support/topoone-ui/logs/ （Mac） / ~/.config/topoone-ui/logs/ （Linux）</span>
      </template>
    </div>

    <!-- 顶部菜单栏 -->
    <TopBar />

    <!-- 主内容行 -->
    <div class="app-row2">
      <!-- 活动栏 -->
      <ActivityBar />

      <!-- 左侧面板（设置页隐藏） -->
      <LeftPanel v-show="!isSettingsPage" />

      <!-- 主内容区 -->
      <main class="content-area">
        <div class="content-body">
          <router-view v-slot="{ Component }">
            <keep-alive :include="['CoderPage']">
              <component
                :is="Component"
                :key="route.name"
              />
            </keep-alive>
          </router-view>
        </div>
      </main>

      <!-- 右侧面板（设置页隐藏） -->
      <RightPanel v-show="!isSettingsPage" />
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

.backend-error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 16px;
  background: #e81123;
  color: #fff;
  font-size: 12px;
  flex-shrink: 0;
}
.backend-error-banner.banner-warning {
  background: #d4941e;
}
.backend-error-msg {
  opacity: 0.85;
  font-family: monospace;
}
</style>
