<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon,
  Cog6ToothIcon,
  DocumentTextIcon,
  RocketLaunchIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useOnboardingStore } from '@/stores/onboarding'
import type { FileTreeNode } from '@/types/ipc'
import ProjectCard from '@/components/project/ProjectCard.vue'
import ImportZone from '@/components/project/ImportZone.vue'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import FileTree from '@/components/project/FileTree.vue'
import FilePreview from '@/components/project/FilePreview.vue'

const { t } = useI18n()
const projectStore = useProjectStore()
const onboardingStore = useOnboardingStore()

const fileTreeNodes = ref<FileTreeNode[]>([])
const fileTreeLoading = ref(false)
const selectedFile = ref<FileTreeNode | null>(null)

// 监听项目选择和 Tab 切换，加载文件树
watch(
  () => projectStore.selectedProjectId,
  async (newId) => {
    console.log('[HomePage] selectedProjectId changed:', newId)
    if (newId) {
      await loadFileTree()
    }
  }
)

async function loadFileTree() {
  if (!projectStore.selectedProjectId) {
    console.warn('[HomePage] loadFileTree skipped - no selectedProjectId')
    return
  }
  console.log('[HomePage] loadFileTree started for project:', projectStore.selectedProjectId)
  fileTreeLoading.value = true
  try {
    fileTreeNodes.value = await projectStore.getFileTree(projectStore.selectedProjectId)
    console.log('[HomePage] loadFileTree result:', JSON.stringify(fileTreeNodes.value).substring(0, 200))
  } catch (err) {
    console.error('[HomePage] Failed to load file tree:', err)
    fileTreeNodes.value = []
  } finally {
    fileTreeLoading.value = false
    console.log('[HomePage] loadFileTree done, nodes count:', fileTreeNodes.value?.length)
  }
}

function onFileSelect(node: FileTreeNode) {
  if (node.type === 'file') {
    selectedFile.value = node
  }
}

function onClosePreview() {
  selectedFile.value = null
}

function onPinPreview() {
  // 固定到 Tab
  if (selectedFile.value) {
    projectStore.addTab({
      id: `preview-${selectedFile.value.path}`,
      type: 'file',
      title: selectedFile.value.name,
      filePath: selectedFile.value.path,
    })
  }
}

// 快速开始操作
function handleImportClick() {
  // 触发 ImportZone 的文件夹选择
  const btn = document.querySelector('.import-zone-btn') as HTMLButtonElement
  btn?.click()
}

async function handleSampleClick() {
  try {
    await projectStore.initSampleData()
  } catch (err) {
    console.error('Failed to init sample data:', err)
  }
}

function handleTutorialClick() {
  onboardingStore.start()
}

onMounted(async () => {
  await projectStore.loadProjects()
})
</script>

<template>
  <div class="page-home">
    <!-- 默认视图: 项目列表 + 导入 -->
    <div
      v-if="projectStore.viewMode === 'default'"
      class="home-default-view"
    >
      <!-- 页面标题 -->
      <div style="margin-bottom:24px;">
        <h1 style="font-size:20px; font-weight:600; margin-bottom:4px;">TopoOne</h1>
        <p class="text-muted" style="font-size:12px;">{{ t('project.subtitle') }}</p>
      </div>

      <div v-if="projectStore.projects.length > 0" style="margin-bottom:8px;">
        <h2 style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-secondary);">
          {{ t('project.recentProjects') }}
        </h2>
      </div>

      <!-- 项目卡片网格 -->
      <div
        v-if="projectStore.projects.length > 0"
        style="display:grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap:12px; margin-bottom:32px;"
      >
        <ProjectCard
          v-for="project in projectStore.projects"
          :key="project.id"
          :project="project"
          @select="projectStore.selectProject(project.id)"
        />
      </div>

      <div style="margin-bottom:8px;">
        <h2 style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-secondary);">
          {{ t('project.importProject') }}
        </h2>
      </div>
      <ImportZone />

      <!-- 快速开始（无项目时显示大卡片） -->
      <div v-if="projectStore.projects.length === 0" class="quick-start-empty">
        <RocketLaunchIcon class="w-12 h-12 text-accent" />
        <h2 style="font-size:16px; font-weight:600; margin-bottom:8px;">{{ t('project.quickStart') }}</h2>
        <p class="text-muted" style="font-size:12px; margin-bottom:24px;">{{ t('project.quickStartDesc') }}</p>
        <div class="quick-start-cards">
          <div class="card quick-start-card" @click="handleImportClick">
            <FolderIcon class="w-6 h-6 text-accent" />
            <div style="font-size:13px; font-weight:500; margin-bottom:4px;">{{ t('project.importProject') }}</div>
            <div class="text-muted" style="font-size:11px;">{{ t('project.selectLocalRepo') }}</div>
          </div>
          <div class="card quick-start-card" @click="handleSampleClick">
            <DocumentTextIcon class="w-6 h-6 text-green-400" />
            <div style="font-size:13px; font-weight:500; margin-bottom:4px;">{{ t('project.trySample') }}</div>
            <div class="text-muted" style="font-size:11px;">{{ t('project.trySampleDesc') }}</div>
          </div>
          <div class="card quick-start-card" @click="handleTutorialClick">
            <LightBulbIcon class="w-6 h-6 text-yellow-400" />
            <div style="font-size:13px; font-weight:500; margin-bottom:4px;">{{ t('project.viewTutorial') }}</div>
            <div class="text-muted" style="font-size:11px;">{{ t('project.viewTutorialDesc') }}</div>
          </div>
        </div>
      </div>

      <!-- 快速开始（有项目时显示小卡片） -->
      <div v-else style="margin-top:auto; padding-top:24px;">
        <h2 style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-secondary); margin-bottom:12px;">
          {{ t('project.quickStart') }}
        </h2>
        <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:12px;">
          <div class="card" style="padding:12px;">
            <FolderIcon class="w-5 h-5 text-accent" style="margin-bottom:6px;" />
            <div style="font-size:12px; font-weight:500; margin-bottom:4px;">{{ t('project.importProject') }}</div>
            <div class="text-muted" style="font-size:11px;">{{ t('project.selectLocalRepo') }}</div>
          </div>
          <div class="card" style="padding:12px;">
            <CodeBracketIcon class="w-5 h-5 text-accent" style="margin-bottom:6px;" />
            <div style="font-size:12px; font-weight:500; margin-bottom:4px;">{{ t('project.viewAnalysis') }}</div>
            <div class="text-muted" style="font-size:11px;">{{ t('project.browseAST') }}</div>
          </div>
          <div class="card" style="padding:12px;">
            <ChatBubbleLeftRightIcon class="w-5 h-5 text-accent" style="margin-bottom:6px;" />
            <div style="font-size:12px; font-weight:500; margin-bottom:4px;">{{ t('project.aiQnA') }}</div>
            <div class="text-muted" style="font-size:11px;">{{ t('project.askAI') }}</div>
          </div>
        </div>
      </div>
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
        <button class="btn btn-ghost btn-sm">
          <Cog6ToothIcon class="w-4 h-4" />
          <span>{{ t('common.settings') }}</span>
        </button>
        <button class="btn btn-ghost btn-sm" @click="projectStore.deselectProject()">
          {{ t('common.back') }}
        </button>
      </div>

      <!-- Tab 栏 -->
      <HomeTabBar
        :tabs="projectStore.tabs"
        :active-tab-id="projectStore.activeTabId"
        @update:active-tab-id="projectStore.setActiveTab($event)"
        @close="projectStore.closeTab($event)"
      />

      <!-- 内容区 -->
      <div class="home-tab-content">
        <!-- 文件树 + 预览 -->
        <div class="file-tab-layout">
          <div class="file-tree-panel">
            <div v-if="fileTreeLoading" class="empty-state">
              <div class="loading-spinner"></div>
              <span class="text-muted">{{ t('file.loading') }}</span>
            </div>
            <div v-else-if="fileTreeNodes.length === 0" class="empty-state">
              <div style="font-size:11px; color:var(--text-muted);">{{ t('file.noFiles') }}</div>
            </div>
            <FileTree v-else :nodes="fileTreeNodes" @select="onFileSelect" />
          </div>
          <div v-if="selectedFile" class="file-preview-panel">
            <FilePreview
              :node="selectedFile"
              :root-path="projectStore.selectedProject?.rootPath || projectStore.selectedProject?.path || ''"
              @close="onClosePreview"
              @pin="onPinPreview"
            />
          </div>
        </div>
      </div>
    </div>
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
}

.file-tab-layout {
  display: flex;
  height: 100%;
  overflow: hidden;
}

.file-tree-panel {
  flex: 1;
  min-width: 0;
  overflow: auto;
  border-right: 1px solid var(--border);
}

.file-preview-panel {
  width: 50%;
  min-width: 300px;
  overflow: hidden;
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
</style>
