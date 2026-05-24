<script setup lang="ts">
/**
 * 子文档查看器
 *
 * 默认 Markdown 预览模式, 支持切换到编辑模式.
 * 保存后回到预览模式.
 * 自动提取并渲染 ```mermaid / ```plantuml 代码块.
 */

import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PencilIcon,
  DocumentArrowDownIcon,
  ArrowLeftIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('RP-010')


const { t } = useI18n()

const props = defineProps<{
  subDocId?: string
  initialContent?: string
  initialTitle?: string
}>()

const emit = defineEmits<{
  'close': []
}>()

// 状态
const loading = ref(true)
const editing = ref(false)
const doc = ref<{
  id: string
  title: string
  content: string
  templateId: string
  createdAt: string
  updatedAt: string
} | null>(null)
const editContent = ref('')
const editTitle = ref('')
const saving = ref(false)

type DiagramLang = 'mermaid' | 'plantuml'

type DiagramBlock = {
  id: string
  lang: DiagramLang
  code: string
  svg?: string
  loading: boolean
  error?: string
}

const diagramBlocks = ref<DiagramBlock[]>([])
const activeDiagramTab = ref<DiagramLang>('mermaid')

// 主线程直接渲染 mermaid（Worker 中 mermaid v11 无法访问 document）
let mermaidApi: any = null
async function ensureMermaid() {
  if (mermaidApi) return
  const mod = await import('mermaid')
  mermaidApi = mod.default
  mermaidApi.initialize({
    startOnLoad: false,
    securityLevel: 'loose',
    theme: 'dark',
    fontFamily: 'var(--font-sans)',
  })
}

async function renderAllDiagrams() {
  if (!doc.value) return
  const content = doc.value.content
  diagramBlocks.value = extractDiagrams(content)
  if (diagramBlocks.value.length === 0) return

  // 决定默认 tab：优先选存在的
  const hasMermaid = diagramBlocks.value.some(b => b.lang === 'mermaid')
  const hasPlantuml = diagramBlocks.value.some(b => b.lang === 'plantuml')
  if (hasPlantuml && !hasMermaid) activeDiagramTab.value = 'plantuml'
  else activeDiagramTab.value = 'mermaid'

  for (const block of diagramBlocks.value) {
    block.loading = true
    block.error = undefined
    try {
      let svg = ''
      if (block.lang === 'mermaid') {
        await ensureMermaid()
        const id = `sd-${block.id}`
        const result = await mermaidApi.render(id, block.code)
        svg = result.svg
      } else {
        const result = await window.api.render.renderPlantuml({ code: block.code, format: 'svg' })
        svg = atob(result.data)
      }
      block.svg = svg
    } catch (e: any) {
      block.error = e.message || 'Render failed'
      console.error(`[SubDocViewer] ${block.lang} render error:`, e)
    } finally {
      block.loading = false
    }
  }
}

// 提取图表块
function extractDiagrams(content: string): DiagramBlock[] {
  const blocks: DiagramBlock[] = []
  let idx = 0
  const re = /```(mermaid|plantuml)\n([\s\S]*?)```/g
  let m
  while ((m = re.exec(content)) !== null) {
    const code = m[2].trim()
    if (code) {
      blocks.push({ id: `diagram-${idx++}`, lang: m[1] as DiagramLang, code, loading: false })
    }
  }
  return blocks
}

// 加载文档
async function loadDoc() {
  loading.value = true
  try {
    if (props.subDocId) {
      doc.value = await window.api.report.getSubDoc(props.subDocId)
    } else if (props.initialContent) {
      doc.value = {
        id: '',
        title: props.initialTitle || '',
        content: props.initialContent,
        templateId: '',
        createdAt: '',
        updatedAt: '',
      }
    }
    if (doc.value) {
      editContent.value = doc.value.content
      editTitle.value = doc.value.title
      if (doc.value.content) {
        diagramBlocks.value = extractDiagrams(doc.value.content)
      }
    }
  } catch (e) {
    console.error('[SubDocViewer] Failed to load doc:', e)
  } finally {
    loading.value = false
  }
  // 文档加载完成后渲染图表（等 DOM 就绪）
  if (diagramBlocks.value.length > 0) {
    await nextTick()
    renderAllDiagrams()
  }
}

// 进入编辑模式
function startEdit() {
  editing.value = true
  editContent.value = doc.value?.content || ''
  editTitle.value = doc.value?.title || ''
}

// 取消编辑
function cancelEdit() {
  editing.value = false
  editContent.value = doc.value?.content || ''
  editTitle.value = doc.value?.title || ''
}

// 保存
async function saveEdit() {
  if (!doc.value) return
  saving.value = true
  try {
    await window.api.report.updateSubDoc({
      subDocId: doc.value.id,
      title: editTitle.value,
      content: editContent.value,
    })
    doc.value.content = editContent.value
    doc.value.title = editTitle.value
    editing.value = false
  } catch (e) {
    console.error('[SubDocViewer] Failed to save:', e)
  } finally {
    saving.value = false
  }
}

// 渲染 Markdown (简单处理, 实际项目可用 marked)
const renderedContent = computed(() => {
  if (!doc.value) return ''
  // 去掉图表块（plantuml 暂不渲染）
  let html = doc.value.content
  html = html.replace(/```(?:mermaid|plantuml)\n[\s\S]*?```/g, '')

  // 简单 Markdown 处理
  html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>')
  html = html.replace(/^## (.*$)/gm, '<h2>$1</h2>')
  html = html.replace(/^# (.*$)/gm, '<h1>$1</h1>')
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>')
  html = html.replace(/`(.*?)`/g, '<code>$1</code>')
  html = html.replace(/\n/g, '<br>')

  return html
})

// 是否有图表
const hasDiagrams = computed(() => diagramBlocks.value.length > 0)
const diagramLangs = computed(() => [...new Set(diagramBlocks.value.map(b => b.lang))] as DiagramLang[])
const visibleDiagramBlocks = computed(() => diagramBlocks.value.filter(b => b.lang === activeDiagramTab.value))

onMounted(() => {
  loadDoc()
})

// 监听 subDocId 变化，切换 tab 时重新加载数据
watch(() => props.subDocId, () => {
  loadDoc()
})
</script>

<template>
  <div class="subdoc-viewer">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <span class="text-muted">{{ t('common.loading') }}</span>
    </div>

    <!-- 工具栏 -->
    <div v-else class="subdoc-toolbar">
      <div class="toolbar-left">
        <button class="btn btn-ghost btn-sm" @click="emit('close')">
          <ArrowLeftIcon class="w-4 h-4" />
          <span>{{ t('report.backToReport') }}</span>
        </button>
        <span class="doc-title">{{ doc?.title }}</span>
      </div>
      <div class="toolbar-right">
        <template v-if="!editing">
          <button class="btn btn-ghost btn-sm" @click="startEdit">
            <PencilIcon class="w-4 h-4" />
            <span>{{ t('common.edit') }}</span>
          </button>
        </template>
        <template v-else>
          <button class="btn btn-ghost btn-sm" @click="cancelEdit">
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn btn-primary btn-sm"
            @click="saveEdit"
            :disabled="saving"
          >
            <DocumentArrowDownIcon class="w-4 h-4" />
            <span>{{ saving ? t('common.saving') : t('common.save') }}</span>
          </button>
        </template>
      </div>
    </div>

    <!-- 预览模式 -->
    <div v-if="!editing && doc" class="subdoc-preview">
      <div class="doc-meta">
        <span>{{ t('common.created') }}: {{ doc.createdAt }}</span>
        <span v-if="doc.updatedAt">{{ t('common.updated') }}: {{ doc.updatedAt }}</span>
      </div>
      <div class="doc-content" v-html="renderedContent"></div>

      <!-- 结构图渲染区 -->
      <div v-if="hasDiagrams" class="diagram-section">
        <div class="diagram-tabs">
          <button
            v-for="lang in diagramLangs"
            :key="lang"
            :class="['diagram-tab', { active: activeDiagramTab === lang }]"
            @click="activeDiagramTab = lang"
          >{{ lang === 'mermaid' ? 'Mermaid' : 'PlantUML' }}</button>
        </div>
        <div
          v-for="block in visibleDiagramBlocks"
          :key="block.id"
          class="diagram-block"
        >
          <div v-if="block.loading" class="diagram-loading">{{ t('report.mermaidRendering') }}</div>
          <div v-else-if="block.error" class="diagram-error">
            <div class="error-msg">{{ block.error }}</div>
            <pre class="fallback-code"><code>{{ block.code }}</code></pre>
          </div>
          <div v-else-if="block.svg" class="diagram-svg" v-html="block.svg"></div>
        </div>
      </div>
    </div>

    <!-- 编辑模式 -->
    <div v-if="editing" class="subdoc-edit">
      <input
        v-model="editTitle"
        class="edit-title"
        :placeholder="t('report.docTitlePlaceholder')"
      />
      <textarea
        v-model="editContent"
        class="edit-content"
        :placeholder="t('report.docContentPlaceholder')"
      />
    </div>
  </div>
</template>

<style scoped>
.subdoc-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

.loading-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}

.subdoc-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.doc-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
}

.toolbar-right {
  display: flex;
  gap: 4px;
}

.subdoc-preview {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.doc-meta {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
  font-size: 10px;
  color: var(--text-muted);
}

.doc-content {
  font-size: 13px;
  line-height: 1.8;
  color: var(--text-primary);
}

.doc-content :deep(h1) {
  font-size: 20px;
  font-weight: 700;
  margin: 16px 0 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.doc-content :deep(h2) {
  font-size: 16px;
  font-weight: 600;
  margin: 14px 0 6px;
}

.doc-content :deep(h3) {
  font-size: 14px;
  font-weight: 600;
  margin: 12px 0 4px;
}

.doc-content :deep(code) {
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--bg-tertiary);
  font-family: var(--font-mono);
  font-size: 12px;
}

.doc-content :deep(strong) {
  font-weight: 600;
  color: var(--accent);
}

/* 结构图渲染区 */
.diagram-section {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.diagram-tabs {
  display: flex;
  gap: 0;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.diagram-tab {
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 500;
  border: none;
  background: none;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s;
}

.diagram-tab:hover {
  color: var(--text-primary);
}

.diagram-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.diagram-block {
  margin-bottom: 16px;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-secondary);
}

.diagram-loading {
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}

.diagram-error {
  padding: 16px 20px;
  color: var(--danger);
  font-size: 12px;
  font-family: var(--font-mono);
}

.error-msg {
  margin-bottom: 8px;
  color: var(--danger);
}

.fallback-code {
  margin: 0;
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  overflow-x: auto;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-primary);
}

.diagram-svg {
  padding: 12px;
  display: flex;
  justify-content: center;
}

.diagram-svg :deep(svg) {
  max-width: 100%;
  height: auto;
}

.subdoc-edit {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 12px;
  gap: 8px;
}

.edit-title {
  padding: 6px 10px;
  font-size: 14px;
  font-weight: 500;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  outline: none;
}

.edit-title:focus {
  border-color: var(--accent);
}

.edit-content {
  flex: 1;
  padding: 10px 12px;
  font-size: 12px;
  font-family: var(--font-mono);
  line-height: 1.6;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  outline: none;
  resize: none;
}

.edit-content:focus {
  border-color: var(--accent);
}
</style>
