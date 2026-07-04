<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUpTrayIcon } from '@heroicons/vue/24/outline'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'

const { t } = useI18n()
const router = useRouter()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()

const props = withDefaults(defineProps<{ projectId?: string }>(), { projectId: '' })
const emit = defineEmits<{ close: [] }>()

const importMode = ref('share')
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

async function pickAndImport() {
  const filters = [{ name: 'Structure Analysis Export', extensions: ['zip'] }]
  try {
    const filePath = await (window.api as any).dialog.openFile(filters)
    if (!filePath) return

    uploading.value = true
    error.value = ''
    message.value = ''
    progress.value = 0

    const result = await (window.api as any).system.importProjectArchive(filePath, importMode.value, props.projectId)
    const importId = result.importId
    startPolling(importId)
  } catch (e: any) {
    error.value = e.message || '导入失败'
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
        // 自动刷新：导入完成后延迟短暂时间后导航/刷新
        setTimeout(async () => {
          if (newProjectId.value) {
            await projectStore.loadProjects()
            projectStore.selectProject(newProjectId.value)
            // 如果导入到已有项目（restore），刷新任务列表
            if (props.projectId && newProjectId.value === props.projectId) {
              await analysisStore.loadTasks(props.projectId)
            }
            router.push('/code')
          }
          emit('close')
        }, 500)
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
          <div class="mode-selector">
            <label class="mode-option">
              <input v-model="importMode" type="radio" value="share" class="mode-radio">
              <span class="mode-label">{{ t('project.importModeShare', '写入当前项目（分享）') }}</span>
            </label>
            <label class="mode-option">
              <input v-model="importMode" type="radio" value="restore" class="mode-radio">
              <span class="mode-label">{{ t('project.importModeRestore', '覆盖原项目（恢复备份）') }}</span>
            </label>
          </div>
          <button class="btn btn-primary btn-sm" @click="pickAndImport">
            {{ t('project.selectFile', '选择文件') }}
          </button>
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

.mode-selector { display: flex; flex-direction: column; gap: 6px; width: 100%; padding: 0 8px; }
.mode-option { display: flex; align-items: center; gap: 6px; cursor: pointer; padding: 4px 6px; border-radius: 4px; font-size: 11px; }
.mode-option:hover { background: var(--bg-tertiary); }
.mode-radio { accent-color: var(--accent); width: 14px; height: 14px; }
.mode-label { color: var(--text-primary); }
.error-msg { padding: 6px 16px; font-size: 11px; color: var(--error); text-align: center; }
.progress-section { padding: 20px 16px; display: flex; flex-direction: column; gap: 12px; }
.progress-bar-track { height: 6px; background: var(--bg-tertiary); border-radius: 3px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.progress-info { font-size: 11px; color: var(--text-muted); text-align: center; }
.done-text { color: var(--success); font-weight: 500; }
.dialog-footer { display: flex; gap: 6px; padding: 10px 16px; border-top: 1px solid var(--border); }
</style>
