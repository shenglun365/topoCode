<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  ArrowPathIcon,
  ChevronRightIcon,
} from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useNavigationStore } from '@/stores/navigation'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import FileTree from '@/components/project/FileTree.vue'
import ProjectList from '@/components/project/ProjectList.vue'
import type { FileTreeNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-003')
const { t } = useI18n()
const router = useRouter()
const panelStore = usePanelStore()
const navigation = useNavigationStore()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()

// 拖拽调整宽度
const isResizing = ref(false)
const startX = ref(0)
const startWidth = ref(0)

function onResizeStart(e: MouseEvent) {
  isResizing.value = true
  startX.value = e.clientX
  startWidth.value = panelStore.leftWidth
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
  e.preventDefault()
}

function onResizeMove(e: MouseEvent) {
  if (!isResizing.value) return
  const delta = e.clientX - startX.value
  panelStore.setLeftWidth(startWidth.value + delta)
}

function onResizeEnd() {
  isResizing.value = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
}

onMounted(() => {
  document.addEventListener('mouseup', onResizeEnd)
  // 首页初始状态：无项目时自动折叠左侧面板
  if (navigation.currentPage === 'home' && !projectStore.selectedProjectId) {
    panelStore.setLeftCollapsed(true)
  }
  // 代码解析页：无项目时折叠
  if (navigation.currentPage === 'code' && !projectStore.selectedProjectId) {
    panelStore.setLeftCollapsed(true)
  }
  // 分析页面：默认展开左侧面板
  if (navigation.currentPage === 'analysis') {
    panelStore.setLeftCollapsed(false)
  }
})

// 监听页面切换，分析页面默认展开
watch(() => navigation.currentPage, (page) => {
  if (page === 'analysis') {
    panelStore.setLeftCollapsed(false)
  } else if ((page === 'home' || page === 'code') && !projectStore.selectedProjectId) {
    panelStore.setLeftCollapsed(true)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('mouseup', onResizeEnd)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
})

const panelTitleKeys: Record<string, string> = {
  home: 'nav.projects',
  code: 'nav.explorer',
  analysis: 'nav.projects',
  knowledge: 'nav.knowledge',
  coder: 'nav.chat',
  user: 'nav.settings',
}

const title = computed(() => {
  if (projectStore.viewMode === 'project') {
    return t('nav.explorer')
  }
  return t(panelTitleKeys[navigation.currentPage] || 'common.panel')
})

const panelContent = ref('')
const fileTreeNodes = ref<FileTreeNode[]>([])
const fileTreeLoading = ref(false)

// 监听项目选择，加载文件树 + 自动折叠/展开
watch(
  () => projectStore.selectedProjectId,
  async (newId) => {
    if (navigation.currentPage === 'home' || navigation.currentPage === 'code') {
      if (newId) {
        panelStore.setLeftCollapsed(false)
      } else {
        panelStore.setLeftCollapsed(true)
      }
    }
    if (newId) {
      await loadFileTree()
    }
  }
)

async function loadFileTree() {
  if (!projectStore.selectedProjectId) return
  fileTreeLoading.value = true
  try {
    fileTreeNodes.value = await projectStore.getFileTree(projectStore.selectedProjectId)
  } catch (err) {
    console.error('Failed to load file tree:', err)
    fileTreeNodes.value = []
  } finally {
    fileTreeLoading.value = false
  }
}

function onFileSelect(node: FileTreeNode) {
  if (node.name === '__pycache__' || node.name.endsWith('/') || node.type !== 'file') return
  projectStore.openFileTab(node)
}

// 处理选择报告（打开报告 tab）
async function handleSelectReport(item: { taskId: string; type: string; taskName: string }, projectId: string) {
  // 选中项目
  projectStore.selectProject(projectId)
  // 切换到分析页面
  router.push('/analysis')
  navigation.navigateTo('analysis')
  // 打开报告 tab
  const project = projectStore.selectedProject
  projectStore.openReportHomeTab({
    taskId: item.taskId,
    taskName: item.taskName,
    projectName: project?.name,
  })
}

// 处理为项目创建任务（点击"无报告"）
function handleCreateTaskForProject(project: any) {
  // 选中项目并打开任务列表
  projectStore.selectProject(project.id)
  projectStore.openTaskListTab()
  // 切换到代码解析项目视图
  router.push('/code')
  navigation.navigateTo('code')
}

// 处理导入项目
function handleImportProject() {
  router.push('/home')
  navigation.navigateTo('home')
}

// 根据当前页面加载对应的左侧面板内容
function loadPanelContent() {
  switch (navigation.currentPage) {
    case 'home':
      panelContent.value = 'home'
      break
    case 'code':
      panelContent.value = 'code'
      break
    case 'analysis':
      panelContent.value = 'analysis'
      break
    case 'knowledge':
      panelContent.value = 'knowledge'
      break
    case 'coder':
      panelContent.value = 'coder'
      break
    default:
      panelContent.value = ''
  }
}

loadPanelContent()
</script>

<template>
  <aside
    class="panel-left"
    :class="{ collapsed: panelStore.leftCollapsed }"
    :style="{ width: panelStore.leftCollapsed ? 0 : `${panelStore.leftWidth}px` }"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="panel-header">
      <span>{{ title }}</span>
      <div class="panel-header-actions">
        <div
          class="icon-btn"
          :title="t('common.refresh')"
          @click="loadFileTree"
        >
          <ArrowPathIcon class="w-3.5 h-3.5" />
        </div>
        <div
          class="icon-btn"
          :title="t('common.collapse')"
          @click="panelStore.toggleLeft()"
        >
          <ChevronRightIcon class="w-3.5 h-3.5" />
        </div>
      </div>
    </div>
    <div class="panel-body">
      <!-- 分析页面：项目列表（优先判断，不受 viewMode 影响） -->
      <template v-if="navigation.currentPage === 'analysis'">
        <ProjectList
          @select-report="handleSelectReport"
          @import-project="handleImportProject"
          @create-task-for-project="handleCreateTaskForProject"
        />
      </template>

      <!-- 项目文件树 -->
      <template v-else-if="projectStore.viewMode === 'project'">
        <div
          v-if="fileTreeLoading"
          class="empty-state"
        >
          <div class="loading-spinner" />
          <span class="text-muted">{{ t('file.loading') }}</span>
        </div>
        <div
          v-else-if="fileTreeNodes.length === 0"
          class="empty-state"
        >
          <div style="font-size:11px; color:var(--text-muted);">
            {{ t('file.noFiles') }}
          </div>
        </div>
        <FileTree
          v-else
          :nodes="fileTreeNodes"
          @select="onFileSelect"
        />
      </template>

      <!-- 动态内容插槽 -->
      <template v-else>
        <slot :page="panelContent">
          <!-- 默认空状态 -->
          <div class="empty-state">
            <div class="icon">
              📋
            </div>
            <div class="title">
              {{ title }}
            </div>
            <div class="desc">
              {{ t('shell.leftPanel.dynamicContent') }}
            </div>
          </div>
        </slot>
      </template>
    </div>

    <!-- 拖拽调整宽度的手柄 -->
    <div
      v-show="!panelStore.leftCollapsed"
      class="resize-handle"
      @mousedown="onResizeStart"
    />
  </aside>
</template>

<style scoped>
.panel-left {
  position: relative;
  flex-shrink: 0;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.15s ease;
}

.panel-left.resizing {
  transition: none;
}

.panel-left.collapsed {
  width: 0 !important;
  border-right: none;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  min-height: 32px;
}

.panel-header-actions {
  display: flex;
  gap: 4px;
}

.panel-header-actions .icon-btn {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 12px;
}

.panel-header-actions .icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.panel-body {
  flex: 1;
  overflow: auto;
  padding: 4px 0;
}

.resize-handle {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  cursor: col-resize;
  z-index: 20;
}

.resize-handle:hover {
  background: var(--accent);
}
</style>
