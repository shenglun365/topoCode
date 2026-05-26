<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'
import MarkdownIt from 'markdown-it'
import type { FileTreeNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CD-009')
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
const markdownHtml = ref('')
const loading = ref(true)
const error = ref<string | null>(null)

// 判断是否为 markdown 文件
const isMarkdown = computed(() => {
  const ext = (props.node.name || '').split('.').pop()?.toLowerCase()
  return ext === 'md' || ext === 'markdown'
})

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

// Markdown 渲染
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true,
  highlight: function (str: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch (e) {
        // 忽略高亮错误
      }
    }
    return escapeHtml(str)
  }
})

function renderMarkdown() {
  if (!content.value) {
    markdownHtml.value = ''
    return
  }
  markdownHtml.value = md.render(content.value)
}

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
    c: 'c',
    cpp: 'cpp',
    csharp: 'csharp',
    go: 'go',
    rust: 'rust',
    java: 'java',
    kotlin: 'kotlin',
    scala: 'scala',
    ruby: 'ruby',
    php: 'php',
    swift: 'swift',
    r: 'r',
    sql: 'sql',
    perl: 'perl',
    lua: 'lua',
    dart: 'dart',
    haskell: 'haskell',
    elixir: 'elixir',
    erlang: 'erlang',
    zig: 'zig',
    yaml: 'yaml',
    toml: 'toml',
    makefile: 'makefile',
    dockerfile: 'dockerfile',
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

      if (isMarkdown.value) {
        renderMarkdown()
      } else {
        applyHighlight()
      }
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
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 加载状态 -->
    <div
      v-if="loading"
      class="code-loading"
    >
      <div class="loading-spinner" />
      <span>{{ t('file.loading') }}</span>
    </div>

    <!-- 错误状态 -->
    <div
      v-else-if="error"
      class="code-error"
    >
      <span>{{ error }}</span>
    </div>

    <!-- Markdown 渲染 -->
    <div
      v-else-if="isMarkdown"
      class="markdown-container"
    >
      <div
        class="markdown-body"
        v-html="markdownHtml"
      />
    </div>

    <!-- 代码内容 -->
    <div
      v-else
      class="code-container"
    >
      <div
        v-for="line in visibleData"
        :key="line.number"
        class="code-line"
      >
        <span class="line-number">{{ line.number }}</span>
        <span
          class="line-content"
          v-html="line.html"
        />
      </div>
      <div
        v-if="truncated"
        class="code-truncated"
      >
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

/* Markdown 容器 */
.markdown-container {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--bg-primary);
}

.markdown-body {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px 32px;
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
}

/* Markdown 内部样式 */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
  margin-top: 24px;
  margin-bottom: 16px;
  font-weight: 600;
  line-height: 1.25;
  color: var(--text-primary);
}

.markdown-body :deep(h1) { font-size: 2em; border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }
.markdown-body :deep(h2) { font-size: 1.5em; border-bottom: 1px solid var(--border); padding-bottom: 0.3em; }
.markdown-body :deep(h3) { font-size: 1.25em; }
.markdown-body :deep(h4) { font-size: 1em; }

.markdown-body :deep(p) {
  margin-top: 0;
  margin-bottom: 16px;
}

.markdown-body :deep(a) {
  color: var(--accent);
  text-decoration: none;
}

.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

.markdown-body :deep(code) {
  padding: 0.2em 0.4em;
  margin: 0;
  font-size: 85%;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: var(--text-primary);
}

.markdown-body :deep(pre) {
  padding: 16px;
  overflow: auto;
  font-size: 85%;
  line-height: 1.6;
  background: var(--bg-secondary);
  border-radius: 6px;
  margin-bottom: 16px;
}

.markdown-body :deep(pre code) {
  padding: 0;
  margin: 0;
  background: transparent;
  border: none;
}

.markdown-body :deep(blockquote) {
  padding: 0 1em;
  margin: 0 0 16px 0;
  color: var(--text-secondary);
  border-left: 0.25em solid var(--border);
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 2em;
  margin-bottom: 16px;
}

.markdown-body :deep(li) {
  margin-bottom: 4px;
}

.markdown-body :deep(hr) {
  margin: 24px 0;
  border: 0;
  border-top: 1px solid var(--border);
}

.markdown-body :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
}

.markdown-body :deep(table) {
  display: block;
  width: 100%;
  overflow: auto;
  margin-bottom: 16px;
  border-spacing: 0;
  border-collapse: collapse;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 8px 12px;
  border: 1px solid var(--border);
}

.markdown-body :deep(th) {
  background: var(--bg-secondary);
  font-weight: 600;
}

.markdown-body :deep(tr:nth-child(even)) {
  background: var(--bg-secondary);
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
