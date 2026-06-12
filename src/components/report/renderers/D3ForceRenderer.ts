import * as d3 from 'd3'
import { getNodeRadius, nodeColor, type GraphNode, type GraphEdge } from './types'

export interface ForceRenderContext {
  svg: d3.Selection<SVGSVGElement, unknown, null, undefined>
  width: number
  height: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  highlightedIds?: Set<string>
  onDblClick: (nodeId: string) => void
  onContextMenu: (nodeId: string) => void
  onDragEnd: (nodeId: string, x: number, y: number) => void
}

export function renderForceGraph(ctx: ForceRenderContext): d3.Simulation<any, any> | null {
  const { svg, width, height, nodes, edges, highlightedIds, onDblClick, onContextMenu, onDragEnd } = ctx

  const simNodes = nodes.map((n) => ({
    id: n.id,
    _data: n,
    _radius: getNodeRadius(n),
    x: width / 2 + (Math.random() - 0.5) * 100,
    y: height / 2 + (Math.random() - 0.5) * 100,
  }))

  const nodeById = new Map(simNodes.map(n => [n.id, n]))
  const simLinks = edges
    .filter(e => nodeById.has(e.source) && nodeById.has(e.target))
    .map(e => ({ source: e.source, target: e.target }))

  const defs = svg.append('defs')
  defs.append('marker')
    .attr('id', 'force-arrow')
    .attr('viewBox', '0 0 8 6')
    .attr('refX', 8).attr('refY', 3)
    .attr('markerWidth', 5).attr('markerHeight', 3)
    .attr('orient', 'auto')
    .append('path').attr('d', 'M0,0 L8,3 L0,6 Z').attr('fill', '#9ca3af')

  const linkG = svg.append('g').attr('class', 'force-links')
  const nodeG = svg.append('g').attr('class', 'force-nodes')

  const simulation = d3.forceSimulation(simNodes)
    .force('link', d3.forceLink(simLinks).id((d: any) => d.id).distance(120))
    .force('charge', d3.forceManyBody().strength(-300))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius((d: any) => d._radius + 8))

  const link = linkG.selectAll('line')
    .data(simLinks)
    .enter().append('line')
    .attr('stroke', '#9ca3af')
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 0.55)
    .attr('marker-end', 'url(#force-arrow)')

  const nodeEl = nodeG.selectAll('g.node')
    .data(simNodes)
    .enter().append('g')
    .attr('class', 'node')

  nodeEl.each(function (d) {
    const el = d3.select(this)
    const r = d._radius
    const data = d._data
    const hl = highlightedIds?.has(data.id)
    const color = data.isMerged ? '#6b7280' : nodeColor(data)
    const opacity = data.isMerged ? 0.08 : (hl ? 0.3 : 0.15)
    const strokeW = data.isMerged ? 1.5 : (data.hasChildren ? 2 : 1)

    el.append('circle')
      .attr('r', r)
      .attr('fill', color)
      .attr('fill-opacity', opacity)
      .attr('stroke', color)
      .attr('stroke-width', hl ? 2.5 : strokeW)
      .attr('stroke-dasharray', data.isMerged ? '4,3' : 'none')
      .attr('stroke-opacity', hl ? 1 : 0.7)

    if (data.hasChildren && !data.isMerged) {
      el.append('circle')
        .attr('r', r + 3)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3,3')
        .attr('stroke-opacity', 0.4)
    }

    if (data.isMerged) {
      el.append('circle')
        .attr('r', r + 2)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '4,3')
        .attr('stroke-opacity', 0.5)
    }

    el.append('text')
      .attr('text-anchor', 'middle')
      .attr('dominant-baseline', 'central')
      .attr('fill', data.isMerged ? 'var(--text-muted, #6b7280)' : 'var(--text-primary, #e5e7eb)')
      .attr('font-size', `${Math.max(10, Math.min(12, r * 0.55))}px`)
      .attr('font-weight', data.status === 'completed' || data.isMerged ? 600 : 400)
      .attr('opacity', hl ? 1 : 0.85)
      .text(data.label.length > 12 ? data.label.slice(0, 12) + '\u2026' : data.label)

    el.append('title').text(data.isMerged
      ? `${data.label} \u2014 ${data.nodeCount} nodes \u2014 Click to expand`
      : `${data.label} \u2014 ${data.id} \u2014 ${data.nodeCount || 0} nodes`)

    el.call(
      d3.drag<any, any>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart()
          d.fx = d.x; d.fy = d.y
        })
        .on('drag', (event, d) => {
          d.fx = event.x; d.fy = event.y
        })
        .on('end', (_event, d) => {
          if (!_event.active) simulation.alphaTarget(0)
          onDragEnd(d.id, d.x, d.y)
        })
    )
  })

  simulation.on('tick', () => {
    const maxDist = Math.min(width, height) * 0.55
    const cx = width / 2
    const cy = height / 2
    simNodes.forEach((d: any) => {
      const dx = d.x - cx
      const dy = d.y - cy
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (dist > maxDist && dist > 0) {
        const push = (dist - maxDist) * 0.08
        d.x -= (dx / dist) * push
        d.y -= (dy / dist) * push
      }
    })
    link
      .attr('x1', (d: any) => d.source.x)
      .attr('y1', (d: any) => d.source.y)
      .attr('x2', (d: any) => {
        const dx = d.target.x - d.source.x
        const dy = d.target.y - d.source.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const tr = (d.target._radius || 20) + 6
        return d.target.x - (dx / dist) * tr
      })
      .attr('y2', (d: any) => {
        const dx = d.target.x - d.source.x
        const dy = d.target.y - d.source.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const tr = (d.target._radius || 20) + 6
        return d.target.y - (dy / dist) * tr
      })

    nodeEl.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
  })

  const zoom = d3.zoom<SVGSVGElement, unknown>()
    .filter((event) => {
      const el = event.target as Element
      return !el.closest('.node')
    })
    .scaleExtent([0.15, 4])
    .on('zoom', (event) => {
      nodeG.attr('transform', event.transform)
      linkG.attr('transform', event.transform)
    })
    .on('start', (event) => {
      const t = event.transform
      console.log('[ForceZoom] start k=', t.k.toFixed(3), ' x=', t.x.toFixed(0), ' y=', t.y.toFixed(0))
    })
    .on('end', (event) => {
      const t = event.transform
      console.log('[ForceZoom] end   k=', t.k.toFixed(3), ' x=', t.x.toFixed(0), ' y=', t.y.toFixed(0))
    })
  svg.call(zoom)
  console.log('[ForceZoom] init  k=1.000  x=0  y=0')

  nodeEl.on('dblclick', (_event: MouseEvent, d: any) => {
    if (d._data.isMerged || d._data.hasChildren) onDblClick(d._data.id)
    _event.stopPropagation()
  })
  nodeEl.on('contextmenu', (_event: MouseEvent, d: any) => {
    _event.preventDefault()
    if (!d._data.isMerged) onContextMenu(d._data.id)
  })

  return simulation
}
