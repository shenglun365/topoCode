<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { normalizeDiagram } from '@web/services/render'
import { diagramStateStore } from '@web/services/diagramStateStore'

const props = defineProps<{
  code: string
  diagId: string
  msgId?: string
  initialState?: DiagramViewState | null
}>()

const emit = defineEmits<{
  'code-change': [newCode: string]
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

const savedState = diagramStateStore.load(props.diagId, contentId.value) || props.initialState
if (savedState) {
  zs = savedState.zs
  dx = savedState.dx
  dy = savedState.dy
  containerHeight = savedState.h
}

function notifyStateChange() {
  diagramStateStore.save(props.diagId, contentId.value, { zs, dx, dy, h: containerHeight })
  unsaved.value = true
  emit('state-change')
  document.dispatchEvent(new CustomEvent('diagram-state-changed'))
}

function onDiagStateChange() {
  unsaved.value = diagramStateStore.isDirty(contentId.value)
}

onMounted(() => document.addEventListener('diagram-state-changed', onDiagStateChange))
onUnmounted(() => document.removeEventListener('diagram-state-changed', onDiagStateChange))

onMounted(() => { unsaved.value = diagramStateStore.isDirty(contentId.value) })

let notifyTimer: any
function scheduleNotify() {
  clearTimeout(notifyTimer)
  notifyTimer = setTimeout(notifyStateChange, 300)
}

function applyScale() {
  if (svgWrap.value) {
    svgWrap.value.style.transform = `translate(${dx}px,${dy}px) scale(${zs})`
    svgWrap.value.style.transformOrigin = '0 0'
  }
}

async function renderPlantUml() {
  loading.value = true
  error.value = ''
  try {
    const n = normalizeDiagram(props.code, 'plantuml')
    const clean = n.code
    if (n.errors.length) console.log('[diagram] normalize:', n.errors)
    const resp = await fetch('/api/plantuml', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: clean,
    })
    if (!resp.ok) throw new Error('PlantUML server returned ' + resp.status)
    const svg = await resp.text()
    if (svgWrap.value) {
      svgWrap.value.innerHTML = svg
      applyScale()
    }
    loading.value = false
  } catch (e: any) {
    error.value = e.message || '渲染失败'
    loading.value = false
  }
}

// —— 懒渲染 ——
onMounted(() => renderPlantUml())

// ── 缩放 / 平移 ──
function onWheel(e: WheelEvent) {
  if (!(e.ctrlKey || e.metaKey) || !diagView.value) return
  e.preventDefault()
  const rect = diagView.value.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top
  const factor = e.deltaY > 0 ? 0.9 : 1.1
  const old = zs
  zs = Math.max(0.25, Math.min(5, zs * factor))
  dx = mx - (mx - dx) * (zs / old)
  dy = my - (my - dy) * (zs / old)
  console.log(`[diag] zoom msgId=${props.msgId||'-'} ${old.toFixed(3)}→${zs.toFixed(3)} dx=${dx.toFixed(0)} dy=${dy.toFixed(0)}`)
  applyScale()
  zoomPct.value = Math.round(zs * 100) + '%'
  scheduleNotify()
}

let dragging = false, startX = 0, startY = 0, sx = 0, sy = 0

function onSvgMouseDown(e: MouseEvent) {
  if (e.button !== 0) return
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
    fsDx = mx - (mx - fsDx) * (fsScale / old)
    fsDy = my - (my - fsDy) * (fsScale / old)
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
  emit('code-change', newCode)
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
  zs = Math.min(5, zs * 1.25)
  applyScale(); zoomPct.value = Math.round(zs * 100) + '%'; scheduleNotify()
}
function zoomOut() {
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
        <button class="diag-save-btn" :class="{ 'has-unsaved': unsaved }" :disabled="!unsaved" @click="emit('save-state')" title="保存图状态到服务器">
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
      <pre><code class="language-plantuml">{{ code }}</code></pre>
      <textarea class="diag-textarea" ref="textarea" :value="code" spellcheck="false"></textarea>
      <button class="diag-render-btn" @click="onReRender">重新渲染</button>
    </div>

    <div class="diag-resize-handle" @mousedown="onResizeMouseDown"></div>
  </div>
</template>
