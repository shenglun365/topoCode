export function useGraphLayout() {
  console.log('[useGraphLayout] init')

  function _stableHue(id: string): number {
    let h = 0; for (let i = 0; i < id.length; i++) { h = ((h << 5) - h) + id.charCodeAt(i); h |= 0 }
    h = Math.abs(h)
    return ((h * 2654435761) ^ (h >>> 16)) % 360
  }

  function _hueSatLight(depth: number, hue: number): string {
    const t = [[80, 55], [70, 65], [55, 78], [40, 88], [30, 94]]
    const v = t[Math.min(depth, 4)]
    return `hsl(${hue}, ${v[0]}%, ${v[1]}%)`
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

  function applyNodeColors(cy: any, _isExternal?: boolean) {
    const colorRoot: Record<string, string> = {}
    cy.nodes().forEach((n: any) => {
      let key = n.id(), pid = _parentCommId(n.id())
      while (pid !== null) { key = pid; pid = _parentCommId(pid) }
      colorRoot[n.id()] = key
    })
    const rootHue: Record<string, number> = {}
    for (const rk of Object.values(colorRoot)) rootHue[rk] = _stableHue(rk)
    cy.nodes().forEach((n: any) => {
      const nid = n.id(), rid = colorRoot[nid]
      if (!rid) { n.style('background-color', '#999'); return }
      let cd = 0
      for (let cur = nid; cur !== rid;) { const p = _parentCommId(cur); if (p === null) break; cur = p; cd++ }
      n.style('background-color', _hueSatLight(cd, rootHue[rid]))
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

  function _afterLayout(cy: any) {
    cy.one('layoutstop', () => {
      cy.zoom(1.0)
      const conn = cy.nodes().filter((n: any) => n.degree(false) > 0)
      if (!conn.empty()) cy.center(conn); else cy.center()
    })
  }

  return {
    _stableHue, _hueSatLight, _parentCommId,
    applyNodeColors, _buildLayout, _afterLayout,
  }
}
