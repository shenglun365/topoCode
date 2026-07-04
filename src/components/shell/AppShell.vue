<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
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
import { controlDispatcher } from '@/services/control-dispatcher'
import { usePanelStore } from '@/stores/panel'
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'
import { useConfirm } from '@/composables/useConfirm'
import { useAnalysisStore } from '@/stores/analysis'

const { t } = useI18n()

const { showId, componentId } = useComponentId('SH-001')
const { confirmState, confirmResolve } = useConfirm()
const route = useRoute()
const navigation = useNavigationStore()
const funcGroup = useFuncGroupStore()
const statusStore = useStatusStore()
const panelStore = usePanelStore()

// 路由 path 到功能组 ID 的映射
const routeToFuncGroupMap: { [key: string]: FuncGroupId } = {
    '/home': 'home',
    '/code': 'home',
    '/analysis': 'analysis',
    '/knowledge': 'knowledge',
    '/coder': 'coder',
    '/user': 'home',
    '/settings': 'home',
}

// 当前功能组
const currentFuncGroup = computed(() => {
    return routeToFuncGroupMap[route.path] || 'home';
})

// 是否隐藏左右侧栏
const isSettingsPage = computed(() => route.path === '/home' || route.path === '/user' || route.path === '/settings')
const hideLeftPanel = computed(() => route.path === '/home' || route.path === '/code' || route.path === '/user' || route.path === '/settings')
const isAuthPage = computed(() => route.path === '/login' || route.path === '/register')

const showSuccessBanner = ref(false)
const showErrorOverlay = ref(false)
const startingSince = ref(0)

function onBackendReady() {
  // 仅非 error 状态显示成功横幅
  if (statusStore.backend.status !== 'error') {
    showSuccessBanner.value = true
    showErrorOverlay.value = false
    setTimeout(() => { showSuccessBanner.value = false }, 2000)
  }
}

function dismissError() {
  showErrorOverlay.value = false
}

async function retryBackend() {
  try {
    await window.api!.backend.restart()
  } catch (e: any) {
    console.error('[AppShell] backend restart failed:', e)
  }
}

// 初始化后端状态监听
onMounted(async () => {
  try {
    const st: any = await window.api!.backend.getStatus()
    if (st) {
      statusStore.setBackendStatus(st)
      if (st.status === 'error') {
        showErrorOverlay.value = true
      } else if (st.status === 'running') {
        onBackendReady()
      } else if (st.status === 'starting') {
        startingSince.value = Date.now()
      }
    }
      } catch (_) {}

  // 订阅后端推送事件
  try {
    useAnalysisStore().subscribeToEvents()
  } catch (_) {}

  // 每 3 秒轮询本地 PythonBridge 状态（控制层，不经过 ZMQ，避免挂死）
  controlDispatcher.register('backend-status', {
    interval: 3000,
    fetcher: () => window.api!.backend.getStatus(),
    onData: (st: any) => {
      if (st) {
        const wasRunning = statusStore.backend.status === 'running'
        statusStore.setBackendStatus(st, true)
        if (st.status === 'error') {
          showErrorOverlay.value = true
          showSuccessBanner.value = false
        } else if (st.status === 'running') {
          if (!wasRunning) onBackendReady()
        } else if (st.status === 'starting') {
          if (!startingSince.value) startingSince.value = Date.now()
        }
      }
    },
    onError: () => {},
  })
})

const startingElapsed = computed(() => startingSince.value ? Date.now() - startingSince.value : 0)
const showStartingWarning = computed(() =>
  statusStore.backend.status === 'starting' && startingElapsed.value > 8000
)

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

onUnmounted(() => {
  controlDispatcher.unregister('backend-status')
});
</script>

<template>
  <div class="app-shell">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <!-- 后端状态提示条 -->
    <div
      v-if="showSuccessBanner"
      class="backend-error-banner banner-success"
    >
      <span>✓ 本地后端服务已连接</span>
    </div>
    <div
      v-if="statusStore.backend.status === 'starting'"
      class="backend-error-banner banner-warning"
    >
      <span>⏳ 本地后端服务启动中，请等待...</span>
      <span class="backend-error-msg">如长时间未响应，请查看日志：~/.config/topoone-ui/logs/（Linux）或 ~/Library/Application Support/topoone-ui/logs/（macOS）</span>
    </div>

    <!-- 后端异常 DOM 弹窗覆盖 -->
    <div
      v-if="showErrorOverlay"
      class="backend-error-overlay"
    >
      <div class="backend-error-modal">
        <div class="backend-error-icon">
          ⚠
        </div>
        <h2 class="backend-error-title">
          本地后端服务异常
        </h2>
        <div class="backend-error-body">
          <p class="backend-error-desc">
            后端 Python 进程未能正常启动或已意外退出，应用功能受限。
          </p>
          <p
            v-if="statusStore.backend.error"
            class="backend-error-detail"
          >
            {{ statusStore.backend.error }}
          </p>
          <p class="backend-error-hint">
            可能的原因：Python 依赖缺失、数据库文件损坏、端口被占用。
            <br>请检查终端输出的错误日志后重试。
          </p>
        </div>
        <div class="backend-error-actions">
          <button
            class="backend-error-btn primary"
            @click="retryBackend"
          >
            重试启动
          </button>
          <button
            class="backend-error-btn"
            @click="dismissError"
          >
            关闭提示
          </button>
        </div>
      </div>
    </div>

    <!-- 顶部菜单栏 -->
    <TopBar v-show="!panelStore.isFullscreen && !isAuthPage" />

    <!-- 主内容行 -->
    <div class="app-row2">
      <!-- 活动栏 -->
      <ActivityBar v-show="!panelStore.isFullscreen && !isAuthPage" />

      <!-- 左侧面板 -->
      <LeftPanel v-show="!hideLeftPanel && !panelStore.isFullscreen" />

      <!-- 主内容区 -->
      <main class="content-area" :class="{ 'auth-fullscreen': isAuthPage }">
        <div class="content-body">
          <router-view v-slot="{ Component }">
            <keep-alive>
              <component
                :is="Component"
                :key="route.name"
              />
            </keep-alive>
          </router-view>
        </div>
      </main>

      <!-- 右侧面板（设置页隐藏，全屏时用户可手动开启） -->
      <RightPanel v-show="!isSettingsPage && !isAuthPage" />
    </div>

    <!-- 底部状态栏 -->
    <StatusBar v-show="!panelStore.isFullscreen && !isAuthPage" />

    <!-- 新手引导 -->
    <OnboardingTour />

    <!-- 全局确认弹窗（替代 confirm()） -->
    <div v-if="confirmState.visible" class="confirm-overlay" @click.self="confirmResolve(confirmState.choices ? null : false)">
      <div class="confirm-box">
        <p>{{ confirmState.message }}</p>
        <div v-if="confirmState.choices" class="confirm-actions">
          <button
            v-for="c in confirmState.choices"
            :key="c.value"
            class="confirm-btn"
            :class="'confirm-btn-' + (c.variant || 'primary')"
            @click="confirmResolve(c.value)"
          >{{ c.label }}</button>
        </div>
        <div v-else class="confirm-actions">
          <button class="confirm-btn confirm-btn-primary" @click="confirmResolve(true)">{{ t('common.confirm') }}</button>
          <button class="confirm-btn" @click="confirmResolve(false)">{{ t('common.cancel') }}</button>
        </div>
      </div>
    </div>
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
.content-area.auth-fullscreen {
  height: 100vh;
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
.backend-error-banner.banner-success {
  background: #28a745;
}
.backend-error-msg {
  opacity: 0.85;
  font-family: monospace;
}

/* ---- 后端异常弹窗 ---- */
.backend-error-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
}
.backend-error-modal {
  max-width: 460px;
  width: 90vw;
  padding: 2rem;
  background: var(--bg-primary);
  border: 1px solid #e81123;
  border-radius: 0.75rem;
  box-shadow: 0 0 60px rgba(232, 17, 35, 0.25);
  text-align: center;
}
.backend-error-icon {
  font-size: 2.5rem;
  margin-bottom: 0.5rem;
}
.backend-error-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: #e81123;
  margin: 0 0 1rem;
}
.backend-error-body {
  text-align: left;
  margin-bottom: 1.5rem;
}
.backend-error-desc {
  font-size: 0.85rem;
  color: var(--text-primary);
  margin: 0 0 0.75rem;
}
.backend-error-detail {
  font-size: 0.75rem;
  font-family: var(--font-mono);
  color: #e81123;
  background: rgba(232, 17, 35, 0.08);
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  margin: 0 0 0.5rem;
  word-break: break-all;
}
.backend-error-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin: 0;
  line-height: 1.6;
}
.backend-error-actions {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
}
.backend-error-btn {
  padding: 0.45rem 1.25rem;
  font-size: 0.8rem;
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  background: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.15s;
}
.backend-error-btn:hover {
  border-color: var(--accent);
}
.backend-error-btn.primary {
  background: #e81123;
  color: #fff;
  border-color: #e81123;
}
.backend-error-btn.primary:hover {
  background: #c50f1f;
}

.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.confirm-box {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px 24px;
  min-width: 300px;
  max-width: 420px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.confirm-box p {
  margin: 0 0 16px;
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.5;
}

.confirm-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.confirm-btn {
  padding: 6px 16px;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.15s;
}

.confirm-btn:hover {
  border-color: var(--accent);
}

.confirm-btn-primary {
  background: #7c3aed;
  color: #fff;
  border-color: #7c3aed;
}

.confirm-btn-primary:hover {
  background: #6d28d9;
}
</style>
