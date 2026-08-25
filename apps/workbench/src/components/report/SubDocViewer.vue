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
import { useComponentId } from '@topo/web-core/composables/useComponentId'
import { useReportStore } from '@/stores/report-store'
import { useCommunityStore } from '@/stores/community-store'
import { ipc } from '@topo/web-core/services/ipc'
import { communityLabel } from '@/utils/communityLabel'
import SubDocToolbar from './SubDocToolbar.vue'
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
}>()

const emit = defineEmits<{
  'close': []
  'navigate-community': [payload: { taskId: string; communityId: string; edgeType: string }]
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

// 编辑模式
const isEditing = ref(false)
const editContent = ref('')
const saveError = ref('')
const isSaving = ref(false)

function startEdit() {
  if (!doc.value) return
  editContent.value = doc.value.content
  isEditing.value = true
}

async function saveEdit() {
  if (!doc.value || !props.taskId || !props.projectId) return
  isSaving.value = true
  saveError.value = ''
  try {
    doc.value.content = editContent.value
    if (doc.value.id) {
      await ipc.report.updateSubDoc({ subDocId: doc.value.id, content: doc.value.content })
    }
    if (props.parentCommId && props.parentLevel && props.parentEdgeType) {
      await communityStore.saveCommunityResult({
        taskId: props.taskId, edgeType: props.parentEdgeType,
        commLv: props.parentLevel, commId: props.parentCommId,
        name: doc.value.title || props.parentCommId,
        summary: doc.value.content,
        modelId: '',
        templateId: 'community_analyze',
      })
    } else {
      await ipc.report.saveOverallDoc({
        taskId: props.taskId,
        title: doc.value.title || '',
        content: doc.value.content,
      })
    }
    isEditing.value = false
  } catch (e: any) {
    saveError.value = `${t('report.saveFailed')}: ${e.message || String(e)}`
  } finally {
    isSaving.value = false
  }
}

function cancelEdit() {
  isEditing.value = false
  editContent.value = ''
}

function buildChildList(): string[] {
  if (!props.taskId) return []
  const parts: string[] = []
  const allChildren = communityStore.tasks[props.taskId]?.communities
    ?.filter(c => c.parentId === props.parentCommId) ?? []
  if (allChildren.length === 0) return parts
  parts.push('', '---', '', `## ${t('report.structuralReport')}（${allChildren.length}）`, '')
  const includeChildren = allChildren.filter(c => c.edgeType === 'INCLUDE')
  const callChildren = allChildren.filter(c => c.edgeType === 'CALL')
  if (includeChildren.length > 0) {
    parts.push('', `### ${t('report.edgeType.dependency')}（${includeChildren.length}）`, '')
    for (const c of includeChildren) {
      parts.push(`- [${communityLabel(c)}](##community:${c.edgeType}:${c.communityId})`)
    }
  }
  if (callChildren.length > 0) {
    parts.push('', `### ${t('report.edgeType.call')}（${callChildren.length}）`, '')
    for (const c of callChildren) {
      parts.push(`- [${communityLabel(c)}](##community:${c.edgeType}:${c.communityId})`)
    }
  }
  return parts
}

// 加载文档
async function loadDoc() {
  loading.value = true
  try {
    if (props.parentCommId && props.taskId && props.parentEdgeType && props.parentLevel) {
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

        // L1+ 组件：加载父社区名称
        if (props.parentLevel && props.parentLevel !== 'L0') {
          try {
            // 从 communityStore 查找当前社区的 parentId
            const currentComm = communityStore.tasks[props.taskId]?.communities
              .find(c => c.communityId === props.parentCommId)
            const parentId = currentComm?.parentId
            if (parentId) {
              const parentLv = currentComm?.level
                ? `L${parseInt(currentComm.level[1]) - 1}` : 'L0'
              const pr = await window.api!.analysis.getCommunityResult({
                taskId: props.taskId, edgeType: props.parentEdgeType,
                commLv: parentLv, commId: parentId,
              }).catch(() => null)
              if (pr?.name || pr?.summary) {
                parts.push('', `---`, '',
                  `## 父组件\n${pr.name || parentId} — ${(pr.summary || '').slice(0, 200)}`)
              } else if (parentId) {
                parts.push('', `---`, '', `## 父组件\n${parentId}`)
              }
            }
          } catch (e) { console.warn('[SubDocViewer] parent community error:', e) }
        }

        parts.push(...buildChildList())

        doc.value = {
          id: '', title: result.name || props.initialTitle || '',
          content: parts.join('\n'), templateId: '',
          createdAt: result.created_at || result.updated_at || '',
          updatedAt: result.updated_at || '',
        }
      }
    }
    if (!doc.value) {
      const childMarkdown = buildChildList().join('\n')
      if (props.subDocId) {
        doc.value = await reportStore.getSubDoc(props.subDocId)
        if (doc.value && childMarkdown) {
          doc.value.content += '\n' + childMarkdown
        }
      } else if (props.initialContent) {
        doc.value = {
          id: '', title: props.initialTitle || '',
          content: props.initialContent + (childMarkdown ? '\n' + childMarkdown : ''),
          templateId: '', createdAt: '', updatedAt: '',
        }
      } else if (props.parentCommId) {
        console.log('[SubDocViewer] fallback to hint for', props.parentCommId)
        doc.value = {
          id: '', title: props.parentCommId,
          content: `# ${props.parentCommId}\n\n${t('report.noLlmResultHint')}` + (childMarkdown ? '\n' + childMarkdown : ''),
          templateId: '', createdAt: '', updatedAt: '',
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
  console.log('[SubDocViewer] openInBrowser clicked, subDocId prop:', props.subDocId, 'doc.id:', doc.value?.id, 'parentCommId:', props.parentCommId, 'taskId:', props.taskId)
  const params = new URLSearchParams()
  params.set('taskId', props.taskId || '')
  // 架构分析组件上下文：直接打开 doc viewer 的社区文档页（viewer 中 communityId 优先于 docId）
  if (props.parentCommId) {
    params.set('communityId', props.parentCommId)
    params.set('edgeType', props.parentEdgeType || 'INCLUDE')
  }
  let docId = doc.value?.id || props.subDocId
  if (!docId && !props.parentCommId && doc.value?.content && props.taskId) {
    // 非社区上下文且文档未持久化（内联内容）→ 先存为子文档再打开
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
  if (docId) params.set('docId', docId)
  if (!docId && !props.parentCommId) {
    console.warn('[SubDocViewer] openInBrowser aborted: no docId available')
    return
  }
  // 用当前页面 host（浏览器 LAN 访问时 127.0.0.1 指向的是客户端本机，不是服务器）
  const host = window.location.host || `127.0.0.1:${httpPort.value}`
  const url = `http://${host}/doc?${params.toString()}`
  console.log('[SubDocViewer] openInBrowser url:', url)
  const shellApi = (window as any).api?.shell
  if (shellApi?.openExternal) {
    await shellApi.openExternal(url)
      .then(() => console.log('[SubDocViewer] openExternal success'))
      .catch(() => window.open(url, '_blank', 'noopener'))
  } else {
    // 浏览器环境无 shell API → 新标签页打开
    window.open(url, '_blank', 'noopener')
  }
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

watch(
  () => props.taskId ? communityStore.tasks[props.taskId]?.communities : undefined,
  (newComs, oldComs) => {
    if (newComs !== oldComs && doc.value) loadDoc()
  },
  { deep: true }
)

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
      @close="emit('close')"
      @refresh="loadDoc"
      @open-browser="openInBrowser"
      @edit="startEdit"
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
      v-if="doc && !isEditing"
      class="subdoc-preview"
    >
      <div class="doc-meta">
        <span>{{ t('common.created') }}: {{ doc.createdAt }}</span>
        <span v-if="doc.updatedAt">{{ t('common.updated') }}: {{ doc.updatedAt }}</span>
      </div>
      <SubDocContent
        :content="doc.content"
        :task-id="taskId"
        @navigate-community="(p: any) => emit('navigate-community', p)"
      />
    </div>

    <!-- 编辑模式 -->
    <div
      v-if="doc && isEditing"
      class="subdoc-edit"
    >
      <div class="edit-actions">
        <button
          class="btn btn-primary btn-xs"
          :disabled="isSaving"
          @click="saveEdit"
        >
          {{ isSaving ? t('common.saving') : t('common.save') }}
        </button>
        <button
          class="btn btn-ghost btn-xs"
          :disabled="isSaving"
          @click="cancelEdit"
        >
          {{ t('common.cancel') }}
        </button>
      </div>
      <textarea
        v-model="editContent"
        class="edit-textarea"
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
  padding: calc(6px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
}

.doc-title {
  font-size: calc(12px * var(--ui-scale, 1));
  font-weight: 500;
  color: var(--text-primary);
}

.toolbar-right {
  display: flex;
  gap: calc(4px * var(--ui-scale, 1));
}

.subdoc-preview {
  flex: 1;
  overflow-y: auto;
  padding: calc(16px * var(--ui-scale, 1)) calc(20px * var(--ui-scale, 1));
}

.doc-meta {
  display: flex;
  gap: calc(16px * var(--ui-scale, 1));
  margin-bottom: calc(16px * var(--ui-scale, 1));
  padding-bottom: calc(12px * var(--ui-scale, 1));
  border-bottom: 1px solid var(--border);
  font-size: calc(10px * var(--ui-scale, 1));
  color: var(--text-muted);
}

.doc-content {
  font-size: calc(13px * var(--ui-scale, 1));
  line-height: 1.8;
  color: var(--text-primary);
}

.doc-content :deep(h1) {
  font-size: calc(20px * var(--ui-scale, 1));
  font-weight: 700;
  margin: calc(16px * var(--ui-scale, 1)) 0 calc(8px * var(--ui-scale, 1));
  padding-bottom: calc(8px * var(--ui-scale, 1));
  border-bottom: 1px solid var(--border);
}

.doc-content :deep(h2) {
  font-size: calc(16px * var(--ui-scale, 1));
  font-weight: 600;
  margin: calc(14px * var(--ui-scale, 1)) 0 calc(6px * var(--ui-scale, 1));
}

.doc-content :deep(h3) {
  font-size: calc(14px * var(--ui-scale, 1));
  font-weight: 600;
  margin: calc(12px * var(--ui-scale, 1)) 0 calc(4px * var(--ui-scale, 1));
}

.doc-content :deep(code) {
  padding: 1px calc(4px * var(--ui-scale, 1));
  border-radius: calc(3px * var(--ui-scale, 1));
  background: var(--bg-tertiary);
  font-family: var(--font-mono);
  font-size: calc(12px * var(--ui-scale, 1));
}

.doc-content :deep(strong) {
  font-weight: 600;
  color: var(--accent);
}

/* 内联图占位容器 */
.doc-content :deep(.diagram-placeholder) {
  min-height: calc(60px * var(--ui-scale, 1));
  margin: calc(12px * var(--ui-scale, 1)) 0;
  background: var(--bg-tertiary);
  border-radius: calc(6px * var(--ui-scale, 1));
  display: flex;
  align-items: center;
  justify-content: center;
}

.doc-content :deep(.diagram-placeholder .diagram-loading) {
  color: var(--text-muted);
  font-size: calc(12px * var(--ui-scale, 1));
}

.doc-content :deep(.diagram-placeholder .diagram-error) {
  color: var(--danger);
  font-size: calc(12px * var(--ui-scale, 1));
  font-family: var(--font-mono);
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  border-radius: 0 0 calc(6px * var(--ui-scale, 1)) calc(6px * var(--ui-scale, 1));
  background: rgba(var(--danger-rgb, 239, 68, 68), 0.08);
  border-top: 1px solid rgba(var(--danger-rgb, 239, 68, 68), 0.2);
}

.doc-content :deep(.diagram-placeholder .fallback-code) {
  margin: 0;
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  background: var(--bg-primary);
  overflow-x: auto;
  font-size: calc(11px * var(--ui-scale, 1));
  line-height: 1.5;
  color: var(--text-primary);
}

.doc-content :deep(.diagram-placeholder .fallback-diagram) {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
  overflow: hidden;
}

.doc-content :deep(.diagram-placeholder .fallback-diagram-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(6px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  font-size: calc(11px * var(--ui-scale, 1));
}

.doc-content :deep(.fallback-diagram-lang) {
  font-weight: 600;
  color: var(--text-muted);
}

.doc-content :deep(.fallback-diagram-copy) {
  font-size: calc(11px * var(--ui-scale, 1));
  cursor: pointer;
  color: var(--accent);
  background: none;
  border: 1px solid var(--border);
  border-radius: calc(4px * var(--ui-scale, 1));
  padding: calc(2px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
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
  padding: calc(12px * var(--ui-scale, 1));
  gap: calc(8px * var(--ui-scale, 1));
}

.edit-title {
  padding: calc(6px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
  font-size: calc(14px * var(--ui-scale, 1));
  font-weight: 500;
  border: 1px solid var(--border);
  border-radius: calc(4px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  color: var(--text-primary);
  outline: none;
}

/* 编辑模式 */
.edit-actions {
  display: flex;
  gap: calc(6px * var(--ui-scale, 1));
  padding: calc(4px * var(--ui-scale, 1)) 0;
}
.edit-textarea {
  flex: 1;
  width: 100%;
  padding: calc(10px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  font-family: var(--font-mono);
  line-height: 1.5;
  border: 1px solid var(--border);
  border-radius: calc(4px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  color: var(--text-primary);
  outline: none;
  resize: none;
  box-sizing: border-box;
}

/* 表格样式 */
.doc-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: calc(8px * var(--ui-scale, 1)) 0;
  font-size: calc(12px * var(--ui-scale, 1));
}

.doc-content :deep(th),
.doc-content :deep(td) {
  border: 1px solid var(--border);
  padding: calc(6px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
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
  margin: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  background: color-mix(in srgb, var(--error) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--error) 30%, transparent);
  border-radius: calc(6px * var(--ui-scale, 1));
  color: var(--error);
  font-size: calc(12px * var(--ui-scale, 1));
}
</style>
