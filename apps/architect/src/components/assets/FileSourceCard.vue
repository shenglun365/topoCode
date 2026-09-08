<template>
  <!-- 文件源码资产卡：语义资产列表打开的独立浮卡(无图谱画布 → 无节点联动)。
       复用图谱资产卡的同批服务与缓存：source-snippet / line-notes(assetId 键,
       与图谱卡共享落库缓存) / desc。 -->
  <div class="fixed inset-0 z-50 flex items-center justify-center">
    <div
      class="absolute inset-0 bg-ctp-crust/60"
      @click="emit('close')"
    />
    <div
      ref="cardEl"
      class="z-10 max-h-[86vh] flex flex-col rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
      :class="[cardPos ? 'absolute' : 'relative w-[min(880px,94vw)]', dragging ? 'cursor-grabbing select-none' : '']"
      :style="{
        ...(cardW ? { width: cardW + 'px' } : {}),
        ...(cardPos ? { left: cardPos.x + 'px', top: cardPos.y + 'px' } : {}),
      }"
    >
      <!-- 宽度拉伸把手(右缘) -->
      <div
        class="absolute top-0 bottom-0 right-0 w-1.5 cursor-ew-resize z-20"
        :class="resizing ? 'bg-ctp-mauve/40' : 'hover:bg-ctp-mauve/25'"
        @pointerdown="beginResize"
        @pointermove="onResize"
        @pointerup="endResize"
      />
      <!-- 头部：文件名 + 资产数 + 关闭(可拖动；双击复位) -->
      <div
        class="flex items-center gap-1.5 px-3 pt-2.5 pb-1.5 border-b border-ctp-surface0 shrink-0 cursor-move"
        @pointerdown="beginDrag"
        @pointermove="onDrag"
        @pointerup="endDrag"
        @dblclick="resetCard"
      >
        <CodeBracketIcon class="w-3.5 h-3.5 text-ctp-blue shrink-0" />
        <span
          class="font-mono text-[11px] font-semibold text-ctp-text truncate"
          :title="file"
        >{{ shortPath(file) }}</span>
        <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0 shrink-0 font-mono">{{ assets.length }}</span>
        <span class="flex-1" />
        <button
          class="btn btn-xs btn-ghost !text-[9px] shrink-0"
          :title="t('assetMgmt.fileCard.fullHint')"
          @click="fullText = !fullText"
        >{{ fullText ? t('assetMgmt.fileCard.segments') : t('assetMgmt.fileCard.full') }}</button>
        <button
          class="text-ctp-overlay0 hover:text-ctp-red p-0.5"
          :title="t('common.close')"
          @click="emit('close')"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>

      <!-- 资产选择 chips -->
      <div class="flex items-center gap-1 flex-wrap px-3 py-1.5 border-b border-ctp-surface0 shrink-0">
        <button
          v-for="a in assets"
          :key="a.id"
          class="chip !text-[9px] shrink-0 max-w-[240px]"
          :class="selId === a.id ? kindChipClass(a.kind) : 'bg-ctp-surface0 text-ctp-subtext0'"
          :title="`${a.id}${a.desc ? '\n' + a.desc.slice(0, 120) : ''}`"
          @click="selId = a.id"
        >{{ a.name }}</button>
      </div>

      <!-- 选中资产主体 -->
      <div class="flex-1 min-h-0 overflow-auto px-3 py-2 space-y-2">
        <div
          v-if="sel"
          class="flex items-center gap-1.5"
        >
          <span
            class="chip !text-[9px] shrink-0"
            :class="kindChipClass(sel.kind)"
          >{{ t(`assetMgmt.kind.${sel.kind}`) }}</span>
          <span
            v-if="sel.level"
            class="chip !text-[8px] shrink-0"
            :class="levelChipClass(sel.level)"
          >{{ t(`assetMgmt.level.${sel.level}`) }}</span>
          <span class="text-[11px] font-semibold text-ctp-text truncate">{{ sel.name }}</span>
          <span class="flex-1" />
          <button
            class="btn btn-xs btn-ghost !text-[9px]"
            :title="t('assetMgmt.fileCard.locate')"
            @click="emit('goto', sel.id)"
          >
            <MapPinIcon class="w-3 h-3" />{{ t('assetMgmt.fileCard.locate') }}
          </button>
        </div>

        <!-- 无资产文件：纯源码浏览提示 -->
        <div
          v-if="!assets.length"
          class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow"
        >{{ t('assetMgmt.fileCard.noAssets') }}</div>
        <!-- 功能摘要(空则按需生成；与列表/图谱共用 desc 缓存) + 伪码 -->
        <template v-if="sel">
          <p
            v-if="sel.desc"
            class="m-0 text-[10px] leading-relaxed whitespace-pre-wrap text-ctp-subtext1"
          >{{ sel.desc }}</p>
          <button
            v-else
            class="btn btn-xs btn-ghost"
            :disabled="descLoading"
            @click="genDesc()"
          >{{ descLoading ? t('common.loading') : t('assetMgmt.genDesc') }}</button>

        </template>

        <!-- 源码段(选中资产=逐锚点；无资产=文件头部窗口)；逐行解读仅资产模式 -->
        <div
          v-for="(seg, i) in segs"
          :key="`${seg.file}:${seg.startLine}`"
          class="rounded-md border border-ctp-surface0 overflow-hidden"
        >
            <div class="flex items-center gap-1.5 px-2 py-1 bg-ctp-surface0/40">
              <span class="text-[10px] font-medium text-ctp-mauve truncate">
                {{ t('assetMgmt.graph.sourceCode') }}
                <span class="text-ctp-overlay1 font-normal font-mono">{{ shortPath(seg.file) }}:L{{ seg.startLine }}<span v-if="seg.symbol"> · {{ seg.symbol }}</span></span>
              </span>
              <span class="flex-1" />
              <button
                class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0"
                :title="t('assetMgmt.graph.copyLoc')"
                :disabled="!seg.snippet"
                @click.stop="copyLoc(i)"
              >
                <CheckIcon v-if="copiedSeg === i" class="w-3 h-3 text-ctp-green" />
                <ClipboardIcon v-else class="w-3 h-3" />
              </button>
              <template v-if="sel">
                <span
                  v-if="notesState[i]?.cached"
                  class="chip !text-[8px] bg-ctp-teal/15 text-ctp-teal shrink-0"
                  :title="t('assetMgmt.graph.lineNotesCachedTip')"
                >{{ t('assetMgmt.graph.lineNotesCached') }}</span>
                <button
                  class="btn btn-xs btn-ghost !text-[9px]"
                  :disabled="notesState[i]?.loading"
                  :title="t('assetMgmt.graph.lineNotesForce')"
                  @click="loadNotes(i, notesState[i]?.done)"
                >
                  <SparklesIcon
                    class="w-3 h-3"
                    :class="notesState[i]?.loading ? 'animate-pulse' : ''"
                  />{{ t('assetMgmt.graph.lineNotes') }}
                </button>
              </template>
            </div>
            <pre
              class="m-0 px-2 py-1.5 leading-[1.5] font-mono overflow-x-auto bg-ctp-crust"
              :style="{ fontSize: codeFontSize + 'px' }"
            ><template
  v-for="l in seg.snippet?.lines ?? []"
  :key="l.line"
  ><div
  class="flex flex-wrap items-baseline gap-1.5"
  :class="segHl(i, l.line) ? 'bg-ctp-mauve/10 border-l-2 border-ctp-mauve' : ''"
><span class="select-none text-ctp-overlay0 shrink-0 w-8 text-right">{{ l.line }}</span> <span
  :class="segHl(i, l.line) ? 'text-ctp-text font-semibold' : 'text-ctp-subtext0'"
>{{ l.code }}</span><span
  v-if="notes[i]?.[l.line]"
  class="ml-auto shrink-0 max-w-[48%] truncate text-right italic"
  :class="segHl(i, l.line) ? 'text-ctp-mauve' : 'text-ctp-overlay1'"
  :title="notes[i]?.[l.line]"
>{{ notes[i]?.[l.line] }}</span></div></template></pre>
          </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CheckIcon, ClipboardIcon, CodeBracketIcon, MapPinIcon, SparklesIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import { semanticAssetService, type AssetCompareResult, type SourceSnippet } from '@/services/semantic-asset-service'
import type { SemanticAsset } from '@/types'
import { kindChipClass, levelChipClass } from '@/services/semantic-kind-style'
import { useArchSettingsStore } from '@/stores/settings-store'

const props = defineProps<{ file: string; assets: SemanticAsset[]; compareData?: AssetCompareResult | null }>()
const emit = defineEmits<{ close: []; goto: [id: string] }>()
const { t } = useI18n()

const selId = ref(props.assets[0]?.id ?? '')
/** 源码视图切换: false=分段(锚点±10 行) / true=全文(整文件, 锚点区间高亮)。 */
const fullText = ref(false)
const sel = computed(() => props.assets.find((a) => a.id === selId.value) ?? null)
const descLoading = ref(false)

// ---- 与语义图谱资产卡对齐的能力(diff 口径 / 代码字号 / 复制位置) ----

/** 对比口径下源码取数参数：资产参与对比 → 目标侧内容 + git diff 逐行注解
 * (与 SemanticGraphView.snippetOptsFor 同一逻辑)。 */
function snippetOptsFor(assetId: string): { ref?: string; diffBase?: string } {
  const c = props.compareData
  if (!c || c.noChanges) return {}
  let side = ''
  for (const a of c.assets.changed) if (a.id === assetId) side = a.side || 'stale'
  for (const a of c.assets.new) if (a.id === assetId) side = 'target'
  for (const a of c.assets.removed) if (a.id === assetId) side = 'base'
  if (!side) return {}
  const ref = c.targetIsWorktree ? '' : c.target
  return { ref: ref || undefined, diffBase: c.base || undefined }
}

/** 代码字号与全局设置联动(比工具栏字号小一号，与图谱卡同规则)。 */
const settings = useArchSettingsStore()
const FONT_STEPS = [13, 15, 18, 22, 26, 32]
const codeFontSize = computed(() => {
  const fs = Number(settings.fontSize) || 16
  const below = FONT_STEPS.filter((x) => x < fs)
  return Math.max(11, below.length ? below[below.length - 1]! : 11)
})

const copiedSeg = ref(-1)

// ---- 浮卡拖动 + 宽度拉伸 ----
const cardEl = ref<HTMLElement | null>(null)
const cardPos = ref<{ x: number; y: number } | null>(null)
const cardW = ref(0)
const dragging = ref(false)
const resizing = ref(false)
let dragOff = { x: 0, y: 0 }
let resizeStart = { x: 0, w: 0 }

function beginDrag(e: PointerEvent) {
  if ((e.target as HTMLElement).closest('button,input')) return
  const el = cardEl.value
  if (!el) return
  dragging.value = true
  const r = el.getBoundingClientRect()
  if (!cardW.value) cardW.value = r.width
  if (!cardPos.value) cardPos.value = { x: r.left, y: r.top }
  dragOff = { x: e.clientX - cardPos.value.x, y: e.clientY - cardPos.value.y }
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}
function onDrag(e: PointerEvent) {
  if (!dragging.value) return
  const el = cardEl.value
  const w = el?.offsetWidth ?? 0
  const x = Math.min(Math.max(e.clientX - dragOff.x, 8), window.innerWidth - w - 8)
  const y = Math.min(Math.max(e.clientY - dragOff.y, 8), window.innerHeight - 48)
  cardPos.value = { x, y }
}
function endDrag() { dragging.value = false }
function beginResize(e: PointerEvent) {
  const el = cardEl.value
  if (!el) return
  resizing.value = true
  resizeStart = { x: e.clientX, w: el.offsetWidth }
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}
function onResize(e: PointerEvent) {
  if (!resizing.value) return
  cardW.value = Math.min(Math.max(resizeStart.w + (e.clientX - resizeStart.x), 520), Math.round(window.innerWidth * 0.96))
}
function endResize() { resizing.value = false }
function resetCard() { cardPos.value = null; cardW.value = 0 }
async function copyLoc(i: number) {
  const seg = segs.value[i]
  const s2 = seg?.snippet
  if (!s2?.lines?.length) return
  const start = s2.lines[0]!.line
  const end = s2.lines[s2.lines.length - 1]!.line
  const loc = `${seg!.file}:L${start}${end !== start ? `-L${end}` : ''}${seg!.symbol ? ' ' + seg!.symbol : ''}`
  try {
    await navigator.clipboard.writeText(loc)
    copiedSeg.value = i
    setTimeout(() => { if (copiedSeg.value === i) copiedSeg.value = -1 }, 1500)
  } catch { /* 剪贴板不可用忽略 */ }
}
/** 源码路径展示：去开头 ./ 后从头省略目录段(保尾部)，完整路径悬停展示。 */
function shortPath(p: string): string {
  let s = p.replace(/^\.\//, '')
  if (s.length <= 44) return s
  const parts = s.split('/')
  while (parts.length > 1 && parts.join('/').length > 44) parts.shift()
  s = '…/' + parts.join('/')
  return s
}

interface Seg { file: string; startLine: number; endLine: number; symbol: string; snippet: SourceSnippet | null; hl: [number, number][] }
const segs = ref<Seg[]>([])
const notes = reactive<Record<number, Record<number, string>>>({})
const notesState = reactive<Record<number, { loading?: boolean; cached?: boolean; degraded?: boolean; error?: string; done?: boolean }>>({})

watch([selId, fullText], () => { void rebuild() }, { immediate: true })

/** 行是否在锚点高亮区间内。 */
function segHl(i: number, line: number): boolean {
  return (segs.value[i]?.hl ?? []).some(([a, b]) => line >= a && line <= b)
}

/** 重建源码段：取选中资产在本文件的锚点，逐段拉符号体源码窗口。 */
async function rebuild() {
  segs.value = []
  for (const k of Object.keys(notes)) delete notes[Number(k)]
  for (const k of Object.keys(notesState)) delete notesState[Number(k)]
  const a = sel.value
  const refs = (a?.astRefs ?? []).filter((r) => r.file === props.file)
  if (fullText.value) {
    // 全文模式：整文件窗口, 选中资产的锚点区间高亮
    segs.value = [{ file: props.file, startLine: 1, endLine: 0, symbol: '', snippet: null,
                    hl: refs.map((r) => [r.startLine, r.endLine] as [number, number]) }]
    const s0 = segs.value[0]!
    s0.snippet = (await semanticAssetService.sourceSnippet(props.file, 1, undefined, 0, 99998, 99999, snippetOptsFor(a.id))) ?? null
    if (s0.snippet?.lines?.length) s0.endLine = s0.snippet.lines[s0.snippet.lines.length - 1]!.line
    return
  }
  if (!a) {
    // 无资产文件：文件头部窗口(纯源码浏览, 无逐行解读)
    segs.value = [{ file: props.file, startLine: 1, endLine: 400, symbol: '', snippet: null, hl: [] }]
    const s0 = segs.value[0]!
    s0.snippet = (await semanticAssetService.sourceSnippet(props.file, 1, undefined, 0, 399, 400)) ?? null
    return
  }
  const opts = snippetOptsFor(a.id)
  segs.value = refs.map((r) => ({
    file: r.file, startLine: r.startLine, endLine: r.endLine, symbol: r.symbol, snippet: null,
    hl: [[r.startLine, r.endLine]] as [number, number][],
  }))
  for (let i = 0; i < segs.value.length; i++) {
    const s = segs.value[i]!
    s.snippet = (await semanticAssetService.sourceSnippet(
      s.file, s.startLine, s.symbol || undefined, 10, 10, 400, opts,
    )) ?? null
  }
}

/** 逐行解读(手动触发；force=重生成)。line-notes 后端按 assetId+file+行区间落库缓存，
 * 与语义图谱资产卡共享同一份缓存。 */
async function loadNotes(i: number, force = false) {
  const s = segs.value[i]
  const a = sel.value
  if (!s?.snippet?.lines?.length || !a || notesState[i]?.loading) return
  const start = s.snippet.lines[0]!.line
  const end = s.snippet.lines[s.snippet.lines.length - 1]!.line
  notesState[i] = { loading: true }
  try {
    const r = await semanticAssetService.lineNotes(a.id, s.file, start, end, { force })
    const norm: Record<number, string> = {}
    for (const [k, v] of Object.entries(r.notes || {})) norm[Number(k)] = String(v)
    notes[i] = norm
    notesState[i] = { done: true, cached: !!r.cached, degraded: !!r.degraded, error: r.error || undefined }
  } catch (err: any) {
    notesState[i] = { done: true, error: err?.message || 'failed' }
  }
}

/** 功能摘要按需生成(与列表/图谱共用 desc 缓存)。 */
async function genDesc() {
  const a = sel.value
  if (!a || descLoading.value || a.desc) return
  descLoading.value = true
  try {
    const r = await semanticAssetService.assetDesc(a.id)
    a.desc = r.desc || ''
  } finally {
    descLoading.value = false
  }
}
</script>
