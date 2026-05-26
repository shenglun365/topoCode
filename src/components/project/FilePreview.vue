<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentIcon,
  XMarkIcon,
  Square2StackIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import type { FileTreeNode } from '@/types/ipc'
import { useProjectStore } from '@/stores/project'
import { useDebugStore } from '@/stores/debug'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-010')
const debug = useDebugStore()

const props = defineProps<{
  node: FileTreeNode
  rootPath: string
}>()

const emit = defineEmits<{
  close: []
  pin: []
}>()

const { t } = useI18n()
const projectStore = useProjectStore()

const content = ref('')
const loading = ref(true)
const error = ref<string | null>(null)
const isBinary = ref(false)
const lineCount = ref(0)

// 检测是否为二进制文件
function isBinaryFile(fileName: string): boolean {
  const binaryExtensions = new Set([
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
    '.mp3', '.mp4', '.avi', '.mov', '.wav',
    '.zip', '.tar', '.gz', '.rar', '.7z',
    '.exe', '.dll', '.so', '.dylib',
    '.class', '.pyc', '.o', '.obj',
    '.db', '.sqlite', '.sqlite3',
  ])
  const ext = fileName.split('.').pop()?.toLowerCase() || ''
  return binaryExtensions.has(`.${ext}`)
}

// 读取文件内容
async function loadFileContent() {
  debug.log('FilePreview', `[loadFileContent] ${props.node.type}: ${props.node.name}, path=${props.node.path}`)
  if (!props.node.path) {
    debug.log('FilePreview', `  → no path, returning`)
    return
  }
  // 目录不可读取
  if (props.node.type === 'directory') {
    debug.log('FilePreview', `  → BLOCKED (directory)`)
    error.value = t('preview.isDirectory')
    loading.value = false
    return
  }

  loading.value = true
  error.value = null
  isBinary.value = false

  // 检测二进制文件
  if (isBinaryFile(props.node.name)) {
    isBinary.value = true
    loading.value = false
    return
  }

  // 检测大文件
  if (props.node.size && props.node.size > 5 * 1024 * 1024) {
    error.value = t('preview.fileTooLarge')
    loading.value = false
    return
  }

  try {
    // Electron 环境：通过主进程读取文件
    if (window.api && window.api.fs) {
      const fullPath = props.rootPath + '/' + props.node.path
      const result = await window.api.fs.readFile(fullPath)
      content.value = result
      lineCount.value = result.split('\n').length
    } else {
      // 浏览器环境：提示不可用
      error.value = t('preview.electronOnly')
    }
  } catch (err: any) {
    error.value = err.message || t('preview.readFailed')
  } finally {
    loading.value = false
  }
}

// 语法高亮（简单实现，后续可替换为 Shiki）
const highlightedLines = computed(() => {
  if (!content.value) return []
  return content.value.split('\n')
})

watch(() => props.node.path, () => {
  loadFileContent()
}, { immediate: true })
</script>

<template>
  <div class="file-preview">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 标题栏 -->
    <div class="preview-header">
      <div class="preview-title">
        <DocumentIcon class="w-4 h-4" />
        <span class="title-text">{{ node.name }}</span>
        <span
          v-if="node.language"
          class="badge badge-gray"
        >{{ node.language }}</span>
      </div>
      <div class="preview-actions">
        <button
          class="btn btn-ghost btn-icon"
          :title="t('preview.pinToTab')"
          @click="emit('pin')"
        >
          <Square2StackIcon class="w-4 h-4" />
        </button>
        <button
          class="btn btn-ghost btn-icon"
          :title="t('common.close')"
          @click="emit('close')"
        >
          <XMarkIcon class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- 内容区 -->
    <div class="preview-content">
      <!-- 加载中 -->
      <div
        v-if="loading"
        class="preview-loading"
      >
        <div class="loading-spinner" />
        <span class="text-muted">{{ t('common.loading') }}</span>
      </div>

      <!-- 错误 -->
      <div
        v-else-if="error"
        class="preview-error"
      >
        <ExclamationTriangleIcon class="w-5 h-5" />
        <span>{{ error }}</span>
      </div>

      <!-- 二进制文件 -->
      <div
        v-else-if="isBinary"
        class="preview-binary"
      >
        <DocumentIcon class="w-8 h-8" />
        <span class="text-muted">{{ t('preview.binaryFile') }}</span>
      </div>

      <!-- 代码内容 -->
      <div
        v-else
        class="code-view"
      >
        <div class="code-lines">
          <div
            v-for="(line, idx) in highlightedLines"
            :key="idx"
            class="code-line"
          >
            <span class="line-number">{{ idx + 1 }}</span>
            <span class="line-content">{{ line || ' ' }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 状态栏 -->
    <div
      v-if="!loading && !error && !isBinary"
      class="preview-footer"
    >
      <span class="text-muted">{{ lineCount }} {{ t('common.lines') }}</span>
      <span
        v-if="node.size"
        class="text-muted"
      >
        {{ node.size > 1024 * 1024 ? `${(node.size / 1024 / 1024).toFixed(1)}MB` : node.size > 1024 ? `${(node.size / 1024).toFixed(1)}KB` : `${node.size}B` }}
      </span>
      <span
        v-if="node.path"
        class="text-muted"
      >{{ node.path }}</span>
    </div>
  </div>
</template>

<style scoped>
.file-preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary);
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-tertiary);
}

.preview-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  overflow: hidden;
}

.title-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-actions {
  display: flex;
  gap: 4px;
}

.preview-content {
  flex: 1;
  overflow: auto;
}

.preview-loading,
.preview-error,
.preview-binary {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px;
  color: var(--text-muted);
}

.preview-error {
  color: #ef4444;
}

.loading-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.code-view {
  height: 100%;
  overflow: auto;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
}

.code-lines {
  display: flex;
  flex-direction: column;
}

.code-line {
  display: flex;
  padding: 0 12px;
  min-height: 1.5em;
}

.code-line:hover {
  background: var(--bg-hover);
}

.line-number {
  width: 40px;
  text-align: right;
  padding-right: 12px;
  color: var(--text-muted);
  user-select: none;
  flex-shrink: 0;
}

.line-content {
  flex: 1;
  white-space: pre;
  overflow: visible;
}

.preview-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 12px;
  border-top: 1px solid var(--border);
  font-size: 10px;
  background: var(--bg-tertiary);
}
</style>
