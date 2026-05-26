<script setup lang="ts">
/** PIXI.js Canvas 组件 - WebGL 加速的图谱渲染 */

import { ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePixiCanvas, type PixiNode, type PixiEdge } from '@/composables/usePixiCanvas'
import {
  ArrowDownTrayIcon,
  ArrowPathIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('VZ-005')


const { t } = useI18n()

const props = withDefaults(defineProps<{
  nodes?: PixiNode[]
  edges?: PixiEdge[]
  width?: number
  height?: number
  showToolbar?: boolean
  showFps?: boolean
  backgroundColor?: number
}>(), {
  nodes: () => [],
  edges: () => [],
  width: 800,
  height: 500,
  showToolbar: true,
  showFps: true,
  backgroundColor: 0x1e1e2e,
})

const canvasRef = ref<HTMLCanvasElement | null>(null)
const { isReady, fps, nodeCount, renderGraph, exportPng } = usePixiCanvas(canvasRef, {
  width: props.width,
  height: props.height,
  backgroundColor: props.backgroundColor,
})

// 监听数据变化
watch(
  () => [props.nodes, props.edges],
  () => {
    if (isReady.value) {
      renderGraph(props.nodes, props.edges)
    }
  },
  { deep: true }
)

// 初始渲染
onMounted(() => {
  if (props.nodes.length > 0 && isReady.value) {
    renderGraph(props.nodes, props.edges)
  }
})

function refresh() {
  renderGraph(props.nodes, props.edges)
}
</script>

<template>
  <div class="pixi-canvas-container">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 工具栏 -->
    <div
      v-if="showToolbar"
      class="canvas-toolbar"
    >
      <div class="toolbar-left">
        <span class="toolbar-label">PIXI.js WebGL</span>
        <span
          v-if="!isReady"
          class="toolbar-status"
        >{{ t('render.initializing') }}</span>
        <span
          v-else
          class="toolbar-status"
        >
          {{ nodeCount }} {{ t('visualization.nodes') }} / {{ edges.length }} {{ t('visualization.edges') }}
        </span>
      </div>

      <div class="toolbar-right">
        <span
          v-if="showFps && isReady"
          class="fps-badge"
        >
          {{ fps }} FPS
        </span>

        <button
          class="btn btn-ghost btn-sm"
          :disabled="!isReady"
          @click="refresh"
        >
          <ArrowPathIcon class="w-4 h-4" />
        </button>

        <div class="divider-vertical" />

        <button
          class="btn btn-ghost btn-sm"
          :disabled="!isReady"
          @click="exportPng()"
        >
          <ArrowDownTrayIcon class="w-4 h-4" />
          <span>PNG</span>
        </button>
      </div>
    </div>

    <!-- Canvas 容器 -->
    <div class="canvas-wrapper">
      <canvas
        ref="canvasRef"
        class="pixi-canvas"
      />

      <!-- 未初始化提示 -->
      <div
        v-if="!isReady"
        class="canvas-overlay"
      >
        <div class="loading-spinner" />
        <span>{{ t('render.webglInitializing') }}</span>
      </div>

      <!-- 空状态 -->
      <div
        v-else-if="!nodes.length"
        class="canvas-overlay empty"
      >
        <div class="title">
          {{ t('common.waiting') }}
        </div>
        <div class="desc">
          {{ t('render.waitingWebglGraphData') }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pixi-canvas-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  position: relative;
}

.canvas-toolbar {
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
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.fps-badge {
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--success);
  background: rgba(166, 227, 161, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  margin-right: 8px;
}

.canvas-wrapper {
  flex: 1;
  position: relative;
  overflow: hidden;
}

.pixi-canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.canvas-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  color: var(--text-muted);
  gap: 12px;
  font-size: 13px;
}

.canvas-overlay.empty {
  background: transparent;
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

.canvas-overlay .title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.canvas-overlay .desc {
  font-size: 12px;
  max-width: 300px;
  text-align: center;
}
</style>
