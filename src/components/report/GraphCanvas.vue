<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as d3 from 'd3'
import type { GraphNode, GraphEdge } from './renderers/types'
import { renderForceGraph } from './renderers/D3ForceRenderer'
import { renderDagreGraph } from './renderers/DagreRenderer'

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
  style: 'd3force' | 'dagre'
  highlightedIds?: Set<string>
  hiddenIds?: Set<string>
  resetTrigger?: number
}>()

const emit = defineEmits<{
  'node-dblclick': [nodeId: string]
  'node-drag-end': [nodeId: string, x: number, y: number]
  'node-context-menu': [nodeId: string]
}>()

const svgRef = ref<SVGSVGElement | null>(null)
const containerRef = ref<HTMLElement | null>(null)
let svg: d3.Selection<SVGSVGElement, unknown, null, undefined> | null = null
let simulation: d3.Simulation<any, any> | null = null

const width = ref(800)
const height = ref(420)

function fitView() {
  const el = containerRef.value
  if (!el) return
  width.value = el.clientWidth || 800
  height.value = el.clientHeight || 420
}

let resizeObs: ResizeObserver | null = null
let resizeTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  fitView()
  if (containerRef.value) {
    resizeObs = new ResizeObserver(() => {
      fitView()
      if (resizeTimer) clearTimeout(resizeTimer)
      resizeTimer = setTimeout(() => render(), 150)
    })
    resizeObs.observe(containerRef.value)
  }
  nextTick(() => initSvg())
})

onUnmounted(() => {
  resizeObs?.disconnect()
  if (resizeTimer) clearTimeout(resizeTimer)
  simulation?.stop()
  if (svgRef.value) {
    (d3.select(svgRef.value as any) as any).on('.zoom', null)
  }
})

function initSvg() {
  if (!svgRef.value) return
  svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()
  render()
}

watch(() => [props.nodes, props.edges, props.style, props.hiddenIds, props.resetTrigger], () => {
  render()
}, { deep: true })

function render() {
  if (!svg || !svgRef.value) return
  simulation?.stop()
  svg.on('.zoom', null)
  delete (svgRef.value as any).__zoom
  svg.selectAll('*').remove()

  const visible = props.hiddenIds
    ? props.nodes.filter(n => !props.hiddenIds!.has(n.id))
    : props.nodes
  const visibleEdges = props.hiddenIds
    ? props.edges.filter(e => !props.hiddenIds!.has(e.source) && !props.hiddenIds!.has(e.target))
    : props.edges

  if (visible.length === 0) {
    svg.append('text')
      .attr('x', width.value / 2).attr('y', height.value / 2)
      .attr('text-anchor', 'middle').attr('fill', 'var(--text-muted, #6b7280)')
      .attr('font-size', '13px').text('No data')
    return
  }

  if (props.style === 'dagre') {
    renderDagreGraph({
      svg, width: width.value, height: height.value,
      nodes: visible, edges: visibleEdges,
      highlightedIds: props.highlightedIds,
      onDblClick: (id) => emit('node-dblclick', id),
      onContextMenu: (id) => emit('node-context-menu', id),
    })
  } else {
    simulation = renderForceGraph({
      svg, width: width.value, height: height.value,
      nodes: visible, edges: visibleEdges,
      highlightedIds: props.highlightedIds,
      onDblClick: (id) => emit('node-dblclick', id),
      onContextMenu: (id) => emit('node-context-menu', id),
      onDragEnd: (id, x, y) => emit('node-drag-end', id, x, y),
    })
  }
}
</script>

<template>
  <div
    ref="containerRef"
    class="gc-container"
  >
    <svg
      ref="svgRef"
      :width="width"
      :height="height"
      class="gc-svg"
    />
  </div>
</template>

<style scoped>
.gc-container { flex: 1; overflow: hidden; background: var(--bg-primary); }
.gc-svg { width: 100%; height: 100%; display: block; }
</style>
