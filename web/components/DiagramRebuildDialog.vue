<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  originalCode: string
  rebuiltCode: string
  lang: 'plantuml' | 'mermaid'
}>()

const emit = defineEmits<{
  confirm: [finalCode: string]
  cancel: []
}>()

const editCode = ref('')
const previewSvg = ref('')
const previewError = ref('')
const previewLoading = ref(false)
let previewTimer: any = null

watch(() => props.visible, (v) => {
  if (v) {
    editCode.value = props.rebuiltCode
    renderPreview()
  }
})

function onEdit() {
  clearTimeout(previewTimer)
  previewTimer = setTimeout(renderPreview, 500)
}

async function renderPreview() {
  const code = editCode.value.trim()
  if (!code) return
  previewLoading.value = true
  previewError.value = ''
  previewSvg.value = ''
  try {
    if (props.lang === 'plantuml') {
      const resp = await fetch('/api/plantuml', {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        body: code.replace(/<!--[\s\S]*?-->/g, ''),
      })
      if (!resp.ok) {
        const text = await resp.text()
        throw new Error(text.slice(0, 200) || `HTTP ${resp.status}`)
      }
      previewSvg.value = await resp.text()
    } else {
      const { ensureMermaid, normalizeDiagram } = await import('@web/services/render')
      const mermaidApi = await ensureMermaid()
      const n = normalizeDiagram(code.replace(/<!--[\s\S]*?-->/g, ''), 'mermaid')
      const uid = 'rebuild-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6)
      const result = await mermaidApi.render(uid, n.code)
      previewSvg.value = result.svg
    }
  } catch (e: any) {
    previewError.value = e.message || '渲染失败'
  } finally {
    previewLoading.value = false
  }
}

function onConfirm() {
  emit('confirm', editCode.value)
}

function onCancel() {
  clearTimeout(previewTimer)
  emit('cancel')
}

function onOverlayClick(e: MouseEvent) {
  if ((e.target as HTMLElement).classList.contains('dialog-overlay')) onCancel()
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="dialog-overlay" @click="onOverlayClick">
      <div class="dialog-panel">
        <div class="dialog-header">
          <span class="dialog-title">图重建确认</span>
          <button class="dialog-close" @click="onCancel">&times;</button>
        </div>

        <div class="dialog-body">
          <div class="code-section">
            <div class="code-panel original-panel">
              <div class="code-panel-title">原始代码</div>
              <pre class="code-pre"><code>{{ originalCode }}</code></pre>
            </div>
            <div class="code-panel edit-panel">
              <div class="code-panel-title">重建后代码 <span class="editable-badge">可编辑</span></div>
              <textarea
                class="code-textarea"
                v-model="editCode"
                @input="onEdit"
                spellcheck="false"
              ></textarea>
            </div>
          </div>

          <div class="preview-section">
            <div class="preview-title">效果预览</div>
            <div class="preview-content">
              <div v-if="previewLoading" class="preview-loading">渲染中…</div>
              <div v-else-if="previewError" class="preview-error">{{ previewError }}</div>
              <div v-else class="preview-svg" v-html="previewSvg"></div>
            </div>
          </div>
        </div>

        <div class="dialog-footer">
          <button class="btn-cancel" @click="onCancel">取消</button>
          <button class="btn-confirm" @click="onConfirm">确认替换</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}
.dialog-panel {
  background: var(--bg, #fff);
  border-radius: var(--radius-lg, 12px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  width: min(92vw, 960px);
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border, #e0e0e0);
}
.dialog-title {
  font-weight: 600;
  font-size: var(--ui-font-size, 14px);
}
.dialog-close {
  background: none;
  border: none;
  font-size: 22px;
  cursor: pointer;
  color: var(--text-muted, #999);
  line-height: 1;
}
.dialog-close:hover { color: var(--text, #333); }
.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.code-section {
  display: flex;
  gap: 12px;
}
.code-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.code-panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted, #888);
  margin-bottom: 6px;
}
.editable-badge {
  color: var(--accent, #4a90d9);
  font-weight: 400;
  font-size: 11px;
}
.code-pre {
  margin: 0;
  flex: 1;
  background: var(--bg-code, #f5f5f5);
  border: 1px solid var(--border, #e0e0e0);
  border-radius: var(--radius-sm, 6px);
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.5;
  overflow: auto;
  white-space: pre;
}
.code-textarea {
  width: 100%;
  flex: 1;
  height: auto;
  box-sizing: border-box;
  background: var(--bg, #fff);
  border: 1px solid var(--border, #e0e0e0);
  border-radius: var(--radius-sm, 6px);
  padding: 10px 12px;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  line-height: 1.5;
  resize: vertical;
  color: var(--text, #333);
}
.code-textarea:focus {
  outline: none;
  border-color: var(--accent, #4a90d9);
}
.preview-section {
  display: flex;
  flex-direction: column;
}
.preview-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted, #888);
  margin-bottom: 6px;
}
.preview-content {
  border: 1px solid var(--border, #e0e0e0);
  border-radius: var(--radius-sm, 6px);
  padding: 12px;
  min-height: 100px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: auto;
}
.preview-loading {
  color: var(--text-muted, #888);
  font-size: 13px;
}
.preview-error {
  color: var(--error, #e53935);
  font-size: 13px;
  word-break: break-word;
}
.preview-svg {
  width: 100%;
  display: flex;
  justify-content: center;
}
.preview-svg :deep(svg) {
  max-width: 100%;
  height: auto;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border, #e0e0e0);
}
.btn-cancel {
  padding: 8px 18px;
  border: 1px solid var(--border, #e0e0e0);
  border-radius: var(--radius-sm, 6px);
  background: var(--bg, #fff);
  cursor: pointer;
  font-size: var(--ui-font-size, 13px);
  color: var(--text, #333);
}
.btn-cancel:hover {
  background: var(--bg-hover, #f0f0f0);
}
.btn-confirm {
  padding: 8px 18px;
  border: none;
  border-radius: var(--radius-sm, 6px);
  background: var(--accent, #4a90d9);
  color: #fff;
  cursor: pointer;
  font-size: var(--ui-font-size, 13px);
  font-weight: 500;
}
.btn-confirm:hover {
  opacity: 0.9;
}
</style>