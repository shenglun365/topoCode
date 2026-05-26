<template>
  <div class="project-import">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 默认视图 -->
    <div
      v-if="!selectedProject"
      class="default-view"
    >
      <div class="page-header">
        <h1 class="page-title">
          {{ t('home.welcome') }}
        </h1>
        <p class="page-subtitle">
          {{ t('home.subtitle') }}
        </p>
      </div>

      <!-- 项目卡片网格 -->
      <div
        v-if="projects.length > 0"
        class="project-section"
      >
        <h2 class="section-title">
          {{ t('home.recentProjects') }}
        </h2>
        <div class="project-grid">
          <ProjectCard
            v-for="project in projects"
            :key="project.id"
            :project="project"
            @select="selectProject"
          />
        </div>
      </div>

      <!-- 导入区域 -->
      <ImportZone @import="importProject" />

      <!-- 快速入门 -->
      <div
        v-if="projects.length === 0"
        class="quick-start"
      >
        <h2 class="section-title">
          {{ t('home.quickStart') }}
        </h2>
        <div class="quick-steps">
          <div class="step-item">
            <div class="step-number">
              1
            </div>
            <div class="step-content">
              <h3 class="step-title">
                {{ t('home.step1Title') }}
              </h3>
              <p class="step-desc">
                {{ t('home.step1Desc') }}
              </p>
            </div>
          </div>
          <div class="step-item">
            <div class="step-number">
              2
            </div>
            <div class="step-content">
              <h3 class="step-title">
                {{ t('home.step2Title') }}
              </h3>
              <p class="step-desc">
                {{ t('home.step2Desc') }}
              </p>
            </div>
          </div>
          <div class="step-item">
            <div class="step-number">
              3
            </div>
            <div class="step-content">
              <h3 class="step-title">
                {{ t('home.step3Title') }}
              </h3>
              <p class="step-desc">
                {{ t('home.step3Desc') }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 项目视图 -->
    <div
      v-else
      class="project-view"
    >
      <div class="project-title-bar">
        <button
          class="back-btn"
          @click="deselectProject"
        >
          <ArrowLeftIcon class="w-4 h-4" />
          {{ t('home.back') }}
        </button>
        <div class="project-info">
          <h2 class="project-name">
            {{ selectedProjectName }}
          </h2>
          <span
            class="project-status"
            :class="selectedProjectStatus"
          >
            {{ statusText }}
          </span>
        </div>
        <div class="project-actions">
          <button
            class="action-btn"
            @click="toggleViewMode"
          >
            <ArrowPathIcon class="w-4 h-4" />
            {{ viewMode === 'files' ? t('home.tasks') : t('home.files') }}
          </button>
        </div>
      </div>

      <!-- 文件树视图 -->
      <div
        v-if="viewMode === 'files'"
        class="view-content"
      >
        <FileTree
          v-if="selectedProjectData"
          :root="selectedProjectData"
          :expanded="{}"
          @toggle="handleToggle"
        />
      </div>

      <!-- 任务列表视图 -->
      <div
        v-else
        class="view-content"
      >
        <div
          v-if="tasks.length === 0"
          class="empty-state"
        >
          <QueueListIcon class="w-12 h-12 empty-icon" />
          <p class="empty-text">
            {{ t('home.noTasks') }}
          </p>
        </div>
        <div
          v-else
          class="task-list"
        >
          <TaskCard
            v-for="task in tasks"
            :key="task.id"
            :task="task"
            @run="runTask"
            @delete="deleteTask"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeftIcon,
  ArrowPathIcon,
  QueueListIcon,
} from '@heroicons/vue/24/outline'
import ProjectCard from './ProjectCard.vue'
import ImportZone from './ImportZone.vue'
import FileTree from './FileTree.vue'
import TaskCard from '../analysis/TaskCard.vue'
import type { ProjectMeta, AnalysisTask, TreeNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-003')
const { t } = useI18n()

const props = defineProps<{
  projects: ProjectMeta[]
  selectedProject: string | null
  viewMode: 'files' | 'tasks'
  tasks?: AnalysisTask[]
  fileTree?: TreeNode
}>()

const emit = defineEmits<{
  select: [projectId: string]
  deselect: []
  import: [path: string]
  'switch-view': [mode: 'files' | 'tasks']
  'run-task': [taskId: string]
  'delete-task': [taskId: string]
}>()

const localViewMode = ref<'files' | 'tasks'>(props.viewMode)

const selectedProjectData = computed(() => {
  return props.projects.find(p => p.id === props.selectedProject)
})

const selectedProjectName = computed(() => {
  return selectedProjectData.value?.name || ''
})

const selectedProjectStatus = computed(() => {
  return selectedProjectData.value?.syncStatus || 'synced'
})

const statusText = computed(() => {
  const status = selectedProjectStatus.value
  return {
    synced: t('project.synced'),
    changed: t('project.changed'),
    error: t('project.error'),
  }[status] || status
})

function selectProject(projectId: string) {
  emit('select', projectId)
}

function deselectProject() {
  emit('deselect')
}

function importProject(path: string) {
  emit('import', path)
}

function toggleViewMode() {
  localViewMode.value = localViewMode.value === 'files' ? 'tasks' : 'files'
  emit('switch-view', localViewMode.value)
}

function handleToggle(nodeId: string) {
  // 处理文件树展开/折叠
}

function runTask(taskId: string) {
  emit('run-task', taskId)
}

function deleteTask(taskId: string) {
  emit('delete-task', taskId)
}
</script>

<style scoped lang="scss">
.project-import {
  @apply h-full overflow-y-auto;
}

.default-view {
  @apply flex flex-col gap-6 p-6;
}

.page-header {
  @apply text-center;
}

.page-title {
  @apply text-2xl font-bold text-[--text-primary] mb-2;
}

.page-subtitle {
  @apply text-sm text-[--text-secondary];
}

.project-section {
  @apply flex flex-col gap-3;
}

.section-title {
  @apply text-sm font-semibold text-[--text-secondary];
}

.project-grid {
  @apply grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4;
}

.quick-start {
  @apply flex flex-col gap-4 mt-4;
}

.quick-steps {
  @apply flex flex-col gap-3;
}

.step-item {
  @apply flex items-start gap-3 p-4 rounded-lg bg-[--bg-secondary] border border-[--border];
}

.step-number {
  @apply flex items-center justify-center w-8 h-8 rounded-full bg-[--accent]/20 text-[--accent] text-sm font-bold;
}

.step-content {
  @apply flex-1;
}

.step-title {
  @apply text-sm font-medium text-[--text-primary] mb-1;
}

.step-desc {
  @apply text-xs text-[--text-muted];
}

.project-view {
  @apply flex flex-col h-full;
}

.project-title-bar {
  @apply flex items-center gap-3 p-4 border-b border-[--border] bg-[--bg-secondary];
}

.back-btn {
  @apply flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-[--bg-tertiary] text-[--text-secondary] hover:bg-[--bg-hover] hover:text-[--text-primary] transition-colors;
}

.project-info {
  @apply flex items-center gap-2 flex-1;
}

.project-name {
  @apply text-sm font-semibold text-[--text-primary];
}

.project-status {
  @apply px-2 py-0.5 text-xs rounded-full;

  &.synced {
    @apply bg-green-500/20 text-green-400;
  }

  &.changed {
    @apply bg-yellow-500/20 text-yellow-400;
  }

  &.error {
    @apply bg-red-500/20 text-red-400;
  }
}

.project-actions {
  @apply flex gap-2;
}

.action-btn {
  @apply flex items-center gap-1 px-3 py-1.5 text-xs rounded bg-[--bg-tertiary] text-[--text-secondary] hover:bg-[--bg-hover] hover:text-[--text-primary] transition-colors;
}

.view-content {
  @apply flex-1 overflow-y-auto p-4;
}

.empty-state {
  @apply flex flex-col items-center justify-center h-full text-center;
}

.empty-icon {
  @apply text-[--text-muted] mb-2;
}

.empty-text {
  @apply text-xs text-[--text-muted];
}

.task-list {
  @apply flex flex-col gap-3;
}
</style>
