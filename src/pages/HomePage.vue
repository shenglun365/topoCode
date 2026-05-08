<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon,
  Cog6ToothIcon,
  DocumentTextIcon,
  RocketLaunchIcon,
  XCircleIcon,
  LightBulbIcon,
  CodeBracketIcon,
  ChatBubbleLeftRightIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useOnboardingStore } from '@/stores/onboarding'
import ProjectCard from '@/components/project/ProjectCard.vue'
import ImportZone from '@/components/project/ImportZone.vue'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import CodeViewer from '@/components/code/CodeViewer.vue'

const { t } = useI18n()
const projectStore = useProjectStore()
const onboardingStore = useOnboardingStore()

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
        <button class="btn btn-ghost btn-sm" v-if="projectStore.tabs.length > 0" @click="projectStore.closeAllTabs()" :title="t('project.closeAllTabs')">
          <XCircleIcon class="w-4 h-4" />
          <span>{{ t('project.closeAllTabs') }}</span>
        </button>
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
        v-if="projectStore.tabs.length > 0"
        :tabs="projectStore.tabs"
        :active-tab-id="projectStore.activeTabId"
        @update:activeTabId="onTabUpdate"
        @close="onTabClose"
      />

      <!-- 内容区 -->
      <div class="home-tab-content">
        <!-- 代码视图 -->
        <div v-if="projectStore.activeTab" class="code-viewer-full">
          <CodeViewer
            :node="projectStore.activeTab.node"
            :root-path="projectStore.selectedProject?.rootPath || projectStore.selectedProject?.path || ''"
            @close="onCloseCodeViewer"
          />
        </div>
        <div v-else class="empty-state centered">
          <DocumentTextIcon class="w-12 h-12 text-accent" />
          <div class="title">{{ t('file.selectFile') }}</div>
          <div class="desc">{{ t('file.selectFileDesc') }}</div>
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
  display: flex;
}

.code-viewer-full {
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
</style>
