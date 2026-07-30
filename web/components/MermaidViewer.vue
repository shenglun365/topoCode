<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { normalizeDiagram, ensureMermaid, enqueueRender, fitScale } from '@web/services/render'
import { diagramStateStore } from '@web/services/diagramStateStore'
import DiagramRebuildDialog from '@web/components/DiagramRebuildDialog.vue'

function stripHtml(s: string) { return s.replace(/<!--[\s\S]*?-->/g, '') }

const props = defineProps<{
  code: string
  diagId: string
  msgId?: string
  initialState?: DiagramViewState | null
}>()

const emit = defineEmits<{
  'code-change': [diagId: string, newCode: string]
  'state-change': []
  'save-state': []
}>()

const contentId = computed(() => props.msgId || '')

const svgWrap = ref<HTMLElement>()
const diagView = ref<HTMLElement>()
const textarea = ref<HTMLTextAreaElement>()
const container = ref<HTMLElement>()
const loading = ref(true)
const error = ref('')
const activeTab = ref<'chart' | 'code'>('chart')
const zoomPct = ref('100%')
const unsaved = ref(false)

let zs = 1, dx = 0, dy = 0
let containerHeight: number | undefined
let userZoomed = false
let ro: ResizeObserver | null = null
let hasSavedState = false

const savedState = diagramStateStore.load(props.diagId, contentId.value) || props.initialState
if (savedState) {
  hasSavedState = true
  zs = savedState.zs
  dx = savedState.dx
  dy = savedState.dy
}

// ── 角劲渲染：仅当容器进入视口后才开始渲染 ——


function notifyStateChange() {
  diagramStateStore.save(props.diagId, contentId.value, { zs, dx, dy })
  unsaved.value = true
  emit('state-change')
  document.dispatchEvent(new CustomEvent('diagram-state-changed'))
}

function onDiagStateChange() {
  unsaved.value = diagramStateStore.isDiagDirty(props.diagId, contentId.value)
}

onMounted(() => document.addEventListener('diagram-state-changed', onDiagStateChange))
onUnmounted(() => document.removeEventListener('diagram-state-changed', onDiagStateChange))

onMounted(() => { unsaved.value = diagramStateStore.isDiagDirty(props.diagId, contentId.value) })

let notifyTimer: any
function scheduleNotify() {
  clearTimeout(notifyTimer)
  notifyTimer = setTimeout(notifyStateChange, 300)
}

function applyScale() {
  if (svgWrap.value) {
    const svg = svgWrap.value.querySelector('svg')
    if (svg) {
      const vb = svg.getAttribute('viewBox')
      if (vb) {
        const parts = vb.trim().split(/\s+/).map(Number)
        if (parts.length >= 4) {
          const nw = parts[2]
          const nh = parts[3]
          if (nw > 0 && nh > 0) {
            svg.style.width = Math.round(nw * zs) + 'px'
            svg.style.height = Math.round(nh * zs) + 'px'
          }
        }
      }
      svg.style.marginLeft = dx + 'px'
      svg.style.marginTop = dy + 'px'
    }
    svgWrap.value.style.transform = ''
    svgWrap.value.style.transformOrigin = ''
  }
}

function reFit() {
  if (userZoomed || hasSavedState || !diagView.value || !svgWrap.value) return
  const s = fitScale(svgWrap.value.scrollWidth, svgWrap.value.scrollHeight, diagView.value.clientWidth, diagView.value.clientHeight)
  if (s !== null) { zs = s; dx = 0; dy = 0; zoomPct.value = Math.round(s * 100) + '%'; applyScale(); scheduleNotify() }
}

async function renderMermaid(codeOverride?: string) {
  loading.value = true
  error.value = ''
  try {
    const mermaidApi = await ensureMermaid()
    const n = normalizeDiagram(stripHtml(codeOverride ?? props.code), 'mermaid')
    const clean = n.code
    const valid = await mermaidApi.parse(clean, { suppressErrors: true })
    if (!valid) throw new Error('图解法错误')
    const uid = 'm-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6)
    const result = await mermaidApi.render(uid, clean)
    if (svgWrap.value) {
      svgWrap.value.innerHTML = result.svg
      applyScale()
    }
    loading.value = false
    await nextTick()
    if (svgWrap.value && diagView.value) {
      const sw = svgWrap.value.scrollWidth
      const sh = svgWrap.value.scrollHeight
      const cw = diagView.value.clientWidth
      const ch = diagView.value.clientHeight
      if (!hasSavedState && (sw > cw || sh > ch)) {
        const s = fitScale(sw, sh, cw, ch)
        if (s !== null && s < zs) {
          zs = s; dx = 0; dy = 0
          zoomPct.value = Math.round(s * 100) + '%'
          applyScale()
        }
      }
    }
  } catch (e: any) {
    error.value = e.message || '渲染失败'
    loading.value = false
  }
}

onMounted(() => {
  enqueueRender(renderMermaid)
  if (diagView.value) {
    ro = new ResizeObserver(() => reFit())
    ro.observe(diagView.value)
  }
})
watch(() => props.code, () => { userZoomed = false; activeTab.value = 'chart'; renderMermaid() })

function onWheel(e: WheelEvent) {
  if (!(e.ctrlKey || e.metaKey) || !diagView.value) return
  e.preventDefault()
  userZoomed = true
  const rect = diagView.value.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const factor = e.deltaY > 0 ? 0.9 : 1.1
  const old = zs
  zs = Math.max(0.25, Math.min(5, zs * factor))
  dx = dx + mx * (1 - zs / old)
  dy = dy + my * (1 - zs / old)
  applyScale()
  zoomPct.value = Math.round(zs * 100) + '%'
  scheduleNotify()
}

let dragging = false, startX = 0, startY = 0, sx = 0, sy = 0

function onSvgMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  userZoomed = true
  dragging = true; startX = e.clientX; startY = e.clientY; sx = dx; sy = dy
}

function onWindowMouseMove(e: MouseEvent) {
  if (!dragging) return
  dx = sx + (e.clientX - startX)
  dy = sy + (e.clientY - startY)
  applyScale()
}

function onWindowMouseUp() {
  if (!dragging) return
  dragging = false
  scheduleNotify()
}

onMounted(() => {
  window.addEventListener('mousemove', onWindowMouseMove)
  window.addEventListener('mouseup', onWindowMouseUp)
})
onUnmounted(() => {
  window.removeEventListener('mousemove', onWindowMouseMove)
  window.removeEventListener('mouseup', onWindowMouseUp)
  ro?.disconnect()
})

function downloadSvg() {
  const svg = svgWrap.value?.querySelector('svg')
  if (!svg) return
  const xml = new XMLSerializer().serializeToString(svg.cloneNode(true))
  const blob = new Blob(['<?xml version="1.0"?>' + xml], { type: 'image/svg+xml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'diagram.svg'; a.click()
  URL.revokeObjectURL(url)
}

function fullscreen() {
  const svg = svgWrap.value?.innerHTML
  if (!svg) return
  const ov = document.createElement('div')
  ov.className = 'diag-fullscreen-overlay'
  const fc = document.createElement('div')
  fc.className = 'diag-fs-content'
  fc.innerHTML = svg
  const closeBtn = document.createElement('button')
  closeBtn.className = 'diag-fs-close'
  closeBtn.textContent = '\u00D7'
  ov.appendChild(closeBtn); ov.appendChild(fc)
  document.body.appendChild(ov)
  let fsScale = 1, fsDx = 0, fsDy = 0, fsDragging = false, fsStartX = 0, fsStartY = 0, fsSx = 0, fsSy = 0
  function fsUpdate() { fc.style.transform = `translate(${fsDx}px,${fsDy}px) scale(${fsScale})` }
  ov.addEventListener('wheel', (e) => {
    e.preventDefault()
    const old = fsScale
    fsScale = Math.max(0.25, Math.min(5, fsScale + (e.deltaY > 0 ? -0.2 : 0.2)))
    const rect = fc.getBoundingClientRect()
    const mx = e.clientX - rect.left, my = e.clientY - rect.top
    fsDx = fsDx + mx * (1 - fsScale / old)
    fsDy = fsDy + my * (1 - fsScale / old)
    fsUpdate()
  }, { passive: false })
  fc.onmousedown = (e) => {
    fsDragging = true; fsStartX = e.clientX; fsStartY = e.clientY; fsSx = fsDx; fsSy = fsDy; fc.style.cursor = 'grabbing'
  }
  const mm = (e: MouseEvent) => {
    if (!fsDragging) return; fsDx = fsSx + (e.clientX - fsStartX); fsDy = fsSy + (e.clientY - fsStartY); fsUpdate()
  }
  const mu = () => { fsDragging = false; fc.style.cursor = '' }
  window.addEventListener('mousemove', mm); window.addEventListener('mouseup', mu)
  closeBtn.onclick = () => { window.removeEventListener('mousemove', mm); window.removeEventListener('mouseup', mu); ov.remove() }
}

function onReRender() {
  const newCode = textarea.value?.value.trim()
  if (!newCode) return
  emit('code-change', props.diagId, newCode)
}

const rebuilding = ref(false)
const rebuildDialogVisible = ref(false)
const rebuildResult = ref('')

async function onRebuild() {
  rebuilding.value = true
  try {
    const resp = await fetch('/api/mermaid/rebuild', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: stripHtml(props.code) }),
    })
    if (!resp.ok) {
      const text = await resp.text()
      throw new Error(text.slice(0, 200) || `HTTP ${resp.status}`)
    }
    const result = await resp.json()
    rebuildResult.value = result.code
    rebuildDialogVisible.value = true
  } catch (e: any) {
    console.log('[diagram] rebuild failed:', e.message)
  } finally {
    rebuilding.value = false
  }
}

async function onRebuildConfirm(finalCode: string) {
  rebuildDialogVisible.value = false
  if (textarea.value) textarea.value.value = finalCode
  activeTab.value = 'chart'
  await nextTick()
  emit('code-change', props.diagId, finalCode)
  renderMermaid(finalCode)
}

let rsDragging = false, rsStartY = 0, rsStartH = 0

function onResizeMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
  e.preventDefault()
  rsDragging = true; rsStartY = e.clientY; rsStartH = container.value?.offsetHeight || 120
  document.body.style.cursor = 'ns-resize'; document.body.style.userSelect = 'none'
}

function onWindowResizeMouseMove(e: MouseEvent) {
  if (!rsDragging || !container.value) return
  containerHeight = Math.max(120, rsStartH + (e.clientY - rsStartY))
  container.value.style.height = containerHeight + 'px'
  container.value.style.flex = 'none'
}

function onWindowResizeMouseUp() {
  if (!rsDragging) return
  rsDragging = false
  document.body.style.cursor = ''; document.body.style.userSelect = ''
  scheduleNotify()
}

onMounted(() => {
  window.addEventListener('mousemove', onWindowResizeMouseMove)
  window.addEventListener('mouseup', onWindowResizeMouseUp)
})
onUnmounted(() => {
  window.removeEventListener('mousemove', onWindowResizeMouseMove)
  window.removeEventListener('mouseup', onWindowResizeMouseUp)
})

function zoomIn() {
  userZoomed = true
  zs = Math.min(5, zs * 1.25)
  applyScale(); zoomPct.value = Math.round(zs * 100) + '%'; scheduleNotify()
}
function zoomOut() {
  userZoomed = true
  zs = Math.max(0.25, zs * 0.8)
  applyScale(); zoomPct.value = Math.round(zs * 100) + '%'; scheduleNotify()
}
</script>

<template>
  <div class="diagram-container" ref="container" :style="containerHeight ? { height: containerHeight + 'px', flex: 'none' } : {}">
    <div class="diag-toolbar">
      <div class="diag-tabs">
        <button class="diag-tab" :class="{ 'diag-tab-active': activeTab === 'chart' }" @click="activeTab = 'chart'">图表</button>
        <button class="diag-tab" :class="{ 'diag-tab-active': activeTab === 'code' }" @click="activeTab = 'code'">代码</button>
      </div>
      <div class="diag-actions">
        <template v-if="activeTab === 'chart'">
          <button class="diag-zoom-out" title="缩小" @click="zoomOut">−</button>
          <span class="diag-zoom-pct">{{ zoomPct }}</span>
          <button class="diag-zoom-in" title="放大" @click="zoomIn">+</button>
        </template>
        <button class="diag-save-btn" :class="{ 'has-unsaved': unsaved }" :disabled="!unsaved" @click="emit('save-state')" title="保存同消息所有未保存的图状态">
          <span v-if="unsaved" class="save-red-dot"></span>保存
        </button>
        <template v-if="activeTab === 'chart'">
          <button class="diag-download" title="下载" @click="downloadSvg">⬇</button>
          <button class="diag-fullscreen" title="全屏" @click="fullscreen">⛶</button>
        </template>
      </div>
    </div>

    <div v-show="activeTab === 'chart'" class="diag-view" ref="diagView" @wheel.prevent="onWheel">
      <div v-if="loading" class="diagram-loading">Mermaid rendering...</div>
      <div v-else-if="error" class="diag-error">✖ {{ error }}</div>
      <div class="diag-svg-wrap" ref="svgWrap" :style="{ display: (loading || error) ? 'none' : '' }" @mousedown="onSvgMouseDown"></div>
    </div>

    <div v-show="activeTab === 'code'" class="diag-code">
      <div class="diag-code-actions">
        <button class="diag-render-btn" @click="onReRender">重新渲染</button>
        <button class="diag-rebuild-btn" @click="onRebuild" :disabled="rebuilding">
          {{ rebuilding ? '重建中…' : '重建' }}
        </button>
      </div>
      <textarea class="diag-textarea" ref="textarea" :value="code" spellcheck="false"></textarea>
    </div>

    <DiagramRebuildDialog
      :visible="rebuildDialogVisible"
      :original-code="code"
      :rebuilt-code="rebuildResult"
      lang="mermaid"
      @confirm="onRebuildConfirm"
      @cancel="rebuildDialogVisible = false"
    />

    <div class="diag-resize-handle" @mousedown="onResizeMouseDown"></div>
  </div>
</template>

<style>
.diagram-container{border:1px solid var(--border,#e4e4e7);border-radius:var(--radius-lg,12px);overflow:hidden;margin:8px 0;position:relative;min-height:120px;display:flex;flex-direction:column}
.diag-toolbar{display:flex;align-items:center;justify-content:space-between;padding:4px 8px;background:var(--bg-hover,#f0f0f2);border-bottom:1px solid var(--border,#e4e4e7);gap:4px}
.diag-tabs{display:flex;gap:2px}
.diag-tab{background:none;border:none;padding:3px 10px;border-radius:var(--radius-sm,6px);cursor:pointer;font-size:12px;color:var(--text-muted,#888);transition:all .15s}
.diag-tab:hover{color:var(--text-secondary,#666);background:var(--bg-tertiary,#e8e8e8)}
.diag-tab-active{background:var(--accent,#4d6bfe);color:#fff}
.diag-tab-active:hover{background:var(--accent-hover,#3a56d4);color:#fff}
.diag-actions{display:flex;align-items:center;gap:2px}
.diag-actions button{background:none;border:none;color:var(--text-muted,#888);cursor:pointer;padding:2px 6px;border-radius:4px;font-size:13px;line-height:1}
.diag-actions button:hover{background:var(--bg-tertiary,#e8e8e8);color:var(--text-primary,#1a1a1a)}
.diag-save-btn{font-size:12px!important;padding:2px 5px!important;display:inline-flex!important;align-items:center;gap:2px;margin:0 4px}
.diag-save-btn:disabled{opacity:0.35;cursor:not-allowed!important}
.diag-save-btn.has-unsaved{color:var(--accent,#4d6bfe)!important}
.diag-save-btn.has-unsaved:hover{background:var(--accent-light)!important}
.save-red-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:#ef4444}
.diag-zoom-pct{font-size:11px;color:var(--text-muted,#888);min-width:30px;text-align:center}
.diag-view{flex:1;min-height:0}
.diag-svg-wrap{transform-origin:0 0;cursor:grab}
.diag-svg-wrap:active{cursor:grabbing}
.diag-code{padding:0;display:flex;flex-direction:column;max-height:55vh;overflow-y:auto}
.diag-textarea{width:100%;min-height:150px;border:none;padding:12px;font-family:var(--font-mono,monospace);font-size:13px;background:var(--bg-code,#f4f4f5);color:var(--code-text,#1a1a1a);resize:vertical;outline:none;box-sizing:border-box;tab-size:2}
.diag-render-btn{display:block;width:100%;padding:8px;background:var(--accent,#4d6bfe);color:#fff;border:none;cursor:pointer;font-size:13px}
.diag-render-btn:hover{background:var(--accent-hover,#3a56d4)}
.diag-code-actions{display:flex}
.diag-code-actions .diag-render-btn{flex:1}
.diag-rebuild-btn{flex:1;padding:8px 14px;background:none;border:none;border-left:1px solid var(--border,#e4e4e7);cursor:pointer;font-size:13px;color:var(--text-muted,#888)}
.diag-rebuild-btn:hover:not(:disabled){color:var(--accent,#4d6bfe);background:var(--bg-hover,#e8e8e8)}
.diag-rebuild-btn:disabled{opacity:0.4;cursor:not-allowed}
.diagram-loading{padding:32px;color:var(--text-muted,#888);font-size:var(--ui-font-size,14px);text-align:center}
.diag-error{padding:32px;text-align:center;color:#e06c75;font-size:14px}
.diag-resize-handle{position:absolute;bottom:0;left:0;right:0;height:6px;cursor:ns-resize;background:transparent;z-index:1}
.diag-resize-handle::after{content:'';display:block;height:2px;margin:2px 24px;border-radius:1px;background:var(--border,#e4e4e7);transition:background .15s}
.diag-resize-handle:hover::after,.diag-resize-handle:active::after{background:var(--accent,#4d6bfe)}
.diag-fullscreen-overlay{position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99999;display:flex;align-items:center;justify-content:center;padding:40px}
.diag-fullscreen-overlay .diag-fs-close{position:absolute;top:16px;right:16px;background:rgba(255,255,255,.15);border:none;color:#fff;font-size:24px;width:40px;height:40px;border-radius:50%;cursor:pointer;z-index:1}
.diag-fullscreen-overlay .diag-fs-close:hover{background:rgba(255,255,255,.3)}
.diag-fullscreen-overlay .diag-fs-content{max-width:95%;max-height:90vh;overflow:auto;transform-origin:0 0}
.diag-fullscreen-overlay .diag-fs-content svg{max-width:none!important}
</style>