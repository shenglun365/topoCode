<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { fitScale } from '@web/services/render'
import { diagramStateStore } from '@web/services/diagramStateStore'
import DiagramRebuildDialog from '@web/components/DiagramRebuildDialog.vue'

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

// ── 状态 ──
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
  console.log(`[PlantUmlViewer] restoreState diagId=${props.diagId} zs=${zs.toFixed(3)} dx=${dx} dy=${dy}`)
}

function notifyStateChange() {
  console.log(`[PlantUmlViewer] save diagId=${props.diagId} zs=${zs.toFixed(3)} dx=${dx.toFixed(0)} dy=${dy.toFixed(0)}`)
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
      const nw = parseFloat(svg.getAttribute('width') || '0')
      const nh = parseFloat(svg.getAttribute('height') || '0')
      if (nw > 0 && nh > 0) {
        const sw = Math.round(nw * zs)
        const sh = Math.round(nh * zs)
        svg.style.width = sw + 'px'
        svg.style.height = sh + 'px'
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
  const sw = svgWrap.value.scrollWidth, sh = svgWrap.value.scrollHeight
  const cw = diagView.value.clientWidth, ch = diagView.value.clientHeight
  const s = fitScale(sw, sh, cw, ch)
  if (s !== null) { zs = s; dx = 0; dy = 0; zoomPct.value = Math.round(s * 100) + '%'; applyScale(); scheduleNotify() }
}

async function renderPlantUml() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/plantuml', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: props.code,
    })
    if (!resp.ok) throw new Error('PlantUML server returned ' + resp.status)
    const svg = await resp.text()
    if (svgWrap.value) {
      svgWrap.value.innerHTML = svg
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
      console.log(`[PlantUmlViewer] afterRender diagId=${props.diagId} zs=${zs.toFixed(3)} dx=${dx} dy=${dy} container=${cw}x${ch}`)
    }
  } catch (e: any) {
    error.value = e.message || '渲染失败'
    loading.value = false
  }
}

// —— 懒渲染 + 响应 code prop 变化 ——
onMounted(() => {
  renderPlantUml()
  if (diagView.value) {
    ro = new ResizeObserver(() => reFit())
    ro.observe(diagView.value)
  }
})
watch(() => props.code, () => { userZoomed = false; activeTab.value = 'chart'; renderPlantUml() })

// ── 缩放 / 平移 ──
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
  console.log(`[diag] zoom msgId=${props.msgId||'-'} ${old.toFixed(3)}→${zs.toFixed(3)} dx=${dx.toFixed(0)} dy=${dy.toFixed(0)}`)
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
    const resp = await fetch('/api/plantuml/rebuild', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: props.code, type: 'auto' }),
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

function onRebuildConfirm(finalCode: string) {
  rebuildDialogVisible.value = false
  if (textarea.value) textarea.value.value = finalCode
  emit('code-change', props.diagId, finalCode)
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
      <div v-if="loading" class="diagram-loading">PlantUML rendering...</div>
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
      lang="plantuml"
      @confirm="onRebuildConfirm"
      @cancel="rebuildDialogVisible = false"
    />

    <div class="diag-resize-handle" @mousedown="onResizeMouseDown"></div>
  </div>
</template>

<style>
.diagram-container{display:flex;flex-direction:column}
.diag-view{flex:1;min-height:0}
.diag-code{padding:0;display:flex;flex-direction:column;max-height:55vh;overflow-y:auto}
.diag-textarea{width:100%;min-height:150px;border:none;padding:12px;font-family:var(--font-mono,monospace);font-size:13px;background:var(--bg-code,#f4f4f5);color:var(--code-text,#1a1a1a);resize:vertical;outline:none;box-sizing:border-box;tab-size:2}
.diag-code-actions{display:flex}
.diag-code-actions .diag-render-btn{flex:1}
.diag-rebuild-btn{flex:1;padding:8px 14px;background:none;border:none;border-left:1px solid var(--border,#e4e4e7);cursor:pointer;font-size:13px;color:var(--text-muted,#888)}
.diag-rebuild-btn:hover:not(:disabled){color:var(--accent,#4d6bfe);background:var(--bg-hover,#e8e8e8)}
.diag-rebuild-btn:disabled{opacity:0.4;cursor:not-allowed}
</style>
