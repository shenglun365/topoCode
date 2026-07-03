<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowDownTrayIcon } from '@heroicons/vue/24/outline'
import { ipc } from '@/services/ipc'

const { t } = useI18n()

const props = defineProps<{
  projectId: string
  projectName: string
}>()
const emit = defineEmits<{ close: [] }>()

interface TaskItem {
  id: string
  name: string
  checked: boolean
}

const loading = ref(true)
const tasks = ref<TaskItem[]>([])
const allChecked = ref(true)
const exportId = ref('')
const exporting = ref(false)
const progress = ref(0)
const message = ref('')
const done = ref(false)
const downloadUrl = ref('')
const error = ref('')
const httpBase = ref('http://localhost:3456')
let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  try {
    const result = await ipc.analysis.listTasks(props.projectId)
    tasks.value = (result || []).map((t: any) => ({
      id: t.id || t.task_id,
      name: t.name,
      checked: true,
    }))
    try {
      const port = await (window.api as any).system.getHttpPort()
      if (port) httpBase.value = `http://localhost:${port}`
    } catch { /* use default */ }
  } catch (e) {
    error.value = '加载任务列表失败'
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

function toggleAll() {
  allChecked.value = !allChecked.value
  tasks.value.forEach(t => (t.checked = allChecked.value))
}

const selectedCount = () => tasks.value.filter(t => t.checked).length

async function startExport() {
  const selected = tasks.value.filter(t => t.checked).map(t => t.id)
  if (selected.length === 0) return
  exporting.value = true
  error.value = ''
  try {
    const result = await (window.api as any).system.exportProject(props.projectId, selected)
    exportId.value = result.exportId
    startPolling()
  } catch (e: any) {
    error.value = e.message || '导出失败'
    exporting.value = false
  }
}

function startPolling() {
  pollTimer = setInterval(async () => {
    try {
      const status = await (window.api as any).system.exportStatus(exportId.value)
      if (!status) return
      progress.value = status.progress || 0
      message.value = status.message || ''
      if (status.status === 'done') {
        if (pollTimer) clearInterval(pollTimer)
        done.value = true
        exporting.value = false
        downloadUrl.value = `${httpBase.value}/api/export/${exportId.value}/download`
      } else if (status.status === 'error') {
        if (pollTimer) clearInterval(pollTimer)
        error.value = status.message || '导出失败'
        exporting.value = false
      }
    } catch {
      // ignore
    }
  }, 10000)
}

function close() {
  if (pollTimer) clearInterval(pollTimer)
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div class="dialog-overlay" @click.self="close">
      <div class="dialog-card">
        <div class="dialog-header">
          <span class="dialog-title">{{ t('project.exportStructure', '导出结构分析') }}</span>
          <button v-if="!exporting" class="dialog-close" @click="close">&times;</button>
        </div>

        <div v-if="loading" class="dialog-loading">
          <div class="spinner" /><span>{{ t('common.loading') }}...</span>
        </div>

        <template v-else-if="!exporting && !done">
          <div class="dialog-hint">{{ t('project.exportSelectHint', '选择要导出的分析任务') }}</div>
          <div class="select-all-row">
            <label class="cb-row">
              <input v-model="allChecked" type="checkbox" class="cb" @change="toggleAll">
              <span class="cb-label">{{ t('common.selectAll', '全选') }} ({{ tasks.length }})</span>
            </label>
          </div>
          <div class="task-list">
            <label v-for="task in tasks" :key="task.id" class="cb-row">
              <input v-model="task.checked" type="checkbox" class="cb">
              <span class="cb-label">{{ task.name }}</span>
            </label>
          </div>
          <div v-if="error" class="error-msg">{{ error }}</div>
          <div class="dialog-footer">
            <span class="selected-info">{{ t('project.exportSelected', { n: selectedCount() }) }}</span>
            <div class="dialog-actions">
              <button class="btn btn-ghost btn-sm" @click="close">{{ t('common.cancel') }}</button>
              <button class="btn btn-primary btn-sm" :disabled="selectedCount() === 0" @click="startExport">
                {{ t('project.exportAction', '导出') }}
              </button>
            </div>
          </div>
        </template>

        <div v-else class="progress-section">
          <div class="progress-bar-track">
            <div class="progress-bar-fill" :style="{ width: progress + '%' }" />
          </div>
          <div class="progress-info">
            <span v-if="!done">{{ message || t('common.processing', '处理中...') }}</span>
            <span v-else class="done-text">{{ t('project.exportDone', '导出完成') }}</span>
          </div>
          <div v-if="error" class="error-msg">{{ error }}</div>
          <div class="dialog-footer" style="justify-content:flex-end">
            <template v-if="done">
              <a :href="downloadUrl" class="btn btn-primary btn-sm" download @click="close">
                <ArrowDownTrayIcon class="icon-sm" /> {{ t('project.downloadExport', '下载') }}
              </a>
            </template>
            <button class="btn btn-ghost btn-sm" @click="close">{{ t('common.close') }}</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000; }
.dialog-card { background: var(--bg-primary); border: 1px solid var(--border); border-radius: 10px; min-width: 420px; max-width: 480px; max-height: 80vh; display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,0.25); }
.dialog-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.dialog-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.dialog-close { font-size: 18px; color: var(--text-muted); background: none; border: none; cursor: pointer; padding: 0 4px; }
.dialog-close:hover { color: var(--text-primary); }
.dialog-loading { padding: 24px; text-align: center; color: var(--text-muted); display: flex; align-items: center; justify-content: center; gap: 8px; }
.spinner { width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.dialog-hint { padding: 8px 16px; font-size: 10px; color: var(--text-muted); }
.select-all-row { padding: 4px 16px; border-bottom: 1px solid var(--border); }
.task-list { flex: 1; overflow-y: auto; padding: 4px 16px; max-height: 300px; }
.cb-row { display: flex; align-items: center; gap: 6px; padding: 5px 4px; cursor: pointer; font-size: 11px; }
.cb-row:hover { background: var(--bg-tertiary); border-radius: 4px; }
.cb { accent-color: var(--accent); width: 14px; height: 14px; }
.cb-label { flex: 1; color: var(--text-primary); }
.error-msg { padding: 6px 16px; font-size: 11px; color: var(--error); }
.dialog-footer { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; border-top: 1px solid var(--border); }
.selected-info { font-size: 10px; color: var(--text-muted); }
.dialog-actions { display: flex; gap: 6px; }
.icon-sm { width: 14px; height: 14px; }
.progress-section { padding: 20px 16px; display: flex; flex-direction: column; gap: 12px; }
.progress-bar-track { height: 6px; background: var(--bg-tertiary); border-radius: 3px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.progress-info { font-size: 11px; color: var(--text-muted); text-align: center; }
.done-text { color: var(--success); font-weight: 500; }
</style>
