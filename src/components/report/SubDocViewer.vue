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
  ArrowPathIcon,
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
const regenMode = ref<'full' | 'mermaid' | 'plantuml'>('full')
const regenSubMode = ref<'ai' | 'manual'>('ai')
const regenPrompt = ref('')
const regenManualCode = ref('')
const regenLoading = ref(false)
const regenError = ref('')

const canRegenerate = computed(() => !!props.regenerationType && !!props.taskId && !!props.projectId)

const existingMermaid = computed(() => {
  if (!doc.value?.content) return ''
  const m = doc.value.content.match(/```mermaid\n([\s\S]*?)```/)
  return m ? m[1].trim() : ''
})

const existingPlantuml = computed(() => {
  if (!doc.value?.content) return ''
  const m = doc.value.content.match(/```plantuml\n([\s\S]*?)```/)
  return m ? m[1].trim() : ''
})

const existingDiagramCode = computed(() => {
  if (regenMode.value === 'mermaid') return existingMermaid.value
  if (regenMode.value === 'plantuml') return existingPlantuml.value
  return ''
})

watch(regenSubMode, (val) => {
  if (val === 'manual' && !regenManualCode.value) {
    regenManualCode.value = existingDiagramCode.value
  }
})

function openRegenDialog(mode?: 'full' | 'mermaid' | 'plantuml') {
  regenMode.value = mode || 'full'
  regenSubMode.value = 'ai'
  regenPrompt.value = ''
  regenManualCode.value = ''
  regenError.value = ''
  showRegenDialog.value = true
}

function closeRegenDialog() {
  showRegenDialog.value = false
  regenLoading.value = false
  regenError.value = ''
}

async function submitRegen() {
  if (!props.taskId || !props.projectId) return
  if (props.regenerationType === 'community' && (!props.parentCommId || !props.parentLevel || !props.parentEdgeType)) {
    regenError.value = 'Missing community context for regeneration'
    return
  }
  regenLoading.value = true
  regenError.value = ''

  try {
    if (regenMode.value === 'mermaid' || regenMode.value === 'plantuml') {
      if (regenSubMode.value === 'manual') {
        // 手动输入模式：直接保存用户填入的代码
        if (!regenManualCode.value.trim()) {
          regenError.value = 'Please enter diagram code'
          regenLoading.value = false
          return
        }
        const current = await window.api.analysis.getCommunityResult({
          taskId: props.taskId, edgeType: props.parentEdgeType,
          commLv: props.parentLevel, commId: props.parentCommId,
        }).catch(() => null)
        const code = regenManualCode.value.trim()
        await reportStore.saveCommunityResult({
          taskId: props.taskId, edgeType: props.parentEdgeType,
          commLv: props.parentLevel, commId: props.parentCommId,
          name: current?.name || props.parentCommId,
          summary: current?.summary || '',
          mermaid: regenMode.value === 'mermaid' ? code : (current?.mermaid || ''),
          plantuml: regenMode.value === 'plantuml' ? code : (current?.plantuml || ''),
          modelId: current?.model_id,
          templateId: current?.template_id || 'community_analyze',
        })
        await loadDoc()
        closeRegenDialog()
        return
      }

      if (!props.parentCommId || !props.parentLevel || !props.parentEdgeType || !props.taskId) {
        throw new Error('Missing community context for diagram regeneration')
      }
      const existing = regenMode.value === 'mermaid' ? existingMermaid.value : existingPlantuml.value
      if (!existing) {
        regenError.value = `No existing ${regenMode.value} code found in document`
        regenLoading.value = false
        return
      }
      const result = await reportStore.regenerateCommunityDiagram(
        props.taskId, props.parentCommId, props.parentLevel, props.parentEdgeType,
        props.projectId, existing, regenPrompt.value, regenMode.value,
      )
      if (result.success && result.code) {
        // Replace diagram code in doc content
        if (doc.value) {
          const lang = regenMode.value === 'mermaid' ? 'mermaid' : 'plantuml'
          const oldBlock = `\`\`\`${lang}\n${existing}\`\`\``
          const newBlock = `\`\`\`${lang}\n${result.code}\`\`\``
          doc.value.content = doc.value.content.replace(oldBlock, newBlock)
          diagramBlocks.value = extractDiagrams(doc.value.content)
          await nextTick()
          renderAllDiagrams()
        }
        closeRegenDialog()
      } else {
        regenError.value = result.error || 'Unknown error'
      }
      return
    }

    // Full document regeneration
    let result: { success: boolean; content?: string; error?: string }
    if (props.regenerationType === 'community') {
      result = await reportStore.regenerateCommunityDoc(
        props.taskId, props.parentCommId!, props.parentLevel!, props.parentEdgeType!,
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

const diagramBlocks = ref<DiagramBlock[]>([])

// 主线程直接渲染 mermaid（Worker 中 mermaid v11 无法访问 document）
let mermaidApi: any = null
async function ensureMermaid() {
  if (mermaidApi) return
  try {
    const mod = await import('mermaid')
    mermaidApi = mod.default
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
    console.warn(`[SubDocViewer] injectDiagram: placeholder NOT FOUND id=inline-${block.id}`)
    return
  }
  if (block.svg) {
    el.innerHTML = block.svg
  } else if (block.error) {
    const escapedCode = escapeHtml(block.code)
    const escapedError = escapeHtml(block.error)
    el.innerHTML = `<div class="fallback-diagram">
      <div class="fallback-diagram-header">
        <span class="fallback-diagram-lang">${escapeHtml(block.lang.toUpperCase())}</span>
        <button class="fallback-diagram-copy" onclick="navigator.clipboard.writeText(this.parentElement.parentElement.querySelector('code').textContent)">📋 复制代码</button>
      </div>
      <pre class="fallback-code"><code>${escapedCode}</code></pre>
      <div class="diagram-error">${escapedError}</div>
    </div>`
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
  if (diagramBlocks.value.length === 0) return

  for (const block of diagramBlocks.value) {
    block.loading = true
    block.error = undefined
    const cleaned = normalizeDiagramCode(block.lang, block.code)
    try {
      let svg = ''
      if (block.lang === 'mermaid') {
        await ensureMermaid()
        const id = `sd-${block.id}`
        const result = await mermaidApi.render(id, cleaned)
        svg = result.svg
      } else {
        const result = await window.api.render.renderPlantuml({ code: cleaned, format: 'svg' })
        svg = atob(result.data)
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
    // 社区文档：从 DB 重新读取 LLM 结果并构建内容
    if (props.regenerationType === 'community' && props.taskId && props.parentCommId && props.parentEdgeType && props.parentLevel) {
      const result = await window.api.analysis.getCommunityResult({
        taskId: props.taskId,
        edgeType: props.parentEdgeType,
        commLv: props.parentLevel,
        commId: props.parentCommId,
      }).catch(() => null)
      if (result?.name || result?.summary) {
        const parts: string[] = [
          `# 社区: ${result.name || props.parentCommId}`,
          '',
          `**ID**: ${props.parentCommId}`,
          '',
          result.summary || '',
        ]
        if (result.mermaid) parts.push('', '```mermaid', result.mermaid, '```')
        if (result.plantuml) parts.push('', '```plantuml', result.plantuml, '```')
        doc.value = {
          id: '', title: result.name || props.initialTitle || '',
          content: parts.join('\n'),
          templateId: '', createdAt: '', updatedAt: '',
        }
      }
    }
    if (!doc.value) {
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
          @click="loadDoc"
        >
          <ArrowPathIcon class="w-3.5 h-3.5" />
          <span>{{ t('common.refresh') }}</span>
        </button>
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
          @click="openRegenDialog()"
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
        @viewCommunityMD="(p: any) => emit('view-child-md', { ...p, taskId: props.taskId || '' })"
      />

    </div>

    <!-- 重新生成对话框 -->
    <Teleport to="body">
      <div
        v-if="showRegenDialog"
        class="regen-overlay"
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
            <div class="regen-mode-selector">
              <label
                :class="['regen-mode-option', { active: regenMode === 'full' }]"
                @click="regenMode = 'full'"
              >
                <input type="radio" name="regenMode" value="full" v-model="regenMode">
                <span class="regen-mode-label">{{ t('report.regenModeFull') }}</span>
              </label>
              <label
                v-if="existingMermaid"
                :class="['regen-mode-option', { active: regenMode === 'mermaid' }]"
                @click="regenMode = 'mermaid'"
              >
                <input type="radio" name="regenMode" value="mermaid" v-model="regenMode">
                <span class="regen-mode-label">Mermaid</span>
              </label>
              <label
                v-if="existingPlantuml"
                :class="['regen-mode-option', { active: regenMode === 'plantuml' }]"
                @click="regenMode = 'plantuml'"
              >
                <input type="radio" name="regenMode" value="plantuml" v-model="regenMode">
                <span class="regen-mode-label">PlantUML</span>
              </label>
            </div>
            <template v-if="regenMode !== 'full'">
              <div class="regen-submode-toggle">
                <button
                  :class="['regen-submode-btn', { active: regenSubMode === 'ai' }]"
                  :disabled="regenLoading"
                  @click="regenSubMode = 'ai'"
                >AI {{ t('report.regenerate') }}</button>
                <button
                  :class="['regen-submode-btn', { active: regenSubMode === 'manual' }]"
                  :disabled="regenLoading"
                  @click="regenSubMode = 'manual'"
                >{{ t('common.manual') }}</button>
              </div>
            </template>
            <template v-if="regenSubMode === 'manual' && regenMode !== 'full'">
              <label class="regen-label">{{ regenMode === 'mermaid' ? 'Mermaid' : 'PlantUML' }} {{ t('report.regenCodeLabel') }}</label>
              <textarea
                v-model="regenManualCode"
                class="regen-textarea code-input"
                :disabled="regenLoading"
                rows="10"
              />
            </template>
            <template v-else>
              <label class="regen-label">{{ t('report.regenPrompt') }}</label>
              <textarea
                v-model="regenPrompt"
                class="regen-textarea"
                :placeholder="regenMode === 'full' ? t('report.regenPromptPlaceholder') : t('report.regenDiagramPromptPlaceholder')"
                :disabled="regenLoading"
                rows="5"
              />
            </template>
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
              {{ regenSubMode === 'manual' && regenMode !== 'full' ? t('common.save') : (regenMode === 'full' ? t('report.regenerateSubmit') : (regenMode === 'mermaid' ? t('report.regenMermaidSubmit') : t('report.regenPlantumlSubmit'))) }}
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
  padding: 8px 12px;
  border-radius: 0 0 6px 6px;
  background: rgba(var(--danger-rgb, 239, 68, 68), 0.08);
  border-top: 1px solid rgba(var(--danger-rgb, 239, 68, 68), 0.2);
}

.doc-content :deep(.diagram-placeholder .fallback-code) {
  margin: 0;
  padding: 8px 12px;
  background: var(--bg-primary);
  overflow-x: auto;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-primary);
}

.doc-content :deep(.diagram-placeholder .fallback-diagram) {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.doc-content :deep(.diagram-placeholder .fallback-diagram-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  font-size: 11px;
}

.doc-content :deep(.fallback-diagram-lang) {
  font-weight: 600;
  color: var(--text-muted);
}

.doc-content :deep(.fallback-diagram-copy) {
  font-size: 11px;
  cursor: pointer;
  color: var(--accent);
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
}

.doc-content :deep(.fallback-diagram-copy:hover) {
  background: var(--bg-hover);
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
.regen-mode-selector {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 8px;
}
.regen-mode-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
  color: var(--text-primary);
  background: var(--bg-primary);
  transition: all 0.15s;
}
.regen-mode-option:hover {
  border-color: var(--accent);
}
.regen-mode-option.active {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.regen-submode-toggle {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}
.regen-submode-btn {
  flex: 1;
  padding: 4px 8px;
  font-size: 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  text-align: center;
}
.regen-submode-btn:hover {
  border-color: var(--accent);
}
.regen-submode-btn.active {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
}
.regen-submode-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.regen-mode-option input[type="radio"] {
  accent-color: var(--accent);
}
.regen-mode-label {
  font-size: 11px;
  font-weight: 500;
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
.regen-textarea.code-input {
  font-size: 11px;
  min-height: 160px;
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
