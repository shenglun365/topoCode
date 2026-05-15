<script setup lang="ts">
/**
 * 子文档查看器
 *
 * 默认 Markdown 预览模式, 支持切换到编辑模式.
 * 保存后回到预览模式.
 */

import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PencilIcon,
  DocumentArrowDownIcon,
  ArrowLeftIcon,
} from '@heroicons/vue/24/outline'

const { t } = useI18n()

const props = defineProps<{
  subDocId: string
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

// 加载文档
async function loadDoc() {
  loading.value = true
  try {
    doc.value = await window.api.report.getSubDoc(props.subDocId)
    editContent.value = doc.value.content
    editTitle.value = doc.value.title
  } catch (e) {
    console.error('[SubDocViewer] Failed to load doc:', e)
  } finally {
    loading.value = false
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
  let html = doc.value.content

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

onMounted(() => {
  loadDoc()
})
</script>

<template>
  <div class="subdoc-viewer">
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
