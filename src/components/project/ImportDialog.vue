<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpTrayIcon } from '@heroicons/vue/24/outline'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'

const { t } = useI18n()
const router = useRouter()
const projectStore = useProjectStore()

const emit = defineEmits<{ close: [] }>()

const uploading = ref(false)
const progress = ref(0)
const message = ref('')
const done = ref(false)
const newProjectId = ref('')
const newProjectName = ref('')
const error = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  if (!file.name.endsWith('.zip')) {
    error.value = t('project.importNeedZip', '请选择 .zip 格式的导出包')
    return
  }

  uploading.value = true
  error.value = ''
  const baseUrl = `http://127.0.0.1:3456`

  try {
    const formData = new FormData()
    formData.append('file', file)

    const resp = await fetch(`${baseUrl}/api/import`, { method: 'POST', body: formData })
    if (!resp.ok) {
      const errData = await resp.json().catch(() => null)
      throw new Error(errData?.detail || `HTTP ${resp.status}`)
    }
    const data = await resp.json()
    const importId = data.importId

    startPolling(importId)
  } catch (e: any) {
    error.value = e.message || '上传失败'
    uploading.value = false
  }
}

function startPolling(importId: string) {
  pollTimer = setInterval(async () => {
    try {
      const status = await (window.api as any).system.importStatus(importId)
      if (!status) return
      progress.value = status.progress || 0
      message.value = status.message || ''
      if (status.status === 'done') {
        if (pollTimer) clearInterval(pollTimer)
        done.value = true
        uploading.value = false
        newProjectId.value = status.result?.projectId || ''
        newProjectName.value = status.result?.projectName || ''
      } else if (status.status === 'error') {
        if (pollTimer) clearInterval(pollTimer)
        error.value = status.message || '导入失败'
        uploading.value = false
      }
    } catch {
      // ignore
    }
  }, 10000)
}

async function goToProject() {
  if (newProjectId.value) {
    await projectStore.loadProjects()
    projectStore.selectProject(newProjectId.value)
    router.push('/code')
  }
  emit('close')
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
          <span class="dialog-title">{{ t('project.importStructure', '导入结构分析') }}</span>
          <button v-if="!uploading && !done" class="dialog-close" @click="close">&times;</button>
        </div>

        <div v-if="!uploading && !done" class="upload-area">
          <div class="upload-icon"><ArrowUpTrayIcon class="icon-lg" /></div>
          <div class="upload-hint">{{ t('project.importHint', '选择之前导出的结构分析包 (.zip)') }}</div>
          <label class="upload-btn-label">
            <input type="file" accept=".zip" class="file-input" @change="handleFileSelect">
            <span class="btn btn-primary btn-sm">{{ t('project.selectFile', '选择文件') }}</span>
          </label>
          <div v-if="error" class="error-msg">{{ error }}</div>
        </div>

        <div v-else class="progress-section">
          <div class="progress-bar-track">
            <div class="progress-bar-fill" :style="{ width: progress + '%' }" />
          </div>
          <div class="progress-info">
            <span v-if="!done">{{ message || t('common.processing', '处理中...') }}</span>
            <span v-else class="done-text">
              {{ t('project.importDone', '导入完成') }}: {{ newProjectName }}
            </span>
          </div>
          <div v-if="error" class="error-msg">{{ error }}</div>
          <div class="dialog-footer" style="justify-content:flex-end">
            <template v-if="done">
              <button class="btn btn-primary btn-sm" @click="goToProject">
                {{ t('project.goToProject', '查看项目') }}
              </button>
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
.dialog-card { background: var(--bg-primary); border: 1px solid var(--border); border-radius: 10px; min-width: 420px; max-width: 480px; box-shadow: 0 8px 32px rgba(0,0,0,0.25); }
.dialog-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.dialog-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.dialog-close { font-size: 18px; color: var(--text-muted); background: none; border: none; cursor: pointer; padding: 0 4px; }
.dialog-close:hover { color: var(--text-primary); }
.upload-area { padding: 32px 16px; display: flex; flex-direction: column; align-items: center; gap: 12px; }
.upload-icon { color: var(--text-muted); }
.icon-lg { width: 40px; height: 40px; }
.upload-hint { font-size: 12px; color: var(--text-muted); text-align: center; }
.file-input { display: none; }
.upload-btn-label { cursor: pointer; }
.error-msg { padding: 6px 16px; font-size: 11px; color: var(--error); text-align: center; }
.progress-section { padding: 20px 16px; display: flex; flex-direction: column; gap: 12px; }
.progress-bar-track { height: 6px; background: var(--bg-tertiary); border-radius: 3px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.progress-info { font-size: 11px; color: var(--text-muted); text-align: center; }
.done-text { color: var(--success); font-weight: 500; }
.dialog-footer { display: flex; gap: 6px; padding: 10px 16px; border-top: 1px solid var(--border); }
</style>
