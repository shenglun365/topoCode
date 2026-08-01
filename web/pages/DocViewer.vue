<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { diagramStateStore } from '@web/services/diagramStateStore'
import { parseDocContent } from '@web/services/parseContent'
import MermaidViewer from '@web/components/MermaidViewer.vue'
import PlantUmlViewer from '@web/components/PlantUmlViewer.vue'
import { useFloatDrag } from '@web/composables/useFloatDrag'
import { useDocState } from '@web/composables/useDocState'
import { useNotes } from '@web/composables/useNotes'
import { codeFullscreen } from '@web/services/render'
import { useHeatmap } from '@web/composables/useHeatmap'
import { useToast } from '@web/composables/useToast'
import { useGraphState } from '@web/composables/useGraphState'
import GraphContextMenu from '@web/components/graph/GraphContextMenu.vue'
import StarLogoMark from '@web/components/StarLogoMark.vue'

const taskId = ref(new URLSearchParams(location.search).get('taskId') || '')
const urlCid = new URLSearchParams(location.search).get('communityId') || new URLSearchParams(location.search).get('cid') || ''
const urlEt = new URLSearchParams(location.search).get('edgeType') || 'INCLUDE'

const {
  floatBounds, updateFloatBoundaries, clampFloatPosition,
  _fitPanel, _restoreWithBounds, clampToBounds,
  makeElementDraggable, makeFloatDraggable, mountAutoClose,
  onWindowResize: onWindowResize_,
} = useFloatDrag()
const {
  notesModalVisible, notesList, notesFilterStatus, notesSortOrder,
  notesProjectFilter, notesProjectOptions, notesUserText,
  notesSelectedSessions, notesSessions, notesExecStep, notesAutoDelete,
  notesDotVisible, filteredNotes,
  openNotesModal, deleteRefFromNote, deleteNoteById, deleteSelectedRefs,
  manualDrafts, executeNotes, _addRefToDraft,
  _notesLoad, initNotesChannel,
} = useNotes(taskId)
const {
  heatmapData, heatmapSize, heatmapLoading,
  loadHeatmap, heatmapBg, setHeatmapSize,
} = useHeatmap()

const {
  docId, originalDocId,
  docCommId, docEdgeType, docBreadcrumb, doc, loading, children,
  docContentRef,
  tocVisible, tocCallChildren, tocIncludeChildren, tocLoading,
  files, filePage, fileSearch, filePreview, fileSummary, pageMode, filteredFiles: filteredFiles_,
  pushDocBc, loadDoc, loadChildren, navigateTo, navBack,
  loadFiles, filterFiles, openFilePreview,
  toggleToc, loadTocData, tocNavigate,
} = useDocState(taskId)

const {
  graphCommId, graphEdgeType, graphBreadcrumb, graphNodes, graphEdges,
  graphLoading, cyContainer, externalGraphData,
  followMode, showEdges, gran, graphTab, isHeatmap, toolbarCollapsed, toolbarTitle,
  rightCommTree, rightDepth, layoutTimeout, etOptions,
  filterVisible, filterQuery, filterToggleState, filterNodeList, filteredNodeList,
  contextMenuVisible, contextMenuPos, contextNodeId, contextNodeIsExternal, contextNodeHasChildren,
  pushGraphBc, loadGraph, renderGraph,
  setEdgeType, loadRightCommTree, navigateComm,
  toggleFollowMode, toggleEdges, toggleGran, heatmapDrill, resetLayout,
  toggleFilter, applyFilter, cycleFilter, filterToggleLabel, filterToggleTitle,
  _nodeFilterColor, isNodeHidden, toggleNodeFilter, applyCenterMode,
  getCy, getManualHidden, getManualShown, getCenterNodes,
  ctxCopyText: ctxCopy,
  // ... rest of useGraphState destructuring
  initContextMenuAutoClose,
} = useGraphState(taskId)

const { toast } = useToast()

const fontSize = ref(parseInt(localStorage.getItem('topoone-font-size') || '18'))
const leftVisible = ref(true)
const rightVisible = ref(true)
const tocFloatRef = ref<HTMLDivElement>()
const fileCommFloatRef = ref<HTMLDivElement>()

const commFloatVisible = ref(false)

// Annotation state
const showAnnotations = ref(true)
const editAnnoData = ref<{ id?: string; text: string; isNew?: boolean } | null>(null)

// Layout
const leftFlex = ref('1 1 55%')
const rightFlex = ref('1 1 45%')
const resizerRef = ref<HTMLDivElement>()

function ctxDrilldown() {
  const nid = contextNodeId.value
  if (gran.value === 'file' || nid === graphCommId.value) { contextMenuVisible.value = false; return }
  const cy = getCy()
  const node = cy?.getElementById(nid)
  if (node && node.data('hasChildren') === false) { gran.value = 'file'; rightDepth.value = 1 }
  graphCommId.value = nid
  const drillLabel = graphNodes.value.find(n => n.id === nid)?.label || nid.slice(0, 16)
  pushGraphBc({ cid: nid, et: graphEdgeType.value, label: drillLabel })
  loadGraph()
  loadRightCommTree()
  contextMenuVisible.value = false
}
function ctxCenter() {
  const nid = contextNodeId.value
  const cn = getCenterNodes()
  const idx = cn.indexOf(nid)
  if (idx >= 0) cn.splice(idx, 1); else cn.push(nid)
  applyCenterMode()
  contextMenuVisible.value = false
}

console.log('[DocViewer] using useDocState + useGraphState')

function toggleTab() {
  if (graphTab.value === 'graph') {
    graphTab.value = 'heatmap'
    loadHeatmap(taskId.value, graphEdgeType.value, graphCommId.value)
  } else {
    graphTab.value = 'graph'
  }
}

function ctxOpenDoc() {
  docId.value = ''
  docCommId.value = contextNodeId.value
  docEdgeType.value = graphEdgeType.value
  pushDocBc({ label: contextNodeId.value.slice(0, 16), cid: contextNodeId.value, et: graphEdgeType.value })
  loadDoc()
  contextMenuVisible.value = false
}

function ctxSaveNote() {
  const n = graphNodes.value.find(x => x.id === contextNodeId.value)
  if (!n) return
  _addRefToDraft({
    projectId: doc.value?.projectId || '', projectName: doc.value?.projectName || '', taskId: taskId.value,
    componentId: n.id, label: n.label, text: n.label,
  })
  toast('已存入便签')
  contextMenuVisible.value = false
}

function handleCtxCopy(nodeId: string) {
  console.log('[handleCtxCopy] doc=', doc.value?.projectId, doc.value?.projectName)
  ctxCopy(nodeId, { projectId: doc.value?.projectId || '', projectName: doc.value?.projectName || '' })
}

// ── Selection toolbar (exact legacy logic) ──
let selBarTimer: any = null

function initSelectionToolbar() {
  document.addEventListener('selectionchange', () => {
    clearTimeout(selBarTimer)
    selBarTimer = setTimeout(() => {
      const sel = window.getSelection()
      const el = sel && sel.anchorNode && sel.anchorNode.parentElement
      const inDoc = el && (el.closest('#content') || el.closest('.content'))
      if (!inDoc || !sel || sel.isCollapsed || !sel.toString().trim()) {
        removeSelBar()
        return
      }
      showSelBar(sel)
    }, 150)
  })
  document.addEventListener('contextmenu', (e) => {
    const target = e.target as HTMLElement
    if (target.closest?.('#content') || target.closest?.('.content')) { console.log('[selBar] suppress browser context menu in content'); e.preventDefault() }
  })
}

let selBarEl: HTMLElement | null = null

function removeSelBar() {
  if (selBarEl) console.log('[selBar] HIDE')
  selBarEl?.remove(); selBarEl = null
}

function showSelBar(sel: Selection) {
  removeSelBar()
  const text = sel.toString().trim()
  if (!text) { console.log('[selBar] skip: empty text'); return }
  const range = sel.getRangeAt(0)
  const rect = range.getBoundingClientRect()
  console.log(`[selBar] raw rect: l=${rect.left} t=${rect.top} r=${rect.right} b=${rect.bottom} w=${rect.width} h=${rect.height}`)
  if (rect.width === 0 && rect.height === 0) { console.log('[selBar] skip: zero rect'); return }
  if (rect.left === 0 && rect.top === 0 && rect.width === 0) { console.log('[selBar] skip: zero-origin rect'); return }
  selBarEl = document.createElement('div')
  selBarEl.className = 'sel-toolbar'
  selBarEl.innerHTML = '<button data-action="copy">复制</button><button data-action="note">存入便签</button>'
  document.body.appendChild(selBarEl)
  void selBarEl.offsetHeight
  const bw = selBarEl.offsetWidth || 80
  let left = Math.max(4, Math.min(rect.left + (rect.width - bw) / 2, window.innerWidth - bw - 4))
  let top = rect.top - selBarEl.offsetHeight - 6
  if (top < 0) top = rect.bottom + 6
  console.log(`[selBar] pos calc: bw=${bw} oh=${selBarEl.offsetHeight} left=${left} top=${top} vw=${window.innerWidth} vh=${window.innerHeight}`)
  if (left + bw < 0 || left > window.innerWidth || top + selBarEl.offsetHeight < 0 || top > window.innerHeight) {
    console.log('[selBar] skip: off-screen position'); removeSelBar(); return
  }
  selBarEl.style.left = left + 'px'
  selBarEl.style.top = top + 'px'
  console.log(`[selBar] SHOW at ${left},${top}`)
  const selText = text
  selBarEl.querySelector('[data-action="copy"]')!.addEventListener('click', () => {
    try {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(selText).then(() => { toast('已复制'); removeSelBar() }).catch(() => { toast('复制失败'); removeSelBar() })
      } else {
        const ta = document.createElement('textarea')
        ta.value = selText; ta.style.cssText = 'position:fixed;opacity:0'; document.body.appendChild(ta)
        ta.select(); document.execCommand('copy'); document.body.removeChild(ta)
        toast('已复制'); removeSelBar()
      }
    } catch (_) { toast('复制失败'); removeSelBar() }
  })
  selBarEl.querySelector('[data-action="note"]')!.addEventListener('click', () => {
    _addRefToDraft({ projectId: '', projectName: '', taskId: taskId.value, componentId: '', label: selText.slice(0, 40), text: selText.slice(0, 2000) })
    toast('已存入便签')
    removeSelBar()
  })
}



// ── i18n helper ──
function _(key: string): string {
  const locale = navigator.language.startsWith('zh') ? 'zh-CN' : 'en-US'
  const dict: Record<string, Record<string, string>> = {
    'zh-CN': {
      'title': 'TopoCode 文档浏览',
      'fontSize': '字号',
      'notes': '便签',
      'docPanel': '文档面板',
      'graphPanel': '图谱面板',
      'aiAssistant': 'AI',
      'back': '返回',
      'graphOps': '图谱操作',
      'follow': '跟随',
      'locked': '锁定',
      'edges': '连线',
      'component': '组件',
      'file': '文件',
      'graph': '图谱',
      'heatmap': '热图',
      'filter': '筛选',
      'reset': '重置',
      'searchNode': '搜索节点...',
      'loading': '加载中...',
      'noData': '暂无数据',
    },
    'en-US': {
      'title': 'TopoCode Doc Viewer',
      'fontSize': 'Font Size',
      'notes': 'Notes',
      'docPanel': 'Doc Panel',
      'graphPanel': 'Graph Panel',
      'aiAssistant': 'AI',
      'back': 'Back',
      'graphOps': 'Graph',
      'follow': 'Follow',
      'locked': 'Locked',
      'edges': 'Edges',
      'component': 'Component',
      'file': 'File',
      'graph': 'Graph',
      'heatmap': 'Heatmap',
      'filter': 'Filter',
      'reset': 'Reset',
      'searchNode': 'Search nodes...',
      'loading': 'Loading...',
      'noData': 'No data',
    },
  }
  return dict[locale]?.[key] || dict['zh-CN'][key] || key
}

// ── Heading anchors (exact legacy logic) ──
function attachHeadingButtons() {
  nextTick(() => {
    if (!docContentRef.value) return
    const isRoot = !docCommId.value
    const selector = isRoot ? 'h1' : 'h1, h2, h3, h4'
    docContentRef.value.querySelectorAll(selector).forEach(h => {
      if (h.querySelector('.hd-btn')) return
      const commLinks: Record<string, string> = {}
      let m: RegExpMatchArray | null = null
      let next = h.nextElementSibling
      while (next && !/^H[1-6]$/.test(next.tagName)) {
        if (next.tagName === 'P' || next.tagName === 'LI') {
          next.querySelectorAll('a[href^="##community:"]').forEach(a => {
            const parts = a.getAttribute('href')?.replace('##community:', '').split(':')
            if (parts && parts.length === 2) commLinks[parts[0]] = parts[1]
          })
          if (!m) m = next.textContent?.match(/comm-[\w-]+-L\d+-[\d-]+/)
        }
        next = next.nextElementSibling
      }
      if (!m) m = h.textContent?.match(/comm-[\w-]+-L\d+-[\d-]+/)
      if (!m && !isRoot && !Object.keys(commLinks).length) {
        if (docCommId.value) m = [docCommId.value]
      }
      let ets = isRoot ? ['INCLUDE', 'CALL'] : Object.keys(commLinks).slice(0, 1)
      if (!ets.length) {
        if (m) ets = isRoot ? ['INCLUDE', 'CALL'] : [docEdgeType.value || 'INCLUDE']
        else return
      }
      const hText = h.textContent?.trim() || ''
      const btn = document.createElement('span')
      btn.className = 'hd-btn'
      ets.forEach(et => {
        const cid = commLinks[et] || (m ? m[0] : '')
        if (!cid || cid === 'undefined') return
        const icon = isRoot
          ? (et === 'INCLUDE'
            ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M16 12H8M12 8l4 4-4 4"/></svg>'
            : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M8 12h8M12 16l-4-4 4-4"/></svg>')
          : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="14" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="18" r="3"/><line x1="8" y1="8" x2="16" y2="4"/><line x1="8" y1="13" x2="4" y2="16"/><line x1="16" y1="13" x2="20" y2="16"/></svg>'
        const title = isRoot
          ? (et === 'INCLUDE' ? '在依赖关系中查看' : '在调用关系中查看')
          : '在结构图中查看'
        const ib = document.createElement('span')
        ib.className = 'hd-btn-icon'
        ib.title = title
        ib.innerHTML = icon
        ib.onclick = (e) => {
          e.preventDefault(); e.stopPropagation()
          if (!cid) return
          // This is a doc→graph link: update graph state, switch to graph tab
          graphCommId.value = cid
          graphEdgeType.value = et as any
          pushGraphBc({ cid, et, label: hText.slice(0, 24) })
          loadGraph()
          loadRightCommTree()
          graphTab.value = 'graph'
        }
        btn.appendChild(ib)
      })
      if (btn.children.length) h.appendChild(btn)
    })
  })
}
function checkHash() {
  if (location.hash) {
    const el = docContentRef.value?.querySelector(location.hash)
    if (el) el.scrollIntoView({ behavior: 'smooth' })
  }
}

// ── Annotations ──
function getAnnotationBlocks(html: string): string {
  if (!html) return html
  return html.replace(/<!--\s*annotation:([^\s]+)\s*-->([\s\S]*?)<!--\s*\/annotation\s*-->/g,
    (_, id, text) => `<div class="doc-annotation" data-anno-id="${id}"><div class="doc-anno-marker"></div><div class="doc-anno-body"><p>${text.trim()}</p></div></div>`)
}
function onDocAnnoClick(e: MouseEvent) {
  const fsBtn = (e.target as HTMLElement).closest('.code-fs-btn') as HTMLElement
  if (fsBtn) {
    const wrap = fsBtn.closest('.code-block-wrap')
    const codeEl = wrap?.querySelector('code')
    const text = codeEl?.textContent || ''
    if (text) { codeFullscreen(text); return }
  }
  const anno = (e.target as HTMLElement).closest('.doc-annotation') as HTMLElement
  if (!anno) return
  editAnnoData.value = { id: anno.dataset.annoId || '', text: anno.querySelector('.doc-anno-body')?.textContent?.trim() || '', isNew: false }
}
function addNewAnnotation() { editAnnoData.value = { text: '', isNew: true } }
function saveAnnotation() {
  if (!editAnnoData.value || !doc.value) { editAnnoData.value = null; return }
  const { id, text, isNew } = editAnnoData.value
  if (!text?.trim()) { editAnnoData.value = null; return }
  if (isNew) { doc.value.content += `\n\n<!-- annotation:${Date.now().toString(36)} -->${text.trim()}<!-- /annotation -->` }
  else { const r = new RegExp(`<!--\\s*annotation:${id}\\s*-->[\\s\\S]*?<!--\\s*/annotation\\s*-->`, 'g'); doc.value.content = doc.value.content.replace(r, `<!-- annotation:${id} -->${text.trim()}<!-- /annotation -->`) }
  editAnnoData.value = null; toast('批注已保存')
}
function deleteAnnotation() {
  if (!editAnnoData.value?.id || !doc.value) return
  doc.value.content = doc.value.content.replace(new RegExp(`<!--\\s*annotation:${editAnnoData.value.id}\\s*-->[\\s\\S]*?<!--\\s*/annotation\\s*-->\\n?`, 'g'), '')
  editAnnoData.value = null; toast('批注已删除')
}


function toggleLeft() {
  leftVisible.value = !leftVisible.value
  if (!leftVisible.value) { rightFlex.value = '1 1 100%'; leftFlex.value = '' }
  else { leftFlex.value = '1 1 55%'; rightFlex.value = '1 1 45%' }
  nextTick(() => updateFloatBoundaries())
}
function toggleRight() {
  rightVisible.value = !rightVisible.value
  if (!rightVisible.value) { leftFlex.value = '1 1 100%'; rightFlex.value = '' }
  else { leftFlex.value = '1 1 55%'; rightFlex.value = '1 1 45%' }
  nextTick(() => updateFloatBoundaries())
}
function applyFontSize(val: number) {
  document.documentElement.style.setProperty('--content-font-size', val + 'px')
  try { localStorage.setItem('topoone-font-size', String(val)) } catch (_) {}
}

watch(fontSize, applyFontSize)
watch(docContentRef, () => { if (docContentRef.value) { attachHeadingButtons() } })
watch(commFloatVisible, (v) => { if (v) loadRightCommTree() })
watch(filterVisible, (v) => {
  if (v) {
    nextTick(() => {
      const gfp = document.querySelector('.graph-filter-panel') as HTMLElement
      const handle = gfp?.querySelector('.graph-filter-drag-icon') as HTMLElement
      if (gfp && handle && !gfp.dataset.dragInit) {
        makeElementDraggable(gfp, handle, 'fpPos_v2_' + taskId.value, 'graphFilter')
        gfp.dataset.dragInit = '1'
      }
    })
  }
})

// ── Diagram view state ──
const docBlocks = computed(() => parseDocContent(doc.value?.content || '', docId.value || originalDocId.value))
const hasUnsavedDiag = ref(false)
function checkDiagState() {
  const id = docId.value || originalDocId.value
  if (!id) { hasUnsavedDiag.value = false; return }
  hasUnsavedDiag.value = diagramStateStore.hasUnsaved(id)
}
watch(doc, () => setTimeout(checkDiagState, 200), { deep: true })
watch(docContentRef, () => setTimeout(checkDiagState, 500))
onMounted(() => document.addEventListener('diagram-state-changed', checkDiagState))
onUnmounted(() => document.removeEventListener('diagram-state-changed', checkDiagState))

async function saveDiagramStates() {
  const id = docId.value || originalDocId.value
  if (!id) return
  if (!doc.value) return
  doc.value.content = diagramStateStore.embedInContent(doc.value.content, id)
  try {
    const r = await fetch(`/api/notes/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: doc.value.content }) })
    if (!r.ok) throw new Error()
    diagramStateStore.removeAll(id)
    hasUnsavedDiag.value = false
    document.dispatchEvent(new CustomEvent('diagram-state-changed'))
    const { toast } = await import('@web/composables/useToast')
    toast('图状态已保存')
  } catch (_) {}
}

onMounted(() => {
  applyFontSize(fontSize.value)
  loadDoc(() => { checkHash() })
  loadGraph()
  loadFiles()
  initSelectionToolbar()
  _notesLoad()
  initNotesChannel()
  window.addEventListener('resize', () => onWindowResize_(tocFloatRef, fileCommFloatRef))
  initContextMenuAutoClose()
  // Initialize float positions (near center divider) + boundaries
  nextTick(() => {
    updateFloatBoundaries()
    // Position floats near the divider line
    const leftPanel = document.querySelector('.left-panel') as HTMLElement
    const rightPanel = document.querySelector('.right-panel') as HTMLElement
    if (leftPanel && tocFloatRef.value) {
      const lr = leftPanel.getBoundingClientRect()
      tocFloatRef.value.style.left = (lr.right - 136) + 'px'
      tocFloatRef.value.style.top = (lr.top + 44) + 'px'
    }
    if (rightPanel && fileCommFloatRef.value) {
      const rr = rightPanel.getBoundingClientRect()
      fileCommFloatRef.value.style.left = (rr.left + 104) + 'px'
      fileCommFloatRef.value.style.top = (rr.top + 44) + 'px'
      fileCommFloatRef.value.style.alignItems = 'flex-start'
    }
  })
  // Wire up floating panels + resizer
  nextTick(() => {
    if (tocFloatRef.value) {
      makeFloatDraggable(tocFloatRef.value, 'tocPos_v2_' + taskId.value)
      mountAutoClose(tocFloatRef.value, () => { tocVisible.value = false })
    }
    if (fileCommFloatRef.value) {
      makeFloatDraggable(fileCommFloatRef.value, 'commPos_v2_' + taskId.value)
      mountAutoClose(fileCommFloatRef.value, () => { commFloatVisible.value = false })
    }
    // Graph toolbar drag (via header) — clear stale saved position from broken drag
    const tbKey = 'tbPos_v2_' + taskId.value
    try { if (localStorage.getItem(tbKey)) { const p = JSON.parse(localStorage.getItem(tbKey) || '{}'); if (p.x === 0 && p.y === 0) localStorage.removeItem(tbKey) } } catch (_) {}
    const gtb = document.querySelector('.graph-toolbar') as HTMLElement
    if (gtb) {
      gtb.style.left = ''; gtb.style.top = ''; gtb.style.transform = ''
      const gtbHeader = gtb.querySelector('.graph-toolbar-header') as HTMLElement
      if (gtbHeader) makeElementDraggable(gtb, gtbHeader, tbKey, 'graphToolbar')
    }
    // Filter panel drag (via drag icon)
    const gfp = document.querySelector('.graph-filter-panel') as HTMLElement
    const gfpHandle = gfp?.querySelector('.graph-filter-drag-icon') as HTMLElement
    if (gfp && gfpHandle) makeElementDraggable(gfp, gfpHandle, 'fpPos_v2_' + taskId.value, 'graphFilter')
    // Resizer drag
    const resizer = resizerRef.value
    const layout = document.querySelector('.layout') as HTMLElement
    if (resizer && layout) {
      let isResizing = false
      resizer.addEventListener('mousedown', () => { isResizing = true; document.body.style.cursor = 'col-resize' })
      document.addEventListener('mousemove', (e) => {
        if (!isResizing) return
        const rect = layout.getBoundingClientRect()
        let pct = (e.clientX - rect.left) / rect.width * 100
        if (pct < 20) pct = 20
        if (pct > 80) pct = 80
        leftFlex.value = '1 1 ' + pct + '%'
        rightFlex.value = '1 1 ' + (100 - pct) + '%'
        updateFloatBoundaries()
        if (tocFloatRef.value) clampFloatPosition(tocFloatRef.value, 'tocFloat')
        if (fileCommFloatRef.value) clampFloatPosition(fileCommFloatRef.value, 'fileCommFloat')
      })
      document.addEventListener('mouseup', () => { isResizing = false; document.body.style.cursor = '' })
    }
  })
  // Update URL on state changes
  setInterval(() => {
    const p = new URLSearchParams(location.search)
    const cid = docCommId.value || ''
    if (cid && p.get('communityId') !== cid) {
      p.set('communityId', cid)
      if (taskId.value) p.set('taskId', taskId.value)
      if (docEdgeType.value) p.set('edgeType', docEdgeType.value)
      history.replaceState(null, '', '?' + p.toString())
    }
  }, 1000)
})
</script>

<template>
  <div class="viewer">
    <div class="header">
      <StarLogoMark :size="26" />
      <span class="title">TopoCode Doc Viewer</span>
      <select v-model.number="fontSize">
        <option :value="13">13px</option><option :value="15">15px</option>
        <option :value="18">18px</option><option :value="22">22px</option>
        <option :value="26">26px</option><option :value="32">32px</option>
      </select>
      <button class="diag-save-btn" :class="{ 'has-unsaved': hasUnsavedDiag }" :disabled="!hasUnsavedDiag" @click="saveDiagramStates" title="保存图状态到服务器">
        <span v-if="hasUnsavedDiag" class="save-red-dot"></span>保存图状态
      </button>
      <button class="toggle-btn notes-btn" :class="{ active: false }" @click="openNotesModal" title="便签">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
        <span v-if="notesDotVisible" class="notes-dot"></span>
      </button>
      <button class="toggle-btn" :class="{ active: leftVisible }" @click="toggleLeft" title="文档面板">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
      </button>
      <button class="toggle-btn" :class="{ active: rightVisible }" @click="toggleRight" title="图谱面板">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="5" cy="19" r="2"/><line x1="12" y1="9" x2="17" y2="7"/><line x1="12" y1="15" x2="17" y2="17"/><line x1="12" y1="9" x2="7" y2="7"/><line x1="12" y1="15" x2="7" y2="17"/></svg>
      </button>
      <a :href="`/chat?taskId=${taskId}`" target="_blank" class="header-link">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> AI
      </a>
      <a href="/" class="header-link">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg> 返回
      </a>
    </div>

    <div class="layout">
      <div v-show="leftVisible" class="left-panel" :style="{ flex: leftFlex }">
        <!-- Left Breadcrumb -->
        <div class="breadcrumb">
          <template v-if="docBreadcrumb.length">
            <span class="bc-link" @click="navBack(-1)">根</span>
            <template v-for="(bc, i) in docBreadcrumb" :key="i">
              <span class="bc-sep"> › </span>
              <span class="bc-link" @click="navBack(i)">{{ bc.label }}</span>
            </template>
          </template>
          <span v-else-if="doc" class="bc-link">{{ doc.title }}</span>
        </div>

        <div v-if="pageMode === 'file-summary' && filePreview" class="file-preview-panel">
          <div class="file-preview-header"><button class="tb-btn" @click="pageMode = 'doc'; filePreview = null">← 返回文档</button></div>
          <div class="file-preview-info"><code>{{ filePreview }}</code></div>
          <div class="file-summary-area">
            <div v-if="fileSummary?.found" class="file-summary-text">{{ fileSummary.summary }}</div>
            <div v-else class="file-summary-empty">暂无摘要</div>
          </div>
        </div>

        <div v-else class="doc-scroll">
          <div v-if="loading" class="loading">加载中...</div>
          <div v-else-if="doc" ref="docContentRef" class="content" @click="onDocAnnoClick">
            <template v-for="(b, i) in docBlocks" :key="i">
              <span v-if="b.type === 'text'" class="doc-render" v-html="getAnnotationBlocks(b.html || '')"></span>
              <MermaidViewer
                v-else-if="b.type === 'mermaid'"
                :code="b.code!"
                :diag-id="b.diagId!"
                :msg-id="docId.value || originalDocId.value"
                :initial-state="b.initialState"
                @save-state="saveDiagramStates"
              />
              <PlantUmlViewer
                v-else-if="b.type === 'plantuml'"
                :code="b.code!"
                :diag-id="b.diagId!"
                :msg-id="docId.value || originalDocId.value"
                :initial-state="b.initialState"
                @save-state="saveDiagramStates"
              />
            </template>
          </div>
          <div v-else class="content"><p>请通过 URL 参数传入 taskId</p></div>

          <!-- File list section (inside scroll, below content) -->
          <div v-if="files.length" class="file-list-section">
            <h3>文件列表 ({{ files.length }})</h3>
            <input v-model="fileSearch" class="file-search" placeholder="搜索文件..." @input="filterFiles" />
            <div v-for="f in filteredFiles_.slice(0, 20)" :key="f.path" class="file-item" @click="openFilePreview(f.path)">
              <span class="file-name">{{ f.name }}</span>
              <span class="file-path">{{ f.path }}</span>
            </div>
          </div>

          <!-- Children (inside scroll, below content) -->
          <div v-if="children.length" class="children-section">
            <h3>子组件 ({{ children.length }})</h3>
            <div v-for="c in children" :key="c.commId" class="child-item">
              <a :href="`/doc?taskId=${taskId}&communityId=${c.commId}&edgeType=${docEdgeType}`">{{ c.name || c.commId }}</a>
            </div>
          </div>
        </div>

        <!-- TOC float (left side, over content) -->
        <div class="toc-float" id="tocFloat" ref="tocFloatRef">
          <button class="toc-toggle" @click="toggleToc">{{ tocVisible ? '✕' : '☰' }}</button>
          <div v-if="tocVisible" class="toc-panel">
            <div v-if="tocLoading" class="toc-loading">加载中...</div>
            <template v-else>
              <div v-if="tocCallChildren.length" class="toc-section">
                <div class="toc-title">调用分析 ({{ tocCallChildren.length }})</div>
                <div v-for="c in tocCallChildren" :key="c.commId" class="toc-item" @click="tocNavigate(c)">{{ c.name || c.commId }}</div>
              </div>
              <div v-if="tocIncludeChildren.length" class="toc-section">
                <div class="toc-title">依赖分析 ({{ tocIncludeChildren.length }})</div>
                <div v-for="c in tocIncludeChildren" :key="c.commId" class="toc-item" @click="tocNavigate(c)">{{ c.name || c.commId }}</div>
              </div>
              <div v-if="!tocCallChildren.length && !tocIncludeChildren.length" class="toc-empty">没有更深层的组件结构</div>
            </template>
          </div>
        </div>
      </div>

      <div class="resizer" ref="resizerRef"></div>

      <div v-show="rightVisible" class="right-panel" :style="{ flex: rightFlex }">
        <!-- Right Breadcrumb -->
        <div class="breadcrumb">
          <span class="bc-link" @click="graphBreadcrumb = []; graphCommId = ''; loadGraph(); loadRightCommTree()">根</span>
          <template v-for="(cs, i) in graphBreadcrumb" :key="i">
            <span class="bc-sep"> › </span>
            <span class="bc-link" @click="graphBreadcrumb = graphBreadcrumb.slice(0, i + 1); graphCommId = cs.cid; graphEdgeType = cs.et; loadGraph(); loadRightCommTree()">{{ cs.label || cs.cid.slice(0, 16) }} <span class="bc-et">({{ cs.et }})</span></span>
          </template>
        </div>

        <!-- Community index float -->
        <div class="toc-float" id="fileCommFloat" ref="fileCommFloatRef">
          <button class="toc-toggle" @click="commFloatVisible = !commFloatVisible">{{ commFloatVisible ? '✕' : '☰' }}</button>
          <div v-if="commFloatVisible" class="toc-panel file-comm-panel">
            <div class="right-panel-toolbar" style="display:flex;align-items:center;gap:4px;margin-bottom:2px;padding-bottom:3px;border-bottom:1px solid var(--border);flex-wrap:wrap">
              <div class="right-panel-toolbar" style="display:flex;align-items:center;gap:4px;padding-top:2px;flex-wrap:wrap">
                <div class="et-tabs">
                  <button v-for="et in etOptions" :key="et" class="et-tab" :class="{ active: graphEdgeType === et }" @click="setEdgeType(et)">{{ et === 'INCLUDE' ? '内部依赖' : et === 'CALL' ? '内部调用' : et === 'EXTERNAL_INCLUDE' ? '外部依赖' : '外部调用' }}</button>
                </div>
              </div>
              <div class="right-panel-toolbar" style="display:flex;align-items:center;gap:4px;padding-top:2px;flex-wrap:wrap">
                <label v-if="gran === 'component'" style="font-size:var(--ui-font-size);color:var(--text-muted)">深度: <select v-model.number="rightDepth" @change="loadGraph" class="depth-select">
                  <option :value="1">1</option><option :value="2">2</option><option :value="3">3</option><option :value="4">4</option><option :value="5">5</option>
                </select></label>
                <span v-if="gran === 'component'" class="tab-sep">|</span>
                <label style="font-size:var(--ui-font-size);color:var(--text-muted)">超时: <select v-model.number="layoutTimeout" class="depth-select">
                  <option :value="30">30s</option><option :value="60">60s</option><option :value="90">90s</option><option :value="120">120s</option>
                </select></label>
              </div>
              <hr class="right-panel-hr">
              <div id="rightCommList">
                <div v-if="rightCommTree.length" class="comm-tree">
                  <div v-for="c in rightCommTree" :key="c.commId" class="comm-tree-item" @click="navigateComm(c.commId, c.name)">
                    <span class="comm-tree-name">{{ c.name || c.commId }}</span>

                  </div>
                </div>
                <div v-else class="comm-tree-empty" style="font-size:var(--ui-font-size);color:var(--text-muted);padding:8px">加载社区列表...</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Graph toolbar -->
        <div class="graph-toolbar" :class="{ collapsed: toolbarCollapsed }">
          <div class="graph-toolbar-header" @mousedown.stop>
            <span class="graph-toolbar-title">{{ toolbarTitle }}</span>
            <button class="graph-toolbar-collapse" @click="toolbarCollapsed = !toolbarCollapsed">{{ toolbarCollapsed ? '+' : '−' }}</button>
          </div>
          <div v-show="!toolbarCollapsed" class="graph-toolbar-body">
            <button class="tb-btn" :class="{ active: followMode, 'tb-disabled': isHeatmap }" @click="toggleFollowMode">{{ followMode ? '跟随' : '独立' }}</button>
            <button class="tb-btn" :class="{ active: showEdges, 'tb-disabled': isHeatmap }" @click="toggleEdges">连线</button>
            <button class="tb-btn" :class="{ active: gran === 'component', 'tb-disabled': isHeatmap }" @click="toggleGran">{{ gran === 'component' ? '组件' : '文件' }}</button>
            <button class="tb-btn" :class="{ active: true }" @click="toggleTab">{{ graphTab === 'graph' ? '关系图' : '热力图' }}</button>
            <button class="tb-btn" :class="{ 'tb-disabled': isHeatmap }" @click="toggleFilter">筛选</button>
            <button class="tb-btn" :class="{ 'tb-disabled': isHeatmap }" @click="resetLayout">重置</button>
          </div>
        </div>

        <!-- Filter panel (right side floating) -->
        <div v-if="filterVisible" class="graph-filter-panel open">
          <button class="graph-filter-close" @click="filterVisible = false">✕</button>
          <div class="graph-filter-header">
            <span class="graph-filter-drag-icon">⠿</span>
            <input v-model="filterQuery" class="filter-input" placeholder="搜索节点..." @input="applyFilter" />
            <button class="tb-btn graph-filter-toggle" @click="cycleFilter" :title="filterToggleTitle()">{{ filterToggleLabel() }}</button>
          </div>
          <div class="graph-filter-list">
            <div v-for="n in filteredNodeList" :key="n.id" class="graph-filter-item" :class="{ filtered: isNodeHidden(n.id) }" @click="toggleNodeFilter(n.id)">
              <span class="gfi-dot" :style="{ background: _nodeFilterColor(n.id) }"></span>
              <span class="gfi-label">{{ n.label }}</span>
            </div>
            <div v-if="!filteredNodeList.length" class="graph-filter-empty">无匹配节点</div>
          </div>
        </div>

        <!-- Graph -->
        <div v-show="graphTab === 'graph'" class="cy-container">
          <div class="cy-canvas" ref="cyContainer"></div>
          <div v-if="graphLoading" class="cy-overlay"><div class="cy-overlay-box"><div class="spinner"></div><span>加载图谱...</span></div></div>
          <div v-if="!graphNodes.length && !graphLoading" class="cy-placeholder">暂无图谱数据</div>
        </div>

        <!-- Heatmap -->
        <div v-show="graphTab === 'heatmap'" class="heatmap-container">
          <div class="heatmap-controls">
            <label>规模: <select v-model.number="heatmapSize" @change="loadHeatmap(taskId.value, graphEdgeType.value, graphCommId.value)">
              <option :value="5">5x5</option><option :value="10">10x10</option><option :value="15">15x15</option>
              <option :value="20">20x20</option><option :value="30">30x30</option><option :value="50">50x50</option>
            </select></label>
          </div>
          <div v-if="heatmapLoading" class="loading">加载热力图...</div>
          <div v-else-if="heatmapData" class="heatmap-grid">
            <table><thead><tr><th></th><th v-for="c in heatmapData.cols" :key="c" class="hm-col-hdr" :title="c">{{ c.slice(0,12) }}</th></tr></thead>
              <tbody><tr v-for="(row, ri) in heatmapData.matrix" :key="ri">
                <th class="hm-row-hdr" :title="heatmapData.rows[ri]">{{ heatmapData.rows[ri].slice(0,12) }}</th>
                <td v-for="(val, ci) in row" :key="ci" :style="{ background: heatmapBg(val, heatmapData.maxCount), textAlign:'center', padding:'2px 4px', minWidth:'20px', fontSize:'var(--ui-font-size)', border:'1px solid var(--border)', cursor:'pointer' }"
                    @click="heatmapData.commIds?.[ci] && heatmapDrill(heatmapData.commIds[ci])">{{ val > 0 ? val : '' }}</td>
              </tr></tbody>
            </table>
          </div>
          <div v-else class="cy-placeholder" style="position:static">暂无热力图数据</div>
        </div>

        <GraphContextMenu
          :visible="contextMenuVisible"
          :pos="contextMenuPos"
          :node-id="contextNodeId"
          :graph-comm-id="graphCommId"
          :is-external="contextNodeIsExternal"
          :has-children="contextNodeHasChildren"
          :center-nodes="getCenterNodes()"
          @copy="handleCtxCopy(contextNodeId); contextMenuVisible = false"
          @drilldown="ctxDrilldown"
          @center="ctxCenter"
          @open-doc="ctxOpenDoc"
          @save-note="ctxSaveNote"
        />

        <!-- Notes Modal (legacy-aligned) -->
        <div v-if="notesModalVisible" class="note-overlay" @click.self="notesModalVisible = false">
          <div class="note-modal">
            <div class="note-modal-header">
              <h2>便签簿</h2>
              <button class="close" @click="notesModalVisible = false">&times;</button>
            </div>
            <div class="note-modal-filter">
              <select v-model="notesProjectFilter">
                <option value="">全部项目</option>
                <option v-for="p in notesProjectOptions" :key="p" :value="p">{{ p }}</option>
              </select>
              <select v-model="notesFilterStatus">
                <option value="all">全部状态</option>
                <option value="draft">草稿</option>
                <option value="pending">待处理</option>
                <option value="done">已完成</option>
              </select>
              <select v-model="notesSortOrder">
                <option value="seq">按序号</option>
                <option value="time">按时间</option>
              </select>
              <span class="info">{{ filteredNotes.reduce((a:any,n:any)=>a+(n.refs?.length||0),0) }} 条</span>
            </div>
            <div class="note-modal-body">
              <div v-if="!filteredNotes.length" class="note-empty">暂无草稿，在文档区选中文本后可存入便签</div>
              <template v-for="n in filteredNotes" :key="n.id">
                <div v-for="(r, ri) in n.refs" :key="r._id || ri" class="note-draft-card">
                  <div class="draft-header">
                    <input type="checkbox" class="cbox" :value="n.id + '|' + r._id" />
                    <span class="draft-seq">#{{ n.seq }}.{{ r.seq || (ri+1) }}</span>
                    <span class="draft-meta">
                      <span v-if="r.projectName" class="ref-id">{{ r.projectName }}</span>
                      <span v-if="r.taskId" class="ref-id">{{ r.taskId.slice(0,8) }}</span>
                      <span v-if="r.componentId" class="ref-id">{{ r.componentId.slice(0,12) }}</span>
                      <button class="copy-id-btn" title="复制引用ID" @click.stop="navigator.clipboard?.writeText(r.componentId || r._id).then(()=>toast('已复制'))?.catch(()=>{})">复制</button>
                    </span>
                    <span class="draft-actions">
                      <button class="del" @click.stop="deleteRefFromNote(n.id, r._id)">删除</button>
                    </span>
                  </div>
                  <div class="draft-body">
                    <textarea :value="r.text" @input="(e:any)=>{const t=e.target.value;const found=notesList.value.find(x=>x.id===n.id);if(found){const rf=found.refs.find((x:any)=>x._id===r._id);if(rf)rf.text=t}}" rows="2"></textarea>
                  </div>
                </div>
              </template>
            </div>
            <div class="note-modal-user-text">
              <textarea v-model="notesUserText" placeholder="描述分析需求..." rows="2"></textarea>
              <div class="hint">提示：使用 #编号 引用材料</div>
            </div>
            <div v-if="notesExecStep === 'sessions'" class="note-modal-sessions">
              <select id="noteSessionSelect" class="session-select" size="5">
                <option value="__new__">＋ 新建会话</option>
                <option v-for="s in notesSessions" :key="s.id" :value="s.id">{{ s.title || s.id.slice(0,12) }}</option>
              </select>
            </div>
            <div class="note-modal-footer">
              <label class="checkbox-label"><input type="checkbox" v-model="notesAutoDelete" checked> 自动删除已处理引用</label>
              <button class="btn btn-secondary" @click="deleteSelectedRefs">删除选中</button>
              <button class="btn btn-secondary" @click="manualDrafts">手动处理</button>
              <button class="btn btn-primary" @click="executeNotes">{{ notesExecStep === 'sessions' ? '确认发送' : '执行' }}</button>
            </div>
          </div>
        </div>

        <!-- Annotation Editor -->
        <div v-if="editAnnoData" class="dialog-overlay" @click.self="editAnnoData = null">
          <div class="dialog-box" style="width:520px">
            <h3>{{ editAnnoData.isNew ? '添加批注' : '编辑批注' }}</h3>
            <div v-if="editAnnoData.id" style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono);margin-bottom:8px">{{ editAnnoData.id }}</div>
            <textarea v-model="editAnnoData.text" class="anno-textarea" placeholder="输入批注内容..."></textarea>
            <div class="dialog-actions">
              <button v-if="!editAnnoData.isNew" class="dialog-btn" style="color:#ef4444" @click="deleteAnnotation">删除</button>
              <span style="flex:1"></span>
              <button class="dialog-btn" @click="editAnnoData = null">取消</button>
              <button class="dialog-btn primary" @click="saveAnnotation">保存</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
:root{--bg:#ffffff;--bg-secondary:#f7f7f8;--bg-hover:#f0f0f2;--bg-code:#f4f4f5;--text:#1a1a1a;--text-secondary:#6b6b76;--text-muted:#8e8e98;--border:#e4e4e7;--accent:#4d6bfe;--accent-hover:#3a56d4;--accent-light:rgba(77,107,254,0.08);--shadow-sm:0 1px 2px rgba(0,0,0,0.04);--radius-sm:6px;--radius-md:8px;--radius-lg:12px;--font:'Inter',-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;--font-mono:"JetBrains Mono","Fira Code",monospace;--transition:0.2s ease;--content-font-size:18px;--ui-font-size:14px}
@media(prefers-color-scheme:dark){:root{--bg:#212121;--bg-secondary:#2d2d2d;--bg-hover:#3d3d3d;--bg-code:#2a2a2a;--text:#e8e8e8;--text-secondary:#a0a0a0;--text-muted:#6b6b6b;--border:#3d3d3d;--accent:#60a5fa;--accent-hover:#3b82f6;--accent-light:rgba(96,165,250,0.12)}}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--bg);color:var(--text);font-size:14px;overflow:hidden;height:100vh;-webkit-font-smoothing:antialiased}
.viewer{display:flex;flex-direction:column;height:100vh}
.header{display:flex;align-items:center;gap:6px;padding:6px 12px;border-bottom:1px solid var(--border);height:40px;flex-shrink:0;flex-wrap:wrap}
.header .title{font-weight:500;font-size:var(--ui-font-size);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:100px}
.header select,.toggle-btn{font-size:var(--ui-font-size);border-radius:var(--radius-sm)}
.header select{padding:2px 5px;border:1px solid var(--border);background:var(--bg);color:var(--text);outline:none}
.toggle-btn{background:none;border:1px solid var(--border);padding:3px 5px;cursor:pointer;color:var(--text-muted);display:inline-flex;align-items:center}
.toggle-btn:hover{background:var(--bg-hover);color:var(--text)}
.toggle-btn.active{color:var(--accent);border-color:var(--accent);background:var(--accent-light)}
.header-link,.toggle-btn{text-decoration:none}
.header-link{color:var(--accent);font-size:var(--ui-font-size);display:inline-flex;align-items:center;gap:2px;padding:3px 6px}
.header-link:hover{background:var(--bg-hover)}
.layout{display:flex;flex:1;overflow:hidden}
.left-panel,.right-panel{overflow-y:auto;min-width:0;display:flex;flex-direction:column;position:relative}
.resizer{width:5px;cursor:col-resize;background:var(--border);flex-shrink:0}
.breadcrumb{font-size:var(--ui-font-size);padding:4px 12px;border-bottom:1px solid var(--border);color:var(--text-muted);flex-shrink:0;display:flex;flex-wrap:wrap;gap:2px}
.bc-link{color:var(--accent);cursor:pointer}
.bc-link:hover{text-decoration:underline}
.bc-sep{color:var(--text-muted)}
.bc-et{font-size:11px;color:var(--text-muted);font-weight:400}
.doc-scroll{overflow-y:auto;flex:1}
.content{padding:16px 20px 120px;font-size:var(--content-font-size,14px);line-height:1.7;overflow-wrap:break-word}
.content h1{font-size:1.5em;margin:0.5em 0 0.25em}
.content h2{font-size:1.2em;margin:0.4em 0 0.2em}
.content h3{font-size:1.05em;margin:0.3em 0 0.15em}
.content p{margin:0.4em 0}
.content code{background:var(--bg-code);padding:1px 5px;border-radius:3px;font-size:0.9em}
.content pre{background:var(--bg-code);padding:10px;border-radius:5px;overflow-x:auto;font-size:calc(var(--content-font-size,14px)*0.85)}
.content pre code{background:none;padding:0}
.content blockquote{border-left:3px solid var(--accent);padding-left:10px;margin:0.4em 0;color:var(--text-muted)}
.content ul,.content ol{padding-left:22px;margin:0.3em 0}
.content a{color:var(--accent)}
.content table{border-collapse:collapse;width:100%;margin:0.4em 0}
.content th,.content td{border:1px solid var(--border);padding:5px 8px;text-align:left;font-size:0.9em}
.content th{background:var(--bg-code)}
.hd-btn{display:inline-flex;align-items:center;gap:1px;margin-left:4px;vertical-align:middle}
.hd-btn-icon{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border:1px solid var(--border);border-radius:3px;background:var(--bg-secondary);cursor:pointer;opacity:0.5;font-size:10px;line-height:1}
.hd-btn-icon:hover{opacity:1;border-color:var(--accent)}
.loading{text-align:center;padding:30px;color:var(--text-muted);font-size:var(--ui-font-size)}
.file-list-section{padding:16px 20px;border-top:1px solid var(--border)}
.file-list-section h3{font-size:var(--ui-font-size);font-weight:600;margin-bottom:8px}
.file-search{width:100%;padding:4px 8px;font-size:var(--ui-font-size);border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--text);margin-bottom:8px}
.file-search:focus{outline:none;border-color:var(--accent)}
.file-item{padding:4px 8px;border-radius:3px;cursor:pointer;display:flex;gap:6px;align-items:center;font-size:var(--ui-font-size)}
.file-item:hover{background:var(--bg-code)}
.file-name{font-weight:500;white-space:nowrap;color:var(--text)}
.file-path{color:var(--text-muted);font-family:monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.file-preview-panel{padding:16px 20px;flex:1;overflow-y:auto}
.file-preview-header{margin-bottom:12px}
.file-preview-info code{font-family:var(--font-mono);font-size:var(--ui-font-size);background:var(--bg-code);padding:2px 6px;border-radius:3px}
.file-summary-area{margin-top:16px}
.file-summary-text{font-size:var(--ui-font-size);line-height:1.7;white-space:pre-wrap;color:var(--text)}
.file-summary-empty{font-size:var(--ui-font-size);color:var(--text-muted);font-style:italic}
.children-section{padding:16px 20px;border-top:1px solid var(--border)}
.children-section h3{font-size:var(--ui-font-size);font-weight:600;margin-bottom:8px}
.child-item{padding:4px 0}
.child-item a{color:var(--accent);text-decoration:none;font-size:var(--ui-font-size)}
.child-item a:hover{text-decoration:underline}
.graph-toolbar{position:absolute;top:8px;left:50%;transform:translateX(-50%);z-index:100;background:var(--bg);border:1px solid var(--border);border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.12);min-width:140px;user-select:none}
.graph-toolbar.collapsed .graph-toolbar-body{display:none}
.graph-toolbar-header{display:flex;align-items:center;gap:6px;padding:3px 8px;cursor:move;border-bottom:1px solid var(--border)}
.graph-toolbar.collapsed .graph-toolbar-header{border-bottom:none}
.graph-toolbar-title{font-size:var(--ui-font-size);color:var(--text-muted);flex:1}
.graph-toolbar-collapse{width:18px;height:18px;padding:0;font-size:var(--ui-font-size);line-height:1;border:none;background:transparent;color:var(--text-muted);cursor:pointer;border-radius:3px}
.graph-toolbar-collapse:hover{background:var(--bg-hover);color:var(--text)}
.et-tabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:4px}
.et-tab{padding:2px 8px;border:1px solid var(--border);border-radius:4px;font-size:11px;background:var(--bg);color:var(--text-muted);cursor:pointer;white-space:nowrap}
.et-tab:hover{border-color:var(--accent);color:var(--text)}
.et-tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.depth-select{font-size:var(--ui-font-size);padding:1px 4px;border:1px solid var(--border);border-radius:3px;background:var(--bg);color:var(--text)}
.tab-sep{color:var(--text-muted)}
.right-panel-hr{margin:4px 0;border:none;border-top:1px solid var(--border)}
.comm-tree{font-size:var(--ui-font-size);max-height:200px;overflow-y:auto;margin-top:4px}
.comm-tree-item{display:flex;align-items:center;gap:4px;padding:3px 6px;border-radius:3px;cursor:pointer}
.comm-tree-item:hover{background:var(--bg-hover)}
.comm-tree-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)}
.comm-tree-doc{flex-shrink:0}
.sel-toolbar{position:fixed;z-index:9999;display:flex;gap:2px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-md);box-shadow:0 4px 12px rgba(0,0,0,0.18);padding:3px;pointer-events:auto}
.sel-toolbar button{background:none;border:none;padding:4px 10px;font-size:var(--ui-font-size);cursor:pointer;border-radius:4px;color:var(--text);white-space:nowrap}
.sel-toolbar button:hover{background:var(--bg-hover);color:var(--accent)}
.graph-toolbar-body{display:flex;gap:2px;padding:3px 6px;background:var(--bg);border-top:1px solid var(--border);font-size:var(--ui-font-size);flex-wrap:wrap}
.tb-btn{padding:2px 8px;border:1px solid var(--border);border-radius:3px;background:var(--bg-secondary);color:var(--text-muted);cursor:pointer;white-space:nowrap;font-size:var(--ui-font-size)}
.tb-btn:hover{border-color:var(--accent);color:var(--text)}
.tb-btn.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.tb-btn.tb-disabled{opacity:0.35;cursor:default;pointer-events:none}
.graph-filter-panel{position:absolute;right:8px;top:60px;width:220px;max-height:320px;background:var(--bg);border:1px solid var(--border);border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:100;display:flex;flex-direction:column;padding:6px;font-size:var(--ui-font-size);opacity:0.85;transition:opacity 0.2s}
.graph-filter-panel:hover{opacity:1}
.graph-filter-close{position:absolute;top:-34px;left:-1px;width:28px;height:28px;border:1px solid var(--border);background:var(--bg);color:var(--text-muted);cursor:pointer;border-radius:5px 5px 0 0;font-size:14px;display:flex;align-items:center;justify-content:center;z-index:101}
.graph-filter-close:hover{background:var(--bg-hover);color:var(--text)}
.graph-filter-header{display:flex;gap:4px;align-items:center}
.graph-filter-drag-icon{color:var(--text-muted);cursor:move;user-select:none;font-size:14px;line-height:20px}
.graph-filter-toggle{white-space:nowrap}
.graph-filter-list{max-height:200px;overflow-y:auto;margin-top:4px;border-top:1px solid var(--border);padding-top:4px}
.graph-filter-item{display:flex;align-items:center;gap:4px;padding:2px 4px;font-size:var(--ui-font-size);cursor:pointer;border-radius:3px;color:var(--text)}
.gfi-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;display:inline-block}
.gfi-label{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.graph-filter-item:hover{background:var(--bg-hover)}
.graph-filter-item.filtered{color:var(--text-muted);text-decoration:line-through}
.graph-filter-empty{padding:8px;text-align:center;color:var(--text-muted);font-size:var(--ui-font-size)}
.filter-input{flex:1;min-width:0;padding:3px 6px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:var(--ui-font-size);background:var(--bg);color:var(--text);outline:none}
.filter-input:focus{border-color:var(--accent)}
.cy-container{flex:1;min-height:0;position:relative;overflow:hidden}
.cy-canvas{position:absolute;inset:0}
.cy-placeholder{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:var(--ui-font-size);background:var(--bg)}
.cy-overlay{position:absolute;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.3)}
.cy-overlay-box{display:flex;flex-direction:column;align-items:center;gap:10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:20px 28px;min-width:160px}
.note-card{padding:8px 10px;border-radius:var(--radius-md);background:var(--bg-secondary);margin-bottom:4px;border-left:3px solid transparent}
.note-card .status-dot.draft{border-left-color:#f59e0b;background:#f59e0b}
.note-card .status-dot.sent{border-left-color:#10b981;background:#10b981}
.note-card-header{display:flex;align-items:center;gap:6px;font-size:var(--ui-font-size)}
.note-card-seq{font-weight:600;color:var(--accent);min-width:24px}
.note-card-refs{color:var(--text-muted);font-size:var(--ui-font-size)}
.note-card-text{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)}
.status-dot{width:6px;height:6px;border-radius:50%;display:inline-block;flex-shrink:0}
.status-dot.draft{background:#f59e0b}
.status-dot.sent{background:#10b981}
.spinner{width:28px;height:28px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin 0.8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.heatmap-container{flex:1;display:flex;flex-direction:column;overflow:hidden}
.heatmap-controls{padding:6px 12px;border-bottom:1px solid var(--border);font-size:var(--ui-font-size);display:flex;align-items:center;gap:8px;flex-shrink:0}
.heatmap-controls select{padding:2px 4px;font-size:var(--ui-font-size);border:1px solid var(--border);border-radius:3px;background:var(--bg);color:var(--text)}
.heatmap-grid{flex:1;overflow:auto;padding:8px;font-size:var(--ui-font-size)}
.heatmap-grid table{border-collapse:separate;border-spacing:0}
.heatmap-grid td{border:1px solid var(--border);padding:2px 4px;text-align:center;min-width:20px}
.heatmap-grid th{border:1px solid var(--border);padding:2px 6px;font-weight:500;font-size:var(--ui-font-size);max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;background:var(--bg)}
.hm-row-hdr{position:sticky;left:0;z-index:2;min-width:60px;max-width:160px;border-right:2px solid var(--border)}
.hm-col-hdr{position:sticky;top:0;z-index:1;border-bottom:2px solid var(--border)}
.toc-float{position:fixed;z-index:50;display:flex;flex-direction:column;align-items:flex-start;cursor:grab;user-select:none;opacity:0.6;transition:opacity 0.15s;width:fit-content}
.toc-float:hover{opacity:1}
.toc-float.dragging{cursor:grabbing}
#tocFloat{top:44px;left:auto;right:auto}
#fileCommFloat{top:44px;left:auto;right:auto;align-items:flex-start}
.toc-toggle{width:30px;height:30px;border:1px solid var(--accent);background:var(--accent-light);border-radius:5px;cursor:pointer;font-size:var(--ui-font-size);color:var(--accent);display:flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(0,0,0,0.1)}
.toc-toggle:hover{background:var(--accent);color:#fff;border-color:var(--accent)}
.toc-panel{margin-top:4px;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 10px;max-width:280px;min-width:200px;min-height:60px;max-height:50vh;overflow-y:auto;box-shadow:0 4px 12px rgba(0,0,0,0.12);font-size:var(--ui-font-size)}
.toc-float.flip-overflow .toc-panel{position:absolute;top:100%;margin-top:4px;left:auto;right:auto}
.toc-float.flip-overflow.flip-up .toc-panel{top:auto;bottom:100%;margin-top:0;margin-bottom:4px}
.toc-float.flip-overflow.flip-left .toc-panel{right:0;left:auto}
.toc-section + .toc-section{margin-top:6px;padding-top:6px;border-top:1px solid var(--border)}
.toc-title{font-weight:600;margin-bottom:4px;font-size:var(--ui-font-size)}
.toc-item{padding:3px 4px;cursor:pointer;color:var(--accent);border-radius:2px;font-size:var(--ui-font-size)}
.toc-item:hover{background:var(--bg-code)}
.toc-empty{color:var(--text-muted);font-style:italic;padding:8px;text-align:center;font-size:var(--ui-font-size)}
.toc-loading{color:var(--text-muted);padding:8px;text-align:center;font-size:var(--ui-font-size)}
.file-comm-panel{width:260px}
.ctx-menu{position:fixed;z-index:1000;min-width:140px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.25);padding:4px;font-size:var(--ui-font-size)}
.ctx-item{padding:5px 8px;border-radius:4px;cursor:pointer;color:var(--text)}
.ctx-item:hover{background:var(--bg-hover)}
.ctx-divider{height:1px;background:var(--border);margin:3px 6px}
.notes-btn{position:relative}
.notes-dot{position:absolute;top:-2px;right:-2px;width:8px;height:8px;border-radius:50%;background:#ef4444;border:2px solid var(--bg);animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.note-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;animation:fadeIn .15s ease}
.note-modal{width:780px;max-height:85vh;background:var(--bg);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,0.25)}
.note-modal-header{display:flex;align-items:center;padding:16px 20px;border-bottom:1px solid var(--border);flex-shrink:0}
.note-modal-header h2{font-size:16px;font-weight:600;flex:1;color:var(--text)}
.note-modal-header .close{background:none;border:none;color:var(--text-muted);font-size:20px;cursor:pointer;padding:2px 8px;border-radius:4px}
.note-modal-header .close:hover{color:var(--text);background:var(--bg-hover)}
.note-modal-filter{display:flex;gap:8px;align-items:center;padding:10px 20px;border-bottom:1px solid var(--border);flex-shrink:0;flex-wrap:wrap}
.note-modal-filter select{padding:4px 8px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;background:var(--bg);color:var(--text);outline:none}
.note-modal-filter select:focus{border-color:var(--accent)}
.note-modal-filter .info{font-size:13px;color:var(--text-muted);margin-left:auto}
.note-modal-body{flex:1;overflow-y:auto;padding:12px 20px;min-height:0}
.note-draft-card{border:1px solid var(--border);border-radius:var(--radius-md);margin-bottom:8px;padding:10px 12px;background:var(--bg-secondary)}
.note-draft-card:hover{border-color:var(--accent)}
.draft-header{display:flex;align-items:center;gap:6px;margin-bottom:6px}
.draft-header .cbox{flex-shrink:0}
.draft-header .draft-seq{font-size:13px;color:var(--accent);font-weight:600;min-width:28px;flex-shrink:0;padding-top:2px}
.draft-header .draft-meta{flex:1;font-size:13px;color:var(--text-secondary);line-height:1.5;min-width:0}
.draft-header .draft-meta .ref-id{display:inline-block;background:var(--accent-light);color:var(--accent);padding:1px 6px;border-radius:4px;font-size:12px;margin:1px 3px 1px 0}
.copy-id-btn{background:none;border:none;font-size:12px;cursor:pointer;padding:0 2px;border-radius:3px;color:var(--text-muted);vertical-align:middle}
.copy-id-btn:hover{background:var(--accent-light);color:var(--accent)}
.draft-actions{flex-shrink:0;display:flex;gap:4px}
.draft-actions button{background:none;border:none;font-size:12px;color:var(--text-muted);cursor:pointer;padding:2px 6px;border-radius:4px}
.draft-actions button:hover{background:var(--bg-hover);color:var(--text)}
.draft-actions .del:hover{color:#ef4444}
.draft-body textarea{width:100%;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;font-family:var(--font);color:var(--text);background:var(--bg);outline:none;resize:vertical;min-height:36px;transition:border-color .15s;box-sizing:border-box}
.draft-body textarea:focus{border-color:var(--accent)}
.note-modal-user-text{padding:8px 20px;border-top:1px solid var(--border);flex-shrink:0}
.note-modal-user-text textarea{width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:var(--radius-md);font-size:13px;font-family:var(--font);color:var(--text);background:var(--bg);outline:none;resize:none;min-height:48px;transition:border-color .15s;box-sizing:border-box}
.note-modal-user-text textarea:focus{border-color:var(--accent)}
.note-modal-user-text .hint{font-size:12px;color:var(--text-muted);margin-top:4px}
.note-modal-sessions{padding:8px 20px;border-top:1px solid var(--border);flex-shrink:0;max-height:160px;overflow-y:auto}
.session-select{width:100%;padding:4px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;background:var(--bg);color:var(--text);outline:none}
.session-select option{padding:4px 6px}
.note-modal-footer{display:flex;align-items:center;gap:8px;padding:12px 20px;border-top:1px solid var(--border);flex-shrink:0;flex-wrap:wrap}
.note-modal-footer .checkbox-label{font-size:13px;color:var(--text-secondary);display:flex;align-items:center;gap:4px;cursor:pointer;margin-right:auto}
.note-modal-footer .btn{background:none;border:1px solid var(--border);border-radius:var(--radius-md);padding:6px 14px;font-size:13px;cursor:pointer;color:var(--text);transition:all .15s}
.note-modal-footer .btn:hover{border-color:var(--accent)}
.note-modal-footer .btn-secondary{background:var(--bg-secondary)}
.note-modal-footer .btn-primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.note-empty{padding:40px;text-align:center;font-size:13px;color:var(--text-muted);line-height:1.6}
.doc-annotation{display:flex;gap:8px;margin:12px 0;padding:10px 12px;background:var(--bg-hover);border-radius:var(--radius-md);cursor:pointer}
.doc-annotation:hover{outline:1px solid var(--accent)}
.doc-anno-marker{width:3px;flex-shrink:0;background:var(--accent);border-radius:2px;opacity:.6}
.doc-anno-body{flex:1;font-size:13px;color:var(--text-secondary);line-height:1.6}
.doc-anno-body p{margin:4px 0}
.dialog-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;animation:fadeIn .15s ease}
.dialog-box{background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:24px;max-width:90vw;box-shadow:0 8px 32px rgba(0,0,0,0.25)}
.dialog-box h3{font-size:15px;font-weight:600;color:var(--text);margin-bottom:12px}
.dialog-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
.dialog-btn{padding:7px 16px;border-radius:8px;font-size:13px;cursor:pointer;border:1px solid var(--border);background:var(--bg);color:var(--text)}
.dialog-btn:hover{border-color:var(--accent)}
.dialog-btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.anno-textarea{width:100%;min-height:120px;font-size:13px;padding:10px;border:1px solid var(--border);border-radius:8px;resize:vertical;outline:none;box-sizing:border-box;font-family:inherit;background:var(--bg);color:var(--text)}
.anno-textarea:focus{border-color:var(--accent)}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
</style>
