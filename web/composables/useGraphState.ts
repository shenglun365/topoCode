import { ref, computed, nextTick } from 'vue'
import * as api from '@web/services/api'
import type { GraphNode, GraphEdge, CommunityChild } from '@web/types'
import cytoscape from 'cytoscape'
import coseBilkent from 'cytoscape-cose-bilkent'
import { useGraphLayout } from './useGraphLayout'
cytoscape.use(coseBilkent)

export function useGraphState(taskId: ReturnType<typeof ref<string>>) {
  console.log('[useGraphState] init')
  const { applyNodeColors, _buildLayout, _afterLayout } = useGraphLayout()

  const urlCid = new URLSearchParams(location.search).get('communityId') || new URLSearchParams(location.search).get('cid') || ''
  const urlEt = new URLSearchParams(location.search).get('edgeType') || 'INCLUDE'

  // ── Graph state ──
  const graphCommId = ref(urlCid)
  const graphEdgeType = ref(urlEt)
  const graphBreadcrumb = ref<{ cid: string; et: string; label?: string }[]>([])
  const graphNodes = ref<GraphNode[]>([])
  const graphEdges = ref<GraphEdge[]>([])
  const graphLoading = ref(false)
  const cyContainer = ref<HTMLDivElement>()
  const externalGraphData = ref<any>(null)
  const followMode = ref(true)
  const showEdges = ref(true)
  const gran = ref('component')
  const graphTab = ref<'graph' | 'heatmap'>('graph')
  const toolbarCollapsed = ref(false)
  const toolbarTitle = ref('图谱操作')
  const isHeatmap = computed(() => graphTab.value === 'heatmap')
  const rightCommTree = ref<CommunityChild[]>([])
  const rightDepth = ref(1)
  const layoutTimeout = ref(60)
  const etOptions = ['INCLUDE', 'CALL', 'EXTERNAL_INCLUDE', 'EXTERNAL_CALL'] as const

  // ── Filter state ──
  const filterVisible = ref(false)
  const filterQuery = ref('')
  const filterToggleState = ref('hideOrphan')
  const filterNodeList = ref<{ id: string; label: string }[]>([])
  const filteredNodeList = computed(() => {
    if (!filterQuery.value) return filterNodeList.value
    const q = filterQuery.value.toLowerCase()
    return filterNodeList.value.filter(n => n.label.toLowerCase().includes(q))
  })

  // ── Context menu state ──
  const contextMenuVisible = ref(false)
  const contextMenuPos = ref({ x: 0, y: 0 })
  const contextNodeId = ref('')
  const contextNodeIsExternal = ref(false)
  const contextNodeHasChildren = ref(true)
  let ctxMenuTimer: any = null

  // ── Internal mutable state (non-reactive for perf) ──
  let _cy: any = null
  let _manualHidden = new Set<string>()
  let _manualShown = new Set<string>()
  let _centerNodes: string[] = []
  let _dragPrevPos: { x: number; y: number } | null = null

  function getCy() { return _cy }
  function getManualHidden() { return _manualHidden }
  function getManualShown() { return _manualShown }
  function getCenterNodes() { return _centerNodes }

  function pushGraphBc(item: { cid: string; et: string; label?: string }) {
    const last = graphBreadcrumb.value[graphBreadcrumb.value.length - 1]
    if (last?.cid === item.cid) return
    graphBreadcrumb.value.push(item)
  }

  // ── Graph loading & rendering ──
  async function loadGraph() {
    graphLoading.value = true
    try {
      const et = graphEdgeType.value
      if (et === 'EXTERNAL_INCLUDE' || et === 'EXTERNAL_CALL') {
        const data = await api.get('/api/external-graph', { task_id: taskId.value, edge_type: et, depth: String(rightDepth.value), comm_id: graphCommId.value || '' })
        externalGraphData.value = data
        graphNodes.value = data.nodes || []; graphEdges.value = data.edges || []
      } else {
        const graph = await api.getCommunityGraph(taskId.value, et, graphCommId.value || undefined, gran.value, rightDepth.value)
        graphNodes.value = graph.nodes; graphEdges.value = graph.edges
      }
    } catch (e) { console.error(e) } finally { graphLoading.value = false }
    nextTick(() => renderGraph())
  }

  function renderGraph() {
    if (!cyContainer.value || !graphNodes.value.length) return
    if (_cy) { _cy.destroy(); _cy = null }
    const container = cyContainer.value

    const elements: any[] = []
    for (const n of graphNodes.value) elements.push({ data: { id: n.id, label: n.label } })
    for (const e of graphEdges.value) elements.push({ data: { id: e.id, source: e.source, target: e.target } })

    try {
      _cy = cytoscape({
        container, elements,
        style: [
          { selector: 'node', style: { 'background-color': '#4d6bfe', label: 'data(label)', 'font-size': '11px', 'text-valign': 'center', 'text-halign': 'center', width: 30, height: 30 } },
          { selector: 'edge', style: { width: 1.5, 'line-color': '#6b6b76', 'target-arrow-color': '#6b6b76', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier' } },
          { selector: 'node.hidden', style: { display: 'none' } },
          { selector: 'node.center-highlight', style: { 'border-color': '#f59e0b', 'border-width': 3 } },
        ],
        layout: _buildLayout(_cy, graphNodes.value.length),
      })
      applyNodeColors(_cy)
      toolbarTitle.value = `图操作（${graphNodes.value.length} 节点 / ${graphEdges.value.length} 边）`
      setupFollowMode()
    } catch (e) { console.warn('[renderGraph] failed:', e); return }
    _afterLayout(_cy)
    loadSavedLayout()
    setupNodeEvents()
    // Update filter node list if filter is open
    if (filterVisible.value && _cy) {
      filterNodeList.value = _cy.nodes().map((n: any) => ({ id: n.id(), label: n.data('label') || n.id() }))
    }
  }

  function setupFollowMode() {
    _dragPrevPos = null
    _cy.off('grab drag free', 'node')
    if (followMode.value) {
      _cy.on('drag', 'node', (evt: any) => {
        const node = evt.target; const pos = node.position()
        if (!_dragPrevPos) { _dragPrevPos = { x: pos.x, y: pos.y }; return }
        const dx = pos.x - _dragPrevPos.x; const dy = pos.y - _dragPrevPos.y
        if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return
        _dragPrevPos = { x: pos.x, y: pos.y }
        const neighbors = node.closedNeighborhood().nodes().filter((n: any) => !n.same(node))
        neighbors.forEach((n: any) => { const np = n.position(); n.position({ x: np.x + dx * 0.7, y: np.y + dy * 0.7 }) })
      })
      _cy.on('free', 'node', () => { _dragPrevPos = null })
    } else {
      _cy.on('grab', 'node', (evt: any) => {
        const grabbed = evt.target
        _cy.nodes().forEach((n: any) => { if (!n.same(grabbed)) n.lock() })
      })
      _cy.on('free', 'node', () => { if (_cy) _cy.nodes().unlock() })
    }
  }

  function loadSavedLayout() {
    api.get('/api/graph-layout', { taskId: taskId.value, commId: graphCommId.value || '', edgeType: graphEdgeType.value, gran: gran.value, depth: String(rightDepth.value) }).then((saved: any) => {
      if (saved?.nodes && Object.keys(saved.nodes).length) {
        for (const [id, pos] of Object.entries(saved.nodes) as [string, any][]) {
          const n = _cy.getElementById(id); if (n.length) n.position({ x: pos.x, y: pos.y })
        }
        _cy.layout({ name: 'preset', fit: true }).run()
      }
    }).catch(() => {})
  }

  function setupNodeEvents() {
    _cy.on('dragfree', () => {
      const nodes: Record<string, any> = {}
      _cy.nodes().forEach((n: any) => { const p = n.position(); nodes[n.id()] = { x: p.x, y: p.y } })
      api.post('/api/graph-layout', { taskId: taskId.value, commId: graphCommId.value || '', edgeType: graphEdgeType.value, gran: gran.value, depth: rightDepth.value, nodes } as any).catch(() => {})
      contextMenuVisible.value = false
      if (ctxMenuTimer) { clearTimeout(ctxMenuTimer); ctxMenuTimer = null }
    })
    _cy.on('dblclick', 'node', (evt: any) => {
      const nid = evt.target.id()
      if (nid === graphCommId.value) return
      const label = graphNodes.value.find(n => n.id === nid)?.label || nid.slice(0, 16)
      pushGraphBc({ cid: nid, et: graphEdgeType.value, label })
      graphCommId.value = nid
      if (evt.target.data('hasChildren') === false) gran.value = 'file'
      loadGraph()
      loadRightCommTree()
    })
    _cy.on('dblclick', (evt: any) => { if (evt.target === _cy) _cy.fit(undefined, 50) })
    // Context menu on node tap (left-click as legacy)
    _cy.on('tap', 'node', (evt: any) => {
      const node = evt.target
      const nid = node.id()
      const isExt = !!node.data('isExternal')
      const hasChildren = node.data('hasChildren') !== false
      contextNodeId.value = nid
      contextNodeIsExternal.value = isExt
      contextNodeHasChildren.value = hasChildren
      const cyRect = _cy.container().getBoundingClientRect()
      const pos = node.renderedPosition()
      let mx = cyRect.left + pos.x, my = cyRect.top + pos.y
      const mw = 150, mh = 180
      if (mx + mw > window.innerWidth) mx = window.innerWidth - mw - 4
      if (my + mh > window.innerHeight) my = window.innerHeight - mh - 4
      contextMenuPos.value = { x: Math.max(0, mx), y: Math.max(0, my) }
      contextMenuVisible.value = true
      evt.stopPropagation()
      if (ctxMenuTimer) { clearTimeout(ctxMenuTimer); ctxMenuTimer = null }
      ctxMenuTimer = setTimeout(() => { contextMenuVisible.value = false; ctxMenuTimer = null }, 15000)
    })
    _cy.on('tap', (evt: any) => {
      if (evt.target === _cy) { contextMenuVisible.value = false; if (ctxMenuTimer) { clearTimeout(ctxMenuTimer); ctxMenuTimer = null } }
    })
  }

  // ── Graph operations ──
  function setEdgeType(et: string) {
    graphEdgeType.value = et
    if (et.startsWith('EXTERNAL_')) gran.value = 'component'
    if (gran.value === 'file' && (et === 'EXTERNAL_INCLUDE' || et === 'EXTERNAL_CALL')) {
      graphEdgeType.value = et === 'EXTERNAL_INCLUDE' ? 'INCLUDE' : 'CALL'
    }
    graphCommId.value = ''
    graphBreadcrumb.value = []
    loadGraph()
    loadRightCommTree()
  }

  async function loadRightCommTree() {
    try {
      const kids = await api.getCommunityChildren(taskId.value, graphCommId.value || undefined, graphEdgeType.value)
      rightCommTree.value = kids
    } catch (_) { rightCommTree.value = [] }
  }

  function navigateComm(cid: string, name?: string) {
    graphCommId.value = cid
    pushGraphBc({ cid, et: graphEdgeType.value, label: name || cid.slice(0, 16) })
    loadGraph()
    loadRightCommTree()
  }

  function toggleFollowMode() {
    followMode.value = !followMode.value
    if (_cy) {
      _cy.off('grab drag free', 'node')
      _dragPrevPos = null
      setupFollowMode()
    }
  }

  function toggleEdges() {
    showEdges.value = !showEdges.value
    if (_cy) showEdges.value ? _cy.edges().show() : _cy.edges().hide()
  }

  function toggleGran() { gran.value = gran.value === 'component' ? 'file' : 'component'; loadGraph() }

  function heatmapDrill(cid: string) {
    const hmLabel = graphNodes.value.find((n: any) => n.id === cid)?.label || cid.slice(0, 16)
    pushGraphBc({ cid, et: graphEdgeType.value, label: hmLabel })
    graphCommId.value = cid
    loadGraph()
    loadRightCommTree()
    graphTab.value = 'heatmap'
  }

  function resetLayout() {
    if (!_cy) return
    _centerNodes = []
    _manualHidden.clear()
    _manualShown.clear()
    filterQuery.value = ''
    filterToggleState.value = 'hideOrphan'
    _cy.nodes().removeClass('hidden center-highlight').show()
    _cy.edges().show()
    api.del('/api/graph-layout', { taskId: taskId.value, commId: graphCommId.value || '', edgeType: graphEdgeType.value, gran: gran.value, depth: rightDepth.value } as any).catch(() => {})
    _cy.layout(_buildLayout(_cy, _cy.nodes().length)).run()
    _afterLayout(_cy)
  }

  // ── Filter ──
  function toggleFilter() {
    filterVisible.value = !filterVisible.value
    if (filterVisible.value && _cy) {
      filterNodeList.value = _cy.nodes().map((n: any) => ({ id: n.id(), label: n.data('label') || n.id() }))
    }
  }

  function applyFilter() {
    if (!_cy) return
    const q = filterQuery.value.toLowerCase().trim()
    _cy.nodes().forEach((n: any) => {
      if (_manualHidden.has(n.id())) { n.hide(); return }
      if (_manualShown.has(n.id())) { n.show(); return }
      if (q && !n.data('label').toLowerCase().includes(q)) { n.hide(); return }
      n.show()
    })
  }

  function cycleFilter() {
    if (!_cy) return
    const total = _cy.nodes()
    const candidates = _centerNodes.length > 0 ? total.filter((n: any) => !n.hidden()) : total
    if (filterToggleState.value === 'hideOrphan') {
      const isolated = candidates.filter((n: any) => n.degree(false) === 0)
      if (isolated.length > 0) { isolated.hide(); isolated.forEach((n: any) => _manualHidden.add(n.id())) }
      filterToggleState.value = 'hideAll'
    } else if (filterToggleState.value === 'hideAll') {
      const hasNonIsoHidden = candidates.some((n: any) => n.hidden() && n.degree(false) > 0)
      if (!hasNonIsoHidden) { candidates.hide(); candidates.forEach((n: any) => _manualHidden.add(n.id())) }
      filterToggleState.value = 'showAll'
    } else {
      total.show(); _manualHidden.clear(); _manualShown.clear()
      filterToggleState.value = 'hideOrphan'
    }
    if (_centerNodes.length > 0) applyCenterMode()
    applyFilter()
  }

  function filterToggleLabel(): string {
    return { hideOrphan: '隐藏孤立', hideAll: '隐藏全部', showAll: '显示全部' }[filterToggleState.value] || '隐藏孤立'
  }

  function filterToggleTitle(): string {
    return { hideOrphan: '隐藏孤立节点（无连线）', hideAll: '隐藏所有节点', showAll: '显示所有节点' }[filterToggleState.value] || '隐藏孤立节点（无连线）'
  }

  function _nodeFilterColor(id: string): string {
    if (!_cy) return '#999'
    const n = _cy.getElementById(id)
    if (n.length) return n.style('background-color') || '#999'
    return '#999'
  }

  function isNodeHidden(id: string): boolean {
    if (_manualHidden.has(id)) return true
    if (_cy) { const n = _cy.getElementById(id); if (n.length && n.hasClass('hidden')) return true }
    return false
  }

  function toggleNodeFilter(id: string) {
    if (_manualHidden.has(id)) { _manualHidden.delete(id); _manualShown.add(id) }
    else { _manualHidden.add(id); _manualShown.delete(id) }
    applyFilter()
  }

  function applyCenterMode() {
    if (!_cy) return
    _cy.nodes().removeClass('center-highlight')
    if (!_centerNodes.length) { _cy.nodes().show(); _manualHidden.forEach((id: string) => { const n = _cy.getElementById(id); if (n.length) n.hide() }); return }
    const vs = new Set(_centerNodes)
    _centerNodes.forEach((cid: string) => { const cn = _cy.getElementById(cid); if (cn.length) cn.neighbourhood().forEach((n: any) => vs.add(n.id())) })
    _cy.nodes().forEach((n: any) => {
      const id = n.id()
      if (_manualHidden.has(id)) { n.hide(); return } if (_manualShown.has(id)) { n.show(); return }
      vs.has(id) ? n.show() : n.hide()
    })
    _centerNodes.forEach((cid: string) => { const cn = _cy.getElementById(cid); if (cn.length) cn.addClass('center-highlight') })
  }

  // ── Context menu ──
  function ctxCopyText(contextNodeIdVal: string): string | null {
    const n = graphNodes.value.find(x => x.id === contextNodeIdVal)
    if (!n) return null
    const info = { projectId: '', projectName: '', taskId: taskId.value, nodeId: n.id, nodeName: n.label }
    return JSON.stringify(info, null, 2)
  }

  // Auto-close context menu on outside click
  function initContextMenuAutoClose() {
    document.addEventListener('mousedown', (e) => {
      if (!contextMenuVisible.value) return
      const target = e.target as HTMLElement
      const cyContainerEl = document.querySelector('.cy-canvas')
      if (cyContainerEl && cyContainerEl.contains(target)) return
      if (target.closest('.ctx-menu')) return
      contextMenuVisible.value = false
      if (ctxMenuTimer) { clearTimeout(ctxMenuTimer); ctxMenuTimer = null }
    })
  }

  return {
    graphCommId, graphEdgeType, graphBreadcrumb, graphNodes, graphEdges,
    graphLoading, cyContainer, externalGraphData,
    followMode, showEdges, gran, graphTab, isHeatmap, toolbarCollapsed, toolbarTitle,
    rightCommTree, rightDepth, layoutTimeout, etOptions,
    filterVisible, filterQuery, filterToggleState, filterNodeList, filteredNodeList,
    contextMenuVisible, contextMenuPos, contextNodeId, contextNodeIsExternal, contextNodeHasChildren,
    getCy, getManualHidden, getManualShown, getCenterNodes,
    pushGraphBc, loadGraph, renderGraph,
    setEdgeType, loadRightCommTree, navigateComm,
    toggleFollowMode, toggleEdges, toggleGran, heatmapDrill, resetLayout,
    toggleFilter, applyFilter, cycleFilter, filterToggleLabel, filterToggleTitle,
    _nodeFilterColor, isNodeHidden, toggleNodeFilter, applyCenterMode,
    ctxCopyText, initContextMenuAutoClose,
  }
}
