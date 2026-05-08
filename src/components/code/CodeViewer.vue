<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import type { FileTreeNode } from '@/types/ipc'

const props = defineProps<{
  node: FileTreeNode
  rootPath: string
}>()

const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()

const content = ref('')
const highlightedLines = ref<string[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

// 大文件保护：最多渲染 5000 行
const MAX_LINES = 5000
const totalLines = ref(0)
const truncated = ref(false)

const visibleData = computed(() => {
  const limit = Math.min(totalLines.value, MAX_LINES)
  const result: { number: number; html: string }[] = []
  const lines = highlightedLines.value
  for (let i = 0; i < limit; i++) {
    result.push({ number: i + 1, html: lines[i] || '' })
  }
  return result
})

// 语法高亮 — 整体高亮后按行分割
function applyHighlight() {
  if (!content.value) {
    highlightedLines.value = []
    return
  }
  const language = props.node.language || 'plaintext'
  const langMap: Record<string, string> = {
    python: 'python',
    javascript: 'javascript',
    typescript: 'typescript',
    vue: 'xml',
    html: 'xml',
    css: 'css',
    scss: 'scss',
    json: 'json',
    markdown: 'markdown',
    bash: 'bash',
    shell: 'bash',
  }
  const hljsLang = langMap[language] || language
  const rawLines = content.value.split('\n')

  try {
    const highlighted = hljs.highlight(content.value, { language: hljsLang })
    const html = highlighted.value
    const htmlLines = html.split('\n')
    highlightedLines.value = rawLines.map((line, idx) => {
      if (htmlLines[idx]) return htmlLines[idx]
      return escapeHtml(line)
    })
  } catch (e) {
    highlightedLines.value = rawLines.map(escapeHtml)
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// 读取文件
async function loadFileContent() {
  if (!props.node.path || props.node.type === 'directory') {
    error.value = t('preview.isDirectory')
    loading.value = false
    return
  }

  loading.value = true
  error.value = null

  try {
    if (window.api && window.api.fs) {
      const fullPath = props.rootPath + '/' + props.node.path
      const result = await window.api.fs.readFile(fullPath)
      content.value = result
      const lines = result.split('\n')
      truncated.value = lines.length > MAX_LINES
      totalLines.value = lines.length
      applyHighlight()
    } else {
      error.value = t('preview.electronOnly')
    }
  } catch (err: any) {
    error.value = err?.message || t('common.loadFailed')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadFileContent()
})

watch(() => props.node, () => {
  content.value = ''
  loadFileContent()
}, { deep: true })

function handleClose() {
  emit('close')
}
</script>

<template>
  <div class="code-viewer">
    <!-- 加载状态 -->
    <div v-if="loading" class="code-loading">
      <div class="loading-spinner"></div>
      <span>{{ t('file.loading') }}</span>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="code-error">
      <span>{{ error }}</span>
    </div>

    <!-- 代码内容 -->
    <div v-else class="code-container">
      <div
        v-for="line in visibleData"
        :key="line.number"
        class="code-line"
      >
        <span class="line-number">{{ line.number }}</span>
        <span class="line-content" v-html="line.html"></span>
      </div>
      <div v-if="truncated" class="code-truncated">
        <span>{{ t('preview.truncated', { max: MAX_LINES, total: totalLines }) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.code-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.code-loading,
.code-error {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  color: var(--text-muted);
  font-size: 12px;
  gap: 8px;
}

.code-error {
  color: var(--error);
}

.code-container {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--bg-primary);
  font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 21px;
  tab-size: 4;
}

.code-line {
  display: flex;
  align-items: flex-start;
  min-height: 21px;
  line-height: 21px;
}

.line-number {
  width: 50px;
  min-width: 50px;
  text-align: right;
  padding-right: 12px;
  padding-top: 0;
  color: var(--text-muted);
  opacity: 0.5;
  user-select: none;
  flex-shrink: 0;
}

.line-content {
  flex: 1;
  padding-right: 12px;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-wrap: break-word;
  overflow-wrap: break-word;
}

.code-truncated {
  padding: 12px 16px 12px 62px;
  color: var(--warning);
  font-size: 12px;
  font-style: italic;
  border-top: 1px solid var(--border);
}

/* highlight.js 样式覆盖 */
.line-content :deep(.hljs) {
  background: transparent !important;
  padding: 0 !important;
  font-family: inherit !important;
  font-size: inherit !important;
}

.code-loading {
  flex: 1;
}
</style>
