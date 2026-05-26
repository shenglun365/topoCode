<script setup lang="ts">
/** Mermaid 查看器 - 在 Worker 中渲染 Mermaid 图表 */

import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMermaidRender } from '@/composables/useMermaidRender'
import {
  ArrowPathIcon,
  ArrowDownTrayIcon,
  CodeBracketIcon,
  EyeIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('VZ-003')


const { t } = useI18n()

const props = withDefaults(defineProps<{
  diagram?: string
  theme?: 'dark' | 'light' | 'forest' | 'neutral'
  cache?: boolean
  editable?: boolean
  showToolbar?: boolean
}>(), {
  diagram: '',
  theme: 'dark',
  cache: true,
  editable: false,
  showToolbar: true,
})

const emit = defineEmits<{
  'render-complete': [svg: string]
  'render-error': [error: string]
}>()

const diagramCode = ref(props.diagram)
const editorCode = ref(props.diagram)
const viewMode = ref<'preview' | 'editor'>(props.editable ? 'editor' : 'preview')

// 同步 props 变化
watch(() => props.diagram, (v) => {
  diagramCode.value = v
  editorCode.value = v
})

const { svg, loading, error, progress, refresh, exportSvg, exportPng } = useMermaidRender(
  diagramCode,
  { theme: props.theme, cache: props.cache }
)

// 监听渲染完成
watch(svg, (v) => {
  if (v) emit('render-complete', v)
})

watch(error, (v) => {
  if (v) emit('render-error', v)
})

function applyEdit() {
  diagramCode.value = editorCode.value
  viewMode.value = 'preview'
}

function toggleView() {
  viewMode.value = viewMode.value === 'preview' ? 'editor' : 'preview'
}
</script>

<template>
  <div class="mermaid-viewer">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 工具栏 -->
    <div
      v-if="showToolbar"
      class="viewer-toolbar"
    >
      <div class="toolbar-left">
        <span class="toolbar-label">Mermaid</span>
        <span
          v-if="loading"
          class="toolbar-status"
        >
          {{ t('render.rendering') }} {{ progress }}%
        </span>
        <span
          v-else-if="error"
          class="toolbar-status error"
        >
          <ExclamationTriangleIcon class="w-3 h-3" />
          {{ error }}
        </span>
        <span
          v-else-if="svg"
          class="toolbar-status success"
        >
          {{ t('render.renderComplete') }}
        </span>
      </div>

      <div class="toolbar-right">
        <!-- 进度条 -->
        <div
          v-if="loading"
          class="progress-bar"
        >
          <div
            class="progress-fill"
            :style="{ width: `${progress}%` }"
          />
        </div>

        <button
          v-if="props.editable"
          class="btn btn-ghost btn-sm"
          :title="t('visualization.toggleView')"
          @click="toggleView"
        >
          <component
            :is="viewMode === 'preview' ? CodeBracketIcon : EyeIcon"
            class="w-4 h-4"
          />
        </button>

        <button
          class="btn btn-ghost btn-sm"
          :disabled="loading"
          :title="t('common.refresh')"
          @click="refresh"
        >
          <ArrowPathIcon class="w-4 h-4" />
        </button>

        <div class="divider-vertical" />

        <button
          class="btn btn-ghost btn-sm"
          :disabled="!svg"
          :title="t('visualization.exportSvg')"
          @click="exportSvg()"
        >
          <ArrowDownTrayIcon class="w-4 h-4" />
          <span>SVG</span>
        </button>

        <button
          class="btn btn-ghost btn-sm"
          :disabled="!svg"
          :title="t('visualization.exportPng')"
          @click="exportPng()"
        >
          <ArrowDownTrayIcon class="w-4 h-4" />
          <span>PNG</span>
        </button>
      </div>
    </div>

    <!-- 内容区 -->
    <div class="viewer-content">
      <!-- 编辑器模式 -->
      <div
        v-if="viewMode === 'editor' && props.editable"
        class="editor-pane"
      >
        <textarea
          v-model="editorCode"
          class="mermaid-editor"
          spellcheck="false"
          :placeholder="t('render.inputMermaidSyntax')"
        />
        <div class="editor-actions">
          <button
            class="btn btn-secondary btn-sm"
            :disabled="loading"
            @click="applyEdit"
          >
            {{ t('render.applyAndRender') }}
          </button>
        </div>
      </div>

      <!-- 预览模式 -->
      <div
        v-else
        class="preview-pane"
      >
        <!-- 加载中 -->
        <div
          v-if="loading && !svg"
          class="render-loading"
        >
          <div class="loading-spinner" />
          <span>{{ t('render.rendering') }} {{ progress }}%</span>
        </div>

        <!-- 错误状态 -->
        <div
          v-else-if="error && !svg"
          class="render-error"
        >
          <ExclamationTriangleIcon class="icon" />
          <div class="title">
            {{ t('render.renderFailed') }}
          </div>
          <div class="desc">
            {{ error }}
          </div>
          <button
            class="btn btn-secondary btn-sm"
            @click="refresh"
          >
            {{ t('common.retry') }}
          </button>
        </div>

        <!-- 渲染结果 -->
        <div
          v-else-if="svg"
          class="render-result"
          v-html="svg"
        />

        <!-- 空状态 -->
        <div
          v-else
          class="empty-state"
        >
          <CodeBracketIcon class="icon" />
          <div class="title">
            {{ t('common.waiting') }}
          </div>
          <div class="desc">
            {{ t('render.inputMermaidToRender') }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mermaid-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
}

.viewer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
  min-height: 40px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.toolbar-status {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}

.toolbar-status.error {
  color: var(--danger);
}

.toolbar-status.success {
  color: var(--success);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.progress-bar {
  width: 80px;
  height: 4px;
  background: var(--bg-hover);
  border-radius: 2px;
  overflow: hidden;
  margin-right: 8px;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.2s;
}

.viewer-content {
  flex: 1;
  overflow: auto;
  position: relative;
}

/* 编辑器 */
.editor-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.mermaid-editor {
  flex: 1;
  padding: 16px;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.6;
  background: var(--bg-primary);
  color: var(--text-primary);
  border: none;
  outline: none;
  resize: none;
  tab-size: 2;
}

.editor-actions {
  padding: 8px 12px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
}

/* 预览 */
.preview-pane {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.render-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-muted);
  font-size: 13px;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.render-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px;
  text-align: center;
}

.render-error .icon {
  width: 40px;
  height: 40px;
  color: var(--danger);
}

.render-error .title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.render-error .desc {
  font-size: 12px;
  color: var(--text-muted);
  max-width: 400px;
}

.render-result {
  width: 100%;
  display: flex;
  justify-content: center;
}

.render-result :deep(svg) {
  max-width: 100%;
  height: auto;
}

/* 适配 Mermaid 暗色主题 */
.render-result :deep(svg) text {
  fill: var(--text-primary) !important;
}

.render-result :deep(svg) .node rect,
.render-result :deep(svg) .node circle,
.render-result :deep(svg) .node polygon {
  fill: var(--bg-secondary) !important;
  stroke: var(--accent) !important;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
}

.empty-state .icon {
  width: 48px;
  height: 48px;
  opacity: 0.5;
}

.empty-state .title {
  font-size: 14px;
  font-weight: 600;
}

.empty-state .desc {
  font-size: 12px;
}
</style>
