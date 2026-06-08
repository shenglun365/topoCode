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
import { DocumentArrowDownIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
import { useReportStore } from '@/stores/report-store'
import { useCommunityStore } from '@/stores/community-store'
import { ipc } from '@/services/ipc'
import SubDocToolbar from './SubDocToolbar.vue'
import SubDocRegenDialog from './SubDocRegenDialog.vue'
import SubDocContent from './SubDocContent.vue'
const { showId, componentId } = useComponentId('RP-010')

const reportStore = useReportStore()
const communityStore = useCommunityStore()


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
const saveError = ref('')

async function handleRegenerated(payload: { content: string; mode: 'full' | 'mermaid' | 'plantuml' }) {
  if (!doc.value) return
  if (payload.mode === 'full') {
    if (props.regenerationType === 'community' && props.parentCommId) {
      const name = doc.value.title || props.parentCommId
      doc.value.content = `# 社区: ${name}\n\n**ID**: ${props.parentCommId}\n\n${payload.content}`
    } else {
      doc.value.content = payload.content
    }
  } else {
    const lang = payload.mode
    const existing = payload.mode === 'mermaid' ? existingMermaid.value : existingPlantuml.value
    if (existing) {
      const oldBlock = '```' + lang + '\n' + existing + '\n```'
      const newBlock = '```' + lang + '\n' + payload.content + '\n```'
      doc.value.content = doc.value.content.replace(oldBlock, newBlock)
    }
  }
  showRegenDialog.value = false
  saveError.value = ''
  if (!props.taskId || !props.projectId) {
    saveError.value = t('report.saveFailedNoProject')
    return
  }
  try {
    if (props.regenerationType === 'overall') {
      let finalContent = doc.value.content
      if (props.taskId) {
        const communities = communityStore.tasks[props.taskId]?.communities || []
        const hasAppendix = finalContent.includes('## 组件附录')
        if (!hasAppendix && communities.some(c => c.level === 'L0')) {
          const appendixParts = ['', '---', '', '## 组件附录', '', '| 类型 | 名称 |', '|------|------|']
          for (const et of ([{ key: 'CALL' as const, label: '调用' }, { key: 'INCLUDE' as const, label: '依赖' }])) {
            for (const item of communities.filter(c => c.level === 'L0' && c.edgeType === et.key)) {
              const name = (item.name || item.communityId).replace(/\|/g, '\\|').replace(/\n/g, ' ')
              appendixParts.push(`| ${et.label} | [${name}](##community:${et.key}:${item.communityId}) |`)
            }
          }
          appendixParts.push('')
          finalContent += appendixParts.join('\n')
        }
      }
      await ipc.report.saveOverallDoc({
        taskId: props.taskId,
        title: doc.value.title || t('report.pipeline.overallArchitecture'),
        content: finalContent,
      })
      doc.value.content = finalContent
    } else if (props.regenerationType === 'community') {
      if (doc.value.id) {
        await ipc.report.updateSubDoc({ subDocId: doc.value.id, content: doc.value.content })
      }
      if (props.parentCommId && props.parentLevel && props.parentEdgeType) {
        const current =
          await window.api?.analysis.getCommunityResult({
            taskId: props.taskId, edgeType: props.parentEdgeType,
            commLv: props.parentLevel, commId: props.parentCommId,
          }).catch(() => null)
        await communityStore.saveCommunityResult({
          taskId: props.taskId, edgeType: props.parentEdgeType,
          commLv: props.parentLevel, commId: props.parentCommId,
          name: current?.name || props.parentCommId,
          summary: payload.mode === 'full' ? payload.content : (current?.summary || ''),
          mermaid: payload.mode === 'mermaid' ? payload.content : (current?.mermaid || ''),
          plantuml: payload.mode === 'plantuml' ? payload.content : (current?.plantuml || ''),
          modelId: current?.model_id,
          templateId: current?.template_id || 'community_analyze',
        })
      }
    }
  } catch (e: any) {
    saveError.value = `${t('report.saveFailed')}: ${e.message || String(e)}`
  }
}

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

// 加载文档
async function loadDoc() {
  loading.value = true
  try {
    if (props.regenerationType === 'community' && props.taskId && props.parentCommId && props.parentEdgeType && props.parentLevel) {
      const result = await window.api!.analysis.getCommunityResult({
        taskId: props.taskId, edgeType: props.parentEdgeType,
        commLv: props.parentLevel, commId: props.parentCommId,
      }).catch(() => null)
      if (result?.name || result?.summary) {
        const parts: string[] = [
          `# 社区: ${result.name || props.parentCommId}`, '',
          `**ID**: ${props.parentCommId}`, '',
          result.summary || '',
        ]
        if (result.mermaid) parts.push('', '```mermaid', result.mermaid, '```')
        if (result.plantuml) parts.push('', '```plantuml', result.plantuml, '```')
        doc.value = {
          id: '', title: result.name || props.initialTitle || '',
          content: parts.join('\n'), templateId: '', createdAt: '', updatedAt: '',
        }
      }
    }
    if (!doc.value) {
      if (props.subDocId) {
        doc.value = await reportStore.getSubDoc(props.subDocId)
      } else if (props.initialContent) {
        doc.value = {
          id: '', title: props.initialTitle || '',
          content: props.initialContent, templateId: '', createdAt: '', updatedAt: '',
        }
      }
    }
  } catch (e) {
    console.error('[SubDocViewer] Failed to load doc:', e)
  } finally {
    loading.value = false
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
      docId = (result as any).id || (result as any).subDocId
      if (docId) doc.value.id = docId
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
  window.api!.shell.openExternal(url)
    .then(() => console.log('[SubDocViewer] openExternal success'))
    .catch((err: any) => console.error('[SubDocViewer] openExternal error:', err))
}


onMounted(async () => {
  loadDoc()
  try {
    httpPort.value = await window.api!.system.getHttpPort()
  } catch (e) {
    // 默认 3456
  }
})

watch(() => props.subDocId, () => {
  loadDoc()
})

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

    <SubDocToolbar
      v-else
      :title="doc?.title || ''"
      :can-open-in-browser="canOpenInBrowser"
      :can-regenerate="canRegenerate"
      @close="emit('close')"
      @refresh="loadDoc"
      @open-browser="openInBrowser"
      @open-regen-dialog="showRegenDialog = true"
    />

    <!-- 保存错误提示 -->
    <div
      v-if="saveError"
      class="save-error-banner"
    >
      {{ saveError }}
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
      <SubDocContent
        v-if="doc"
        :content="doc.content"
        :task-id="taskId"
        :project-id="projectId"
        :parent-level="parentLevel"
        :parent-comm-id="parentCommId"
        :parent-edge-type="parentEdgeType"
        @navigate-community="(p: any) => emit('navigate-community', p)"
        @open-child-analysis="(p: any) => emit('open-child-analysis', p)"
        @view-child-md="(p: any) => emit('view-child-md', p)"
      />

    </div>

    <SubDocRegenDialog
      :visible="showRegenDialog"
      :regeneration-type="regenerationType || 'community'"
      :task-id="taskId || ''"
      :project-id="projectId || ''"
      :existing-mermaid="existingMermaid"
      :existing-plantuml="existingPlantuml"
      :parent-comm-id="parentCommId"
      :parent-level="parentLevel"
      :parent-edge-type="parentEdgeType"
      @close="showRegenDialog = false"
      @regenerated="handleRegenerated"
    />
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

.save-error-banner {
  margin: 8px 12px;
  padding: 8px 12px;
  background: color-mix(in srgb, var(--error) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--error) 30%, transparent);
  border-radius: 6px;
  color: var(--error);
  font-size: 12px;
}
</style>
