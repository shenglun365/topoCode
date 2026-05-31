<script setup lang="ts">
/** D3 力导向图 - Worker 计算布局 + SVG 渲染 */

import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useD3Graph } from '@/composables/useD3Graph'
import {
  MagnifyingGlassIcon,
  MagnifyingGlassPlusIcon,
  MagnifyingGlassMinusIcon,
  ArrowPathIcon,
  ArrowDownTrayIcon,
} from '@heroicons/vue/24/outline'
import type { D3Node, D3Edge } from '@/workers/types'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('VZ-004')
const { t } = useI18n()

const props = withDefaults(defineProps<{
  nodes?: D3Node[]
  edges?: D3Edge[]
  width?: number
  height?: number
  iterations?: number
  linkDistance?: number
  chargeStrength?: number
  showToolbar?: boolean
  showLabels?: boolean
  nodeColors?: Record<string, string>
}>(), {
  nodes: () => [],
  edges: () => [],
  width: 800,
  height: 500,
  iterations: 300,
  linkDistance: 120,
  chargeStrength: -300,
  showToolbar: true,
  showLabels: true,
  nodeColors: () => ({
    default: '#89b4fa',
    module: '#a6e3a1',
    class: '#f9e2af',
    function: '#f38ba8',
    knowledge: '#cba6f7',
  }),
})

const graphData = computed(() => ({
  nodes: props.nodes,
  edges: props.edges,
}))

const { nodes, edges, loading, error, progress } = useD3Graph(graphData, {
  width: props.width,
  height: props.height,
  iterations: props.iterations,
  linkDistance: props.linkDistance,
  chargeStrength: props.chargeStrength,
})

// 缩放/平移
const scale = ref(1)
const translate = ref({ x: 0, y: 0 })
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })

function zoomIn() { scale.value = Math.min(scale.value * 1.2, 5) }
function zoomOut() { scale.value = Math.max(scale.value * 0.8, 0.2) }
function resetView() { scale.value = 1; translate.value = { x: 0, y: 0 } }

// 拖拽平移
function onmousedown(e: MouseEvent) {
  if ((e.target as HTMLElement).closest('.d3-node')) return
  isDragging.value = true
  dragStart.value = { x: e.clientX - translate.value.x, y: e.clientY - translate.value.y }
}

function onmousemove(e: MouseEvent) {
  if (!isDragging.value) return
  translate.value = { x: e.clientX - dragStart.value.x, y: e.clientY - dragStart.value.y }
}

function onmouseup() {
  isDragging.value = false
}

function getNodeColor(node: any): string {
  const group = node.group || 'default'
  return props.nodeColors[group] || props.nodeColors.default
}

function findNodeById(nodeId: string): any | undefined {
  return nodes.value.find(n => n.id === nodeId)
}

function exportSvg() {
  const svgEl = document.querySelector('.d3-graph-svg') as SVGElement
  if (!svgEl) return
  const data = new XMLSerializer().serializeToString(svgEl)
  const blob = new Blob([data], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'force-graph.svg'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="d3-force-graph">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 工具栏 -->
    <div
      v-if="showToolbar"
      class="graph-toolbar"
    >
      <div class="toolbar-left">
        <span class="toolbar-label">{{ t('visualization.forceDirected') }}</span>
        <span
          v-if="loading"
          class="toolbar-status"
        >
          {{ t('render.layoutComputing') }} {{ progress }}%
        </span>
        <span
          v-else-if="error"
          class="toolbar-status error"
        >
          {{ error }}
        </span>
        <span
          v-else
          class="toolbar-status"
        >
          {{ nodes.length }} {{ t('visualization.nodes') }} / {{ edges.length }} {{ t('visualization.edges') }}
        </span>
      </div>

      <div class="toolbar-right">
        <button
          class="btn btn-ghost btn-sm"
          :title="t('common.zoomIn')"
          @click="zoomIn"
        >
          <MagnifyingGlassPlusIcon class="w-4 h-4" />
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :title="t('common.zoomOut')"
          @click="zoomOut"
        >
          <MagnifyingGlassMinusIcon class="w-4 h-4" />
        </button>
        <button
          class="btn btn-ghost btn-sm"
          :title="t('visualization.resetView')"
          @click="resetView"
        >
          <MagnifyingGlassIcon class="w-4 h-4" />
        </button>
        <div class="divider-vertical" />
        <button
          class="btn btn-ghost btn-sm"
          :disabled="!nodes.length"
          :title="t('visualization.exportSvg')"
          @click="exportSvg"
        >
          <ArrowDownTrayIcon class="w-4 h-4" />
        </button>
      </div>
    </div>

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

    <!-- SVG 画布 -->
    <div
      class="graph-canvas"
      :class="{ dragging: isDragging }"
      @mousedown="onmousedown"
      @mousemove="onmousemove"
      @mouseup="onmouseup"
      @mouseleave="onmouseup"
    >
      <!-- 加载中 -->
      <div
        v-if="loading && !nodes.length"
        class="render-loading"
      >
        <div class="loading-spinner" />
        <span>{{ t('render.layoutComputing') }} {{ progress }}%</span>
      </div>

      <!-- 错误 -->
      <div
        v-else-if="error"
        class="render-error"
      >
        <div class="title">
          {{ t('render.layoutFailed') }}
        </div>
        <div class="desc">
          {{ error }}
        </div>
      </div>

      <!-- 空状态 -->
      <div
        v-else-if="!nodes.length"
        class="empty-state"
      >
        <div class="title">
          {{ t('common.waiting') }}
        </div>
        <div class="desc">
          {{ t('render.waitingGraphData') }}
        </div>
      </div>

      <!-- 图谱 -->
      <svg
        v-else
        class="d3-graph-svg"
        :width="width"
        :height="height"
        :viewBox="`0 0 ${width} ${height}`"
      >
        <defs>
          <marker
            id="d3-arrow"
            markerWidth="10"
            markerHeight="7"
            refX="10"
            refY="3.5"
            orient="auto"
          >
            <polygon
              points="0 0, 10 3.5, 0 7"
              fill="var(--text-muted)"
              opacity="0.6"
            />
          </marker>
          <pattern
            id="d3-grid"
            width="40"
            height="40"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M 40 0 L 0 0 0 40"
              fill="none"
              stroke="var(--border)"
              stroke-width="0.5"
              opacity="0.2"
            />
          </pattern>
          <filter id="d3-glow">
            <feGaussianBlur
              stdDeviation="3"
              result="coloredBlur"
            />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g :transform="`translate(${translate.x}, ${translate.y}) scale(${scale})`">
          <!-- 网格 -->
          <rect
            width="100%"
            height="100%"
            fill="url(#d3-grid)"
          />

          <!-- 边 -->
          <g class="d3-edges">
            <line
              v-for="(edge, i) in edges"
              :key="`edge-${i}`"
              :x1="findNodeById(edge.source)?.x || 0"
              :y1="findNodeById(edge.source)?.y || 0"
              :x2="findNodeById(edge.target)?.x || 0"
              :y2="findNodeById(edge.target)?.y || 0"
              stroke="var(--text-muted)"
              stroke-width="1.5"
              opacity="0.3"
              marker-end="url(#d3-arrow)"
            />
          </g>

          <!-- 节点 -->
          <g class="d3-nodes">
            <g
              v-for="node in nodes"
              :key="node.id"
              class="d3-node"
              :transform="`translate(${node.x}, ${node.y})`"
              @click.stop
            >
              <!-- 外圈光晕 -->
              <circle
                r="24"
                :fill="getNodeColor(node)"
                opacity="0.1"
              />
              <!-- 内圈 -->
              <circle
                r="18"
                :fill="getNodeColor(node)"
                opacity="0.2"
                :stroke="getNodeColor(node)"
                stroke-width="2"
                class="node-circle"
              />
              <!-- 标签 -->
              <text
                v-if="showLabels"
                y="4"
                text-anchor="middle"
                :fill="getNodeColor(node)"
                font-size="10"
                font-weight="600"
                font-family="var(--font-mono)"
                class="node-label"
              >{{ node.label || node.id }}</text>
            </g>
          </g>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.d3-force-graph {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  position: relative;
}

.graph-toolbar {
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

.toolbar-status.error {
  color: var(--danger);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.progress-bar {
  height: 2px;
  background: var(--bg-hover);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.2s;
}

.graph-canvas {
  flex: 1;
  overflow: hidden;
  position: relative;
  cursor: grab;
}

.graph-canvas.dragging {
  cursor: grabbing;
}

.d3-graph-svg {
  width: 100%;
  height: 100%;
}

/* 节点交互 */
.d3-node {
  cursor: pointer;
  transition: opacity 0.2s;
}

.d3-node:hover .node-circle {
  stroke-width: 3;
  filter: url(#d3-glow);
}

.d3-node:hover .node-label {
  font-size: 11px;
}

/* 状态 */
.render-loading,
.render-error,
.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: var(--text-muted);
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.render-error .title,
.empty-state .title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.render-error .desc,
.empty-state .desc {
  font-size: 12px;
  max-width: 300px;
}
</style>
