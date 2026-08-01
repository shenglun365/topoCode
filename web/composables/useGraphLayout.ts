export function useGraphLayout() {
  console.log('[useGraphLayout] init')

  // 外部专用色带 [EXT_HUE_START, EXT_HUE_END)：内部色相稳定避开该区间
  const EXT_HUE_START = 190
  const EXT_HUE_END = 235

  function _stableHue(id: string): number {
    let h = 0; for (let i = 0; i < id.length; i++) { h = ((h << 5) - h) + id.charCodeAt(i); h |= 0 }
    h = Math.abs(h)
    return ((h * 2654435761) ^ (h >>> 16)) % 360
  }

  function _externalHue(id: string): number {
    return EXT_HUE_START + (_stableHue(id) % (EXT_HUE_END - EXT_HUE_START))
  }

  function _internalHue(id: string): number {
    const span = 360 - (EXT_HUE_END - EXT_HUE_START)
    let h = _stableHue(id) % span
    if (h >= EXT_HUE_START) h += (EXT_HUE_END - EXT_HUE_START)
    return h
  }

  function _hueSatLight(depth: number, hue: number): string {
    const t = [[80, 55], [70, 65], [55, 78], [40, 88], [30, 94]]
    const v = t[Math.min(depth, 4)]
    return `hsl(${hue}, ${v[0]}%, ${v[1]}%)`
  }

  function _levelNum(id: string): number | null {
    const m = /L(\d+)/.exec(id || '')
    return m ? parseInt(m[1]) : null
  }

  function _parentCommId(cid: string): string | null {
    const p = (cid || '').split('-')
    for (let i = 0; i < p.length; i++) {
      if (/^L\d+$/.test(p[i])) {
        const lv = parseInt(p[i].substring(1))
        if (lv === 0) return null
        const r = p.slice(0, i); r.push('L' + (lv - 1)); const s = p.slice(i + 1); s.pop()
        if (lv === 1) s.shift(); else if (lv === 2) r.push('L0')
        return r.concat(s).join('-')
      }
    }
    return null
  }

  function applyNodeColors(cy: any, opts?: { visitedCommId?: string; gran?: string }) {
    const visitedCommId = (opts?.visitedCommId || '').trim()
    const gran = opts?.gran || 'component'
    const visitedLv = visitedCommId ? _levelNum(visitedCommId) : null
    // 色系根层级: 根视图 → L0 全部为色系根; 访问 Lk 社区 → 其第一级子节点 (Lk+1) 为色系根
    const rootLevel = visitedCommId && visitedLv !== null ? visitedLv + 1 : 0

    const nodeById: Record<string, any> = {}
    cy.nodes().forEach((m: any) => { nodeById[m.id()] = m })

    cy.nodes().forEach((n: any) => {
      const nid = n.id()
      // 外部节点: 固定色带 + 白色虚线描边（二次区分）
      if (n.data('isExternal')) {
        n.addClass('ext-node')
        n.style('background-color', _hueSatLight(0, _externalHue(nid)))
        return
      }
      const lv = _levelNum(n.data('commLv') || '')
      // 文件级 / 无层级节点: 色系根 = 所属社区
      if (gran === 'file' || lv === null) {
        const commId = n.data('commId') || n.data('parentId') || nid
        n.style('background-color', _hueSatLight(0, _internalHue(commId)))
        return
      }
      // 内部节点: 回溯到色系根 (优先 parentId, 兜底字符串), 深度控制明暗
      const depth = Math.max(0, lv - rootLevel)
      let rootId = nid
      let cur = nid
      for (let i = 0; i < depth; i++) {
        const p = nodeById[cur]?.data('parentId') || _parentCommId(cur)
        if (!p) break
        cur = p
        rootId = cur
      }
      n.style('background-color', _hueSatLight(depth, _internalHue(rootId)))
    })
  }

  function _buildLayout(cy: any, nodeCount: number) {
    let numIter = 4000
    if (nodeCount > 500) numIter = 300
    else if (nodeCount > 100) numIter = 1000
    return {
      name: 'cose-bilkent', animate: false,
      nodeRepulsion: 80000, idealEdgeLength: 200, gravity: 0,
      numIter: Math.max(numIter, 1000),
      fit: false, quality: 'proof',
    }
  }

  function _repositionIsolatedNodes(cy: any) {
    const isolated = cy.nodes().filter((n: any) => n.degree(false) === 0)
    if (isolated.empty()) return
    const ext = cy.extent()
    const pad = 30, nodeW = 34, nodeH = 34
    const colStep = nodeW + 8, rowH = nodeH + 8
    const xMin = ext.x1 + pad, xMax = ext.x2 - pad
    const yMin = ext.y1 + pad, yMax = ext.y2 - pad
    const cols = Math.max(1, Math.floor((xMax - xMin) / colStep))
    cy.batch(() => {
      isolated.sort((a: any, b: any) => (a.id() < b.id() ? -1 : 1))
        .forEach((n: any, i: number) => {
          const row = Math.floor(i / cols), col = i % cols
          const x = Math.min(xMax - nodeW / 2, xMin + nodeW / 2 + col * colStep)
          const y = Math.max(yMin, yMax - rowH / 2 - row * rowH)
          n.position({ x, y })
        })
    })
  }

  function _afterLayout(cy: any) {
    cy.one('layoutstop', () => {
      cy.zoom(1.0)
      const conn = cy.nodes().filter((n: any) => n.degree(false) > 0)
      if (!conn.empty()) cy.center(conn); else cy.center()
      _repositionIsolatedNodes(cy)
    })
  }

  return {
    _stableHue, _hueSatLight, _parentCommId,
    applyNodeColors, _buildLayout, _afterLayout,
  }
}
