<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import cytoscape from 'cytoscape'
import { useComponentSelectionStore } from '@/stores/component-selection-store'

export interface GraphNode {
  id: string
  label: string
  nodeCount?: number
  qualityScore?: number | null
  avgCoreness?: number
  maxCoreness?: number
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
  style: 'force'
  highlightedIds?: Set<string>
  hiddenIds?: Set<string>
  resetTrigger?: number
  recenterTrigger?: number
  lockMode?: 'linked' | 'locked'
  repulsion?: number
  zoomLevel?: number
  fontSize?: number
  fullscreen?: boolean
  positions?: Record<string, { x: number; y: number }>
  showGuideButton?: boolean
  selectMode?: boolean
}>()

const emit = defineEmits<{
  'node-dblclick': [nodeId: string]
  'node-context-menu': [nodeId: string]
  'node-drag-end': [nodeId: string, x: number, y: number]
  'zoom-changed': [level: number]
  'guide-click': []
  'selection-changed': [nodeIds: string[]]
}>()

const selectionStore = useComponentSelectionStore()

const container = ref<HTMLDivElement>()
const tooltip = ref<HTMLDivElement>()
let cy: cytoscape.Core | null = null

function getNodeRadius(n: GraphNode): number {
  const baseCount = n.nodeCount || 5
  const coreBoost = n.avgCoreness ? 1 + Math.min(n.avgCoreness / 10, 0.5) : 1
  const countRadius = (Math.sqrt(baseCount) * 3 + 14) * coreBoost
  const textRadius = Math.min(n.label.length * 2 + 14, 38)
  return Math.round(Math.max(textRadius, Math.min(40, countRadius)))
}

const EXTERNAL_TIER_COLORS = ['#b45309', '#d97706', '#f59e0b', '#fbbf24', '#fde68a']

function nodeColor(n: GraphNode): string {
  if (n.compareState === 'added') return '#22c55e'
  if (n.compareState === 'removed') return '#ef4444'
  if (n.compareState === 'changed') return '#f97316'
  if (n.compareState === 'unchanged') return '#6b7280'
  if (n.isExternal) {
    const tier = (n as any)._extTier
    return tier ? EXTERNAL_TIER_COLORS[tier - 1] || '#f59e0b' : '#f59e0b'
  }
  if (n.avgCoreness != null && n.avgCoreness >= 0.5) {
    const t = Math.min(n.avgCoreness / 8, 1)
    return corenessGradient(t)
  }
  return '#60a5fa'
}

function corenessGradient(t: number): string {
  const r = Math.round(59 + (239 - 59) * t)
  const g = Math.round(130 + (68 - 130) * t)
  const b = Math.round(246 + (68 - 246) * t)
  return `rgb(${r},${g},${b})`
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
          label: n.label.length > 24 ? n.label.slice(0, 23) + '\u2026' : n.label,
          _label: n.label,
          _nodeCount: n.nodeCount || 0,
          _hasChildren: !!n.hasChildren,
          _isMerged: !!n.isMerged,
          _isExternal: !!n.isExternal,
          _isFile: !!n.isFile,
          _compareState: n.compareState || '',
          _highlighted: hl.has(n.id),
          _color: color,
          _radius: r,
        },
        classes: n.isMerged ? 'merged' : (n.isFile ? 'file' : (n.hasChildren ? 'drillable' : 'leaf')),
        selected: false,
        locked: false,
      }
    })

  const edgeIdSet = new Set(cyNodes.map(n => n.data.id))
  const cyEdges: { group: 'edges'; data: { id: string; source: string; target: string; _count: number; _bidirectional?: boolean } }[] = (() => {
    const edgeMap = new Map<string, (typeof props.edges)[0]>()
    for (const e of props.edges) {
      if (!edgeIdSet.has(e.source) || !edgeIdSet.has(e.target)) continue
      const key = `${e.source}→${e.target}`
      if (!edgeMap.has(key)) edgeMap.set(key, e)
    }
    const result: { group: 'edges'; data: { id: string; source: string; target: string; _count: number; _bidirectional?: boolean } }[] = []
    const seen = new Set<string>()
    for (const [key, e] of edgeMap) {
      if (seen.has(key)) continue
      const revKey = `${e.target}→${e.source}`
      const isBi = edgeMap.has(revKey)
      if (isBi) seen.add(revKey)
      seen.add(key)
      result.push({
        group: 'edges',
        data: {
          id: isBi ? `${e.source}↔${e.target}` : key,
          source: e.source,
          target: e.target,
          _count: e.count || 0,
          _bidirectional: isBi,
        },
      })
    }
    return result
  })()

  const fs = (props.fontSize || 10) + 4
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
        'font-size': `${fs}px`,
        'color': '#e5e7eb',
        'label': 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': `${fs * 12}px`,
        'min-zoomed-font-size': Math.max(4, fs * 0.5),
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
      selector: 'node.file',
      style: { 'shape': 'round-rectangle', 'border-style': 'solid', 'border-width': 1, 'background-opacity': 0.12 },
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
    {
      selector: 'edge[_bidirectional]',
      style: {
        'source-arrow-shape': 'triangle',
        'source-arrow-color': '#9ca3af',
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
    if (node.data('_isMerged')) return
    emit('node-dblclick', node.id())
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

  cy.on('grab', 'node', (evt: any) => {
    const node = evt.target
    if (node.data('_isMerged')) return
    dragNodeId = node.id()
    dragPrevPos = { ...node.position() }
    console.log('[CytoscapeGraph] grab', dragNodeId, 'pos:', dragPrevPos.x.toFixed(1), dragPrevPos.y.toFixed(1))
    if (props.lockMode === 'locked') {
      cy?.nodes().forEach(n => { if (!n.same(node) && !n.data('_isMerged')) n.lock() })
    }
  })
  cy.on('free', 'node', (evt: any) => {
    const node = evt.target
    if (node.data('_isMerged')) return
    if (dragNodeId === node.id()) {
      const pos = node.position()
      console.log('[CytoscapeGraph] free → emit node-drag-end', node.id(), 'pos:', pos.x.toFixed(1), pos.y.toFixed(1))
      emit('node-drag-end', node.id(), pos.x, pos.y)
    }
    dragNodeId = ''
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

    scheduleOffScreenCheck()

    if (isoNodes.length === 0) return

    const cols = Math.min(isoNodes.length, 6)
    const spacing = 60
    const gridW = (cols - 1) * spacing
    const maxR = Math.max(...isoNodes.map(n => n.data('_radius') as number))
    const gridY = bb.y2 + maxR + 15
    const startX = cx - gridW / 2

    isoNodes.forEach((n, i) => {
      if (props.positions?.[n.id()]) return
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
    { name: 'cose', idealEdgeLength: 100, nodeRepulsion: props.repulsion || 8000, nodeOverlap: 20, padding: 20, fit: false, animate: false, numIter: 4000 }
  )

  lastAppliedRepulsion = props.repulsion || 8000
  cy.one('layoutstop', () => {
    if (!cy) return
    cy.zoom(1.0)
    centerOnConnected()
    applyPresetPositions()
  })
  layout.run()

  cy.on('zoom', () => {
    emit('zoom-changed', cy?.zoom() ?? 1)
  })

  if (selectionStore.selecting) {
    cy.boxSelectionEnabled(true)
    cy.autounselectify(false)
  }
  cy.on('select unselect', 'node', () => {
    if (!selectionStore.selecting) return
    const ids = cy?.nodes(':selected').map(n => n.id()) ?? []
    emit('selection-changed', ids)
  })

  cy.on('viewport', () => { scheduleOffScreenCheck() })

  cy.on('mouseover', 'node', (evt) => {
    const node = evt.target
    const d = node.data()
    if (d._isMerged) return
    node.style({ 'background-opacity': 0.4, 'border-opacity': 1, 'text-opacity': 1 })
    container.value!.style.cursor = 'pointer'

    if (!tooltip.value) return
    const drillInfo = d._isFile ? '可双击查看摘要' : d._hasChildren ? '可双击下钻' : '可双击查看文件'
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
  const inst = cy
  cy = null
  try { inst.layout().stop() } catch (_) {}
  try { inst.destroy() } catch (_) {}
}

function centerOnConnected() {
  if (!cy) return
  const connected = cy.nodes().filter((n: any) => n.degree(false) > 0 && !n.data('_isMerged'))
  if (connected.empty()) { cy.center(); return }
  cy.center(connected)
}

let applyingPreset = false

function applyPresetPositions() {
  if (applyingPreset || !cy || !props.positions) return
  const pos = props.positions
  const preset: Record<string, { x: number; y: number }> = {}
  const totalNodes = cy.nodes().length
  cy.nodes().forEach((n: any) => {
    const id = n.data('id')
    if (pos[id]) {
      preset[id] = { x: pos[id].x, y: pos[id].y }
    }
  })
  if (Object.keys(preset).length === 0) return
  const sampleIds = Object.keys(preset).slice(0, 3)
  console.log('[CytoscapeGraph] applyPresetPositions style=', props.style, 'matching nodes=', Object.keys(preset).length, '/', totalNodes, 'sample=', sampleIds.map(id => `${id}=(${preset[id].x.toFixed(0)},${preset[id].y.toFixed(0)})`))
  applyingPreset = true
  try {
    try { cy!.layout().stop() } catch (_) {}
    cy!.layout({ name: 'preset', positions: preset, fit: false } as any).run()
  } catch (_) {}
  applyingPreset = false
}

let repulsionTimer: ReturnType<typeof setTimeout> | null = null
let lastAppliedRepulsion: number | undefined

onMounted(() => { nextTick(buildCytoscape) })
onUnmounted(() => { if (repulsionTimer) clearTimeout(repulsionTimer); if (offScreenTimer) clearTimeout(offScreenTimer); destroyCy() })

watch(() => props.resetTrigger, () => { destroyCy(); nextTick(buildCytoscape) })
watch(() => [props.nodes, props.edges, props.style, props.hiddenIds], () => { destroyCy(); nextTick(buildCytoscape) }, { deep: false })

watch(() => props.repulsion, (v) => {
  if (!cy) return
  const r = v || 15000
  if (r === lastAppliedRepulsion) return
  lastAppliedRepulsion = r
  if (repulsionTimer) clearTimeout(repulsionTimer)
  repulsionTimer = setTimeout(() => {
    try {
      const layout = cy!.layout({
        name: 'cose', idealEdgeLength: 100, nodeRepulsion: r,
        nodeOverlap: 20, padding: 20, fit: false, animate: true,
        animationDuration: 1500, numIter: 4000,
      })
      layout.run()
    } catch (_) {}
  }, 200)
})

watch(() => props.recenterTrigger, () => {
  if (!cy) return
  cy.resize()
  centerOnConnected()
})

watch(() => props.zoomLevel, (v) => {
  if (!cy || v == null) return
  if (Math.abs(cy.zoom() - v) < 0.01) return
  cy.zoom({ level: v, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } })
})

watch(() => props.fontSize, (v) => {
  if (!cy || v == null) return
  cy.style()
    .selector('node')
    .style({
      'font-size': `${v}px`,
      'text-max-width': `${v * 12}px`,
      'min-zoomed-font-size': Math.max(4, v * 0.5),
    })
    .update()
})

watch(() => props.positions, () => {
  applyPresetPositions()
})

watch(() => selectionStore.selecting, (v) => {
  if (!cy) return
  cy.boxSelectionEnabled(v)
  cy.autounselectify(!v)
  if (!v) {
    cy.elements().unselect()
  }
})

const offScreenDirs = ref(new Set<string>())
const DIRS = ['E', 'SE', 'S', 'SW', 'W', 'NW', 'N', 'NE'] as const

function checkOffScreen() {
  if (!cy) return
  const ext = cy.extent()
  const vpW = ext.x2 - ext.x1
  const vpH = ext.y2 - ext.y1
  const pad = Math.max(vpW, vpH) * 0.05
  const bx1 = ext.x1 + pad
  const by1 = ext.y1 + pad
  const bx2 = ext.x2 - pad
  const by2 = ext.y2 - pad
  const vpCx = (ext.x1 + ext.x2) / 2
  const vpCy = (ext.y1 + ext.y2) / 2

  const dirSet = new Set<string>()
  cy.nodes().forEach((n: any) => {
    if (n.data('_isMerged') || n.data('_hidden')) return
    const p = n.position()
    if (p.x >= bx1 && p.x <= bx2 && p.y >= by1 && p.y <= by2) return
    const angle = Math.atan2(p.y - vpCy, p.x - vpCx)
    const deg = ((angle * 180 / Math.PI) + 360) % 360
    const octant = Math.round(deg / 45) % 8
    dirSet.add(DIRS[octant])
  })
  offScreenDirs.value = dirSet
}

function offScreenTitle(dir: string): string {
  const map: Record<string, string> = {
    N: '上方有节点', NE: '右上方有节点', E: '右侧有节点', SE: '右下方有节点',
    S: '下方有节点', SW: '左下方有节点', W: '左侧有节点', NW: '左上方有节点',
  }
  return map[dir] || ''
}

function panDir(dir: string) {
  if (!cy) return
  const w = cy.width() * 0.25
  const h = cy.height() * 0.25
  const offsets: Record<string, { x: number; y: number }> = {
    E:  { x: -w, y: 0 },
    SE: { x: -w, y: -h },
    S:  { x: 0, y: -h },
    SW: { x: w, y: -h },
    W:  { x: w, y: 0 },
    NW: { x: w, y: h },
    N:  { x: 0, y: h },
    NE: { x: -w, y: h },
  }
  const off = offsets[dir]
  if (off) cy.panBy(off)
}

watch(offScreenDirs, () => {})

let offScreenTimer: ReturnType<typeof setTimeout> | null = null
function scheduleOffScreenCheck() {
  if (offScreenTimer) clearTimeout(offScreenTimer)
  offScreenTimer = setTimeout(checkOffScreen, 100)
}

function zoomIn() {
  if (!cy) return
  cy.zoom({ level: cy.zoom() * 1.2, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } })
}

function zoomOut() {
  if (!cy) return
  cy.zoom({ level: cy.zoom() / 1.2, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } })
}

function zoomTo(nodeId: string, animate = true) {
  if (!cy) return
  const node = cy.getElementById(nodeId)
  if (node.length === 0) return
  cy.animate(
    {
      center: { eles: node },
      zoom: 1.0,
      duration: animate ? 400 : 0,
    },
  )
}

defineExpose({
  getAllPositions: (): Record<string, { x: number; y: number }> => {
    if (!cy) return {}
    const result: Record<string, { x: number; y: number }> = {}
    cy.nodes().forEach((n: any) => {
      if (n.data('_isMerged')) return
      result[n.data('id')] = { x: n.position().x, y: n.position().y }
    })
    return result
  },
  zoomIn,
  zoomOut,
  zoomTo,
})
</script>

<template>
  <div class="cytoscape-graph">
    <div
      ref="container"
      class="cg-container"
    />
    <div
      ref="tooltip"
      class="cg-tooltip"
    />
    <div
      v-for="d in DIRS"
      v-show="offScreenDirs.has(d)"
      :key="d"
      :class="['cg-offscreen', `cg-offscreen-${d.toLowerCase()}`]"
      :style="props.fullscreen && ['se','s','sw'].includes(d.toLowerCase()) ? { bottom: '40px' } : undefined"
      :title="offScreenTitle(d)"
      @click.stop="panDir(d)"
    >
      <span class="cg-offscreen-arrow" />
    </div>
    <div
      class="cg-zoom-btns"
      :style="props.fullscreen ? { top: '52px' } : undefined"
    >
      <button
        class="cg-zoom-btn"
        title="缩小"
        @click="zoomOut"
      >
        −
      </button>
      <button
        class="cg-zoom-btn"
        title="放大"
        @click="zoomIn"
      >
        +
      </button>
    </div>
    <button
      v-if="showGuideButton !== false"
      class="cg-guide-btn"
      :style="props.fullscreen ? { bottom: '52px' } : undefined"
      @click="emit('guide-click')"
    >
      <svg
        class="w-4 h-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      ><path d="M2.25 12.76c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 0 1 1.037-.443 48.282 48.282 0 0 0 5.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z" /></svg>
    </button>
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

.cg-offscreen {
  position: absolute; z-index: 210;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
}
.cg-offscreen-arrow {
  display: block;
  width: 0; height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-bottom: 10px solid rgba(124, 58, 237, 0.7);
  filter: drop-shadow(0 0 3px rgba(124, 58, 237, 0.3));
}
.cg-offscreen-n  { top: 6px; left: 50%; transform: translateX(-50%); }
.cg-offscreen-n  .cg-offscreen-arrow { transform: rotate(0deg); }
.cg-offscreen-ne { top: 6px; right: 6px; }
.cg-offscreen-ne .cg-offscreen-arrow { transform: rotate(45deg); }
.cg-offscreen-e  { top: 50%; right: 6px; transform: translateY(-50%); }
.cg-offscreen-e  .cg-offscreen-arrow { transform: rotate(90deg); }
.cg-offscreen-se { bottom: 6px; right: 6px; }
.cg-offscreen-se .cg-offscreen-arrow { transform: rotate(135deg); }
.cg-offscreen-s  { bottom: 6px; left: 50%; transform: translateX(-50%); }
.cg-offscreen-s  .cg-offscreen-arrow { transform: rotate(180deg); }
.cg-offscreen-sw { bottom: 6px; left: 6px; }
.cg-offscreen-sw .cg-offscreen-arrow { transform: rotate(225deg); }
.cg-offscreen-w  { top: 50%; left: 6px; transform: translateY(-50%); }
.cg-offscreen-w  .cg-offscreen-arrow { transform: rotate(270deg); }
.cg-offscreen-nw { top: 6px; left: 6px; }
.cg-offscreen-nw .cg-offscreen-arrow { transform: rotate(315deg); }

.cg-zoom-btns {
  position: absolute; top: 12px; left: 12px; z-index: 211;
  display: flex; flex-direction: column; gap: 2px;
}
.cg-zoom-btn {
  width: 26px; height: 26px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.9rem; font-weight: 700;
  background: var(--bg-primary); color: var(--text-muted);
  border: 1px solid var(--border); cursor: pointer;
}
.cg-zoom-btn:first-child { border-radius: 0.25rem 0.25rem 0 0; }
.cg-zoom-btn:last-child { border-radius: 0 0 0.25rem 0.25rem; }
.cg-zoom-btn:hover { color: var(--text-primary); border-color: var(--accent); }

.cg-guide-btn {
  position: absolute; bottom: 12px; right: 12px; z-index: 211;
  width: 32px; height: 32px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem;
  background: var(--bg-primary); color: var(--accent);
  border: 1px solid var(--accent); border-radius: 50%;
  cursor: pointer; transition: all 0.15s;
}
.cg-guide-btn:hover {
  background: var(--accent); color: #fff;
  box-shadow: 0 0 8px rgba(124, 58, 237, 0.4);
}
</style>
