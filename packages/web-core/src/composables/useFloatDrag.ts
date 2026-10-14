import { reactive } from 'vue'

export type FloatBounds = Record<string, { minX: number; maxX: number; minY: number; maxY: number }>

export function useFloatDrag() {
  console.log('[useFloatDrag] init')
  const floatBounds = reactive<FloatBounds>({})

  // ── Float bounds: viewport-relative (for position:fixed floats) ──
  // ── + panel-relative (for position:absolute toolbar/filter) ──
  function updateFloatBoundaries() {
    const leftPanel = document.querySelector('.left-panel') as HTMLElement
    const rightPanel = document.querySelector('.right-panel') as HTMLElement
    if (leftPanel && !leftPanel.style.display.startsWith('none') && leftPanel.offsetHeight > 0) {
      const lr = leftPanel.getBoundingClientRect()
      floatBounds.tocFloat = { minX: lr.left, maxX: lr.right - 30, minY: lr.top, maxY: lr.bottom - 30 }
    } else {
      floatBounds.tocFloat = { minX: 0, maxX: 0, minY: 0, maxY: 0 }
    }
    if (rightPanel && !rightPanel.style.display.startsWith('none') && rightPanel.offsetHeight > 0) {
      const rr = rightPanel.getBoundingClientRect()
      floatBounds.fileCommFloat = { minX: rr.left, maxX: rr.right - 30, minY: rr.top + 44, maxY: rr.bottom - 30 }
      const pw = rightPanel.offsetWidth, ph = rightPanel.offsetHeight
      floatBounds.graphToolbar = { minX: 0, maxX: pw - 30, minY: 8, maxY: ph - 30 }
      floatBounds.graphFilter = { minX: 0, maxX: pw - 30, minY: 0, maxY: ph - 30 }
    }
    console.log('[useFloatDrag] updateFloatBoundaries', JSON.stringify(floatBounds))
  }

  function clampFloatPosition(el: HTMLElement, key: string) {
    const b = floatBounds[key]
    if (!b || b.minX === 0 && b.maxX === 0) return
    const isInline = el.style.left !== ''
    const curLeft = isInline ? parseInt(el.style.left) : el.offsetLeft
    const curTop = isInline ? parseInt(el.style.top) : el.offsetTop
    let changed = false
    if (curLeft !== undefined && !isNaN(curLeft)) {
      if (curLeft < b.minX) { el.style.left = b.minX + 'px'; changed = true }
      if (curLeft > b.maxX) { el.style.left = b.maxX + 'px'; changed = true }
    }
    if (curTop !== undefined && !isNaN(curTop)) {
      if (curTop < b.minY) { el.style.top = b.minY + 'px'; changed = true }
      if (curTop > b.maxY) { el.style.top = b.maxY + 'px'; changed = true }
    }
    if (changed) console.log('[useFloatDrag] clampFloatPosition', key, curLeft, curTop, '→', el.style.left, el.style.top)
  }

  // ── Fit panel position to avoid overflow (exact legacy logic) ──
  function _fitPanel(floatEl: HTMLElement) {
    const panel = floatEl.querySelector('.toc-panel') as HTMLElement
    if (!panel) return
    const parent = floatEl.parentElement
    if (!parent) return
    const pr = parent.getBoundingClientRect()
    const fr = floatEl.getBoundingClientRect()
    const pw = panel.offsetWidth, ph = panel.offsetHeight
    if (!pw && !ph) return
    const frRel = fr.left - pr.left
    const overflowRight = pw > 0 && frRel + pw > pr.width
    const overflowBottom = ph > 0 && fr.top - pr.top + ph > pr.height
    console.log(`[useFloatDrag] fitPanel id=${floatEl.id} pr={l:${pr.left},r:${pr.right},w:${pr.width}} fr={l:${fr.left},t:${fr.top}} rel=${frRel} pw=${pw} ph=${ph} oR=${overflowRight} oB=${overflowBottom}`)
    if (overflowRight || overflowBottom) {
      floatEl.classList.add('flip-overflow')
      if (overflowBottom) floatEl.classList.add('flip-up')
      else floatEl.classList.remove('flip-up')
      if (overflowRight) floatEl.classList.add('flip-left')
      else floatEl.classList.remove('flip-left')
    } else {
      floatEl.classList.remove('flip-overflow', 'flip-up', 'flip-left')
    }
  }

  // ── Get element position relative to its positioned parent ──
  function _floatPos(el: HTMLElement): { left: number; top: number } {
    const r = el.getBoundingClientRect()
    const p = el.offsetParent
    if (p) { const pr = p.getBoundingClientRect(); return { left: r.left - pr.left, top: r.top - pr.top } }
    return { left: r.left, top: r.top }
  }

  // ── Clamp position to float bounds (viewport-relative coords) ──
  function _restoreWithBounds(el: HTMLElement, left: number, top: number, boundsKey?: string) {
    const b = boundsKey ? floatBounds[boundsKey] : undefined
    el.style.right = ''
    if (b && b.minX !== 0 && b.maxX !== 0) {
      el.style.left = Math.max(b.minX, Math.min(b.maxX, left)) + 'px'
      el.style.top = Math.max(b.minY, Math.min(b.maxY, top)) + 'px'
    } else {
      el.style.left = left + 'px'
      el.style.top = top + 'px'
    }
    _fitPanel(el)
  }

  // ── Same for panel-relative (toolbar/filter which stay position:absolute) ──
  function clampToBounds(el: HTMLElement, left: number, top: number, boundsKey?: string) {
    const b = boundsKey ? floatBounds[boundsKey] : undefined
    if (b && b.minX !== 0 && b.maxX !== 0) {
      el.style.left = Math.max(b.minX, Math.min(b.maxX, left)) + 'px'
      el.style.top = Math.max(b.minY, Math.min(b.maxY, top)) + 'px'
    } else {
      el.style.left = left + 'px'
      el.style.top = top + 'px'
    }
  }

  // ── Generic drag for any floating element (handles transform offset) ──
  function makeElementDraggable(el: HTMLElement, handle: HTMLElement, storageKey: string, boundsKey?: string) {
    let dragging = false, moved = false, startX = 0, startY = 0, origLeft = 0, origTop = 0, origTransform = ''
    try {
      const saved = localStorage.getItem(storageKey)
      if (saved) { const p = JSON.parse(saved); el.style.right = ''; clampToBounds(el, p.x, p.y, boundsKey); el.style.transform = 'none' }
    } catch (_) {}
    handle.addEventListener('mousedown', (e) => {
      moved = false; startX = e.clientX; startY = e.clientY
      origTransform = el.style.transform || getComputedStyle(el).transform
      if (origTransform && origTransform !== 'none') {
        el.style.transform = 'none'
        void el.offsetHeight
      }
      const pos = _floatPos(el)
      origLeft = pos.left; origTop = pos.top
      dragging = true
      document.addEventListener('mousemove', onMove); document.addEventListener('mouseup', onUp)
      e.stopPropagation()
    })
    function onMove(e: MouseEvent) {
      if (!dragging) return
      const dx = e.clientX - startX, dy = e.clientY - startY
      if (!moved && (Math.abs(dx) > 3 || Math.abs(dy) > 3)) moved = true
      if (moved) {
        el.style.right = ''
        let left = origLeft + dx
        let top = origTop + dy
        const b = boundsKey ? floatBounds[boundsKey] : undefined
        if (b && b.minX !== 0 && b.maxX !== 0) {
          left = Math.max(b.minX, Math.min(b.maxX, left))
          top = Math.max(b.minY, Math.min(b.maxY, top))
        }
        el.style.left = left + 'px'
        el.style.top = top + 'px'
      }
    }
    function onUp() {
      if (!dragging) return
      dragging = false
      document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp)
      if (moved) {
        try { localStorage.setItem(storageKey, JSON.stringify({ x: parseInt(el.style.left) || 0, y: parseInt(el.style.top) || 0 })) } catch (_) {}
      }
    }
    console.log('[useFloatDrag] makeElementDraggable', storageKey, boundsKey)
  }

  // ── Floating panel drag (toggle button doubles as drag handle) ──
  function makeFloatDraggable(el: HTMLElement, storageKey: string) {
    let dragging = false, ox = 0, oy = 0, fitPending = false
    const boundsKey = el.id
    try {
      const saved = localStorage.getItem(storageKey)
      if (saved) { const p = JSON.parse(saved); el.style.right = ''; _restoreWithBounds(el, p.x, p.y, boundsKey); console.log('[drag] RESTORE id=' + boundsKey + ' to ' + p.x + ',' + p.y) }
    } catch (_) {}
    el.addEventListener('mousedown', (e) => {
      if ((e.target as HTMLElement).closest('.toc-panel')) return
      e.preventDefault()
      el.classList.add('dragging')
      const rect = el.getBoundingClientRect()
      ox = e.clientX - rect.left; oy = e.clientY - rect.top
      const b = floatBounds[boundsKey]
      console.log(`[drag] START id=${boundsKey} clientXY=${e.clientX},${e.clientY} offset=${ox},${oy} bounds=${JSON.stringify(b)}`)
      if (!b || (b.minX === 0 && b.maxX === 0)) { el.style.left = rect.left + 'px'; el.style.top = rect.top + 'px' }
      document.addEventListener('mousemove', onMove); document.addEventListener('mouseup', onUp)
    })
    function onMove(ev: MouseEvent) {
      const b = floatBounds[boundsKey]
      if (!b || (b.minX === 0 && b.maxX === 0)) return
      el.style.right = ''
      const left = Math.max(b.minX, Math.min(b.maxX, ev.clientX - ox))
      const top = Math.max(b.minY, Math.min(b.maxY, ev.clientY - oy))
      el.style.left = left + 'px'; el.style.top = top + 'px'
      if (!fitPending) {
        fitPending = true
        requestAnimationFrame(() => { fitPending = false; _fitPanel(el) })
      }
    }
    function onUp() {
      el.classList.remove('dragging')
      document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp)
      _fitPanel(el)
      const saved = { x: parseInt(el.style.left) || 0, y: parseInt(el.style.top) || 0 }
      console.log(`[drag] SAVE id=${boundsKey} pos=${JSON.stringify(saved)}`)
      try { localStorage.setItem(storageKey, JSON.stringify(saved)) } catch (_) {}
    }
    console.log('[useFloatDrag] makeFloatDraggable', storageKey)
  }

  // ── Auto-close floating panels ──
  function mountAutoClose(el: HTMLElement, closeFn: () => void) {
    let timer: any = null
    el.addEventListener('mouseleave', () => { timer = setTimeout(closeFn, 1500) })
    el.addEventListener('mouseenter', () => { if (timer) { clearTimeout(timer); timer = null } })
    console.log('[useFloatDrag] mountAutoClose on', el.id)
  }

  // ── Window resize ──
  function onWindowResize(tocFloatRef: any, fileCommFloatRef: any) {
    updateFloatBoundaries()
    if (tocFloatRef?.value) clampFloatPosition(tocFloatRef.value, 'tocFloat')
    if (fileCommFloatRef?.value) clampFloatPosition(fileCommFloatRef.value, 'fileCommFloat')
  }

  return {
    floatBounds,
    updateFloatBoundaries,
    clampFloatPosition,
    _fitPanel,
    _floatPos,
    _restoreWithBounds,
    clampToBounds,
    makeElementDraggable,
    makeFloatDraggable,
    mountAutoClose,
    onWindowResize,
  }
}
