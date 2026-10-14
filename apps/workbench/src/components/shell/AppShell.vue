<script setup lang="ts">
import { onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import TopBar from './TopBar.vue'
import ActivityBar from './ActivityBar.vue'
import RightPanel from './RightPanel.vue'
import StatusBar from './StatusBar.vue'
import OnboardingTour from '@/components/onboarding/OnboardingTour.vue'
import { useFuncGroupStore, type FuncGroupId } from '@/stores/funcGroup'
import { useStatusStore } from '@/stores/status'
import { controlDispatcher } from '@/services/control-dispatcher'
import { usePanelStore } from '@/stores/panel'
import { useProjectStore } from '@/stores/project'
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'
import { useDialog } from '@topo/web-core/composables/useDialog'
import AppDialog from '@topo/web-core/components/AppDialog.vue'
import { useAnalysisStore } from '@/stores/analysis'
import { useCrashReportStore } from '@/stores/crashReport'

const { t } = useI18n()

const { showId, componentId } = useComponentId('SH-001')
const { dialog } = useDialog()
const route = useRoute()
const funcGroup = useFuncGroupStore()
const statusStore = useStatusStore()
const panelStore = usePanelStore()
const projectStore = useProjectStore()
const crashReportStore = useCrashReportStore()

// P5: URL 为项目唯一事实源；回退最近项目（多页签各自 URL 驱动，互不影响）
const LAST_PROJECT_KEY = 'topoone-last-project'
const TITLE_PAGE_KEYS: Record<string, string> = {
  '/home': 'nav.projects',
  '/code': 'nav.code',
  '/analysis': 'pageTitle.analysis',
  '/chat': 'nav.chat',
  '/coder': 'nav.coder',
}

async function syncProjectFromRoute() {
  const qProject = typeof route.query.project === 'string' ? route.query.project : ''
  if (route.path === '/home') {
    projectStore.deselectProject()
    return
  }
  if (route.path !== '/code' && route.path !== '/analysis') return
  const id = qProject || localStorage.getItem(LAST_PROJECT_KEY) || ''
  if (!id) return
  const group = route.path === '/analysis' ? 'analysis' : 'code'
  if (funcGroup.context[group].projectId === id) return
  // 最近项目键由 projectStore.selectProject 统一维护
  await projectStore.selectProject(id)
}

function updateTitle() {
  const project = projectStore.selectedProject
  const pageKey = TITLE_PAGE_KEYS[route.path]
  const parts = ['TopoCode']
  if (project?.name) parts.push(project.name)
  if (pageKey) parts.push(t(pageKey))
  document.title = parts.join(' · ')
}

watch(
  () => [route.query.project, route.path] as const,
  () => syncProjectFromRoute(),
  { immediate: true },
)

watch(
  () => [projectStore.selectedProject, route.path] as const,
  () => updateTitle(),
  { immediate: true },
)

// 路由 path 到功能组 ID 的映射
const routeToFuncGroupMap: { [key: string]: FuncGroupId } = {
    '/home': 'home',
    '/code': 'home',
    '/analysis': 'analysis',
    '/coder': 'coder',
}

// 当前功能组
const currentFuncGroup = computed(() => {
    return routeToFuncGroupMap[route.path] || 'home';
})

// 是否隐藏左右侧栏
const hideShellPage = computed(() => route.meta.hideShell === true)
const isSettingsPage = computed(() => route.path === '/home')
const isAuthPage = computed(() => hideShellPage.value)

// 后端状态轮询：仅更新状态供状态栏展示。
// 后台服务状态的弹窗提示机制已移除（后续由独立的服务状态监控页面统一设计）。
onMounted(async () => {
   try {
     const st: any = await window.api!.backend.getStatus()
     if (st) {
       statusStore.setBackendStatus(st)
     }
   } catch (_) {}

   // 初始化崩溃报告存储
   crashReportStore.init()

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
         statusStore.setBackendStatus(st, true)
       }
     },
     onError: () => {},
   })
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

onUnmounted(() => {
  controlDispatcher.unregister('backend-status')
  crashReportStore.cleanup()
});
</script>

<template>
  <div class="app-shell">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <!-- 顶部菜单栏 -->
    <TopBar v-show="!panelStore.isFullscreen && !isAuthPage" />

    <!-- 主内容行 -->
    <div class="app-row2">
      <!-- 活动栏 -->
      <ActivityBar v-show="!panelStore.isFullscreen && !isAuthPage" />

      <!-- 主内容区 -->
      <main
        class="content-area"
        :class="{ 'auth-fullscreen': isAuthPage }"
      >
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

    <!-- 崩溃报告弹窗 -->
    <div
      v-if="crashReportStore.showDialog && crashReportStore.selectedCrash"
      class="confirm-overlay"
      @click.self="crashReportStore.closeDialog"
    >
      <div class="confirm-box crash-dialog">
        <h3 class="crash-dialog-title">{{ t('shell.crashDialog.title') }}</h3>
        <div class="crash-dialog-body">
          <p>{{ t('shell.crashDialog.intro') }}</p>
          <pre class="crash-detail">{{ crashReportStore.selectedCrash.summary }}</pre>
          <p class="crash-time">
            {{ t('shell.crashDialog.time', { time: crashReportStore.selectedCrash.timestamp }) }}
          </p>
          <p class="crash-hint">
            {{ t('shell.crashDialog.hint') }}
          </p>
        </div>
        <div class="confirm-actions">
          <button
            class="confirm-btn confirm-btn-primary"
            @click="crashReportStore.report(crashReportStore.selectedCrash!)"
          >
            {{ t('shell.crashDialog.report') }}
          </button>
          <button
            class="confirm-btn"
            @click="crashReportStore.dismiss(crashReportStore.selectedCrash!)"
          >
            {{ t('shell.crashDialog.dismiss') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 新手引导 -->
    <OnboardingTour />

    <!-- 全局确认/选择弹窗（MS3-U4: useDialog 统一, 吸收原 useConfirm） -->
    <AppDialog :dialog="dialog" @ok="(v) => dialog.onOk?.(v)" @cancel="dialog.onCancel?.()" />
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

/* ---- 全局确认弹窗 ---- */
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
  border-radius: calc(10px * var(--ui-scale, 1));
  padding: calc(20px * var(--ui-scale, 1)) calc(24px * var(--ui-scale, 1));
  min-width: calc(300px * var(--ui-scale, 1));
  max-width: calc(420px * var(--ui-scale, 1));
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.confirm-box p {
  margin: 0 0 calc(16px * var(--ui-scale, 1));
  font-size: calc(14px * var(--ui-scale, 1));
  color: var(--text-primary);
  line-height: 1.5;
}

.confirm-actions {
  display: flex;
  gap: calc(8px * var(--ui-scale, 1));
  justify-content: flex-end;
}

.confirm-btn {
  padding: calc(6px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1));
  font-size: calc(13px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
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

/* 崩溃报告弹窗 */
.crash-dialog {
  max-width: calc(480px * var(--ui-scale, 1));
}
.crash-dialog-title {
  margin: 0 0 calc(12px * var(--ui-scale, 1));
  font-size: calc(16px * var(--ui-scale, 1));
  color: var(--error);
}
.crash-dialog-body p {
  margin: 0 0 calc(8px * var(--ui-scale, 1));
  font-size: calc(13px * var(--ui-scale, 1));
}
.crash-detail {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  padding: calc(10px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  font-family: var(--font-mono);
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0 0 calc(8px * var(--ui-scale, 1));
}
.crash-time {
  color: var(--text-muted);
  font-size: calc(12px * var(--ui-scale, 1));
}
.crash-hint {
  color: var(--text-muted);
  font-size: calc(12px * var(--ui-scale, 1));
}
</style>
