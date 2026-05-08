<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { SparklesIcon } from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import { useProjectStore } from '@/stores/project'
import FileStatsPanel from './FileStatsPanel.vue'
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

// 表单状态
const taskName = ref('')
const scope = ref('')
const patternType = ref<'all' | 'glob' | 'regex'>('all')
const pattern = ref('')
const extensions = ref('')
const excludeDirs = ref('')
const reportTypes = ref<string[]>([])
const loading = ref(false)
const editing = ref<AnalysisTask | null>(null)

// 报告类型选项
const reportTypeOptions = [
  { value: 'dependency', label: t('analysis.dependencyAnalysis') },
  { value: 'callChain', label: t('analysis.callChainAnalysis') },
  { value: 'dataFlow', label: t('analysis.dataFlowAnalysis') },
]

// 自动填充后缀
function onSuggestExtensions(exts: string[]) {
  if (!extensions.value) {
    extensions.value = exts.join(', ')
  }
}

// 加载已有任务配置（编辑模式）
async function loadExistingTask() {
  if (!props.taskId) return
  try {
    const task = await analysisStore.getTask(props.taskId)
    editing.value = task
    taskName.value = task.name || ''
    scope.value = task.scope || ''
    extensions.value = task.extensions?.join(', ') || ''
    excludeDirs.value = task.excludeDirs?.join(', ') || ''
    reportTypes.value = task.reportTypes || []
  } catch (err) {
    console.error('Failed to load task:', err)
  }
}

onMounted(() => {
  loadExistingTask()
})

// 提交表单
async function handleSubmit() {
  if (!taskName.value.trim()) return

  loading.value = true
  try {
    const extArray = extensions.value.split(',').map(s => s.trim()).filter(Boolean)
    const excludeArray = excludeDirs.value.split(',').map(s => s.trim()).filter(Boolean)

    if (editing.value) {
      // 编辑模式
      await analysisStore.updateTaskConfig(editing.value.id, {
        name: taskName.value.trim(),
        scope: scope.value || undefined,
        extensions: extArray.length > 0 ? extArray : undefined,
        excludeDirs: excludeArray.length > 0 ? excludeArray : undefined,
        reportTypes: reportTypes.value.length > 0 ? reportTypes.value : undefined,
      })
      emit('created', editing.value.id)
    } else {
      // 新建模式
      const task = await analysisStore.createTask({
        projectId: props.projectId,
        type: 'full-parse',
        name: taskName.value.trim(),
        scope: scope.value || undefined,
        extensions: extArray.length > 0 ? extArray : undefined,
        excludeDirs: excludeArray.length > 0 ? excludeArray : undefined,
        reportTypes: reportTypes.value.length > 0 ? reportTypes.value : undefined,
      })
      emit('created', task.id)
    }
  } catch (err) {
    console.error('Failed to save task:', err)
  } finally {
    loading.value = false
  }
}

function handleCancel() {
  emit('cancelled')
}
</script>

<template>
  <div class="task-create-form">
    <div class="form-layout">
      <!-- 左侧: 文件分布统计 -->
      <div class="form-sidebar">
        <FileStatsPanel
          :project-id="projectId"
          :scope="scope"
          :pattern-type="patternType"
          :pattern="pattern"
          :exclude-dirs="excludeDirs.split(',').map(s => s.trim()).filter(Boolean)"
          @update:scope="scope = $event"
          @update:pattern-type="patternType = $event"
          @update:pattern="pattern = $event"
          @suggest-extensions="onSuggestExtensions"
        />
      </div>

      <!-- 右侧: 任务配置表单 -->
      <div class="form-main">
        <div class="form-section">
          <label class="form-label">{{ t('analysis.taskName') }} *</label>
          <input
            v-model="taskName"
            class="form-input"
            :placeholder="t('analysis.taskNamePlaceholder')"
          />
        </div>

        <div class="form-section">
          <label class="form-label">{{ t('analysis.analysisRoot') }}</label>
          <input
            v-model="scope"
            class="form-input"
            :placeholder="projectStore.selectedProject?.rootPath || projectStore.selectedProject?.path || ''"
          />
        </div>

        <div class="form-section">
          <label class="form-label">{{ t('analysis.fileExtensions') }}</label>
          <input
            v-model="extensions"
            class="form-input"
            :placeholder="t('analysis.extensionsPlaceholder')"
          />
        </div>

        <div class="form-section">
          <label class="form-label">{{ t('analysis.excludeDirs') }}</label>
          <input
            v-model="excludeDirs"
            class="form-input"
            :placeholder="t('analysis.excludeDirsPlaceholder')"
          />
        </div>

        <div class="form-section">
          <label class="form-label">{{ t('analysis.reportTypes') }}</label>
          <div class="checkbox-group">
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
        </div>

        <!-- 操作按钮 -->
        <div class="form-actions">
          <button
            class="btn btn-ghost"
            @click="handleCancel"
            :disabled="loading"
          >
            {{ t('analysis.cancel') }}
          </button>
          <button
            class="btn btn-primary"
            @click="handleSubmit"
            :disabled="loading || !taskName.trim()"
          >
            <SparklesIcon v-if="!loading" class="w-4 h-4" />
            <span>{{ editing ? t('analysis.update') : t('analysis.create') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-create-form {
  flex: 1;
  overflow: auto;
  padding: 16px;
}

.form-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  max-width: 1000px;
  margin: 0 auto;
}

.form-sidebar {
  flex-shrink: 0;
}

.form-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
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

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  margin-top: auto;
}

.form-actions .btn {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
