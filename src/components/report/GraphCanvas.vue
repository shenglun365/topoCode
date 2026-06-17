<script setup lang="ts">
import { ref } from 'vue'
import CytoscapeGraph from './renderers/CytoscapeGraph.vue'
import type { GraphNode, GraphEdge } from './renderers/CytoscapeGraph.vue'

const cyRef = ref<InstanceType<typeof CytoscapeGraph>>()

defineExpose({
  getAllPositions: () => cyRef.value?.getAllPositions(),
  zoomIn: () => cyRef.value?.zoomIn(),
  zoomOut: () => cyRef.value?.zoomOut(),
  zoomTo: (nodeId: string, animate?: boolean) => cyRef.value?.zoomTo(nodeId, animate),
})

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
  style: 'force'
  highlightedIds?: Set<string>
  hiddenIds?: Set<string>
  resetTrigger?: number
  lockMode?: 'linked' | 'locked'
  repulsion?: number
  recenterTrigger?: number
  zoomLevel?: number
  fontSize?: number
  fullscreen?: boolean
  positions?: Record<string, { x: number; y: number }>
  showGuideButton?: boolean
}>()

const emit = defineEmits<{
  'node-dblclick': [nodeId: string]
  'node-drag-end': [nodeId: string, x: number, y: number]
  'node-context-menu': [nodeId: string]
  'zoom-changed': [level: number]
  'guide-click': []
}>()
</script>

<template>
  <CytoscapeGraph
    ref="cyRef"
    :nodes="nodes"
    :edges="edges"
    :style="style"
    :highlighted-ids="highlightedIds"
    :hidden-ids="hiddenIds"
    :reset-trigger="resetTrigger"
    :lock-mode="lockMode"
    :repulsion="repulsion"
    :recenter-trigger="recenterTrigger"
    :zoom-level="zoomLevel"
    :font-size="fontSize"
    :fullscreen="fullscreen"
    :positions="positions"
    :show-guide-button="showGuideButton"
    @node-dblclick="(id: string) => emit('node-dblclick', id)"
    @node-drag-end="(id: string, x: number, y: number) => emit('node-drag-end', id, x, y)"
    @node-context-menu="(id: string) => emit('node-context-menu', id)"
    @zoom-changed="(level: number) => emit('zoom-changed', level)"
    @guide-click="() => emit('guide-click')"
  />
</template>
