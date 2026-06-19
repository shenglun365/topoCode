<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  FolderIcon,
  Cog6ToothIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useNavigationStore } from '@/stores/navigation'
import { useAnalysisStore } from '@/stores/analysis'
import { useSettingsStore } from '@/stores/settings-store'
import TaskListPanel from '@/components/analysis/TaskListPanel.vue'
import TaskCreateForm from '@/components/analysis/TaskCreateForm.vue'
import ClearCacheDialog from '@/components/project/ClearCacheDialog.vue'
import { useComponentId } from '@/composables/useComponentId'
import { useCommunityStore } from '@/stores/community-store'

const { showId, componentId } = useComponentId('PG-002')
const { t } = useI18n()
const router = useRouter()
const navigation = useNavigationStore()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()
const settingsStore = useSettingsStore()

const showClearCacheDialog = ref(false)
const selectedProject = projectStore.selectedProject

onMounted(() => {
  navigation.navigateTo('code')
})

function onTaskCreated(taskId: string) {
  if (projectStore.activeTabId) {
    projectStore.closeTab(projectStore.activeTabId)
  }
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
  if (projectStore.selectedProjectId) {
    analysisStore.loadTasks(projectStore.selectedProjectId)
    // 清除前端 store 中的社区/组件缓存，避免清后端后还显示旧数据
    const communityStore = useCommunityStore()
    for (const task of analysisStore.tasks) {
      communityStore.clearTask(task.id)
    }
  }
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
          class="btn btn-ghost btn-sm"
          @click="showMenu"
        >
          <Cog6ToothIcon class="w-4 h-4" />
          <span>{{ t('project.projectSettings') }}</span>
        </button>
        <button
          class="btn btn-ghost btn-sm"
          @click="goBack"
        >
          {{ t('common.back') }}
        </button>
      </div>

      <!-- 内容区 -->
      <div class="code-tab-content">
        <template v-if="projectStore.activeTab?.kind === 'taskCreate'">
          <TaskCreateForm
            :project-id="projectStore.selectedProjectId!"
            :task-id="projectStore.activeTab.taskId"
            @created="onTaskCreated"
            @cancelled="onTaskCreated('')"
          />
        </template>
        <template v-else>
          <div class="task-list-panel">
            <TaskListPanel
              :project-id="projectStore.selectedProjectId!"
              @create-task="onTaskListCreateTask"
            />
          </div>
        </template>
      </div>
    </template>

    <!-- 清除缓存菜单 -->
    <Teleport to="body">
      <div
        v-if="menuVisible"
        class="menu-overlay"
        @click="hideMenu"
      >
        <div
          class="menu-popup"
          :style="{ left: menuPosition.x + 'px', top: menuPosition.y + 'px' }"
          @click.stop
        >
          <button
            class="menu-item"
            @click="handleClearCache"
          >
            <Cog6ToothIcon class="w-4 h-4" />
            <span>{{ t('project.clearCache') }}</span>
          </button>
        </div>
      </div>
    </Teleport>

    <!-- 清除缓存确认弹窗 -->
    <ClearCacheDialog
      v-if="showClearCacheDialog"
      :project-id="projectStore.selectedProjectId!"
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

.task-list-panel,
.task-create-form {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.empty-state.centered {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.menu-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
}

.menu-popup {
  position: fixed;
  z-index: 10000;
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border, #313244);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  min-width: 160px;
  padding: 4px;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  background: transparent;
  color: var(--text-primary, #cdd6f4);
  font-size: 13px;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
}

.menu-item:hover {
  background: var(--bg-hover, #313244);
}
</style>
