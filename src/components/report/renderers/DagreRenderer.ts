import * as d3 from 'd3'
import dagre from 'dagre'
import { getNodeRadius, nodeColor, type GraphNode, type GraphEdge } from './types'

export interface DagreRenderContext {
  svg: d3.Selection<SVGSVGElement, unknown, null, undefined>
  width: number
  height: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  highlightedIds?: Set<string>
  onDblClick: (nodeId: string) => void
  onContextMenu: (nodeId: string) => void
}

export function renderDagreGraph(ctx: DagreRenderContext): void {
  const { svg, width, height, nodes, edges, highlightedIds, onDblClick, onContextMenu } = ctx

  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 50, ranksep: 80, edgesep: 20, marginx: 30, marginy: 30 })
  g.setDefaultEdgeLabel(() => ({}))

  const nodeMap = new Map<string, any>()
  nodes.forEach((n) => {
    const r = getNodeRadius(n)
    const nd = { id: n.id, label: n.label, width: r * 3 + 40, height: r * 2 + 10, _data: n, _radius: r }
    g.setNode(n.id, nd)
    nodeMap.set(n.id, nd)
  })

  edges.forEach(e => {
    if (nodeMap.has(e.source) && nodeMap.has(e.target)) {
      g.setEdge(e.source, e.target, {})
    }
  })

  dagre.layout(g)

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  g.nodes().forEach(id => {
    const nd = g.node(id)
    if (!nd) return
    minX = Math.min(minX, nd.x - nd.width / 2)
    minY = Math.min(minY, nd.y - nd.height / 2)
    maxX = Math.max(maxX, nd.x + nd.width / 2)
    maxY = Math.max(maxY, nd.y + nd.height / 2)
  })

  const pad = 30
  const gW = maxX - minX + pad * 2
  const gH = maxY - minY + pad * 2
  const scaleX = width / gW
  const scaleY = height / gH
  const scale = Math.min(scaleX, scaleY, 1.2)
  const tx = (width - gW * scale) / 2 - minX * scale + pad * scale
  const ty = (height - gH * scale) / 2 - minY * scale + pad * scale

  const container = svg.append('g').attr('transform', `translate(${tx},${ty}) scale(${scale})`)

  const defs = svg.append('defs')
  edges.forEach((_e, i) => {
    defs.append('marker')
      .attr('id', `dagre-arrow-${i}`)
      .attr('viewBox', '0 0 8 6')
      .attr('refX', 8).attr('refY', 3)
      .attr('markerWidth', 6).attr('markerHeight', 4)
      .attr('orient', 'auto')
      .append('path').attr('d', 'M0,0 L8,3 L0,6 Z').attr('fill', '#9ca3af')
  })

  g.edges().forEach((e, i) => {
    const edge = g.edge(e)
    if (!edge || !edge.points || edge.points.length < 2) return
    const pts = edge.points as Array<{ x: number; y: number }>

    const targetNode = g.node(e.w) as any
    const lastPt = pts[pts.length - 1]
    const prevPt = pts[pts.length - 2]
    const angle = Math.atan2(lastPt.y - prevPt.y, lastPt.x - prevPt.x)
    const tr = targetNode?._radius || 20
    const adjustedX = lastPt.x - Math.cos(angle) * (tr + 4)
    const adjustedY = lastPt.y - Math.sin(angle) * (tr + 4)

    const pathData = pts.map((p, j) => {
      if (j === pts.length - 1) return `${adjustedX},${adjustedY}`
      return `${p.x},${p.y}`
    })

    container.append('polyline')
      .attr('points', pathData.join(' '))
      .attr('fill', 'none')
    .attr('stroke', '#9ca3af')
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 0.6)
      .attr('marker-end', `url(#dagre-arrow-${i})`)
  })

  const nodeGs = container.selectAll('g.node').data(nodes).enter().append('g')

  nodeGs.each(function (d) {
    const el = d3.select(this)
    const nd = g.node(d.id) as any
    if (!nd) return
    const r = nd._radius || 20
    const cx = nd.x
    const cy = nd.y
    const hl = highlightedIds?.has(d.id)
    const color = d.isMerged ? '#6b7280' : nodeColor(d)
    const opacity = d.isMerged ? 0.08 : (hl ? 0.3 : 0.15)
    const strokeW = d.isMerged ? 1.5 : (d.hasChildren ? 2 : 1)

    el.append('circle')
      .attr('cx', cx).attr('cy', cy).attr('r', r)
      .attr('fill', color)
      .attr('fill-opacity', opacity)
      .attr('stroke', color)
      .attr('stroke-width', hl ? 2.5 : strokeW)
      .attr('stroke-dasharray', d.isMerged ? '4,3' : 'none')
      .attr('stroke-opacity', hl ? 1 : 0.7)

    if (d.hasChildren && !d.isMerged) {
      el.append('circle')
        .attr('cx', cx).attr('cy', cy).attr('r', r + 3)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3,3')
        .attr('stroke-opacity', 0.4)
    }

    if (d.isMerged) {
      el.append('circle')
        .attr('cx', cx).attr('cy', cy).attr('r', r + 2)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '4,3')
        .attr('stroke-opacity', 0.5)
    }

    el.append('text')
      .attr('x', cx).attr('y', cy + 1)
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'central')
      .attr('fill', d.isMerged ? 'var(--text-muted, #6b7280)' : 'var(--text-primary, #e5e7eb)')
      .attr('font-size', `${Math.max(10, Math.min(12, r * 0.55))}px`)
      .attr('font-weight', d.status === 'completed' || d.isMerged ? 600 : 400)
      .attr('opacity', hl ? 1 : 0.85)
      .text(d.label.length > 12 ? d.label.slice(0, 12) + '\u2026' : d.label)

    el.append('title').text(d.isMerged
      ? `${d.label} \u2014 Click to expand`
      : `${d.label} (${d.nodeCount || 0} nodes)`)
  })

  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .filter((event) => {
      const el = event.target as Element
      return !el.closest('.node')
    })
    .scaleExtent([0.15, 4])
    .on('zoom', (event) => {
      container.attr('transform', event.transform)
    })
    .on('start', (event) => {
      const t = event.transform
      console.log('[DagreZoom] start  k=', t.k.toFixed(3), ' x=', t.x.toFixed(0), ' y=', t.y.toFixed(0))
    })
    .on('end', (event) => {
      const t = event.transform
      console.log('[DagreZoom] end    k=', t.k.toFixed(3), ' x=', t.x.toFixed(0), ' y=', t.y.toFixed(0))
    })
  svg.call(zoom)
  svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale))
  console.log('[DagreZoom] init   k=', scale.toFixed(3), ' tx=', tx.toFixed(0), ' ty=', ty.toFixed(0))

  nodeGs.on('dblclick', (_event: MouseEvent, d: any) => {
    if (d.isMerged || d.hasChildren) onDblClick(d.id)
    _event.stopPropagation()
  })
  nodeGs.on('contextmenu', (_event: MouseEvent, d: any) => {
    _event.preventDefault()
    if (!d.isMerged) onContextMenu(d.id)
  })
}
