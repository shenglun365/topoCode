<script setup lang="ts">
import { ref, watch, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  SparklesIcon,
  PencilIcon,
  ArrowLeftIcon,
  ClockIcon,
  ArrowPathIcon,
  DocumentTextIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import { useProjectStore } from '@/stores/project'
import FileStatsPanel from './FileStatsPanel.vue'
import TaskDetailDialog from './TaskDetailDialog.vue'
import type { AnalysisTask } from '@/types/ipc'
import { createLogger } from '@topo/web-core/utils/logger'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('AN-004')
const logger = createLogger('TaskCreateForm')

const props = defineProps<{
  projectId: string
  taskId?: string  // 编辑已有任务时传入
}>()

const emit = defineEmits<{
  created: [taskId: string]
  cancelled: []
}>()

const { t } = useI18n()
const analysisStore = useAnalysisStore()
const projectStore = useProjectStore()

// View/Edit mode
const isEditMode = ref(false)
const task = ref<AnalysisTask | null>(null)
const showDetailDialog = ref(false)

// Form state
const taskName = ref('')
const scope = ref('')
const patternType = ref<'all' | 'glob' | 'regex'>('all')
const pattern = ref('')
const excludeDirs = ref('')
/** 报告类型固定为 内部依赖分析 + 内部调用分析：始终包含，不作为页面选项展示/操作 */
const FIXED_REPORT_TYPES = ['dependency', 'callChain']
const loading = ref(false)

// Multi-select state (from FileStatsPanel)
const selectedScopes = ref<string[]>([])
const selectedExtensions = ref<string[]>([])
const manualExtensionInput = ref('')
const fileStatsRef = ref<InstanceType<typeof FileStatsPanel> | null>(null)

// Computed
const isNewTask = computed(() => !props.taskId)
const isViewMode = computed(() => !isNewTask.value && !isEditMode.value)

// Format relative time
function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('analysis.justNow')
  if (mins < 60) return t('analysis.minutesAgo', { count: mins })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('analysis.hoursAgo', { count: hours })
  const days = Math.floor(hours / 24)
  return t('analysis.daysAgo', { count: days })
}

// Load existing task
async function loadExistingTask() {
  if (!props.taskId) return
  try {
    const loaded = await analysisStore.getTask(props.taskId)
    task.value = loaded
    taskName.value = loaded.name || ''
    scope.value = loaded.scope || ''
    // 安全解析 JSON 字段（后端可能返回字符串）
    const extensionsData = loaded.extensions
    if (extensionsData) {
      const exts = Array.isArray(extensionsData) ? extensionsData : JSON.parse(extensionsData)
      selectedExtensions.value = [...exts]
    }
    // scopes（新字段）优先，为空时回退到 scope（旧字段兼容）
    if (loaded.scopes) {
      const sc = Array.isArray(loaded.scopes) ? loaded.scopes : JSON.parse(loaded.scopes)
      selectedScopes.value = [...sc]
    } else if (loaded.scope) {
      selectedScopes.value = [loaded.scope]
    }
    const taskAny = loaded as any
    const excludeDirsData = taskAny.excludeDirs || taskAny.exclude_dirs
    if (excludeDirsData) {
      const dirs = Array.isArray(excludeDirsData) ? excludeDirsData : JSON.parse(excludeDirsData)
      excludeDirs.value = dirs.join(', ')
    }
    const pt = taskAny.pattern_type
    if (pt && ['all', 'glob', 'regex'].includes(pt)) {
      patternType.value = pt
    }
    if (taskAny.pattern) {
      pattern.value = taskAny.pattern
    }
  } catch (err) {
    logger.error('Failed to load task:', err)
  }
}

onMounted(async () => {
  if (props.taskId) {
    await loadExistingTask()
    isEditMode.value = true  // 编辑模式直接进入
  }
})

// Enter edit mode
function enterEditMode() {
  isEditMode.value = true
}

// Cancel edit (discard changes)
function cancelEdit() {
  isEditMode.value = false
  // Reload original values
  loadExistingTask()
}

// Handle suggested extensions from FileStatsPanel
function onSuggestExtensions(exts: string[]) {
  // Extensions are now managed via selectedExtensions from FileStatsPanel
}

// Handle selected extensions update
function onSelectedExtensionsUpdate(exts: string[]) {
  selectedExtensions.value = exts
}

// Submit form
function onSaveClick() {
  logger.debug('onSaveClick triggered', {
    loading: loading.value,
    taskName: taskName.value,
    isEditMode: isEditMode.value,
    isNewTask: isNewTask.value,
  })

  try {
    handleSubmit()
  } catch (err: any) {
    logger.error('onSaveClick sync error:', err)
  }
}

async function handleSubmit() {
  const name = taskName.value.trim()

  if (!name) {
    logger.warn('handleSubmit: name is empty, aborting')
    return
  }

  const ft = fileStatsRef.value
  if (ft && ft.fileCountLevel === 'block') {
    logger.warn('handleSubmit: file count exceeds 10000, aborting')
    return
  }

  loading.value = true

  try {
    const extArray = selectedExtensions.value.filter(Boolean)
    const excludeArray = excludeDirs.value.split(',').map(s => s.trim()).filter(Boolean)

    if (task.value && !isNewTask.value) {
      // Edit mode - update config
      logger.info('EDIT MODE: updating task', { taskId: task.value.id, name })

      await analysisStore.updateTaskConfig(task.value.id, {
        name,
        scopes: selectedScopes.value.length > 0 ? [...selectedScopes.value] : undefined,
        extensions: extArray.length > 0 ? [...extArray] : undefined,
        excludeDirs: excludeArray.length > 0 ? [...excludeArray] : undefined,
        reportTypes: [...FIXED_REPORT_TYPES],
        patternType: patternType.value !== 'all' ? patternType.value : undefined,
        pattern: pattern.value || undefined,
      } as any)

      isEditMode.value = false
      await loadExistingTask()
      emit('created', task.value.id)
      logger.info('EDIT MODE: completed successfully')
    } else {
      // New task
      const taskParams = {
        projectId: props.projectId,
        type: 'full',
        name,
        scopes: selectedScopes.value.length > 0 ? [...selectedScopes.value] : undefined,
        extensions: extArray.length > 0 ? [...extArray] : undefined,
        excludeDirs: excludeArray.length > 0 ? [...excludeArray] : undefined,
        reportTypes: [...FIXED_REPORT_TYPES],
        patternType: patternType.value !== 'all' ? patternType.value : undefined,
        pattern: pattern.value || undefined,
      }

      logger.info('NEW TASK: creating task', { name, projectId: props.projectId })

      const created = await analysisStore.createTask(taskParams)
      emit('created', created.id)
      logger.info('NEW TASK: completed successfully', { taskId: created.id })
    }
  } catch (err: any) {
    logger.error('Failed to save task:', err)
  } finally {
    loading.value = false
  }
}

function handleCancel() {
  emit('cancelled')
}

// Stop task before editing
async function stopThenEdit() {
  if (!task.value) return
  try {
    await analysisStore.stopTask(task.value.id)
    await loadExistingTask()
    isEditMode.value = true
  } catch (err) {
    logger.error('Failed to stop task:', err)
  }
}

// View task logs
function viewLogs() {
  if (task.value) {
    showDetailDialog.value = true
  }
}
</script>

<template>
  <div class="task-create-form">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- Header bar -->
    <div class="form-header">
      <div class="header-left">
        <button
          v-if="!isNewTask"
          class="icon-btn"
          @click="handleCancel"
        >
          <ArrowLeftIcon class="w-4 h-4" />
        </button>
        <h2 class="form-title">
          {{ isNewTask ? t('analysis.newTask') : (isEditMode ? t('analysis.editTask') : t('analysis.viewTask')) }}
        </h2>
      </div>
      <div class="header-right">
        <!-- View mode actions -->
        <template v-if="isViewMode && task">
          <button
            class="btn btn-ghost"
            @click="viewLogs"
          >
            <DocumentTextIcon class="w-4 h-4" />
            <span>{{ t('analysis.viewLogs') }}</span>
          </button>
          <button
            v-if="task.status === 'running'"
            class="btn btn-warning"
            @click="stopThenEdit"
          >
            <span>{{ t('analysis.stopThenEdit') }}</span>
          </button>
          <button
            v-else
            class="btn btn-primary"
            @click="enterEditMode"
          >
            <PencilIcon class="w-4 h-4" />
            <span>{{ t('analysis.edit') }}</span>
          </button>
        </template>
        <!-- Edit mode actions -->
        <template v-else>
          <button
            class="btn btn-ghost"
            @click="handleCancel"
          >
            {{ t('analysis.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            :disabled="loading || !taskName.trim()"
            @click="onSaveClick"
          >
            <SparklesIcon
              v-if="!loading"
              class="w-4 h-4"
            />
            <span>{{ isNewTask ? t('analysis.saveConfig') : t('analysis.confirmChange') }}</span>
          </button>
        </template>
      </div>
    </div>

    <div class="form-layout">
      <!-- Left: File distribution stats -->
      <div class="form-sidebar">
        <FileStatsPanel
          ref="fileStatsRef"
          :project-id="projectId"
          :scope="scope"
          :pattern-type="patternType"
          :pattern="pattern"
          :exclude-dirs="excludeDirs.split(',').map(s => s.trim()).filter(Boolean)"
          :selected-scopes="selectedScopes"
          :selected-extensions="selectedExtensions"
          @update:scope="scope = $event"
          @update:pattern-type="patternType = $event"
          @update:pattern="pattern = $event"
          @suggest-extensions="onSuggestExtensions"
          @update:selected-scopes="selectedScopes = $event"
          @update:selected-extensions="onSelectedExtensionsUpdate($event)"
        />
      </div>

      <!-- Right: Task config form -->
      <div class="form-main">
        <!-- Task name -->
        <div class="form-section">
          <label class="form-label">{{ t('analysis.taskName') }} {{ isNewTask ? '*' : '' }}</label>
          <input
            v-if="isEditMode || isNewTask"
            v-model="taskName"
            class="form-input"
            :placeholder="t('analysis.taskNamePlaceholder')"
          >
          <div
            v-else
            class="form-value"
          >
            {{ task?.name || '-' }}
            <span class="form-id">{{ task?.id }}</span>
          </div>
        </div>

        <!-- Directory scope (view mode shows tags) -->
        <div class="form-section">
          <label class="form-label">{{ t('analysis.directoryScope') }}</label>
          <div
            v-if="isViewMode"
            class="form-tags"
          >
            <span
              v-if="selectedScopes.length === 0"
              class="empty-tag"
            >{{ t('analysis.allDirectories') }}</span>
            <span
              v-for="s in selectedScopes"
              v-else
              :key="s"
              class="form-tag"
            >{{ s }}</span>
          </div>
          <div
            v-else-if="selectedScopes.length > 0"
            class="form-tags"
          >
            <span
              v-for="s in selectedScopes"
              :key="s"
              class="form-tag removable"
            >
              {{ s }}
              <button
                class="tag-remove"
                @click="fileStatsRef?.removeScopeByPath(s)"
              >
                <span
                  class="x-mark"
                  aria-hidden="true"
                >×</span>
              </button>
            </span>
          </div>
        </div>

        <!-- Selected extensions -->
        <div class="form-section">
          <label class="form-label">{{ t('analysis.fileExtensions') }}</label>
          <div
            v-if="isViewMode"
            class="form-tags"
          >
            <span
              v-if="selectedExtensions.length === 0"
              class="empty-tag"
            >{{ t('analysis.allFiles') }}</span>
            <span
              v-for="ext in selectedExtensions"
              v-else
              :key="ext"
              class="form-tag"
            >{{ ext }}</span>
          </div>
          <div
            v-else-if="selectedExtensions.length > 0"
            class="form-tags"
          >
            <span
              v-for="ext in selectedExtensions"
              :key="ext"
              class="form-tag removable"
            >
              {{ ext }}
              <button
                class="tag-remove"
                @click="fileStatsRef?.removeExtension(ext)"
              >
                <span
                  class="x-mark"
                  aria-hidden="true"
                >×</span>
              </button>
            </span>
          </div>
        </div>

        <!-- Exclude dirs -->
        <div class="form-section">
          <label class="form-label">{{ t('analysis.excludeDirs') }}</label>
          <input
            v-if="isEditMode || isNewTask"
            v-model="excludeDirs"
            class="form-input"
            :placeholder="t('analysis.excludeDirsPlaceholder')"
          >
          <div
            v-else
            class="form-tags"
          >
            <span
              v-for="d in (task?.excludeDirs || [])"
              :key="d"
              class="form-tag"
            >{{ d }}</span>
            <span
              v-if="!task?.excludeDirs?.length"
              class="empty-tag"
            >-</span>
          </div>
        </div>

        <!-- Task metadata (view mode only) -->
        <div
          v-if="isViewMode && task"
          class="form-metadata"
        >
          <div class="metadata-row">
            <ClockIcon class="w-4 h-4" />
            <span>{{ t('analysis.createdAt') }}: {{ task.createdAt }}</span>
          </div>
          <div class="metadata-row">
            <ClockIcon class="w-4 h-4" />
            <span>{{ t('analysis.updatedAt') }}: {{ formatRelativeTime(task.updatedAt) }}</span>
          </div>
          <div class="metadata-row">
            <ArrowPathIcon class="w-4 h-4" />
            <span>{{ t('analysis.configVersion') }}: v{{ task.configVersion || 1 }}</span>
          </div>
          <div class="metadata-row">
            <SparklesIcon class="w-4 h-4" />
            <span>{{ t('analysis.runCount') }}: {{ task.runCount || 0 }}</span>
          </div>
          <div class="metadata-row">
            <DocumentTextIcon class="w-4 h-4" />
            <span>{{ t('analysis.lastStatus') }}: {{ task.lastRunStatus || t('analysis.neverRun') }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Task detail dialog for logs -->
    <TaskDetailDialog
      v-if="showDetailDialog && task"
      :task="task"
      @close="showDetailDialog = false"
    />
  </div>
</template>

<style scoped>
.task-create-form {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.form-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1));
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.header-left {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
}

.header-right {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
}

.form-title {
  font-size: calc(14px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.icon-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: calc(4px * var(--ui-scale, 1));
  display: flex;
  align-items: center;
  border-radius: calc(4px * var(--ui-scale, 1));
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.form-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: calc(16px * var(--ui-scale, 1));
  flex: 1;
  overflow: hidden;
  padding: calc(16px * var(--ui-scale, 1));
}

.form-sidebar {
  flex-shrink: 0;
  overflow-y: auto;
}

.form-main {
  display: flex;
  flex-direction: column;
  gap: calc(16px * var(--ui-scale, 1));
  overflow-y: auto;
  padding-right: calc(8px * var(--ui-scale, 1));
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: calc(6px * var(--ui-scale, 1));
}

.form-label {
  font-size: calc(12px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-secondary);
}

.form-input {
  padding: calc(8px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
  font-size: calc(13px * var(--ui-scale, 1));
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: calc(4px * var(--ui-scale, 1));
  color: var(--text-primary);
  outline: none;
  font-family: inherit;
}

.form-input:focus {
  border-color: var(--accent);
}

.form-value {
  font-size: calc(13px * var(--ui-scale, 1));
  color: var(--text-primary);
  padding: calc(8px * var(--ui-scale, 1)) 0;
}

.form-id {
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-muted);
  font-family: monospace;
  margin-left: calc(8px * var(--ui-scale, 1));
}

.form-tags {
  display: flex;
  flex-wrap: wrap;
  gap: calc(4px * var(--ui-scale, 1));
  padding: calc(4px * var(--ui-scale, 1)) 0;
}

.form-tag {
  padding: calc(2px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  background: var(--bg-tertiary);
  border-radius: calc(12px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--text-secondary);
  font-family: monospace;
}

.form-tag.removable {
  display: inline-flex;
  align-items: center;
  gap: calc(3px * var(--ui-scale, 1));
  padding-right: calc(4px * var(--ui-scale, 1));
}

.tag-remove {
  flex-shrink: 0;
  background: var(--bg-hover);
  border: 1px solid var(--border-subtle);
  cursor: pointer;
  color: var(--text-default);
  padding: 0;
  width: calc(20px * var(--ui-scale, 1));
  height: calc(20px * var(--ui-scale, 1));
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: calc(4px * var(--ui-scale, 1));
  opacity: .6;
  transition: opacity 0.15s, background 0.15s, color 0.15s, border-color 0.15s;
}
.tag-remove:hover {
  opacity: 1;
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.3);
  color: #ef4444;
}
.tag-remove .x-mark {
  font-size: calc(14px * var(--ui-scale, 1));
  line-height: 1;
  font-weight: 700;
}

.empty-tag {
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-muted);
  font-style: italic;
}

.checkbox-group {
  display: flex;
  flex-direction: column;
  gap: calc(8px * var(--ui-scale, 1));
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  font-size: calc(13px * var(--ui-scale, 1));
  color: var(--text-primary);
  cursor: pointer;
}

.checkbox-item input[type="checkbox"] {
  accent-color: var(--accent);
  width: calc(16px * var(--ui-scale, 1));
  height: calc(16px * var(--ui-scale, 1));
}

/* Metadata section */
.form-metadata {
  display: flex;
  flex-direction: column;
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(12px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  margin-top: calc(8px * var(--ui-scale, 1));
}

.metadata-row {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-secondary);
}

.metadata-row .w-4 {
  color: var(--text-muted);
}

.btn-warning {
  background: var(--warning);
  color: var(--bg-primary);
  border: none;
  padding: calc(6px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  border-radius: calc(4px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
}

.btn-warning:hover {
  opacity: 0.9;
}
</style>
