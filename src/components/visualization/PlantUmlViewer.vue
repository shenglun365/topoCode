<script setup lang="ts">
/** PlantUML 查看器 - 通过 Python 后端或远程服务器渲染 */

import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePlantUmlRender } from '@/composables/usePlantUmlRender'
import {
  ArrowPathIcon,
  ArrowDownTrayIcon,
  CodeBracketIcon,
  EyeIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('VZ-002')


const { t } = useI18n()

const props = withDefaults(defineProps<{
  diagram?: string
  format?: 'svg' | 'png'
  useRemote?: boolean
  editable?: boolean
  showToolbar?: boolean
}>(), {
  diagram: '',
  format: 'svg',
  useRemote: true,
  editable: false,
  showToolbar: true,
})

const emit = defineEmits<{
  'render-complete': [data: string]
  'render-error': [error: string]
}>()

const diagramCode = ref(props.diagram)
const editorCode = ref(props.diagram)
const viewMode = ref<'preview' | 'editor'>(props.editable ? 'editor' : 'preview')

watch(() => props.diagram, (v) => {
  diagramCode.value = v
  editorCode.value = v
})

const { imageData, loading, error, exportImage } = usePlantUmlRender(diagramCode, {
  format: props.format,
  useRemote: props.useRemote,
})

watch(imageData, (v) => {
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

function refresh() {
  const code = diagramCode.value
  diagramCode.value = ''
  setTimeout(() => { diagramCode.value = code }, 0)
}
</script>

<template>
  <div class="plantuml-viewer">
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
        <span class="toolbar-label">PlantUML</span>
        <span
          v-if="loading"
          class="toolbar-status"
        >{{ t('render.rendering') }}</span>
        <span
          v-else-if="error"
          class="toolbar-status error"
        >
          <ExclamationTriangleIcon class="w-3 h-3" />
          {{ error }}
        </span>
        <span
          v-else-if="imageData"
          class="toolbar-status success"
        >{{ t('render.renderComplete') }}</span>
      </div>

      <div class="toolbar-right">
        <button
          v-if="props.editable"
          class="btn btn-ghost btn-sm"
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
          @click="refresh"
        >
          <ArrowPathIcon class="w-4 h-4" />
        </button>

        <div class="divider-vertical" />

        <button
          class="btn btn-ghost btn-sm"
          :disabled="!imageData"
          @click="exportImage()"
        >
          <ArrowDownTrayIcon class="w-4 h-4" />
          <span>{{ props.format.toUpperCase() }}</span>
        </button>
      </div>
    </div>

    <!-- 内容区 -->
    <div class="viewer-content">
      <!-- 编辑器 -->
      <div
        v-if="viewMode === 'editor' && props.editable"
        class="editor-pane"
      >
        <textarea
          v-model="editorCode"
          class="plantuml-editor"
          spellcheck="false"
          :placeholder="t('render.inputPlantUmlSyntax')"
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

      <!-- 预览 -->
      <div
        v-else
        class="preview-pane"
      >
        <!-- 加载中 -->
        <div
          v-if="loading && !imageData"
          class="render-loading"
        >
          <div class="loading-spinner" />
          <span>{{ t('render.rendering') }}</span>
        </div>

        <!-- 错误 -->
        <div
          v-else-if="error && !imageData"
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
          v-else-if="imageData"
          class="render-result"
        >
          <img
            :src="imageData"
            :alt="props.format"
          >
        </div>

        <!-- 空状态 -->
        <div
          v-else
          class="empty-state"
        >
          <CodeBracketIcon class="icon" />
          <div class="title">
            {{ t('render.waitingForInput') }}
          </div>
          <div class="desc">
            {{ t('render.inputPlantUml') }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.plantuml-viewer {
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

.toolbar-status.error { color: var(--danger); }
.toolbar-status.success { color: var(--success); }

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.viewer-content {
  flex: 1;
  overflow: auto;
  position: relative;
}

.editor-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.plantuml-editor {
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

.render-result img {
  max-width: 100%;
  height: auto;
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
