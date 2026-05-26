<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderPlusIcon,
  ArrowUpTrayIcon,
  ExclamationCircleIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-004')
const { t } = useI18n()
const projectStore = useProjectStore()

const isDragging = ref(false)
const importError = ref<string | null>(null)
const errorTimer = ref<ReturnType<typeof setTimeout> | null>(null)

function onDragEnter(e: DragEvent) {
  e.preventDefault()
  isDragging.value = true
}

function onDragLeave(e: DragEvent) {
  e.preventDefault()
  // 只有真正离开容器时才重置
  if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) {
    isDragging.value = false
  }
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
}

async function onDrop(e: DragEvent) {
  e.preventDefault()
  isDragging.value = false
  clearError()

  // 提取拖拽路径
  const path = extractFilePath(e)
  if (!path) {
    showError(t('import.error.invalidPath'))
    return
  }

  await doImport(path)
}

async function onSelectFolder() {
  clearError()

  // Electron 环境
  if (window.api && window.api.dialog) {
    try {
      const path = await window.api.dialog.openDirectory()
      if (path) {
        await doImport(path)
      }
    } catch (err: any) {
      showError(err.message || t('import.error.failed'))
    }
  } else {
    // 浏览器环境降级提示
    showError(t('import.error.electronOnly'))
  }
}

async function doImport(path: string) {
  // 检查重复导入
  const existing = projectStore.projects.find(
    p => p.path === path || p.rootPath === path
  )
  if (existing) {
    showError(t('import.error.duplicate'))
    return
  }

  try {
    projectStore.loading = true
    const project = await projectStore.importProject(path)
    // 导入成功，刷新列表
    await projectStore.loadProjects()
  } catch (err: any) {
    showError(err.message || t('import.error.failed'))
  } finally {
    projectStore.loading = false
  }
}

function extractFilePath(e: DragEvent): string | null {
  // 尝试从 DataTransfer 提取路径
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    // Electron 中拖拽文件夹会返回 FileList
    const file = files[0]
    // @ts-ignore - webkitRelativePath 或 path
    const path = file.path || file.webkitRelativePath || file.name
    if (path) return path
  }

  // 尝试从自定义数据提取
  const pathData = e.dataTransfer?.getData('text/uri-list')
  if (pathData) {
    // file:///home/user/path → /home/user/path
    return pathData.replace(/^file:\/\//, '').split('\n')[0]
  }

  const textData = e.dataTransfer?.getData('text/plain')
  if (textData && textData.startsWith('/')) {
    return textData
  }

  return null
}

function showError(msg: string) {
  importError.value = msg
  if (errorTimer.value) clearTimeout(errorTimer.value)
  errorTimer.value = setTimeout(() => {
    importError.value = null
  }, 5000)
}

function clearError() {
  importError.value = null
  if (errorTimer.value) {
    clearTimeout(errorTimer.value)
    errorTimer.value = null
  }
}
</script>

<template>
  <div class="import-zone-wrapper">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      class="import-zone card"
      :class="{ 'drag-over': isDragging }"
      @dragenter="onDragEnter"
      @dragleave="onDragLeave"
      @dragover="onDragOver"
      @drop="onDrop"
    >
      <div class="import-icon">
        <ArrowUpTrayIcon class="w-10 h-10" />
      </div>
      <div style="font-size:14px; font-weight:500; margin-bottom:6px;">
        {{ t('file.dragDrop') }}
      </div>
      <div
        class="text-muted"
        style="font-size:12px; margin-bottom:16px;"
      >
        {{ t('common.or') }}
      </div>
      <button
        class="btn btn-primary"
        :disabled="projectStore.loading"
        @click="onSelectFolder"
      >
        <FolderPlusIcon class="w-4 h-4" />
        <span>{{ t('file.selectFolder') }}</span>
      </button>
      <div
        class="text-muted"
        style="font-size:10px; margin-top:12px;"
      >
        {{ t('file.supportedFormats') }}
      </div>
    </div>

    <!-- 加载状态 -->
    <div
      v-if="projectStore.loading"
      class="import-loading"
    >
      <div class="loading-spinner" />
      <span class="text-muted">{{ t('import.loading') }}</span>
    </div>

    <!-- 错误提示 -->
    <div
      v-if="importError"
      class="import-error"
    >
      <ExclamationCircleIcon class="w-4 h-4" />
      <span>{{ importError }}</span>
    </div>
  </div>
</template>

<style scoped>
.import-zone-wrapper {
  position: relative;
}

.import-zone {
  border: 2px dashed var(--border);
  text-align: center;
  padding: 40px;
  cursor: pointer;
  transition: all 0.2s;
}

.import-zone:hover {
  border-color: var(--accent);
}

.import-zone.drag-over {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.import-icon {
  margin-bottom: 12px;
  opacity: 0.5;
  color: var(--text-muted);
}

.import-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  margin-top: 8px;
}

.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.import-error {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  margin-top: 8px;
  background: color-mix(in srgb, #ef4444 10%, transparent);
  border: 1px solid #ef4444;
  border-radius: 6px;
  color: #ef4444;
  font-size: 12px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
