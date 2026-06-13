<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import cytoscape from 'cytoscape'
import dagre from 'cytoscape-dagre'

cytoscape.use(dagre)

export interface GraphNode {
  id: string
  label: string
  nodeCount?: number
  qualityScore?: number | null
  status?: string
  hasChildren?: boolean
  isExternal?: boolean
  isMerged?: boolean
  remainingCount?: number
  compareState?: 'added' | 'removed' | 'changed' | 'unchanged'
}

export interface GraphEdge {
  source: string
  target: string
  count?: number
}

const props = defineProps<{
  nodes: GraphNode[]
  edges: GraphEdge[]
  style: 'dagre' | 'd3force'
  highlightedIds?: Set<string>
  hiddenIds?: Set<string>
  resetTrigger?: number
  recenterTrigger?: number
  lockMode?: 'linked' | 'locked'
  repulsion?: number
}>()

const emit = defineEmits<{
  'node-dblclick': [nodeId: string]
  'node-context-menu': [nodeId: string]
  'node-drag-end': [nodeId: string, x: number, y: number]
}>()

const container = ref<HTMLDivElement>()
const tooltip = ref<HTMLDivElement>()
let cy: cytoscape.Core | null = null

function getNodeRadius(n: GraphNode): number {
  return Math.round(Math.max(18, Math.min(40, (n.nodeCount || 5) * 1.5 + 12)))
}

function nodeColor(n: GraphNode): string {
  if (n.compareState === 'added') return '#22c55e'
  if (n.compareState === 'removed') return '#ef4444'
  if (n.compareState === 'changed') return '#f97316'
  if (n.compareState === 'unchanged') return '#6b7280'
  if (n.isExternal) return '#f59e0b'
  return '#60a5fa'
}

function buildCytoscape() {
  if (!container.value) return

  const hidden = props.hiddenIds || new Set<string>()
  const hl = props.highlightedIds || new Set<string>()

  const cyNodes = props.nodes
    .filter(n => !hidden.has(n.id))
    .map(n => {
      const r = getNodeRadius(n)
      const color = n.isMerged ? '#6b7280' : nodeColor(n)
      return {
        group: 'nodes' as const,
        data: {
          id: n.id,
          label: n.label.length > 16 ? n.label.slice(0, 16) + '\u2026' : n.label,
          _label: n.label,
          _nodeCount: n.nodeCount || 0,
          _hasChildren: !!n.hasChildren,
          _isMerged: !!n.isMerged,
          _isExternal: !!n.isExternal,
          _compareState: n.compareState || '',
          _highlighted: hl.has(n.id),
          _color: color,
          _radius: r,
        },
        classes: n.isMerged ? 'merged' : (n.hasChildren ? 'drillable' : 'leaf'),
        selected: false,
        locked: false,
      }
    })

  const edgeIdSet = new Set(cyNodes.map(n => n.data.id))
  const cyEdges = props.edges
    .filter(e => edgeIdSet.has(e.source) && edgeIdSet.has(e.target))
    .map(e => ({
      group: 'edges' as const,
      data: {
        id: `${e.source}→${e.target}`,
        source: e.source,
        target: e.target,
        _count: e.count || 0,
      },
    }))

  const styles: cytoscape.Stylesheet[] = [
    {
      selector: 'node',
      style: {
        'background-color': 'data(_color)',
        'background-opacity': 0.18,
        'border-color': 'data(_color)',
        'border-width': (el: any) => el.data('_highlighted') ? 2.5 : (el.data('_isMerged') ? 1.5 : (el.data('_hasChildren') ? 2 : 1)),
        'border-style': (el: any) => el.data('_isMerged') ? 'dashed' : 'solid',
        'border-opacity': (el: any) => el.data('_highlighted') ? 1 : 0.7,
        'shape': 'ellipse',
        'width': (el: any) => el.data('_radius') * 2 + 12,
        'height': (el: any) => el.data('_radius') * 2 + 12,
        'font-size': '10px',
        'color': '#e5e7eb',
        'label': 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'ellipsis',
        'text-max-width': '120px',
        'min-zoomed-font-size': 8,
      },
    },
    {
      selector: 'node:selected',
      style: { 'border-color': '#7c3aed', 'border-width': 3, 'border-opacity': 1 },
    },
    {
      selector: 'node.merged',
      style: { 'background-opacity': 0.08, 'border-style': 'dashed', 'border-opacity': 0.5, 'text-opacity': 0.7 },
    },
    {
      selector: 'node.drillable',
      style: { 'border-style': 'double' },
    },
    {
      selector: 'node:active',
      style: { 'overlay-color': '#7c3aed', 'overlay-padding': 4, 'overlay-opacity': 0.3 },
    },
    {
      selector: 'edge',
      style: {
        'width': 1.5,
        'line-color': '#9ca3af',
        'line-opacity': 0.6,
        'target-arrow-color': '#9ca3af',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 1.2,
        'curve-style': 'bezier',
      },
    },
  ]

  cy = cytoscape({
    container: container.value,
    elements: [...cyNodes, ...cyEdges],
    style: styles,
    zoomingEnabled: true,
    userZoomingEnabled: true,
    panningEnabled: true,
    userPanningEnabled: true,
    boxSelectionEnabled: false,
    autounselectify: true,
    maxZoom: 4,
    minZoom: 0.15,
  })

  nextTick(() => { if (cy) { cy.resize(); cy.fit() } })

  cy.on('dbltap', 'node', (evt) => {
    const node = evt.target
    if (node.data('_isMerged') || node.data('_hasChildren')) {
      emit('node-dblclick', node.id())
    }
  })

  cy.on('cxttap', 'node', (evt) => {
    const node = evt.target
    if (!node.data('_isMerged')) {
      evt.originalEvent?.preventDefault()
      emit('node-context-menu', node.id())
    }
  })

  let dragNodeId = ''
  let dragPrevPos: { x: number; y: number } | null = null

  cy.on('dragfree', 'node', (evt: any) => {
    if (!evt.target.data('_isMerged')) {
      dragNodeId = evt.target.id()
      dragPrevPos = { ...evt.target.position() }
    }
  })
  cy.on('dragfreeon', 'node', (evt: any) => {
    const node = evt.target
    if (!node.data('_isMerged') && dragNodeId === node.id()) {
      dragNodeId = ''
      dragPrevPos = null
      const pos = node.position()
      emit('node-drag-end', node.id(), pos.x, pos.y)
    }
  })

  cy.on('grab', 'node', (evt: any) => {
    const node = evt.target
    if (node.data('_isMerged')) return
    if (props.lockMode === 'locked') {
      cy?.nodes().forEach(n => { if (!n.same(node) && !n.data('_isMerged')) n.lock() })
    }
    dragPrevPos = { ...node.position() }
  })
  cy.on('free', 'node', () => {
    dragPrevPos = null
    if (props.lockMode === 'locked') {
      cy?.nodes().forEach(n => { n.unlock() })
    }
  })
  cy.on('drag', 'node', (evt: any) => {
    const node = evt.target
    if (node.data('_isMerged') || props.lockMode === 'locked' || !dragPrevPos) return
    const pos = node.position()
    const dx = pos.x - dragPrevPos.x
    const dy = pos.y - dragPrevPos.y
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return
    dragPrevPos = { ...pos }

    // move connected neighbours proportionally (damped)
    const closed = node.closedNeighborhood().nodes().filter((n: any) => !n.same(node) && !n.data('_isMerged'))
    closed.forEach((n: any) => {
      const np = n.position()
      n.position({ x: np.x + dx * 0.7, y: np.y + dy * 0.7 })
    })
  })

  cy.on('layoutstop', () => {
    if (!cy) return
    const isoNodes: cytoscape.NodeSingular[] = []
    const bb = cy.elements().boundingBox()
    const cx = (bb.x1 + bb.x2) / 2

    cy.nodes().forEach(n => {
      if (n.degree(false) === 0 && !n.data('_isMerged')) isoNodes.push(n)
    })

    if (isoNodes.length === 0) return

    const cols = Math.min(isoNodes.length, 6)
    const spacing = 60
    const gridW = (cols - 1) * spacing
    const maxR = Math.max(...isoNodes.map(n => n.data('_radius') as number))
    const gridY = bb.y2 + maxR + 15
    const startX = cx - gridW / 2

    isoNodes.forEach((n, i) => {
      const col = i % cols
      const row = Math.floor(i / cols)
      n.position({
        x: startX + col * spacing,
        y: gridY + row * spacing,
      })
    })
  })

  // run layout after all event handlers registered
  const layout = cy.layout(
    props.style === 'dagre'
      ? { name: 'dagre', rankDir: 'LR', nodeSep: 80, rankSep: 120, edgeSep: 30, fit: true, padding: 40 }
      : { name: 'cose', idealEdgeLength: 200, nodeRepulsion: props.repulsion || 15000, gravity: 1.5, fit: true, padding: 40, animate: true, animationDuration: 1500, numIter: 4000 }
  )
  layout.run()

  cy.on('mouseover', 'node', (evt) => {
    const node = evt.target
    const d = node.data()
    if (d._isMerged) return
    node.style({ 'background-opacity': 0.4, 'border-opacity': 1, 'text-opacity': 1 })
    container.value!.style.cursor = 'pointer'

    if (!tooltip.value) return
    const drillInfo = d._hasChildren ? '可双击下钻' : '无下级社区'
    const label = d._label || d.id
    tooltip.value.innerHTML = `
      <div class="cg-tip-name">${escapeHtml(label)}</div>
      <div class="cg-tip-id">${escapeHtml(d.id)}</div>
      <div class="cg-tip-meta">${d._nodeCount} 节点 · ${drillInfo}${d._isExternal ? ' · 外部' : ''}</div>
    `
    tooltip.value.style.display = 'block'
  })
  cy.on('mouseout', 'node', (evt) => {
    const node = evt.target
    const d = node.data()
    const hl = d._highlighted
    node.style({
      'background-opacity': d._isMerged ? 0.08 : (hl ? 0.3 : 0.18),
      'border-opacity': hl ? 1 : 0.7,
      'text-opacity': d._isMerged ? 0.7 : (hl ? 1 : 0.85),
    })
    container.value!.style.cursor = 'default'
    if (tooltip.value) tooltip.value.style.display = 'none'
  })

  cy.on('mousemove', (evt) => {
    if (!tooltip.value || tooltip.value.style.display !== 'block') return
    tooltip.value.style.left = (evt.originalEvent?.clientX || 0) + 12 + 'px'
    tooltip.value.style.top = (evt.originalEvent?.clientY || 0) + 12 + 'px'
  })
}

function escapeHtml(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function destroyCy() {
  if (!cy) return
  try {
    const running = cy.layout({ name: 'preset' } as any)
    if (running) running.stop()
  } catch (_) {}
  const inst = cy
  cy = null
  try { inst.destroy() } catch (_) {}
}

onMounted(() => { nextTick(buildCytoscape) })
onUnmounted(destroyCy)

watch(() => props.resetTrigger, () => { destroyCy(); nextTick(buildCytoscape) })
watch(() => [props.nodes, props.edges, props.style, props.hiddenIds], () => { destroyCy(); nextTick(buildCytoscape) }, { deep: false })

watch(() => props.repulsion, (v) => {
  if (!cy || props.style === 'dagre') return
  try {
    const layout = cy.layout({
      name: 'cose', idealEdgeLength: 200, nodeRepulsion: v || 15000,
      gravity: 1.5, fit: true, padding: 40, animate: true,
      animationDuration: 800, numIter: 2000,
    })
    layout.run()
  } catch (_) {}
})

watch(() => props.recenterTrigger, () => {
  if (!cy) return
  cy.resize()
  cy.fit(undefined, 30)
  cy.center()
})
</script>

<template>
  <div class="cytoscape-graph">
    <div ref="container" class="cg-container" />
    <div ref="tooltip" class="cg-tooltip" />
  </div>
</template>

<style scoped>
.cytoscape-graph {
  display: flex; flex-direction: column; flex: 1; width: 100%; min-height: 0; position: relative;
}
.cg-container {
  flex: 1; width: 100%; min-height: 0;
}
.cg-tooltip {
  display: none;
  position: fixed; z-index: 9999;
  pointer-events: none;
  padding: 0.35rem 0.6rem;
  background: rgba(18, 22, 30, 0.95);
  border: 1px solid rgba(99, 102, 241, 0.4);
  border-radius: 0.3rem;
  max-width: 340px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}
.cg-tip-name {
  font-size: 0.75rem; font-weight: 600;
  color: #e5e7eb; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.cg-tip-id {
  font-size: 0.6rem; color: #9ca3af;
  font-family: var(--font-mono, monospace);
  margin-top: 0.1rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.cg-tip-meta {
  font-size: 0.6rem; color: #a5b4fc;
  margin-top: 0.2rem;
}
</style>
