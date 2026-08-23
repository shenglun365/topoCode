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

const fileInput = ref<HTMLInputElement | null>(null)

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

function pickAndImport() {
  fileInput.value?.click()
}

async function onFileChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  await startUpload(file)
}

async function onDrop(e: DragEvent) {
  const file = e.dataTransfer?.files?.[0]
  if (!file) return
  await startUpload(file)
}

async function startUpload(file: File) {
  uploading.value = true
  error.value = ''
  message.value = ''
  progress.value = 0
  try {
    // 浏览器无本地文件系统访问权：先上传到服务器，再走归档导入
    const serverPath = await (window.api as any).system.uploadArchive(file)
    if (!serverPath) throw new Error(t('project.import.uploadFailed', '上传失败'))
    progress.value = 10
    message.value = t('project.import.importing', '正在导入...')
    const result = await (window.api as any).system.importProjectArchive(serverPath, importMode.value, props.projectId)
    const importId = result.importId
    startPolling(importId)
  } catch (e: any) {
    error.value = e?.message || t('project.import.importFailed')
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
        error.value = status.message || t('project.import.importFailed')
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

function goToProject() {
  if (pollTimer) clearInterval(pollTimer)
  if (newProjectId.value) {
    projectStore.selectProject(newProjectId.value)
    router.push('/code')
  }
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div
      class="dialog-overlay"
      @click.self="close"
    >
      <div class="dialog-card">
        <div class="dialog-header">
          <span class="dialog-title">{{ t('project.importStructure', '导入结构分析') }}</span>
          <button
            v-show="!uploading && !done"
            class="dialog-close"
            @click="close"
          >
            &times;
          </button>
        </div>

        <div
          v-show="!uploading && !done"
          class="upload-area"
          @dragover.prevent
          @drop.prevent="onDrop"
        >
          <input
            ref="fileInput"
            type="file"
            accept=".zip,.json,.jsonl"
            class="hidden-file-input"
            @change="onFileChosen"
          >
          <div class="upload-icon">
            <ArrowUpTrayIcon class="icon-lg" />
          </div>
          <div class="upload-hint">
            {{ t('project.importHint', '选择之前导出的结构分析包 (.zip)，或拖拽到此处') }}
          </div>
          <div class="mode-selector">
            <label class="mode-option">
              <input
                v-model="importMode"
                type="radio"
                value="share"
                class="mode-radio"
              >
              <span class="mode-label">{{ t('project.importModeShare', '写入当前项目（分享）') }}</span>
            </label>
            <label class="mode-option">
              <input
                v-model="importMode"
                type="radio"
                value="restore"
                class="mode-radio"
              >
              <span class="mode-label">{{ t('project.importModeRestore', '覆盖原项目（恢复备份）') }}</span>
            </label>
          </div>
          <button
            class="btn btn-primary btn-sm"
            @click="pickAndImport"
          >
            {{ t('project.selectFile', '选择文件') }}
          </button>
          <div
            v-if="error"
            class="error-msg"
          >
            {{ error }}
          </div>
        </div>

        <div
          v-if="uploading || done"
          class="progress-section"
        >
          <div class="progress-bar-track">
            <div
              class="progress-bar-fill"
              :style="{ width: progress + '%' }"
            />
          </div>
          <div class="progress-info">
            <span v-show="!done">{{ message || t('common.processing', '处理中...') }}</span>
            <span
              v-show="done"
              class="done-text"
            >
              {{ t('project.importDone', '导入完成') }}: {{ newProjectName }}
            </span>
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
              <button
                class="btn btn-primary btn-sm"
                @click="goToProject"
              >
                {{ t('project.goToProject', '查看项目') }}
              </button>
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
.dialog-card { background: var(--bg-primary); border: 1px solid var(--border); border-radius: calc(10px * var(--ui-scale, 1)); min-width: calc(420px * var(--ui-scale, 1)); max-width: calc(480px * var(--ui-scale, 1)); box-shadow: 0 8px 32px rgba(0,0,0,0.25); }
.dialog-header { display: flex; align-items: center; justify-content: space-between; padding: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border); }
.dialog-title { font-size: calc(13px * var(--ui-scale, 1)); font-weight: 600; color: var(--text-primary); }
.dialog-close { font-size: calc(18px * var(--ui-scale, 1)); color: var(--text-muted); background: none; border: none; cursor: pointer; padding: 0 calc(4px * var(--ui-scale, 1)); }
.dialog-close:hover { color: var(--text-primary); }
.upload-area { padding: calc(32px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); display: flex; flex-direction: column; align-items: center; gap: calc(12px * var(--ui-scale, 1)); }
.upload-icon { color: var(--text-muted); }
.icon-lg { width: calc(40px * var(--ui-scale, 1)); height: calc(40px * var(--ui-scale, 1)); }
.upload-hint { font-size: calc(12px * var(--ui-scale, 1)); color: var(--text-muted); text-align: center; }
.hidden-file-input { display: none; }

.mode-selector { display: flex; flex-direction: column; gap: calc(6px * var(--ui-scale, 1)); width: 100%; padding: 0 calc(8px * var(--ui-scale, 1)); }
.mode-option { display: flex; align-items: center; gap: calc(6px * var(--ui-scale, 1)); cursor: pointer; padding: calc(4px * var(--ui-scale, 1)) calc(6px * var(--ui-scale, 1)); border-radius: calc(4px * var(--ui-scale, 1)); font-size: calc(11px * var(--ui-scale, 1)); }
.mode-option:hover { background: var(--bg-tertiary); }
.mode-radio { accent-color: var(--accent); width: calc(14px * var(--ui-scale, 1)); height: calc(14px * var(--ui-scale, 1)); }
.mode-label { color: var(--text-primary); }
.error-msg { padding: calc(6px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); font-size: calc(11px * var(--ui-scale, 1)); color: var(--error); text-align: center; }
.progress-section { padding: calc(20px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); display: flex; flex-direction: column; gap: calc(12px * var(--ui-scale, 1)); }
.progress-bar-track { height: calc(6px * var(--ui-scale, 1)); background: var(--bg-tertiary); border-radius: calc(3px * var(--ui-scale, 1)); overflow: hidden; }
.progress-bar-fill { height: 100%; background: var(--accent); border-radius: calc(3px * var(--ui-scale, 1)); transition: width 0.3s; }
.progress-info { font-size: calc(11px * var(--ui-scale, 1)); color: var(--text-muted); text-align: center; }
.done-text { color: var(--success); font-weight: 500; }
.dialog-footer { display: flex; gap: calc(6px * var(--ui-scale, 1)); padding: calc(10px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1)); border-top: 1px solid var(--border); }
</style>
