<script setup lang="ts">
import TopBar from './TopBar.vue'
import ActivityBar from './ActivityBar.vue'
import LeftPanel from './LeftPanel.vue'
import RightPanel from './RightPanel.vue'
import StatusBar from './StatusBar.vue'
import OnboardingTour from '@/components/onboarding/OnboardingTour.vue'
</script>

<template>
  <div class="app-shell">
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
          <router-view />
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
