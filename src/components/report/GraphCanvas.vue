<script setup lang="ts">
import CytoscapeGraph from './renderers/CytoscapeGraph.vue'
import type { GraphNode, GraphEdge } from './renderers/CytoscapeGraph.vue'

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
  style: 'force' | 'dagre'
  highlightedIds?: Set<string>
  hiddenIds?: Set<string>
  resetTrigger?: number
  lockMode?: 'linked' | 'locked'
  repulsion?: number
  recenterTrigger?: number
  zoomLevel?: number
  fontSize?: number
  fullscreen?: boolean
}>()

const emit = defineEmits<{
  'node-dblclick': [nodeId: string]
  'node-drag-end': [nodeId: string, x: number, y: number]
  'node-context-menu': [nodeId: string]
  'zoom-changed': [level: number]
}>()
</script>

<template>
  <CytoscapeGraph
    :nodes="nodes"
    :edges="edges"
    :style="style === 'dagre' ? 'dagre' : 'force'"
    :highlighted-ids="highlightedIds"
    :hidden-ids="hiddenIds"
    :reset-trigger="resetTrigger"
    :lock-mode="lockMode"
    :repulsion="repulsion"
    :recenter-trigger="recenterTrigger"
    :zoom-level="zoomLevel"
    :font-size="fontSize"
    :fullscreen="fullscreen"
    @node-dblclick="(id: string) => emit('node-dblclick', id)"
    @node-drag-end="(id: string, x: number, y: number) => emit('node-drag-end', id, x, y)"
    @node-context-menu="(id: string) => emit('node-context-menu', id)"
    @zoom-changed="(level: number) => emit('zoom-changed', level)"
  />
</template>
