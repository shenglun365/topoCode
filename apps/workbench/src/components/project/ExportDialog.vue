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
const archivePath = ref('')
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
    error.value = t('project.export.loadFailed')
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
    error.value = e.message || t('project.export.exportFailed')
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
        archivePath.value = status.result?.archivePath || ''
      } else if (status.status === 'error') {
        if (pollTimer) clearInterval(pollTimer)
        error.value = status.message || t('project.export.exportFailed')
        exporting.value = false
      }
    } catch {
      // ignore
    }
  }, 10000)
}

async function handleDownload() {
  try {
    const resp = await fetch(downloadUrl.value)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = downloadUrl.value.split('/').pop() || 'export.zip'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    if (archivePath.value) {
      await (window.api as any).system.exportRemoveArchive(archivePath.value)
    }
  } catch (e: any) {
    console.error('[Export] download failed:', e)
  }
  close()
}

function close() {
  if (pollTimer) clearInterval(pollTimer)
  if (done.value && archivePath.value) {
    (window.api as any).system.exportRemoveArchive(archivePath.value).catch(() => {})
  }
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div class="dialog-overlay">
      <div class="dialog-card">
        <div class="dialog-header">
          <span class="dialog-title">{{ t('project.exportStructure') }}</span>
          <button
            v-if="!exporting"
            class="dialog-close"
            @click="close"
          >
            &times;
          </button>
        </div>

        <div
          v-if="loading"
          class="dialog-loading"
        >
          <div class="spinner" /><span>{{ t('common.loading') }}...</span>
        </div>

        <template v-if="!exporting && !done && !loading">
          <div class="dialog-hint">
            {{ t('project.exportSelectHint') }}
          </div>
          <div class="select-all-row">
            <label class="cb-row">
              <input
                v-model="allChecked"
                type="checkbox"
                class="cb"
                @change="toggleAll"
              >
              <span class="cb-label">{{ t('common.selectAll') }} ({{ tasks.length }})</span>
            </label>
          </div>
          <div class="task-list">
            <label
              v-for="task in tasks"
              :key="task.id"
              class="cb-row"
            >
              <input
                v-model="task.checked"
                type="checkbox"
                class="cb"
              >
              <span class="cb-label">{{ task.name }}</span>
            </label>
          </div>
          <div
            v-if="error"
            class="error-msg"
          >
            {{ error }}
          </div>
          <div class="dialog-footer">
            <span class="selected-info">{{ t('project.exportSelected', { n: selectedCount() }) }}</span>
            <div class="dialog-actions">
              <button
                class="btn btn-ghost btn-sm"
                @click="close"
              >
                {{ t('common.cancel') }}
              </button>
              <button
                class="btn btn-primary btn-sm"
                :disabled="selectedCount() === 0"
                @click="startExport"
              >
                {{ t('project.exportAction') }}
              </button>
            </div>
          </div>
        </template>

        <div
          v-if="!loading && (exporting || done)"
          class="progress-section"
        >
          <div class="progress-bar-track">
            <div
              class="progress-bar-fill"
              :style="{ width: progress + '%' }"
            />
          </div>
          <div class="progress-info">
            <span v-show="!done">{{ message || t('common.processing') }}</span>
            <span
              v-show="done"
              class="done-text"
            >{{ t('project.exportDone') }}</span>
          </div>
          <div
            v-if="error"
            class="error-msg"
          >
            {{ error }}
          </div>
          <div
            class="dialog-footer"
            style="justify-content:flex-end"
          >
            <template v-if="done">
              <a
                class="btn btn-primary btn-sm"
                @click.prevent="handleDownload"
              >
                <ArrowDownTrayIcon class="icon-sm" /> {{ t('project.downloadExport') }}
              </a>
            </template>
            <button
              class="btn btn-ghost btn-sm"
              @click="close"
            >
              {{ t('common.close') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 10000; }
.dialog-card { background: var(--bg-primary); border: 1px solid var(--border); border-radius: calc(10px * var(--ui-scale, 1)); min-width: calc(420px * var(--ui-scale, 1)); max-width: calc(480px * var(--ui-scale, 1)); max-height: 80vh; display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,0.25); }
.dialog-header { display: flex; align-items: center; justify-content: space-between; padding: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border); }
.dialog-title { font-size: calc(13px * var(--ui-scale, 1)); font-weight: 600; color: var(--text-primary); }
.dialog-close { font-size: calc(18px * var(--ui-scale, 1)); color: var(--text-muted); background: none; border: none; cursor: pointer; padding: 0 calc(4px * var(--ui-scale, 1)); }
.dialog-close:hover { color: var(--text-primary); }
.dialog-loading { padding: calc(24px * var(--ui-scale, 1)); text-align: center; color: var(--text-muted); display: flex; align-items: center; justify-content: center; gap: calc(8px * var(--ui-scale, 1)); }
.spinner { width: calc(20px * var(--ui-scale, 1)); height: calc(20px * var(--ui-scale, 1)); border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.dialog-hint { padding: calc(8px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); font-size: calc(10px * var(--ui-scale, 1)); color: var(--text-muted); }
.select-all-row { padding: calc(4px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border); }
.task-list { flex: 1; overflow-y: auto; padding: calc(4px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); max-height: calc(300px * var(--ui-scale, 1)); }
.cb-row { display: flex; align-items: center; gap: calc(6px * var(--ui-scale, 1)); padding: calc(5px * var(--ui-scale, 1)) calc(4px * var(--ui-scale, 1)); cursor: pointer; font-size: calc(11px * var(--ui-scale, 1)); }
.cb-row:hover { background: var(--bg-tertiary); border-radius: calc(4px * var(--ui-scale, 1)); }
.cb { accent-color: var(--accent); width: calc(14px * var(--ui-scale, 1)); height: calc(14px * var(--ui-scale, 1)); }
.cb-label { flex: 1; color: var(--text-primary); }
.error-msg { padding: calc(6px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); font-size: calc(11px * var(--ui-scale, 1)); color: var(--error); }
.dialog-footer { display: flex; align-items: center; justify-content: space-between; padding: calc(10px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-top: 1px solid var(--border); }
.selected-info { font-size: calc(10px * var(--ui-scale, 1)); color: var(--text-muted); }
.dialog-actions { display: flex; gap: calc(6px * var(--ui-scale, 1)); }
.icon-sm { width: calc(14px * var(--ui-scale, 1)); height: calc(14px * var(--ui-scale, 1)); }
.progress-section { padding: calc(20px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); display: flex; flex-direction: column; gap: calc(12px * var(--ui-scale, 1)); }
.progress-bar-track { height: calc(6px * var(--ui-scale, 1)); background: var(--bg-tertiary); border-radius: calc(3px * var(--ui-scale, 1)); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); border-radius: calc(3px * var(--ui-scale, 1)); transition: width 0.3s; }
.progress-info { font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-muted); text-align: center; }
.done-text { color: var(--success); font-weight: 500; }
</style>
