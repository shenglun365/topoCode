<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon,
  Cog6ToothIcon,
  DocumentTextIcon,
  RocketLaunchIcon,
  XCircleIcon,
  XMarkIcon,
  LightBulbIcon,
  CodeBracketIcon,
  ChatBubbleLeftRightIcon,
  WrenchScrewdriverIcon,
  MagnifyingGlassIcon,
  StarIcon,
  Squares2X2Icon,
  ArchiveBoxXMarkIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import ConfirmDialog from '@/components/shared/ConfirmDialog.vue'
import { useAnalysisStore } from '@/stores/analysis'
import { useOnboardingStore } from '@/stores/onboarding'
import { useSettingsStore } from '@/stores/settings'
import ProjectCard from '@/components/project/ProjectCard.vue'
import GroupFilter from '@/components/project/GroupFilter.vue'
import GroupManager from '@/components/project/GroupManager.vue'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import CodeViewer from '@/components/code/CodeViewer.vue'
import TaskListPanel from '@/components/analysis/TaskListPanel.vue'
import TaskCreateForm from '@/components/analysis/TaskCreateForm.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PG-001')
const { t } = useI18n()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()
const onboardingStore = useOnboardingStore()
const settingsStore = useSettingsStore()

// 筛选模式: all | favorites
const filterMode = ref<'all' | 'favorites'>('all')

// 分组筛选
const selectedGroupIds = ref<string[]>([])
const groupFilterRef = ref<InstanceType<typeof GroupFilter> | null>(null)

// 分页
const currentPage = ref(1)
const pageSize = computed(() => settingsStore.projectPageSize)

// 复合搜索
const searchQuery = ref('')

/** 解析复合搜索查询字符串，支持 group:xxx name:xxx language:xxx */
function parseSearchQuery(query: string): { group?: string; name?: string; language?: string; free?: string } {
  const result: { group?: string; name?: string; language?: string; free?: string } = {}
  const tokens = query.trim().split(/\s+/).filter(Boolean)
  const freeTokens: string[] = []

  for (const token of tokens) {
    const colonIdx = token.indexOf(':')
    if (colonIdx > 0) {
      const key = token.slice(0, colonIdx).toLowerCase()
      const value = token.slice(colonIdx + 1).toLowerCase()
      if (key === 'group') result.group = value
      else if (key === 'name') result.name = value
      else if (key === 'language') result.language = value
      else freeTokens.push(token)
    } else {
      freeTokens.push(token.toLowerCase())
    }
  }
  if (freeTokens.length > 0) result.free = freeTokens.join(' ')
  return result
}

// 按筛选模式 + 分组过滤
const scopeFilteredProjects = computed(() => {
  let list = projectStore.projects
  if (filterMode.value === 'favorites') {
    list = list.filter(p => p.favorite)
  }
  // 按分组筛选
  if (selectedGroupIds.value.length > 0) {
    list = list.filter(p => {
      const pGroups = p.groups || []
      return selectedGroupIds.value.some(gid => pGroups.includes(gid))
    })
  }
  return list
})

// 应用搜索过滤
const searchFilteredProjects = computed(() => {
  const parsed = parseSearchQuery(searchQuery.value)
  if (!searchQuery.value.trim()) return scopeFilteredProjects.value

  return scopeFilteredProjects.value.filter(p => {
    // group 过滤
    if (parsed.group && !(p.group || '').toLowerCase().includes(parsed.group)) return false
    // name 过滤
    if (parsed.name && !p.name.toLowerCase().includes(parsed.name)) return false
    // language 过滤
    if (parsed.language && !p.language.toLowerCase().includes(parsed.language)) return false
    // 自由文本过滤（匹配 name/group/language/path）
    if (parsed.free) {
      const searchText = `${p.name} ${p.group || ''} ${p.language} ${p.rootPath || p.path}`.toLowerCase()
      for (const word of parsed.free.split(' ')) {
        if (!searchText.includes(word)) return false
      }
    }
    return true
  })
})

// 分页后的项目列表
const pagedProjects = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return searchFilteredProjects.value.slice(start, start + pageSize.value)
})

// 总页数
const totalPages = computed(() => {
  return Math.ceil(searchFilteredProjects.value.length / pageSize.value)
})

// 当前页项目范围
const pageRange = computed(() => {
  const total = searchFilteredProjects.value.length
  if (total === 0) return { start: 0, end: 0, total: 0 }
  const start = (currentPage.value - 1) * pageSize.value + 1
  const end = Math.min(currentPage.value * pageSize.value, total)
  return { start, end, total }
})

// 切换筛选模式时重置页码
watch(filterMode, () => { currentPage.value = 1 })
watch(searchQuery, () => { currentPage.value = 1 })

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
  // 关闭新建任务 tab，切换回任务列表
  if (projectStore.activeTabId) {
    projectStore.closeTab(projectStore.activeTabId)
  }
  projectStore.openTaskListTab()
}

function onTaskListCreateTask(taskId?: string) {
  projectStore.openTaskCreateForm(taskId)
}

onMounted(async () => {
  await projectStore.loadProjects()
})

// ===== 项目设置菜单（清除缓存） =====
const menuVisible = ref(false)
const menuPosition = ref({ x: 0, y: 0 })
const showClearCacheConfirm = ref(false)
const selectedProject = computed(() => projectStore.selectedProject)
const isSample = computed(() => !!selectedProject.value?.isSample)

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

async function handleClearCache() {
  hideMenu()
  showClearCacheConfirm.value = true
}

async function confirmClearCache() {
  if (!selectedProject.value) return
  showClearCacheConfirm.value = false
  try {
    await projectStore.clearProjectCache(selectedProject.value.id)
    await projectStore.loadProjects()
  } catch (err: any) {
    console.error('Failed to clear cache:', err)
  }
}
</script>

<template>
  <div class="page-home">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- 默认视图: 项目列表 + 导入 -->
    <div
      v-if="projectStore.viewMode === 'default'"
      class="home-default-view"
    >
      <!-- 分组管理（覆盖整个默认视图） -->
      <div v-if="projectStore.activeTab?.kind === 'groupManager'" class="group-manager-panel">
        <div class="group-manager-header">
          <h3 style="font-size:14px; font-weight:600; margin:0;">{{ t('group.manager') }}</h3>
          <button class="btn btn-ghost btn-sm" @click="projectStore.closeTab(projectStore.activeTabId!)">
            <XMarkIcon class="w-4 h-4" />
            <span>{{ t('common.close') }}</span>
          </button>
        </div>
        <div class="group-manager-body">
          <GroupManager />
        </div>
      </div>

      <!-- 项目列表 -->
      <template v-else>
        <!-- 页面标题 -->
        <div style="margin-bottom:24px;">
          <h1 style="font-size:20px; font-weight:600; margin-bottom:4px;">TopoCode</h1>
          <p class="text-muted" style="font-size:12px;">{{ t('project.subtitle') }}</p>
        </div>

        <div v-if="projectStore.projects.length > 0">
        <!-- 筛选按钮 + 搜索 -->
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:8px; flex-wrap:wrap;">
          <div style="display:flex; gap:4px; align-items:center;">
            <button
              :class="['btn', 'btn-sm', filterMode === 'all' ? 'btn-primary' : 'btn-ghost']"
              @click="filterMode = 'all'"
            >
              <Squares2X2Icon class="w-3.5 h-3.5" />
              <span>{{ t('project.allProjects') }}</span>
              <span class="badge badge-gray" style="font-size:9px; margin-left:2px;">{{ projectStore.projects.length }}</span>
            </button>
            <button
              :class="['btn', 'btn-sm', filterMode === 'favorites' ? 'btn-primary' : 'btn-ghost']"
              @click="filterMode = 'favorites'"
            >
              <StarIcon class="w-3.5 h-3.5" />
              <span>{{ t('project.myFavorites') }}</span>
              <span class="badge badge-yellow" style="font-size:9px; margin-left:2px;">{{ projectStore.projects.filter(p => p.favorite).length }}</span>
            </button>
            <!-- 分组筛选 -->
            <GroupFilter ref="groupFilterRef" @change="selectedGroupIds = $event" />
          </div>
          <div style="display:flex; gap:4px; align-items:center;">
            <!-- 每页数量选择 -->
            <span class="text-muted" style="font-size:10px; white-space:nowrap;">{{ t('project.pageSize') }}</span>
            <select
              :value="pageSize"
              @change="settingsStore.setProjectPageSize(Number(($event.target as HTMLSelectElement).value))"
              style="padding:2px 4px; font-size:10px; border:1px solid var(--border); border-radius:3px; background:var(--bg-primary); color:var(--text-primary); outline:none;"
            >
              <option value="20">20</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
            <!-- 复合搜索输入框 -->
            <div style="position:relative;">
              <MagnifyingGlassIcon class="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
              <input
                v-model="searchQuery"
                :placeholder="t('project.searchProjects')"
                style="padding:3px 6px 3px 24px; font-size:10px; border:1px solid var(--border); border-radius:3px; background:var(--bg-primary); color:var(--text-primary); width:160px; outline:none;"
              />
            </div>
          </div>
        </div>

        <!-- 项目卡片网格 -->
        <div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:12px; margin-bottom:12px;">
          <ProjectCard
            v-for="project in pagedProjects"
            :key="project.id"
            :project="project"
            @select="projectStore.selectProject(project.id)"
          />
          <!-- 无匹配结果 -->
          <div v-if="pagedProjects.length === 0" style="grid-column: 1/-1; text-align:center; padding:24px; color:var(--text-muted); font-size:12px;">
            {{ searchQuery ? t('project.noMatch') : t('project.noFavorites') }}
          </div>
        </div>

        <!-- 分页控件 -->
        <div v-if="totalPages > 1" class="pagination-bar">
          <span class="text-muted" style="font-size:11px;">
            {{ t('project.showing') }} {{ pageRange.start }}-{{ pageRange.end }} / {{ pageRange.total }}
          </span>
          <div class="pagination-buttons">
            <button
              class="btn btn-ghost btn-sm"
              :disabled="currentPage === 1"
              @click="currentPage--"
            >
              {{ t('project.prevPage') }}
            </button>
            <span style="font-size:11px; padding:0 8px;">
              {{ currentPage }} / {{ totalPages }}
            </span>
            <button
              class="btn btn-ghost btn-sm"
              :disabled="currentPage === totalPages"
              @click="currentPage++"
            >
              {{ t('project.nextPage') }}
            </button>
          </div>
        </div>
      </div>

      <!-- 快速开始（无项目时显示提示） -->
        <div v-if="projectStore.projects.length === 0" class="quick-start-empty">
          <RocketLaunchIcon class="w-12 h-12 text-accent" />
          <h2 style="font-size:16px; font-weight:600; margin-bottom:8px;">{{ t('project.quickStart') }}</h2>
          <p class="text-muted" style="font-size:12px; margin-bottom:16px;">{{ t('project.quickStartDesc') }}</p>
          <p class="text-muted" style="font-size:11px;">{{ t('project.menuImportHint') }}</p>
        </div>
      </template>
    </div>

    <!-- 项目视图 -->
    <div
      v-else
      class="home-project-view"
    >
      <!-- 项目标题栏 -->
      <div style="display:flex; align-items:center; padding:8px 16px; border-bottom:1px solid var(--border); gap:12px;">
        <FolderIcon class="w-4 h-4 text-accent" />
        <span style="font-size:13px; font-weight:600;">{{ projectStore.selectedProject?.name }}</span>
        <span class="badge badge-green" style="font-size:8px;">{{ t('project.synced') }}</span>
        <div style="flex:1;"></div>
        <button class="btn btn-ghost btn-sm" v-if="projectStore.tabs.length > 0" @click="projectStore.closeAllTabs()" :title="t('project.closeAllTabs')">
          <XCircleIcon class="w-4 h-4" />
          <span>{{ t('project.closeAllTabs') }}</span>
        </button>
        <button class="btn btn-ghost btn-sm" @click="projectStore.openTaskListTab()" :title="t('analysis.taskList')">
          <WrenchScrewdriverIcon class="w-4 h-4" />
          <span>{{ t('analysis.taskList') }}</span>
        </button>
        <button class="btn btn-ghost btn-sm" @click="showMenu">
          <Cog6ToothIcon class="w-4 h-4" />
          <span>{{ t('common.settings') }}</span>
        </button>
        <button class="btn btn-ghost btn-sm" @click="projectStore.deselectProject()">
          {{ t('common.back') }}
        </button>
      </div>

      <!-- Tab 栏 -->
      <HomeTabBar
        v-if="projectStore.currentProjectTabs.length > 0"
        :tabs="projectStore.currentProjectTabs"
        :active-tab-id="projectStore.activeTabId"
        @update:activeTabId="onTabUpdate"
        @close="onTabClose"
      />

      <!-- 内容区 -->
      <div class="home-tab-content">
        <!-- 代码视图 -->
        <div v-if="projectStore.activeTab?.kind === 'file'" class="code-viewer-full">
          <CodeViewer
            :node="projectStore.activeTab.node!"
            :root-path="projectStore.selectedProject?.rootPath || projectStore.selectedProject?.path || ''"
            @close="onCloseCodeViewer"
          />
        </div>

        <!-- 任务列表 -->
        <div v-else-if="projectStore.activeTab?.kind === 'taskList'" class="task-list-panel">
          <TaskListPanel
            :project-id="projectStore.selectedProjectId!"
            @create-task="onTaskListCreateTask"
          />
        </div>

        <!-- 新建/编辑任务 -->
        <div v-else-if="projectStore.activeTab?.kind === 'taskCreate'" class="task-create-form">
          <TaskCreateForm
            :project-id="projectStore.selectedProjectId!"
            :task-id="projectStore.activeTab.taskId"
            @created="onTaskCreated"
            @cancelled="onCloseCodeViewer"
          />
        </div>

        <!-- 分组管理 -->
        <div v-else-if="projectStore.activeTab?.kind === 'groupManager'" class="group-manager-panel">
          <GroupManager />
        </div>

        <!-- 空状态 -->
        <div v-else class="empty-state centered">
          <DocumentTextIcon class="w-12 h-12 text-accent" />
          <div class="title">{{ t('file.selectFile') }}</div>
          <div class="desc">{{ t('file.selectFileDesc') }}</div>
        </div>
      </div>
    </div>

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
          <ArchiveBoxXMarkIcon class="w-4 h-4" />
          <span>{{ t('project.clearCache') }}</span>
        </div>
      </div>
    </Teleport>

    <div
      v-if="menuVisible"
      class="context-menu-backdrop"
      @click="hideMenu"
    ></div>

    <ConfirmDialog
      v-if="showClearCacheConfirm"
      :title="t('common.confirm')"
      :message="t('project.clearCacheConfirm')"
      :confirm-label="t('project.clearCache')"
      variant="warning"
      @cancel="showClearCacheConfirm = false"
      @confirm="confirmClearCache"
    />
  </div>
</template>

<style scoped>
.page-home {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.home-default-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 32px;
  overflow: auto;
}

.home-project-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.home-tab-content {
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

.task-list-view {
  height: 100%;
  overflow: auto;
}

.quick-start-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px 20px;
  text-align: center;
}

.quick-start-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  width: 100%;
  max-width: 600px;
}

.quick-start-card {
  padding: 20px;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}

.quick-start-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.pagination-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid var(--border);
}

.pagination-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
