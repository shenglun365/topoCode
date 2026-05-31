<script setup lang="ts">
import { onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  FolderIcon,
  Cog6ToothIcon,
  DocumentTextIcon,
  XCircleIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useNavigationStore } from '@/stores/navigation'
import { useAnalysisStore } from '@/stores/analysis'
import { useSettingsStore } from '@/stores/settings'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import CodeViewer from '@/components/code/CodeViewer.vue'
import TaskListPanel from '@/components/analysis/TaskListPanel.vue'
import TaskCreateForm from '@/components/analysis/TaskCreateForm.vue'
import GroupManager from '@/components/project/GroupManager.vue'
import ClearCacheDialog from '@/components/project/ClearCacheDialog.vue'
import { useComponentId } from '@/composables/useComponentId'
import { ref } from 'vue'

const { showId, componentId } = useComponentId('PG-002')
const { t } = useI18n()
const router = useRouter()
const navigation = useNavigationStore()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()
const settingsStore = useSettingsStore()

const showClearCacheDialog = ref(false)
const selectedProject = projectStore.selectedProject
const isSample = selectedProject?.isSample

onMounted(() => {
  navigation.navigateTo('code')
})

function onTabUpdate(tabId: string | null) {
  projectStore.setActiveTab(tabId)
}

function onTabClose(tabId: string) {
  projectStore.closeTab(tabId)
}

function onCloseCodeViewer() {
  if (projectStore.activeTabId) {
    projectStore.closeTab(projectStore.activeTabId)
  }
  projectStore.openTaskListTab()
}

function onTaskCreated(taskId: string) {
  if (projectStore.activeTabId) {
    projectStore.closeTab(projectStore.activeTabId)
  }
  projectStore.openTaskListTab()
}

function onTaskListCreateTask(taskId?: string) {
  projectStore.openTaskCreateForm(taskId)
}

function goBack() {
  projectStore.deselectProject()
  router.push('/home')
  navigation.navigateTo('home')
}

function goHome() {
  router.push('/home')
  navigation.navigateTo('home')
}

// ===== 项目设置菜单（清除缓存） =====
const menuVisible = ref(false)
const menuPosition = ref({ x: 0, y: 0 })

function showMenu(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  menuVisible.value = true
  const menuW = 160
  const menuH = 44
  let x = e.clientX
  let y = e.clientY
  if (x + menuW > window.innerWidth) x = window.innerWidth - menuW - 8
  if (y + menuH > window.innerHeight) y = window.innerHeight - menuH - 8
  if (x < 4) x = 4
  if (y < 4) y = 4
  menuPosition.value = { x, y }
}

function hideMenu() {
  menuVisible.value = false
}

function handleClearCache() {
  hideMenu()
  showClearCacheDialog.value = true
}

function onClearCacheDone() {
  showClearCacheDialog.value = false
  projectStore.loadProjects()
}
</script>

<template>
  <div class="page-code">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <!-- 无项目时提示 -->
    <div
      v-if="!projectStore.selectedProjectId"
      class="empty-state centered no-project-hint"
    >
      <FolderIcon class="w-12 h-12 text-accent" />
      <div class="title">
        {{ t('code.noProject') }}
      </div>
      <div class="desc">
        {{ t('code.noProjectDesc') }}
      </div>
      <button
        class="btn btn-primary btn-sm"
        style="margin-top:16px;"
        @click="goHome"
      >
        {{ t('code.goHome') }}
      </button>
    </div>

    <!-- 项目视图 -->
    <template v-else>
      <!-- 项目标题栏 -->
      <div
        style="display:flex; align-items:center; padding:8px 16px; border-bottom:1px solid var(--border); gap:12px;"
      >
        <FolderIcon class="w-4 h-4 text-accent" />
        <span style="font-size:13px; font-weight:600;">{{ projectStore.selectedProject?.name }}</span>
        <span
          class="badge badge-green"
          style="font-size:8px;"
        >{{ t('project.synced') }}</span>
        <div style="flex:1;" />
        <button
          v-if="projectStore.tabs.length > 0"
          class="btn btn-ghost btn-sm"
          :title="t('project.closeAllTabs')"
          @click="projectStore.closeAllTabs()"
        >
          <XCircleIcon class="w-4 h-4" />
          <span>{{ t('project.closeAllTabs') }}</span>
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :title="t('analysis.taskList')"
          @click="projectStore.openTaskListTab()"
        >
          <svg
            class="w-4 h-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M12 6V12L16 14" />
            <circle cx="12" cy="12" r="9" />
          </svg>
          <span>{{ t('analysis.taskList') }}</span>
        </button>
        <button
          class="btn btn-ghost btn-sm"
          @click="showMenu"
        >
          <Cog6ToothIcon class="w-4 h-4" />
          <span>{{ t('common.settings') }}</span>
        </button>
        <button
          class="btn btn-ghost btn-sm"
          @click="goBack"
        >
          {{ t('common.back') }}
        </button>
      </div>

      <!-- Tab 栏 -->
      <HomeTabBar
        v-if="projectStore.currentProjectTabs.length > 0"
        :tabs="projectStore.currentProjectTabs"
        :active-tab-id="projectStore.activeTabId"
        @update:active-tab-id="onTabUpdate"
        @close="onTabClose"
      />

      <!-- 内容区 -->
      <div class="code-tab-content">
        <!-- 代码视图 -->
        <div
          v-if="projectStore.activeTab?.kind === 'file'"
          class="code-viewer-full"
        >
          <CodeViewer
            :node="projectStore.activeTab.node!"
            :root-path="projectStore.selectedProject?.rootPath || projectStore.selectedProject?.path || ''"
            @close="onCloseCodeViewer"
          />
        </div>

        <!-- 任务列表 -->
        <div
          v-else-if="projectStore.activeTab?.kind === 'taskList'"
          class="task-list-panel"
        >
          <TaskListPanel
            :project-id="projectStore.selectedProjectId!"
            @create-task="onTaskListCreateTask"
          />
        </div>

        <!-- 新建/编辑任务 -->
        <div
          v-else-if="projectStore.activeTab?.kind === 'taskCreate'"
          class="task-create-form"
        >
          <TaskCreateForm
            :project-id="projectStore.selectedProjectId!"
            :task-id="projectStore.activeTab.taskId"
            @created="onTaskCreated"
            @cancelled="onCloseCodeViewer"
          />
        </div>

        <!-- 分组管理 -->
        <div
          v-else-if="projectStore.activeTab?.kind === 'groupManager'"
          class="group-manager-panel"
        >
          <GroupManager />
        </div>

        <!-- 空状态 -->
        <div
          v-else
          class="empty-state centered"
        >
          <DocumentTextIcon class="w-12 h-12 text-accent" />
          <div class="title">
            {{ t('file.selectFile') }}
          </div>
          <div class="desc">
            {{ t('file.selectFileDesc') }}
          </div>
        </div>
      </div>
    </template>

    <!-- 清除缓存菜单 -->
    <Teleport to="body">
      <div
        v-if="menuVisible"
        class="context-menu"
        :style="{ left: menuPosition.x + 'px', top: menuPosition.y + 'px' }"
        @click.stop
        @mouseleave="hideMenu"
      >
        <div
          v-if="!isSample"
          class="context-menu-item context-menu-item-warning"
          @click="handleClearCache"
        >
          <svg
            class="w-4 h-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M4 7H20" />
            <path d="M6 7V18C6 19.1046 6.89543 20 8 20H16C17.1046 20 18 19.1046 18 18V7" />
            <path d="M9 7V4H15V7" />
          </svg>
          <span>{{ t('project.clearCache') }}</span>
        </div>
      </div>
    </Teleport>

    <div
      v-if="menuVisible"
      class="context-menu-backdrop"
      @click="hideMenu"
    />

    <ClearCacheDialog
      v-if="showClearCacheDialog"
      :project-id="selectedProject?.id || ''"
      @close="onClearCacheDone"
    />
  </div>
</template>

<style scoped>
.page-code {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.code-tab-content {
  flex: 1;
  overflow: auto;
  display: flex;
}

.code-viewer-full {
  flex: 1;
  overflow: hidden;
}

.task-list-panel,
.task-create-form,
.group-manager-panel {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.group-manager-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.group-manager-body {
  flex: 1;
  overflow: hidden;
}

.empty-state.centered {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
</style>
