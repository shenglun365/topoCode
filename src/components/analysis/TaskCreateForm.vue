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
} from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import { useProjectStore } from '@/stores/project'
import FileStatsPanel from './FileStatsPanel.vue'
import TaskDetailDialog from './TaskDetailDialog.vue'
import type { AnalysisTask } from '@/types/ipc'

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
const reportTypes = ref<string[]>([])
const loading = ref(false)

// Multi-select state (from FileStatsPanel)
const selectedScopes = ref<string[]>([])
const selectedExtensions = ref<string[]>([])
const manualExtensionInput = ref('')

// Report type options
const reportTypeOptions = [
  { value: 'dependency', label: t('analysis.dependencyAnalysis') },
  { value: 'callChain', label: t('analysis.callChainAnalysis') },
  { value: 'dataFlow', label: t('analysis.dataFlowAnalysis') },
]

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
    const excludeDirsData = loaded.excludeDirs || loaded.exclude_dirs
    if (excludeDirsData) {
      const dirs = Array.isArray(excludeDirsData) ? excludeDirsData : JSON.parse(excludeDirsData)
      excludeDirs.value = dirs.join(', ')
    }
    const reportTypesData = loaded.reportTypes || loaded.report_types
    if (reportTypesData) {
      reportTypes.value = Array.isArray(reportTypesData) ? reportTypesData : JSON.parse(reportTypesData)
    }
    // 恢复匹配模式（pattern_type 是 text 字段，无需 JSON 解析）
    const pt = loaded.pattern_type
    if (pt && ['all', 'glob', 'regex'].includes(pt)) {
      patternType.value = pt
    }
    if (loaded.pattern) {
      pattern.value = loaded.pattern
    }
  } catch (err) {
    console.error('Failed to load task:', err)
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
  console.log('=== [TaskCreateForm] onSaveClick triggered ===')
  console.log('[TaskCreateForm] onSaveClick: loading=', loading.value, 'taskName=', taskName.value, 'disabled=', loading.value || !taskName.value.trim())
  console.log('[TaskCreateForm] onSaveClick: isEditMode=', isEditMode.value, 'isNewTask=', isNewTask.value)
  console.log('[TaskCreateForm] onSaveClick: task.value=', task.value ? { id: task.value.id, status: task.value.status } : null)
  console.log('[TaskCreateForm] onSaveClick: selectedExtensions=', selectedExtensions.value)
  console.log('[TaskCreateForm] onSaveClick: reportTypes=', reportTypes.value)
  console.log('[TaskCreateForm] onSaveClick: analysisStore=', analysisStore ? 'exists' : 'null')
  console.log('[TaskCreateForm] onSaveClick: analysisStore.createTask=', typeof analysisStore.createTask)
  
  try {
    handleSubmit()
    console.log('[TaskCreateForm] handleSubmit returned (async promise started)')
  } catch (err: any) {
    console.error('[TaskCreateForm] onSaveClick sync error:', err.message, err.stack)
  }
}

async function handleSubmit() {
  console.log('=== [TaskCreateForm] handleSubmit started ===')
  const name = taskName.value.trim()
  console.log('[TaskCreateForm] handleSubmit: name=', name, 'isNewTask=', isNewTask.value)
  
  if (!name) {
    console.warn('[TaskCreateForm] handleSubmit: name is empty, aborting')
    return
  }

  loading.value = true
  console.log('[TaskCreateForm] handleSubmit: loading set to true')
  
  try {
    const extArray = selectedExtensions.value.filter(Boolean)
    const excludeArray = excludeDirs.value.split(',').map(s => s.trim()).filter(Boolean)

    console.log('[TaskCreateForm] handleSubmit: extArray=', extArray, 'excludeArray=', excludeArray)

    if (task.value && !isNewTask.value) {
      // Edit mode - update config
      console.log('[TaskCreateForm] EDIT MODE: updating task', task.value.id)
      console.log('[TaskCreateForm] EDIT MODE: config to update=', {
        name,
        scopes: selectedScopes.value.length > 0 ? [...selectedScopes.value] : undefined,
        extensions: extArray.length > 0 ? [...extArray] : undefined,
        excludeDirs: excludeArray.length > 0 ? [...excludeArray] : undefined,
        reportTypes: reportTypes.value.length > 0 ? [...reportTypes.value] : undefined,
      })
      
      const updated = await analysisStore.updateTaskConfig(task.value.id, {
        name,
        scopes: selectedScopes.value.length > 0 ? [...selectedScopes.value] : undefined,
        extensions: extArray.length > 0 ? [...extArray] : undefined,
        excludeDirs: excludeArray.length > 0 ? [...excludeArray] : undefined,
        reportTypes: reportTypes.value.length > 0 ? [...reportTypes.value] : undefined,
        patternType: patternType.value !== 'all' ? patternType.value : undefined,
        pattern: pattern.value || undefined,
      })
      console.log('[TaskCreateForm] EDIT MODE: updateTaskConfig returned=', updated)
      
      isEditMode.value = false
      // Reload task to get updated data
      console.log('[TaskCreateForm] EDIT MODE: reloading task...')
      await loadExistingTask()
      console.log('[TaskCreateForm] EDIT MODE: emitting created event, taskId=', task.value.id)
      emit('created', task.value.id)
      console.log('[TaskCreateForm] EDIT MODE: completed successfully')
    } else {
      // New task
      const taskParams = {
        projectId: props.projectId,
        type: 'full',
        name,
        scopes: selectedScopes.value.length > 0 ? [...selectedScopes.value] : undefined,
        extensions: extArray.length > 0 ? [...extArray] : undefined,
        excludeDirs: excludeArray.length > 0 ? [...excludeArray] : undefined,
        reportTypes: reportTypes.value.length > 0 ? [...reportTypes.value] : undefined,
        patternType: patternType.value !== 'all' ? patternType.value : undefined,
        pattern: pattern.value || undefined,
      }
      
      console.log('[TaskCreateForm] NEW TASK: creating task with params:', JSON.stringify(taskParams, null, 2))
      console.log('[TaskCreateForm] NEW TASK: calling analysisStore.createTask...')
      
      const created = await analysisStore.createTask(taskParams)
      console.log('[TaskCreateForm] NEW TASK: createTask returned=', created)
      console.log('[TaskCreateForm] NEW TASK: emitting created event, taskId=', created.id)
      
      emit('created', created.id)
      console.log('[TaskCreateForm] NEW TASK: completed successfully')
    }
  } catch (err: any) {
    console.error('=== [TaskCreateForm] Failed to save task ===')
    console.error('[TaskCreateForm] Error message:', err.message)
    console.error('[TaskCreateForm] Error stack:', err.stack)
    console.error('[TaskCreateForm] Error object:', err)
  } finally {
    loading.value = false
    console.log('[TaskCreateForm] handleSubmit: loading set to false, finally block executed')
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
    console.error('Failed to stop task:', err)
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
    <!-- Header bar -->
    <div class="form-header">
      <div class="header-left">
        <button v-if="!isNewTask" class="icon-btn" @click="handleCancel">
          <ArrowLeftIcon class="w-4 h-4" />
        </button>
        <h2 class="form-title">
          {{ isNewTask ? t('analysis.newTask') : (isEditMode ? t('analysis.editTask') : t('analysis.viewTask')) }}
        </h2>
      </div>
      <div class="header-right">
        <!-- View mode actions -->
        <template v-if="isViewMode && task">
          <button class="btn btn-ghost" @click="viewLogs">
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
          <button class="btn btn-ghost" @click="handleCancel">
            {{ t('analysis.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            @click="onSaveClick"
            :disabled="loading || !taskName.trim()"
          >
            <SparklesIcon v-if="!loading" class="w-4 h-4" />
            <span>{{ isNewTask ? t('analysis.saveConfig') : t('analysis.confirmChange') }}</span>
          </button>
        </template>
      </div>
    </div>

    <div class="form-layout">
      <!-- Left: File distribution stats -->
      <div class="form-sidebar">
        <FileStatsPanel
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
          />
          <div v-else class="form-value">
            {{ task?.name || '-' }}
            <span class="form-id">{{ task?.id }}</span>
          </div>
        </div>

        <!-- Directory scope (view mode shows tags) -->
        <div class="form-section">
          <label class="form-label">{{ t('analysis.directoryScope') }}</label>
          <div v-if="isViewMode" class="form-tags">
            <span v-if="selectedScopes.length === 0" class="empty-tag">{{ t('analysis.allDirectories') }}</span>
            <span v-else v-for="s in selectedScopes" :key="s" class="form-tag">{{ s }}</span>
          </div>
        </div>

        <!-- Selected extensions -->
        <div class="form-section">
          <label class="form-label">{{ t('analysis.fileExtensions') }}</label>
          <div v-if="isViewMode" class="form-tags">
            <span v-if="selectedExtensions.length === 0" class="empty-tag">{{ t('analysis.allFiles') }}</span>
            <span v-else v-for="ext in selectedExtensions" :key="ext" class="form-tag">{{ ext }}</span>
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
          />
          <div v-else class="form-tags">
            <span v-for="d in (task?.excludeDirs || [])" :key="d" class="form-tag">{{ d }}</span>
            <span v-if="!task?.excludeDirs?.length" class="empty-tag">-</span>
          </div>
        </div>

        <!-- Report types -->
        <div class="form-section">
          <label class="form-label">{{ t('analysis.reportTypes') }}</label>
          <div v-if="isEditMode || isNewTask" class="checkbox-group">
            <label
              v-for="opt in reportTypeOptions"
              :key="opt.value"
              class="checkbox-item"
            >
              <input
                type="checkbox"
                :value="opt.value"
                v-model="reportTypes"
              />
              <span>{{ opt.label }}</span>
            </label>
          </div>
          <div v-else class="form-tags">
            <span v-for="r in (task?.reportTypes || [])" :key="r" class="form-tag">{{ r }}</span>
            <span v-if="!task?.reportTypes?.length" class="empty-tag">-</span>
          </div>
        </div>

        <!-- Task metadata (view mode only) -->
        <div v-if="isViewMode && task" class="form-metadata">
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
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.form-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.icon-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  border-radius: 4px;
}

.icon-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.form-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  flex: 1;
  overflow: hidden;
  padding: 16px;
}

.form-sidebar {
  flex-shrink: 0;
  overflow-y: auto;
}

.form-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
  padding-right: 8px;
}

.form-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.form-input {
  padding: 8px 10px;
  font-size: 13px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-primary);
  outline: none;
  font-family: inherit;
}

.form-input:focus {
  border-color: var(--accent);
}

.form-value {
  font-size: 13px;
  color: var(--text-primary);
  padding: 8px 0;
}

.form-id {
  font-size: 11px;
  color: var(--text-muted);
  font-family: monospace;
  margin-left: 8px;
}

.form-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 0;
}

.form-tag {
  padding: 2px 8px;
  background: var(--bg-tertiary);
  border-radius: 12px;
  font-size: 11px;
  color: var(--text-secondary);
  font-family: monospace;
}

.empty-tag {
  font-size: 12px;
  color: var(--text-muted);
  font-style: italic;
}

.checkbox-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}

.checkbox-item input[type="checkbox"] {
  accent-color: var(--accent);
  width: 16px;
  height: 16px;
}

/* Metadata section */
.form-metadata {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-top: 8px;
}

.metadata-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.metadata-row .w-4 {
  color: var(--text-muted);
}

.btn-warning {
  background: var(--warning);
  color: var(--bg-primary);
  border: none;
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-warning:hover {
  opacity: 0.9;
}
</style>
