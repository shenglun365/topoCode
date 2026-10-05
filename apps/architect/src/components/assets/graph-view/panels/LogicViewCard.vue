<template>
  <!-- 逻辑视图资产卡(全局浮窗)：与代码资产卡同款拖拽/四边拉伸/尺寸持久化。
       内容：视图名/概括/成员清单(点击选中画布节点)/AI 详细语义讲解(缓存+指纹失效联动)。 -->
  <div
    ref="cardEl"
    class="card-root fixed flex flex-col max-w-[calc(100vw-1rem)] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
    :class="[
      isCardTop('logic') ? 'z-50' : 'z-40',   // 与代码资产卡点选互顶
      !cardPos ? 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2' : '',
      dragging ? 'cursor-grabbing' : '',
      resizing ? 'select-none' : '',
    ]"
    @mousedown.capture="bringCardToFront('logic')"
    :style="{
      width: cardSize.w + 'px',
      ...(cardSize.h ? { height: cardSize.h + 'px' } : {}),
      ...(cardPos ? { left: cardPos.x + 'px', top: cardPos.y + 'px' } : {}),
    }"
  >
    <header
      class="flex items-center gap-2 px-3 py-2 border-b border-ctp-surface1 shrink-0 cursor-grab"
      @mousedown="beginCardDrag"
      @dblclick.stop
    >
      <ShareIcon class="w-4 h-4 text-ctp-mauve shrink-0" />
      <span class="text-xs font-semibold text-ctp-text truncate">{{ view?.name || viewId }}</span>
      <span v-if="view?.source === 'manual'" class="text-[10px] px-1.5 py-0.5 rounded bg-ctp-mauve/15 text-ctp-mauve shrink-0">{{ t('assetMgmt.logicViews.manualTag') }}</span>
      <span v-if="explained && cached" class="text-[10px] text-ctp-overlay0 shrink-0">{{ t('assetMgmt.logicViews.explainCached') }}</span>
      <button class="ml-auto text-ctp-overlay0 hover:text-ctp-text shrink-0" :title="t('common.close')" @click="emit('close')">
        <XMarkIcon class="w-4 h-4" />
      </button>
    </header>

    <div ref="selHost" class="relative overflow-y-auto px-3 py-2 space-y-3 text-xs">
      <!-- 选区浮条(引用到草稿/复制) -->
      <div
        v-if="selBar"
        data-sel-actions
        class="absolute z-30 flex items-center gap-0.5 rounded-md border border-ctp-surface1 bg-ctp-mantle px-1 py-0.5 shadow-lg"
        :style="{ left: selBarPos.x + 'px', top: selBarPos.y + 'px' }"
      >
        <button
          class="rounded px-1.5 py-0.5 text-[10px] text-ctp-blue hover:bg-ctp-surface0"
          @click.stop="selRef"
        >{{ t('assetMgmt.graph.selActions.quote') }}</button>
        <button
          class="rounded px-1.5 py-0.5 text-[10px] text-ctp-subtext1 hover:bg-ctp-surface0"
          @click.stop="selCopy"
        >{{ selCopied ? t('assetMgmt.graph.selActions.copied') : t('assetMgmt.graph.selActions.copy') }}</button>
      </div>
      <!-- 概括 -->
      <p v-if="view?.summary" class="text-ctp-subtext1 leading-relaxed">{{ view.summary }}</p>

      <!-- 成员清单(点击选中画布节点) -->
      <section>
        <h4 class="text-[11px] font-semibold text-ctp-overlay1 mb-1">{{ t('assetMgmt.logicViews.membersTitle') }} · {{ members.length }}</h4>
        <div class="flex flex-wrap gap-1">
          <button
            v-for="m in members" :key="m.id"
            class="px-1.5 py-0.5 rounded border text-[11px] transition-colors"
            :class="m.isCore
              ? 'border-ctp-mauve/50 text-ctp-mauve bg-ctp-mauve/10 hover:bg-ctp-mauve/20'
              : 'border-ctp-surface1 text-ctp-subtext1 hover:text-ctp-text hover:border-ctp-overlay0'"
            :title="m.isCore ? t('assetMgmt.logicViews.coreTag') : m.id"
            @click="selectNode(m.id)"
          >{{ m.name }}</button>
        </div>
      </section>

      <!-- AI 详细语义讲解 -->
      <section>
        <div class="flex items-center gap-2 mb-1">
          <h4 class="text-[11px] font-semibold text-ctp-overlay1">{{ t('assetMgmt.logicViews.explainTitle') }}</h4>
          <button
            v-if="!explainLoading"
            class="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border transition-colors"
            :class="explained
              ? 'border-ctp-surface1 text-ctp-overlay1 hover:text-ctp-text'
              : 'border-ctp-blue/50 text-ctp-blue bg-ctp-blue/10 hover:bg-ctp-blue/20'"
            @click="explain(explained)"
          >
            <SparklesIcon class="w-3 h-3" />
            {{ explained ? t('assetMgmt.logicViews.regenerate') : t('assetMgmt.logicViews.aiExplain') }}
          </button>
          <span v-else class="flex items-center gap-1 text-[11px] text-ctp-overlay0">
            <ArrowPathIcon class="w-3 h-3 animate-spin" />{{ t('assetMgmt.logicViews.explainLoading') }}
          </span>
        </div>
        <p v-if="explainError" class="text-ctp-red text-[11px]">{{ explainError }}</p>
        <div v-if="explained" class="rounded border border-ctp-surface1 bg-ctp-base/60 px-2.5 py-2 space-y-1.5 leading-relaxed text-ctp-subtext1">
          <template v-for="(para, pi) in explainParas" :key="pi">
            <p v-if="para.heading" class="font-semibold text-ctp-text">{{ para.heading }}</p>
            <p v-for="(line, li) in para.lines" :key="li" class="break-words">
              <template v-for="(seg, si) in line" :key="si">
                <button
                  v-if="seg.ref" class="text-ctp-blue hover:underline"
                  :title="seg.refId"
                  @click="selectNode(seg.refId!)"
                >{{ seg.text }}</button>
                <span v-else>{{ seg.text }}</span>
              </template>
            </p>
          </template>
        </div>
        <p v-else-if="!explainLoading" class="text-ctp-overlay0 text-[11px]">{{ t('assetMgmt.logicViews.explainHint') }}</p>
      </section>
    </div>

    <!-- 四边独立拉伸把手(与代码资产卡同款) -->
    <div class="card-edge card-edge-n" @mousedown="startResize($event, 'n')" @dblclick.stop />
    <div class="card-edge card-edge-s" @mousedown="startResize($event, 's')" @dblclick.stop />
    <div class="card-edge card-edge-w" @mousedown="startResize($event, 'w')" @dblclick.stop />
    <div class="card-edge card-edge-e" @mousedown="startResize($event, 'e')" @dblclick.stop />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, ShareIcon, SparklesIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { semanticAssetService } from '@/services/semantic-asset-service'
import { useSgvWs } from '../key'
import { useSelectionActions } from '../useSelectionActions'
import { currentProjectParams } from '@/services/project-service'
import { bringCardToFront, isCardTop } from '../cardZ'

const props = defineProps<{ viewId: string }>()
// ---- 内容选中 → 引用到草稿 / 复制 ----
const firstCoreId = computed(() => {
  try { return (JSON.parse(view.value?.coreIds || '[]') as string[])[0] || undefined }
  catch { return undefined }
})
const selHost = ref<HTMLElement | null>(null)
const {
  barVisible: selBar, barPos: selBarPos, copied: selCopied, copySel: selCopy, refSel: selRef,
} = useSelectionActions(selHost, () => ({
  projectId: currentProjectParams().project || '',
  viewId: view.value?.id || props.viewId,
  viewName: view.value?.name || '',
  coreAssetId: firstCoreId.value || undefined,
  assetName: view.value?.name || '',
}))
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const ws = useSgvWs()

const view = ref<Awaited<ReturnType<typeof semanticAssetService.listLogicViews>>[number] | null>(null)
const explainLoading = ref(false)
const explained = ref(false)
const cached = ref(false)
const explainError = ref('')
const detailText = ref('')

// ---- 浮窗拖拽 + 四边独立拉伸(与代码资产卡同款机制，独立状态/持久化键) ----
type ResizeEdge = 'n' | 's' | 'w' | 'e'
const SIZE_KEY = 'arch.graphLogicCard.size'
const cardEl = ref<HTMLElement | null>(null)
const cardPos = ref<{ x: number; y: number } | null>(null)
const dragging = ref(false)
const resizing = ref(false)
let dragStartX = 0
let dragStartY = 0
let dragStartPos = { x: 0, y: 0 }
let resizeEdge: ResizeEdge = 's'
let resizeStart = { x: 0, y: 0, w: 560, h: 520, px: 0, py: 0 }

function loadSize(): { w: number; h: number | null } {
  try {
    const raw = JSON.parse(localStorage.getItem(SIZE_KEY) || '')
    if (raw && Number(raw.w) >= 360 && Number(raw.h) >= 240) return { w: Number(raw.w), h: Number(raw.h) }
  } catch { /* 默认尺寸 */ }
  return { w: 560, h: 520 }
}
function saveSize() {
  try { localStorage.setItem(SIZE_KEY, JSON.stringify(cardSize.value)) } catch { /* ignore */ }
}
const cardSize = ref<{ w: number; h: number | null }>(loadSize())

function beginCardDrag(e: MouseEvent) {
  if (e.button !== 0) return
  const el = cardEl.value
  if (!el) return
  if ((e.target as HTMLElement).closest('button, a, input, select')) return
  dragging.value = true
  if (!cardPos.value) {
    const r = el.getBoundingClientRect()
    dragStartPos = { x: r.left, y: r.top }
    cardPos.value = { ...dragStartPos }
  } else {
    dragStartPos = { x: el.offsetLeft, y: el.offsetTop }
  }
  dragStartX = e.clientX
  dragStartY = e.clientY
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp, { once: true })
  e.preventDefault()
}
function startResize(e: MouseEvent, edge: ResizeEdge) {
  if (e.button !== 0) return
  e.preventDefault()
  e.stopPropagation()
  const el = cardEl.value
  if (!el) return
  let px = el.offsetLeft
  let py = el.offsetTop
  if (!cardPos.value) {
    const r = el.getBoundingClientRect()
    px = r.left
    py = r.top
    cardPos.value = { x: px, y: py }
  }
  resizeEdge = edge
  resizing.value = true
  resizeStart = { x: e.clientX, y: e.clientY, w: cardSize.value.w,
                  h: cardSize.value.h ?? el.offsetHeight, px, py }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp, { once: true })
}
function onMove(e: MouseEvent) {
  if (resizing.value) {
    const maxW = Math.min(1100, window.innerWidth - 16)
    const maxH = Math.floor(window.innerHeight * 0.94)
    const dx = e.clientX - resizeStart.x
    const dy = e.clientY - resizeStart.y
    let w = resizeStart.w
    let h = resizeStart.h
    let px = resizeStart.px
    let py = resizeStart.py
    if (resizeEdge === 'e') {
      w = Math.min(maxW, Math.max(360, w + dx))
    } else if (resizeEdge === 'w') {
      w = Math.min(maxW, Math.max(360, w - dx))
      px += resizeStart.w - w
    }
    if (resizeEdge === 's') {
      h = Math.min(maxH, Math.max(240, h + dy))
    } else if (resizeEdge === 'n') {
      h = Math.min(maxH, Math.max(240, h - dy))
      py += resizeStart.h - h
    }
    cardSize.value = { w, h }
    cardPos.value = { x: px, y: py }
    return
  }
  if (!dragging.value) return
  cardPos.value = {
    x: Math.min(window.innerWidth - 80, Math.max(-(cardSize.value.w - 80), dragStartPos.x + (e.clientX - dragStartX))),
    y: Math.min(window.innerHeight - 48, Math.max(0, dragStartPos.y + (e.clientY - dragStartY))),
  }
}
function onUp() {
  dragging.value = false
  if (resizing.value) saveSize()
  resizing.value = false
  window.removeEventListener('mousemove', onMove)
}

/** 成员清单：名称取图谱节点(kind='logic' 图谱=成员资产)；核心成员标记。 */
const members = computed<{ id: string; name: string; isCore: boolean }[]>(() => {
  if (!view.value) return []
  let mids: string[] = []
  let cores: string[] = []
  try {
    mids = JSON.parse(view.value.memberIds || '[]')
    cores = JSON.parse(view.value.coreIds || '[]')
  } catch { return [] }
  const nameById = new Map<string, string>(
    (ws.graph?.value?.nodes ?? []).map((n: { id: string; name?: string }) => [n.id, n.name ?? n.id]))
  return mids.map((id) => ({
    id,
    name: nameById.get(id) ?? id.slice(0, 12),
    isCore: cores.includes(id),
  }))
})

/** 讲解文本分段：段落(标题行/正文行) + 「资产名 (sa-xxx)」引用解析为可点击片段。 */
const REF_RE = /([^\s，。；、（）()]{1,40})\s*[（(]\s*(sa-[A-Za-z0-9_-]+)\s*[）)]/g
const explainParas = computed<{ heading?: string; lines: { text: string; ref?: boolean; refId?: string }[][] }[]>(() => {
  const raw = detailText.value
  if (!raw) return []
  const out: { heading?: string; lines: { text: string; ref?: boolean; refId?: string }[][] }[] = []
  let cur: { heading?: string; lines: { text: string; ref?: boolean; refId?: string }[][] } = { lines: [] }
  for (const ln of raw.split(/\n+/)) {
    const line = ln.trim()
    if (!line) continue
    if (/^#{1,4}\s+/.test(line)) {
      if (cur.heading || cur.lines.length) out.push(cur)
      cur = { heading: line.replace(/^#{1,4}\s+/, ''), lines: [] }
      continue
    }
    const segs: { text: string; ref?: boolean; refId?: string }[] = []
    let last = 0
    for (const m of line.matchAll(REF_RE)) {
      const idx = m.index ?? 0
      if (idx > last) segs.push({ text: line.slice(last, idx) })
      segs.push({ text: `${m[1]} (${m[2]})`, ref: true, refId: m[2] })
      last = idx + m[0].length
    }
    if (last < line.length) segs.push({ text: line.slice(last) })
    cur.lines.push(segs.length ? segs : [{ text: line }])
  }
  if (cur.heading || cur.lines.length) out.push(cur)
  return out
})

/** 成员引用/清单点击 → 选中画布节点(资产卡/代码联动) + 资产卡置顶(否则被本卡遮住)。 */
function selectNode(id: string) {
  if (!id) return
  ws.selId.value = id
  bringCardToFront('asset')
}

/** AI 详细语义讲解：force=重新生成。缓存(含上次会话落库的)指纹一致由后端秒回。 */
async function explain(force = false) {
  if (explainLoading.value) return
  explainLoading.value = true
  explainError.value = ''
  try {
    const r = await semanticAssetService.explainLogicView(props.viewId, force)
    if (r?.detail) {
      detailText.value = r.detail
      explained.value = true
      cached.value = !!r.cached
      if (view.value) view.value.detail = r.detail
    } else {
      explainError.value = t('assetMgmt.logicViews.explainFailed')
    }
  } catch (e: unknown) {
    explainError.value = (e as { message?: string })?.message || t('assetMgmt.logicViews.explainFailed')
  } finally {
    explainLoading.value = false
  }
}

onMounted(async () => {
  try {
    const views = await semanticAssetService.listLogicViews()
    view.value = views.find((v) => v.id === props.viewId) ?? null
    // 后端已有缓存(指纹失效判定由 explain 兜底) → 直接展示旧讲解
    if (view.value?.detail) {
      detailText.value = view.value.detail
      explained.value = true
      cached.value = true
    }
  } catch { /* 列表失败保留空卡 */ }
})
</script>

<style scoped>
/* 四边独立拉伸把手(与代码资产卡同款)：透明热区，hover 显提示条 */
.card-edge {
  position: absolute;
  z-index: 10;
  transition: background-color 0.15s;
}
.card-edge:hover {
  background-color: rgba(136, 137, 163, 0.35);
}
.card-edge-n,
.card-edge-s {
  left: 0;
  right: 0;
  height: 6px;
  cursor: ns-resize;
}
.card-edge-n { top: 0; }
.card-edge-s { bottom: 0; }
.card-edge-e,
.card-edge-w {
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
}
.card-edge-w { left: 0; }
.card-edge-e { right: 0; }
</style>
