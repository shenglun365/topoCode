<script setup lang="ts">
/**
 * 子文档查看器
 *
 * 默认 Markdown 预览模式, 支持切换到编辑模式.
 * 保存后回到预览模式.
 * 自动提取并渲染 ```mermaid / ```plantuml 代码块.
 */

import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentArrowDownIcon,
  ArrowLeftIcon,
  GlobeAltIcon,
  SparklesIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
import { useReportStore } from '@/stores/report'
import ChildSection from '@/components/report/ChildSection.vue'
const { showId, componentId } = useComponentId('RP-010')

const reportStore = useReportStore()


const { t } = useI18n()

const props = defineProps<{
  subDocId?: string
  initialContent?: string
  initialTitle?: string
  taskId?: string
  parentLevel?: string
  parentCommId?: string
  parentEdgeType?: string
  projectId?: string
  regenerationType?: 'community' | 'overall'
}>()

const emit = defineEmits<{
  'close': []
  'navigate-community': [payload: { taskId: string; communityId: string; edgeType: string }]
  'open-child-analysis': [payload: { taskId: string; parentLevel: string; parentCommId: string; edgeType: string; projectId?: string }]
  'view-child-md': [payload: { taskId: string; communityId: string; level: string; edgeType: string; parentLevel: string; parentCommId: string; name: string; summary: string; mermaid?: string; plantuml?: string }]
}>()

// 状态
const loading = ref(true)
const doc = ref<{
  id: string
  title: string
  content: string
  templateId: string
  createdAt: string
  updatedAt: string
} | null>(null)
const httpPort = ref(3456)

// 重新生成
const showRegenDialog = ref(false)
const regenPrompt = ref('')
const regenLoading = ref(false)
const regenError = ref('')

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

// 主线程直接渲染 mermaid（Worker 中 mermaid v11 无法访问 document）
let mermaidApi: any = null
async function ensureMermaid() {
  if (mermaidApi) return
  console.log('[SubDocViewer] ensureMermaid importing...')
  try {
    const mod = await import('mermaid')
    mermaidApi = mod.default
    console.log('[SubDocViewer] ensureMermaid import OK, has render:', typeof mermaidApi?.render, 'has initialize:', typeof mermaidApi?.initialize)
    mermaidApi.initialize({
      startOnLoad: false,
      securityLevel: 'loose',
      theme: 'dark',
      fontFamily: 'var(--font-sans)',
    })
  } catch (e) {
    console.error('[SubDocViewer] ensureMermaid FAILED:', e)
    throw e
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function injectDiagram(block: DiagramBlock) {
  const el = document.getElementById(`inline-${block.id}`)
  if (!el) {
    console.warn(`[SubDocViewer] injectDiagram: placeholder NOT FOUND for id=inline-${block.id}. DOM ready?`, !!document.getElementById(`inline-${block.id}`))
    return
  }
  if (block.svg) {
    el.innerHTML = block.svg
    console.log(`[SubDocViewer] injectDiagram OK id=${block.id} svgLen=${block.svg.length}`)
  } else if (block.error) {
    el.innerHTML = `<div class="diagram-error">${escapeHtml(block.error)}</div><pre class="fallback-code"><code>${escapeHtml(block.code)}</code></pre>`
    console.log(`[SubDocViewer] injectDiagram ERROR id=${block.id}`)
  }
}

/**
 * 标准化 LLM 生成的图表代码，统一规则应用于应用内预览与 web 浏览。
 * 规则与 backend/plantuml_service.py _sanitize_mermaid / render_plantuml 保持一致。
 */
function normalizeDiagramCode(lang: string, code: string): string {
  if (lang === 'mermaid') {
    // 1. Call_0 [Label] → Call_0[Label]（节点 ID 后误加空格）
    code = code.replace(/\b([A-Za-z_]\w*)\s+\[/g, '$1[')
    // 2. subgraph Name [Label] → subgraph Name[Label]
    code = code.replace(/(\bsubgraph\s+\w+(?:\.\w+)*)\s+(\[)/g, '$1$2')
    // 3. 删除节点标签内嵌套括号: A[ip.h (path.c)] → A[ip.h path.c]
    code = code.replace(/\[([^\]\[]*?)\(([^()]*)\)([^\]\[]*?)\]/g, '[$1$2$3]')
    // 4. 剥离 style 指令行（graph TD 不支持）
    code = code.replace(/^\s*style\s+.*$/gm, '')
    // 5. 节点括号内残留 <br> 标签（LLM 有时混入 HTML）
    code = code.replace(/<br\s*\/?>/gi, ' ')
    // 6. 剥离 Mermaid 特有语法: A[Label]:::className → A[Label]（PlantUML 中非法）
    code = code.replace(/:::\w+/g, '')
    // 7. 行尾多余空格: "subgraph ID[Label] \n" → "subgraph ID[Label]\n"（否则 Mermaid 误将空格当下一个 token）
    code = code.replace(/[ \t]+$/gm, '')
    return code
  }
  if (lang === 'plantuml') {
    // PlantUML 走后端 plantuml_service.py 完整链路（encode_plantuml → _sanitize_plantuml）
    // 前端仅做空白符清理
    return code
  }
  return code
}

async function renderAllDiagrams() {
  if (diagramBlocks.value.length === 0) {
    console.log('[SubDocViewer] renderAllDiagrams: no diagram blocks to render')
    return
  }
  console.log(`[SubDocViewer] renderAllDiagrams START count=${diagramBlocks.value.length}`)

  for (const block of diagramBlocks.value) {
    block.loading = true
    block.error = undefined
    const cleaned = normalizeDiagramCode(block.lang, block.code)
    console.log(`[SubDocViewer] rendering ${block.lang} id=${block.id} codeLen=${block.code.length}`)
    try {
      let svg = ''
      if (block.lang === 'mermaid') {
        console.time(`mermaid-${block.id}`)
        await ensureMermaid()
        const id = `sd-${block.id}`
        const result = await mermaidApi.render(id, cleaned)
        svg = result.svg
        console.timeEnd(`mermaid-${block.id}`)
        console.log(`[SubDocViewer] mermaid render OK id=${block.id} svgLen=${svg.length}`)
      } else {
        console.time(`plantuml-${block.id}`)
        const result = await window.api.render.renderPlantuml({ code: cleaned, format: 'svg' })
        svg = atob(result.data)
        console.timeEnd(`plantuml-${block.id}`)
        console.log(`[SubDocViewer] plantuml render OK id=${block.id} svgLen=${svg.length}`)
      }
      block.svg = svg
      injectDiagram(block)
    } catch (e: any) {
      block.error = e.message || 'Render failed'
      console.error(`[SubDocViewer] ${block.lang} render ERROR id=${block.id}:`, e.message)
      injectDiagram(block)
    } finally {
      block.loading = false
    }
  }
  console.log(`[SubDocViewer] renderAllDiagrams DONE`)
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
  console.log(`[SubDocViewer] extractDiagrams found ${blocks.length} diagrams in ${content.length} chars of content`)
  return blocks
}

// 加载文档
async function loadDoc() {
  loading.value = true
  try {
    if (props.subDocId) {
      doc.value = await reportStore.getSubDoc(props.subDocId)
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
const canOpenInBrowser = computed(() => !!(doc.value?.id || props.subDocId || (doc.value?.content && props.taskId)))

const canRegenerate = computed(() => !!props.regenerationType && !!props.taskId && !!props.projectId)

function openRegenDialog() {
  regenPrompt.value = ''
  regenError.value = ''
  showRegenDialog.value = true
}

function closeRegenDialog() {
  showRegenDialog.value = false
  regenLoading.value = false
  regenError.value = ''
}

async function submitRegen() {
  if (!props.taskId || !props.projectId || !props.regenerationType) return
  regenLoading.value = true
  regenError.value = ''

  try {
    let result: { success: boolean; content?: string; error?: string }
    if (props.regenerationType === 'community') {
      if (!props.parentCommId || !props.parentLevel || !props.parentEdgeType) {
        throw new Error('Missing community context for regeneration')
      }
      result = await reportStore.regenerateCommunityDoc(
        props.taskId, props.parentCommId, props.parentLevel, props.parentEdgeType,
        props.projectId, regenPrompt.value,
      )
    } else {
      result = await reportStore.regenerateOverallDoc(
        props.taskId, props.projectId, regenPrompt.value,
      )
    }

    if (result.success && result.content) {
      if (doc.value) {
        doc.value.content = result.content
        diagramBlocks.value = extractDiagrams(result.content)
        await nextTick()
        renderAllDiagrams()
      }
      closeRegenDialog()
    } else {
      regenError.value = result.error || 'Unknown error'
    }
  } catch (e: any) {
    regenError.value = e.message || String(e)
  } finally {
    regenLoading.value = false
  }
}

async function openInBrowser() {
  console.log('[SubDocViewer] openInBrowser clicked, subDocId prop:', props.subDocId, 'doc.id:', doc.value?.id, 'httpPort:', httpPort.value, 'taskId:', props.taskId)
  let docId = doc.value?.id || props.subDocId
  if (!docId && doc.value?.content && props.taskId) {
    console.log('[SubDocViewer] no docId, creating subdoc first')
    try {
      const result = await reportStore.createSubDoc({
        taskId: props.taskId,
        title: doc.value.title || props.initialTitle || '',
        content: doc.value.content,
      })
      docId = result.id || result.subDocId
      doc.value.id = docId
      console.log('[SubDocViewer] subdoc created, id:', docId)
    } catch (e: any) {
      console.error('[SubDocViewer] failed to create subdoc:', e)
      return
    }
  }
  if (!docId) {
    console.warn('[SubDocViewer] openInBrowser aborted: no docId available')
    return
  }
  const url = `http://127.0.0.1:${httpPort.value}/doc?docId=${docId}`
  console.log('[SubDocViewer] openInBrowser url:', url)
  window.api.shell.openExternal(url)
    .then(() => console.log('[SubDocViewer] openExternal success'))
    .catch((err: any) => console.error('[SubDocViewer] openExternal error:', err))
}

// 渲染 Markdown (简单处理, 实际项目可用 marked)
const renderedContent = computed(() => {
  if (!doc.value) return ''
  // 图表块替换为占位容器（内联渲染）
  let html = doc.value.content
  let diagIdx = 0
  let placeholderCount = 0
  html = html.replace(/```(mermaid|plantuml)\n([\s\S]*?)```/g, (match, lang) => {
    const blk = diagramBlocks.value[diagIdx]
    const id = blk ? blk.id : `diagram-${diagIdx}`
    diagIdx++
    placeholderCount++
    return `<div class="diagram-placeholder" id="inline-${id}" data-lang="${lang}"><div class="diagram-loading">${lang === 'mermaid' ? 'Mermaid' : 'PlantUML'} 渲染中...</div></div>`
  })
  if (placeholderCount > 0) console.log(`[SubDocViewer] renderedContent created ${placeholderCount} placeholders (diagramBlocks=${diagramBlocks.value.length})`)

  // GFM 表格支持（兼容缩进表格）
  html = html.replace(/^\s*\|(.+)\|\n\s*\|[-:| ]+\|\n((?:\s*\|.+\|\n?)*)/gm, (match, headerRow, bodyRows) => {
    const headers = headerRow.split('|').map((h: string) => h.trim()).filter((h: string) => h)
    const rows = bodyRows.trim().split('\n').map((row: string) => {
      const cells = row.split('|').map((c: string) => c.trim()).filter((c: string) => c)
      return `<tr>${cells.map((c: string) => `<td>${c}</td>`).join('')}</tr>`
    })
    return `<table><thead><tr>${headers.map((h: string) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`
  })

  // 组件导航链接: [text](##community:edgeType:communityId)
  html = html.replace(/\[([^\]]+)\]\(##community:([^:]+):([^)]+)\)/g, '<a href="#" class="community-link" data-edge-type="$2" data-community-id="$3">$1</a>')

  // 从文档中提取 TOC 锚点映射：[链接文本] → 锚点 ID
  const tocAnchorMap = new Map<string, string>()
  html.replace(/\[([^\]]+)\]\(#([^)]+)\)/g, (_m: string, text: string, id: string) => {
    tocAnchorMap.set(text.trim(), id)
    return _m
  })

  // 根据 TOC 链接文本为标题查找匹配的锚点 ID
  function findAnchor(headingText: string): string | undefined {
    // 优先精确匹配
    if (tocAnchorMap.has(headingText)) return tocAnchorMap.get(headingText)
    // 按括号内社区 ID 匹配（如 comm-bea7b173-call-L0-0000）
    const commMatch = headingText.match(/\(([^)]+)\)$/)
    if (commMatch) {
      const commId = commMatch[1].toLowerCase()
      for (const [tocText, anchorId] of tocAnchorMap) {
        if (tocText.toLowerCase().includes(commId)) return anchorId
      }
    }
    return undefined
  }

  html = html.replace(/^### (.*$)/gm, (_m: string, t: string) => {
    const id = findAnchor(t) || ''
    return id ? `<h3 id="${id}">${t}</h3>` : `<h3>${t}</h3>`
  })
  html = html.replace(/^## (.*$)/gm, (_m: string, t: string) => {
    const id = findAnchor(t) || ''
    return id ? `<h2 id="${id}">${t}</h2>` : `<h2>${t}</h2>`
  })
  html = html.replace(/^# (.*$)/gm, (_m: string, t: string) => {
    const id = findAnchor(t) || ''
    return id ? `<h1 id="${id}">${t}</h1>` : `<h1>${t}</h1>`
  })
  html = html.replace(/^---+\s*$/gm, '<hr>')
  html = html.replace(/^\*\s+/gm, '• ')
  html = html.replace(/^\-\s+/gm, '• ')
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>')
  html = html.replace(/`(.*?)`/g, '<code>$1</code>')
  html = html.replace(/\n/g, '<br>')

  return html
})

function onDocContentClick(e: MouseEvent) {
  const link = (e.target as HTMLElement)?.closest?.('.community-link') as HTMLElement | null
  if (!link || !props.taskId) return
  const communityId = link.dataset.communityId
  const edgeType = link.dataset.edgeType
  if (communityId && edgeType) {
    emit('navigate-community', { taskId: props.taskId, communityId, edgeType })
  }
}

// 是否有图表
const hasDiagrams = computed(() => diagramBlocks.value.length > 0)

// 哈希滚动画板：当 TOC 锚点 ID 不在 DOM 中时，按标题文本模糊查找
function scrollToHash(targetId: string) {
  const el = document.getElementById(targetId)
  if (el) { el.scrollIntoView(); return }
  // fallback: 用目标 ID 做分隔符匹配标题文本
  const targetStr = targetId.replace(/[-]+/g, ' ').toLowerCase()
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(h => {
    const slug = h.textContent!.trim().toLowerCase().replace(/[^\w\u4e00-\u9fff]+/g, ' ')
    if (slug === targetStr) {
      h.scrollIntoView()
    }
  })
}

onMounted(async () => {
  loadDoc()
  try {
    httpPort.value = await window.api.system.getHttpPort()
  } catch (e) {
    // 默认 3456
  }
})

// 监听 subDocId 变化，切换 tab 时重新加载数据
watch(() => props.subDocId, () => {
  loadDoc()
})

// TOC 锚点回退：文档加载后如果哈希未匹配，尝试文本匹配
watch(loading, (v) => {
  if (!v && location.hash) {
    nextTick(() => scrollToHash(decodeURIComponent(location.hash.slice(1))))
  }
})

// 监听 hashchange，拦截用户点击 TOC 链接
function onHashChange() {
  if (location.hash) {
    scrollToHash(decodeURIComponent(location.hash.slice(1)))
  }
}
onMounted(() => window.addEventListener('hashchange', onHashChange))
onUnmounted(() => window.removeEventListener('hashchange', onHashChange))
</script>

<template>
  <div class="subdoc-viewer">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 加载状态 -->
    <div
      v-if="loading"
      class="loading-state"
    >
      <span class="text-muted">{{ t('common.loading') }}</span>
    </div>

    <!-- 工具栏 -->
    <div
      v-else
      class="subdoc-toolbar"
    >
      <div class="toolbar-left">
        <button
          class="btn btn-ghost btn-sm"
          @click="emit('close')"
        >
          <ArrowLeftIcon class="w-4 h-4" />
          <span>{{ t('report.backToReport') }}</span>
        </button>
        <span class="doc-title">{{ doc?.title }}</span>
      </div>
      <div class="toolbar-right">
        <button
          class="btn btn-ghost btn-sm"
          @click="openInBrowser"
        >
          <GlobeAltIcon class="w-4 h-4" />
          <span>{{ t('settings.openInBrowser') }}</span>
        </button>
        <button
          v-if="canRegenerate"
          class="btn btn-ghost btn-sm"
          @click="openRegenDialog"
        >
          <SparklesIcon class="w-3.5 h-3.5" />
          <span>{{ t('report.regenerate') }}</span>
        </button>
      </div>
    </div>

    <!-- 预览模式 -->
    <div
      v-if="doc"
      class="subdoc-preview"
    >
      <div class="doc-meta">
        <span>{{ t('common.created') }}: {{ doc.createdAt }}</span>
        <span v-if="doc.updatedAt">{{ t('common.updated') }}: {{ doc.updatedAt }}</span>
      </div>
      <div
        class="doc-content"
        v-html="renderedContent"
        @click.prevent="onDocContentClick"
      />

      <ChildSection
        v-if="props.parentLevel && props.parentCommId && props.parentEdgeType"
        :task-id="props.taskId || ''"
        :parent-level="props.parentLevel"
        :parent-comm-id="props.parentCommId"
        :edge-type="props.parentEdgeType"
        :project-id="props.projectId"
        @open-child-analysis="(p: any) => emit('open-child-analysis', p)"
        @viewCommunityMD="(p: any) => { console.log('[SubDocViewer] ChildSection viewCommunityMD received', p); emit('view-child-md', { ...p, taskId: props.taskId || '' }) }"
      />

    </div>

    <!-- 重新生成对话框 -->
    <Teleport to="body">
      <div
        v-if="showRegenDialog"
        class="regen-overlay"
        @click.self="!regenLoading && closeRegenDialog()"
      >
        <div class="regen-dialog">
          <div class="regen-dialog-header">
            <span class="regen-dialog-title">{{ t('report.regenerate') }}</span>
            <button
              class="btn btn-ghost btn-xs"
              :disabled="regenLoading"
              @click="closeRegenDialog"
            >
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div class="regen-dialog-body">
            <label class="regen-label">{{ t('report.regenPrompt') }}</label>
            <textarea
              v-model="regenPrompt"
              class="regen-textarea"
              :placeholder="t('report.regenPromptPlaceholder')"
              :disabled="regenLoading"
              rows="5"
            />
            <div
              v-if="regenError"
              class="regen-error"
            >
              <span class="regen-error-text">{{ regenError }}</span>
            </div>
          </div>
          <div class="regen-dialog-footer">
            <button
              class="btn btn-ghost btn-sm"
              :disabled="regenLoading"
              @click="closeRegenDialog"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              v-if="!regenLoading"
              class="btn btn-primary btn-sm"
              @click="submitRegen"
            >
              <SparklesIcon class="w-3.5 h-3.5" />
              {{ t('report.regenerateSubmit') }}
            </button>
            <template v-else>
              <span class="regen-loading-text">{{ t('common.processing') }}...</span>
            </template>
          </div>
        </div>
      </div>
    </Teleport>
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

/* 内联图占位容器 */
.doc-content :deep(.diagram-placeholder) {
  min-height: 60px;
  margin: 12px 0;
  background: var(--bg-tertiary);
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.doc-content :deep(.diagram-placeholder .diagram-loading) {
  color: var(--text-muted);
  font-size: 12px;
}

.doc-content :deep(.diagram-placeholder .diagram-error) {
  color: var(--danger);
  font-size: 12px;
  font-family: var(--font-mono);
}

.doc-content :deep(.diagram-placeholder .fallback-code) {
  margin: 8px 0 0;
  padding: 8px 12px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow-x: auto;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-primary);
}

.doc-content :deep(.diagram-placeholder svg) {
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

/* 重新生成对话框 */
.regen-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
}
.regen-dialog {
  width: 480px;
  max-width: 90vw;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
  display: flex;
  flex-direction: column;
}
.regen-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}
.regen-dialog-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.regen-dialog-body {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.regen-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
}
.regen-textarea {
  width: 100%;
  padding: 8px 10px;
  font-size: 12px;
  font-family: var(--font-mono);
  line-height: 1.5;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  outline: none;
  resize: vertical;
  box-sizing: border-box;
  min-height: 80px;
}
.regen-textarea:focus {
  border-color: var(--accent);
}
.regen-error {
  padding: 6px 10px;
  background: color-mix(in srgb, var(--error) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--error) 30%, transparent);
  border-radius: 4px;
}
.regen-error-text {
  font-size: 11px;
  color: var(--error);
}
.regen-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--border);
}
.regen-loading-text {
  font-size: 11px;
  color: var(--text-muted);
}

/* 表格样式 */
.doc-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 12px;
}

.doc-content :deep(th),
.doc-content :deep(td) {
  border: 1px solid var(--border);
  padding: 6px 10px;
  text-align: left;
}

.doc-content :deep(th) {
  background: var(--bg-tertiary);
  font-weight: 600;
  white-space: nowrap;
}

.doc-content :deep(td) {
  vertical-align: top;
}
</style>
