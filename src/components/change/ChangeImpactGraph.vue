<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  MagnifyingGlassPlusIcon,
  MagnifyingGlassMinusIcon,
  ArrowPathIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
import * as d3 from 'd3'

const { showId, componentId } = useComponentId('CH-007')
const { t } = useI18n()

const props = withDefaults(defineProps<{
  impactedFiles?: string[]
  testFiles?: string[]
  width?: number
  height?: number
}>(), {
  impactedFiles: () => [],
  testFiles: () => [],
  width: 600,
  height: 400,
})

const svgRef = ref<SVGSVGElement | null>(null)
const scale = ref(1)
const translate = ref({ x: 0, y: 0 })
const isDragging = ref(false)
const dragStart = ref({ x: 0, y: 0 })

const nodes = computed(() => {
  const result: Array<{ id: string; group: string; label: string }> = []
  for (const f of props.impactedFiles) {
    const isTest = props.testFiles.includes(f)
    result.push({
      id: f,
      group: isTest ? 'test' : 'changed',
      label: f.split('/').pop() || f,
    })
  }
  if (result.length > 0) {
    result[0] = { ...result[0], group: 'root' }
  }
  return result
})

const edges = computed(() => {
  const result: Array<{ source: string; target: string }> = []
  const root = nodes.value.find(n => n.group === 'root')
  if (root) {
    for (const n of nodes.value) {
      if (n.id !== root.id) {
        result.push({ source: root.id, target: n.id })
      }
    }
  }
  return result
})

const hasData = computed(() => nodes.value.length > 0)

let simulation: d3.Simulation<d3.SimulationNodeDatum, undefined> | null = null

function renderGraph() {
  if (!svgRef.value || !hasData.value) return
  const svg = d3.select(svgRef.value)
  svg.selectAll('*').remove()

  const g = svg.append('g')
  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .scaleExtent([0.2, 5])
    .on('zoom', (event) => {
      g.attr('transform', event.transform)
      scale.value = event.transform.k
    })
  svg.call(zoom)

  const nodeData = nodes.value.map(d => ({ ...d })) as unknown as d3.SimulationNodeDatum[]
  const edgeData = edges.value.map(d => ({ ...d }))

  simulation = d3.forceSimulation(nodeData)
    .force('link', d3.forceLink(edgeData).id((d: any) => d.id).distance(120))
    .force('charge', d3.forceManyBody().strength(-200))
    .force('center', d3.forceCenter(props.width / 2, props.height / 2))
    .force('collision', d3.forceCollide(30))

  const link = g.append('g')
    .selectAll('line')
    .data(edgeData)
    .join('line')
    .attr('stroke', 'var(--border)')
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 0.6)

  const nodeGroup = g.append('g')
    .selectAll<SVGGElement, any>('g')
    .data(nodeData)
    .join('g')
    .call(d3.drag<SVGGElement, any>()
      .on('start', (event, d) => {
        if (!event.active) simulation?.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (event, d) => {
        d.fx = event.x
        d.fy = event.y
      })
      .on('end', (event, d) => {
        if (!event.active) simulation?.alphaTarget(0)
        d.fx = null
        d.fy = null
      }),
    )

  nodeGroup.append('circle')
    .attr('r', 18)
    .attr('fill', (d: any) => {
      switch (d.group) {
        case 'root': return 'var(--accent)'
        case 'test': return 'var(--warning)'
        default: return 'var(--text-muted)'
      }
    })
    .attr('stroke', (d: any) => d.group === 'root' ? 'var(--accent)' : 'var(--border)')
    .attr('stroke-width', 2)

  nodeGroup.append('text')
    .text((d: any) => d.label)
    .attr('text-anchor', 'middle')
    .attr('dy', 28)
    .attr('fill', 'var(--text-primary)')
    .attr('font-size', '10px')
    .attr('font-family', 'monospace')

  simulation.on('tick', () => {
    link
      .attr('x1', (d: any) => d.source.x)
      .attr('y1', (d: any) => d.source.y)
      .attr('x2', (d: any) => d.target.x)
      .attr('y2', (d: any) => d.target.y)
    nodeGroup.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
  })
}

function resetView() {
  scale.value = 1
  translate.value = { x: 0, y: 0 }
  if (svgRef.value) {
    d3.select(svgRef.value).transition().call(
      d3.zoom<SVGSVGElement, unknown>().transform,
      d3.zoomIdentity,
    )
  }
}

watch(() => [props.impactedFiles, props.testFiles], () => {
  simulation?.stop()
  renderGraph()
}, { deep: true })

onMounted(renderGraph)
onUnmounted(() => {
  simulation?.stop()
})
</script>

<template>
  <div class="change-impact-graph">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="graph-toolbar">
      <span class="toolbar-label">{{ t('change.impactGraph') }}</span>
      <div class="toolbar-actions">
        <button
          class="btn btn-ghost btn-icon btn-sm"
          :title="t('common.zoomIn')"
          @click="d3.select(svgRef!).call((d3.zoom() as any).scaleBy, 1.3)"
        >
          <MagnifyingGlassPlusIcon class="w-4 h-4" />
        </button>
        <button
          class="btn btn-ghost btn-icon btn-sm"
          :title="t('common.zoomOut')"
          @click="d3.select(svgRef!).call((d3.zoom() as any).scaleBy, 0.7)"
        >
          <MagnifyingGlassMinusIcon class="w-4 h-4" />
        </button>
        <button
          class="btn btn-ghost btn-icon btn-sm"
          :title="t('visualization.resetView')"
          @click="resetView"
        >
          <ArrowPathIcon class="w-4 h-4" />
        </button>
      </div>
    </div>
    <div
      v-if="!hasData"
      class="graph-empty"
    >
      <span>{{ t('change.noImpactData') }}</span>
    </div>
    <svg
      v-show="hasData"
      ref="svgRef"
      class="impact-svg"
      :width="width"
      :height="height"
    />
  </div>
</template>

<style scoped>
.change-impact-graph {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.graph-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.toolbar-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}

.toolbar-actions {
  display: flex;
  gap: 4px;
}

.graph-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  font-size: 12px;
  color: var(--text-muted);
}

.impact-svg {
  display: block;
  flex: 1;
}
</style>
