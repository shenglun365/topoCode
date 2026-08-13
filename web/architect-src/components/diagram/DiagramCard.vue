<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { CodeBracketIcon, ExclamationTriangleIcon, ArrowsPointingOutIcon, XMarkIcon, MagnifyingGlassPlusIcon, MagnifyingGlassMinusIcon } from '@heroicons/vue/24/outline'
import { renderPlantuml, normalizeMermaid, renderMermaid, DIAGRAM_EDGE_LIMITS, countDiagramEdges, isDiagramSizeError } from '@/composables/useDiagramRenderer'
import type { DiagramLang } from '@/composables/useDiagramRenderer'
import { topoScriptSample } from '@/composables/useTopoScript'
import TopoScriptCanvas from './TopoScriptCanvas.vue'

const props = defineProps<{
  title: string
  diagrams: Partial<Record<DiagramLang, string>>
  badges?: { text: string; cls: string }[]
  playKey?: number
  /** 初始语言；缺省按 diagrams 推导(toposcript > mermaid)。 */
  defaultLang?: DiagramLang
}>()

const { t } = useI18n()
const defaultLang = computed<DiagramLang>(() => (
  props.defaultLang
  ?? (props.diagrams.toposcript ? 'toposcript' : 'mermaid')
))

const langs: DiagramLang[] = ['mermaid', 'plantuml', 'toposcript']
const lang = ref<DiagramLang>(defaultLang.value)
const loading = ref(false)
const svg = ref('')
const error = ref('')
const showSource = ref(false)
const playing = ref(false)
/** 关系规模超限(不扩容)：渲染前置提示，引导缩小数据范围。 */
const sizeLimited = ref(false)
const sizeCount = ref(0)

/** 缩放范围(全屏与非全屏统一)：0.2 ~ 50 倍。 */
const MIN_ZOOM = 0.2
const MAX_ZOOM = 50
const ZOOM_STEP = 1.2

/** 缩放并保持锚点不动(供全屏/内联共用)。 */
function zoomAt(scale: Ref<number>, tx: Ref<number>, ty: Ref<number>,
                delta: number, cx: number, cy: number) {
  const old = scale.value
  scale.value = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale.value * delta))
  const k = scale.value / old
  tx.value = cx - (cx - tx.value) * k
  ty.value = cy - (cy - ty.value) * k
}

// ---- 内联(非全屏)滚轮缩放 + 拖拽平移 + 自适应可视区域 ----
const inlineStageRef = ref<HTMLElement | null>(null)
const inlineScale = ref(1)
const inlineTx = ref(0)
const inlineTy = ref(0)
let inlineDragging = false
let inlineStartX = 0
let inlineStartY = 0
let inlineSx = 0
let inlineSy = 0
let inlineObserver: ResizeObserver | null = null

function inlineReset() {
  inlineScale.value = 1
  inlineTx.value = 0
  inlineTy.value = 0
}

/** 非全屏：让图按可视区域的宽与高自适应缩放并居中(页面拉伸时经 ResizeObserver 实时适配)。 */
function fitInline() {
  const stage = inlineStageRef.value
  const svg = stage ? stage.querySelector('.diagram-svg svg') as SVGSVGElement | null : null
  if (!stage || !svg) return
  let w = 0
  let h = 0
  const vb = svg.viewBox?.baseVal
  if (vb && vb.width > 0 && vb.height > 0) {
    w = vb.width
    h = vb.height
  } else {
    w = parseFloat(svg.getAttribute('width') || '')
    h = parseFloat(svg.getAttribute('height') || '')
    if (!(w > 0 && h > 0)) {
      const cur = Math.max(inlineScale.value, 0.001)
      const r = svg.getBoundingClientRect()
      w = r.width / cur
      h = r.height / cur
    }
  }
  if (!(w > 0 && h > 0)) return
  // 固定为自然尺寸，保证 transform 的 scale 精确匹配可视区域。
  svg.style.width = `${w}px`
  svg.style.height = `${h}px`
  svg.style.maxWidth = 'none'
  const cw = stage.clientWidth
  const ch = stage.clientHeight
  if (cw <= 0 || ch <= 0) return
  const s = Math.min(MAX_ZOOM, Math.min(cw / w, ch / h))
  inlineScale.value = s
  inlineTx.value = (cw - w * s) / 2
  inlineTy.value = (ch - h * s) / 2
}

/** 双击复位：回到自适应可视区域。 */
function inlineRefit() {
  inlineReset()
  fitInline()
}

function setupInlineObserver() {
  const stage = inlineStageRef.value
  if (!stage || inlineObserver) return
  inlineObserver = new ResizeObserver(() => { fitInline() })
  inlineObserver.observe(stage)
}

function teardownInlineObserver() {
  if (inlineObserver) {
    inlineObserver.disconnect()
    inlineObserver = null
  }
}

function inlineWheel(e: WheelEvent) {
  if (!inlineStageRef.value) return
  const rect = inlineStageRef.value.getBoundingClientRect()
  zoomAt(inlineScale, inlineTx, inlineTy,
         e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP,
         e.clientX - rect.left, e.clientY - rect.top)
}

function inlineStartDrag(e: MouseEvent) {
  if (e.button !== 0) return
  inlineDragging = true
  inlineStartX = e.clientX
  inlineStartY = e.clientY
  inlineSx = inlineTx.value
  inlineSy = inlineTy.value
}

function inlineDrag(e: MouseEvent) {
  if (!inlineDragging) return
  inlineTx.value = inlineSx + (e.clientX - inlineStartX)
  inlineTy.value = inlineSy + (e.clientY - inlineStartY)
}

function inlineEndDrag() {
  inlineDragging = false
}

const code = computed(() => props.diagrams[lang.value] ?? '')
const currentCode = computed(() => (lang.value === 'toposcript' && !props.diagrams.toposcript ? topoScriptSample() : props.diagrams[lang.value] ?? ''))

/** 渲染序号：只应用最后一次渲染的结果，避免覆盖中的旧渲染回写 svg/error/loading。 */
let renderSeq = 0

watch(
  () => [lang.value, props.diagrams] as const,
  async () => {
    render()
  },
  { immediate: true },
)

/** 内联图渲染完成 → 自适应可视区域宽高，并挂 ResizeObserver(页面拉伸时实时适配)。 */
watch(svg, (v) => {
  if (!v) {
    teardownInlineObserver()
    return
  }
  nextTick(() => {
    fitInline()
    setupInlineObserver()
  })
})

async function render() {
  const seq = ++renderSeq
  error.value = ''
  sizeLimited.value = false
  showSource.value = false
  inlineReset()
  if (lang.value === 'toposcript') {
    playing.value = false
    if (seq === renderSeq) loading.value = false
    return
  }
  if (!code.value) {
    if (seq === renderSeq) loading.value = false
    return
  }
  // 规模预判：关系边数超限时不发起渲染，直接给出友好的缩小范围提示(避免底层报错)。
  const limit = DIAGRAM_EDGE_LIMITS[lang.value]
  if (limit) {
    const ec = countDiagramEdges(lang.value, code.value)
    if (ec >= limit) {
      sizeCount.value = ec
      sizeLimited.value = true
      svg.value = ''
      if (seq === renderSeq) loading.value = false
      return
    }
  }
  loading.value = true
  try {
    const out = lang.value === 'plantuml'
      ? await renderPlantuml(code.value)
      : await renderMermaid(normalizeMermaid(code.value))
    if (seq === renderSeq) svg.value = out
  } catch (e) {
    if (seq === renderSeq) {
      const msg = (e as Error).message || 'render failed'
      if (isDiagramSizeError(lang.value, msg)) {
        sizeCount.value = countDiagramEdges(lang.value, code.value)
        sizeLimited.value = true
        error.value = ''
        svg.value = ''
      } else {
        error.value = msg
      }
    }
  } finally {
    if (seq === renderSeq) loading.value = false
  }
}

watch(
  () => props.playKey,
  (v) => {
    if (v !== undefined && lang.value === 'toposcript') playing.value = true
  },
)

onBeforeUnmount(() => {
  playing.value = false
  teardownInlineObserver()
})

// ---- 全屏放大浏览(参考 KB chat：图主 DOM 浏览器全屏 + 滚轮缩放/拖拽平移) ----
const fullscreenOpen = ref(false)
const fsStageRef = ref<HTMLElement | null>(null)
const fsScale = ref(1)
const fsTx = ref(0)
const fsTy = ref(0)
const fsSvg = ref('')

let fsDragging = false
let fsStartX = 0
let fsStartY = 0
let fsSx = 0
let fsSy = 0

function openFullscreen() {
  if (!svg.value) return
  fsScale.value = 1
  fsTx.value = 0
  fsTy.value = 0
  fsSvg.value = svg.value
  fullscreenOpen.value = true
  nextTick(() => {
    fsFit()
  })
}

function closeFullscreen() {
  fullscreenOpen.value = false
  fsScale.value = 1
  fsTx.value = 0
  fsTy.value = 0
}

/** 初始按视口自适应缩放并居中。 */
function fsFit() {
  const box = fsStageRef.value
  const wrap = fsStageRef.value?.querySelector('.fs-svg')
  if (!box || !wrap) return
  const rect = box.getBoundingClientRect()
  const sw = wrap.getBoundingClientRect().width || 1
  const sh = wrap.getBoundingClientRect().height || 1
  const s = Math.min(rect.width / sw, rect.height / sh)
  fsScale.value = s
  fsTx.value = (rect.width - sw * s) / 2
  fsTy.value = (rect.height - sh * s) / 2
}

function fsZoomAt(delta: number, cx: number, cy: number) {
  zoomAt(fsScale, fsTx, fsTy, delta, cx, cy)
}

function fsZoom(delta: number) {
  const box = fsStageRef.value
  if (!box) return
  const rect = box.getBoundingClientRect()
  fsZoomAt(delta, rect.width / 2, rect.height / 2)
}

function fsWheel(e: WheelEvent) {
  e.preventDefault()
  const box = fsStageRef.value
  if (!box) return
  const rect = box.getBoundingClientRect()
  fsZoomAt(e.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP, e.clientX - rect.left, e.clientY - rect.top)
}

function fsReset() {
  fsScale.value = 1
  fsTx.value = 0
  fsTy.value = 0
}

function fsStartDrag(e: MouseEvent) {
  if (e.button !== 0) return
  fsDragging = true
  fsStartX = e.clientX
  fsStartY = e.clientY
  fsSx = fsTx.value
  fsSy = fsTy.value
}

function fsDrag(e: MouseEvent) {
  if (!fsDragging) return
  fsTx.value = fsSx + (e.clientX - fsStartX)
  fsTy.value = fsSy + (e.clientY - fsStartY)
}

function fsEndDrag() {
  fsDragging = false
}
</script>

<template>
  <!-- eslint-disable vue/no-v-html -->
  <div class="panel overflow-hidden flex flex-col min-h-0">
    <div class="panel-header shrink-0">
      <div class="flex items-center gap-2 min-w-0">
        <span class="truncate font-medium">{{ title }}</span>
        <span
          v-for="b in badges"
          :key="b.text"
          class="chip shrink-0"
          :class="b.cls"
        >{{ b.text }}</span>
      </div>
      <div class="flex items-center gap-1.5 shrink-0">
        <button
          v-for="l in langs"
          :key="l"
          class="px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer"
          :class="lang === l
            ? 'bg-ctp-blue/15 text-ctp-blue ring-1 ring-ctp-blue/30'
            : 'text-ctp-subtext0 hover:bg-ctp-surface0'"
          :title="t(`architecture.${l}Desc`)"
          @click="lang = l"
        >
          {{ l }}
          <span
            v-if="diagrams[l]"
            class="text-[9px] text-ctp-green"
          >●</span>
          <span
            v-else
            class="text-[9px] text-ctp-overlay0"
          >○</span>
        </button>
        <button
          v-if="code"
          class="btn btn-ghost !py-0.5 text-[11px]"
          @click="showSource = !showSource"
        >
          <CodeBracketIcon class="w-3.5 h-3.5" />{{ showSource ? t('architecture.diagram') : 'src' }}
        </button>
        <button
          v-if="svg && lang !== 'toposcript'"
          class="btn btn-ghost !py-0.5 text-[11px]"
          :title="t('architecture.fullscreen')"
          @click="openFullscreen"
        >
          <ArrowsPointingOutIcon class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <div class="p-3 flex-1 min-h-0 flex flex-col min-w-0">
      <div
        v-if="lang === 'toposcript'"
        class="space-y-2"
      >
        <TopoScriptCanvas
          :code="currentCode"
          :playing="playing"
        />
        <div class="flex items-center gap-2">
          <button
            v-if="!playing"
            class="btn btn-primary"
            @click="playing = true"
          >
            {{ t('architecture.toposcriptDesc') }} ▶
          </button>
          <span
            v-else
            class="text-xs text-ctp-teal animate-pulse"
          >{{ t('architecture.rendering') }}</span>
        </div>
      </div>

      <div
        v-else
        class="relative flex-1 min-h-0"
      >
        <div
          v-if="loading"
          class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay1 z-10 bg-ctp-mantle/60 rounded"
        >
          {{ t('architecture.rendering') }}
        </div>
        <div
          v-if="error"
          class="text-xs text-ctp-red mb-2 flex items-center gap-1 min-w-0"
        >
          <ExclamationTriangleIcon class="w-4 h-4 shrink-0" />
          <span
            class="truncate"
            :title="error"
          >{{ t('architecture.renderFailed') }}<template v-if="error"> — {{ error }}</template></span>
        </div>
        <div
          v-else-if="sizeLimited"
          class="text-xs text-ctp-yellow mb-2 flex items-start gap-1.5 min-w-0"
        >
          <ExclamationTriangleIcon class="w-4 h-4 shrink-0 mt-0.5" />
          <span class="min-w-0">
            {{ t('architecture.diagramTooLarge', { count: sizeCount }) }}<br>
            <span class="text-ctp-subtext0">{{ t('architecture.diagramNarrowHint') }}</span>
          </span>
        </div>
        <div
          v-else-if="svg"
          ref="inlineStageRef"
          class="inline-stage h-full w-full"
          @wheel.prevent="inlineWheel"
          @mousedown="inlineStartDrag"
          @mousemove="inlineDrag"
          @mouseup="inlineEndDrag"
          @mouseleave="inlineEndDrag"
          @dblclick="inlineRefit"
        >
          <div
            class="diagram-svg"
            :style="{ transform: `translate(${inlineTx}px, ${inlineTy}px) scale(${inlineScale})` }"
            v-html="svg"
          />
          <span
            v-if="inlineScale !== 1"
            class="absolute right-1.5 bottom-1.5 z-10 chip bg-ctp-surface0/90 text-ctp-overlay1 font-mono text-[10px]"
            :title="t('architecture.zoomResetHint')"
          >{{ Math.round(inlineScale * 100) }}%</span>
        </div>
        <div
          v-else-if="!code"
          class="text-xs text-ctp-overlay0 py-6 text-center"
        >
          {{ t('common.empty') }}
        </div>
      </div>

      <pre
        v-if="showSource && code"
        class="mt-2 text-[11px] leading-relaxed text-ctp-subtext1 bg-ctp-crust border border-ctp-surface0 rounded-md p-3 overflow-auto max-h-72 whitespace-pre"
      >{{ code }}</pre>
    </div>

    <!-- 全屏放大浏览(Teleport 到 body，脱离分栏/transform 祖先，实现浏览器窗口全屏) -->
    <Teleport to="body">
      <div
        v-if="fullscreenOpen"
        class="fs-overlay"
        @wheel.prevent="fsWheel"
        @click.self="closeFullscreen"
      >
        <div class="fs-panel">
          <div class="fs-toolbar">
            <span class="text-xs font-medium text-ctp-text truncate">{{ title }} · {{ lang }}</span>
            <span class="flex-1" />
            <button
              class="btn btn-xs btn-ghost"
              :title="t('architecture.zoomOut')"
              @click="fsZoom(1 / ZOOM_STEP)"
            >
              <MagnifyingGlassMinusIcon class="w-4 h-4" />
            </button>
            <span class="text-[10px] text-ctp-overlay1 font-mono w-12 text-center">{{ Math.round(fsScale * 100) }}%</span>
            <button
              class="btn btn-xs btn-ghost"
              :title="t('architecture.zoomIn')"
              @click="fsZoom(ZOOM_STEP)"
            >
              <MagnifyingGlassPlusIcon class="w-4 h-4" />
            </button>
            <button
              class="btn btn-xs btn-ghost"
              @click="fsReset"
            >100%</button>
            <button
              class="btn btn-xs btn-ghost text-ctp-red"
              :title="t('architecture.close')"
              @click="closeFullscreen"
            >
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div
            ref="fsStageRef"
            class="fs-stage"
            @mousedown="fsStartDrag"
            @mousemove="fsDrag"
            @mouseup="fsEndDrag"
            @mouseleave="fsEndDrag"
          >
            <div
              class="fs-svg"
              :style="{ transform: `translate(${fsTx}px, ${fsTy}px) scale(${fsScale})` }"
              v-html="fsSvg"
            />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
  <!-- eslint-enable vue/no-v-html -->
</template>

<style scoped>
.inline-stage {
  position: relative;
  overflow: hidden;
  cursor: grab;
  min-height: 60px;
}
.inline-stage:active {
  cursor: grabbing;
}
.diagram-svg {
  width: fit-content;
  transform-origin: 0 0;
}
.diagram-svg :deep(svg) {
  max-width: none;
  height: auto;
}
.fs-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  box-sizing: border-box;
  background: rgba(0, 0, 0, 0.72);
}
.fs-panel {
  display: flex;
  flex-direction: column;
  width: 96vw;
  max-width: 96vw;
  height: 92vh;
  max-height: 92vh;
  min-width: 320px;
  background: var(--ctp-base, #1e1e2e);
  border: 1px solid var(--ctp-surface0, #313244);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.5);
}
.fs-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--ctp-surface0, #313244);
}
.fs-stage {
  flex: 1;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  position: relative;
  cursor: grab;
}
.fs-stage:active {
  cursor: grabbing;
}
.fs-svg {
  width: fit-content;
  padding: 24px;
  box-sizing: border-box;
  transform-origin: 0 0;
}
.fs-svg :deep(svg) {
  max-width: none;
}
.diagram-svg :deep(.node rect),
.diagram-svg :deep(.node circle),
.diagram-svg :deep(.node polygon),
.fs-svg :deep(.node rect),
.fs-svg :deep(.node circle),
.fs-svg :deep(.node polygon) {
  fill: #313244;
  stroke: #585b70;
}
.diagram-svg :deep(.edgePath .path),
.diagram-svg :deep(.edgeLabel),
.fs-svg :deep(.edgePath .path),
.fs-svg :deep(.edgeLabel) {
  stroke: #7f849c;
}
.diagram-svg :deep(.nodeLabel),
.diagram-svg :deep(.edgeLabel),
.fs-svg :deep(.nodeLabel),
.fs-svg :deep(.edgeLabel) {
  color: #cdd6f4;
  fill: #cdd6f4;
}
</style>
