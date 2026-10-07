<script setup lang="ts">
/**
 * 文件资产卡(组件图谱·文件节点)：全文件源码+行级 diff 着色+行级 AI 解读+
 * 文件关联(imports 邻接+文件内符号, 屏蔽数据资产关联)+变更资产清单。
 * 形态复用 FileSourceCard(浮卡/拖动/宽度把手); 服务: source-snippet(diffBase)
 * + file-line-notes(file 维度缓存)。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { DocumentTextIcon, XMarkIcon, SparklesIcon, ArrowPathIcon, ClipboardIcon, LinkIcon } from '@heroicons/vue/24/outline'
import type { FileGraphNode, FileGraphChangedAsset } from '@/services/semantic-asset-service'
import { semanticAssetService, type SourceSnippet } from '@/services/semantic-asset-service'
import { copyText } from '@/utils/clipboard'
import { requestDraftRef } from '@/pages/asset-workspace/draft-ref-bus'

const props = defineProps<{
  node: FileGraphNode
  /** 对比口径(base/target 复用对比选择器)。 */
  compareBase: string
  compareTarget: string
  importsIn: string[]
  importsOut: string[]
  changedAssets: FileGraphChangedAsset[]
}>()
const emit = defineEmits<{
  close: []
  locateFile: [path: string]
}>()

const { t } = useI18n()
const dragPos = ref<{ x: number; y: number } | null>(null)
const dragging = ref(false)
let dragOff = { dx: 0, dy: 0 }
const cardW = ref(0)
const resizing = ref(false)
let resizeStart = { x: 0, w: 0 }

function beginDrag(e: PointerEvent) {
  dragging.value = true
  const el = (e.currentTarget as HTMLElement).closest('.file-card') as HTMLElement
  const r = el.getBoundingClientRect()
  dragOff = { dx: e.clientX - r.left, dy: e.clientY - r.top }
  dragPos.value = { x: r.left, y: r.top }
}
function onDrag(e: PointerEvent) {
  if (!dragging.value) return
  dragPos.value = { x: e.clientX - dragOff.dx, y: e.clientY - dragOff.dy }
}
function endDrag() { dragging.value = false }
function beginResize(e: PointerEvent) {
  resizing.value = true
  resizeStart = { x: e.clientX, w: cardW.value || (cardEl.value?.getBoundingClientRect().width || 680) }
}
function onResize(e: PointerEvent) {
  if (!resizing.value) return
  cardW.value = Math.max(420, resizeStart.w + (e.clientX - resizeStart.x))
}
function endResize() { resizing.value = false }

const cardEl = ref<HTMLElement | null>(null)

// ---- 全文件源码(+对比口径 diff 注解) ----
const snippet = ref<SourceSnippet | null>(null)
const loading = ref(false)
const loadError = ref('')

onMounted(async () => {
  loading.value = true
  try {
    const opts = props.compareBase
      ? { ref: props.compareTarget !== 'worktree' ? props.compareTarget : undefined, diffBase: props.compareBase }
      : {}
    snippet.value = (await semanticAssetService.sourceSnippet(
      props.node.path, 1, undefined, 0, 0, 4000, opts)) ?? null
    if (!snippet.value) loadError.value = t('compGraph.fileUnreadable')
  } catch (e: any) {
    loadError.value = e?.message || 'failed'
  } finally {
    loading.value = false
  }
})

const lines = computed(() => snippet.value?.lines ?? [])
/** 源码窗口上限 4000 行——达到即视为截断。 */
const srcTruncated = computed(() => lines.value.length >= 4000)
const addedCount = computed(() => lines.value.filter((l) => l.kind === 'add').length)
const deletedCount = computed(() => lines.value.filter((l) => l.kind === 'del').length)

// ---- 行级 AI 解读(file 维度缓存) ----
const notes = ref<Record<number, string>>({})
const notesLoading = ref(false)
const notesCached = ref(false)
const notesError = ref('')
const notesElapsed = ref(0)
let notesTimer: ReturnType<typeof setInterval> | null = null

async function loadNotes(force = false) {
  if (notesLoading.value || !lines.value.length) return
  notesLoading.value = true
  notesError.value = ''
  notesElapsed.value = 0
  if (notesTimer) clearInterval(notesTimer)
  notesTimer = setInterval(() => { notesElapsed.value += 1 }, 1000)
  try {
    const first = lines.value[0].line
    const last = lines.value[lines.value.length - 1].line
    const r = await semanticAssetService.fileLineNotes(props.node.path, first, last, force)
    const norm: Record<number, string> = {}
    for (const [k, v] of Object.entries(r?.notes || {})) norm[Number(k)] = String(v)
    notes.value = norm
    notesCached.value = !!r?.cached
    if (r?.error) notesError.value = r.error
  } catch (e: any) {
    notesError.value = e?.message || 'failed'
  } finally {
    if (notesTimer) { clearInterval(notesTimer); notesTimer = null }
    notesLoading.value = false
  }
}

const noteOf = (line: number) => notes.value[line] || ''

function lineCls(l: { kind?: string }): string {
  if (l.kind === 'del') return 'bg-ctp-red/10 text-ctp-red/80'
  if (l.kind === 'add') return 'bg-ctp-green/10 text-ctp-green/90'
  return 'text-ctp-subtext1'
}

async function quoteDraft() {
  const assoc = [...props.importsIn.map((f) => `← ${f}`), ...props.importsOut.map((f) => `→ ${f}`)]
  const lines = [
    `> **引用** · 文件 \`${props.node.path}\``,
    `> 来源：组件图谱 · 组件 ${props.node.compName || props.node.compId} · ${props.node.change || '无变更'}${addedCount.value ? ` · +${addedCount.value}/-${deletedCount.value} 行` : ''}`,
    assoc.length ? `> 关联：${assoc.slice(0, 6).join(' · ')}` : '',
  ].filter(Boolean)
  requestDraftRef({
    source: { fileId: props.node.path, fileLabel: props.node.name },
    text: lines.join('\n'),
  })
}

const copied = ref(false)
async function copyLoc() {
  if (await copyText(props.node.path)) {
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center">
    <div class="absolute inset-0 bg-ctp-crust/60" @click="emit('close')" />
    <div
      ref="cardEl"
      class="file-card z-10 max-h-[86vh] flex flex-col rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
      :class="[dragPos ? 'absolute' : 'relative w-[min(760px,94vw)]', dragging ? 'cursor-grabbing select-none' : '']"
      :style="{
        ...(cardW ? { width: `${cardW}px` } : {}),
        ...(dragPos ? { left: `${dragPos.x}px`, top: `${dragPos.y}px` } : {}),
      }"
    >
      <div class="absolute top-0 bottom-0 right-0 w-1.5 cursor-ew-resize z-20" :class="resizing ? 'bg-ctp-mauve/40' : 'hover:bg-ctp-mauve/25'"
        @pointerdown="beginResize" @pointermove="onResize" @pointerup="endResize" />
      <div class="flex items-center gap-1.5 px-3 pt-2.5 pb-1.5 border-b border-ctp-surface0 shrink-0 cursor-move"
        @pointerdown="beginDrag" @pointermove="onDrag" @pointerup="endDrag">
        <DocumentTextIcon class="w-4 h-4 shrink-0"
          :class="node.change === 'added' ? 'text-ctp-green' : node.change === 'deleted' ? 'text-ctp-red' : 'text-ctp-blue'" />
        <span class="font-mono text-xs text-ctp-text truncate" :title="node.path">{{ node.path }}</span>
        <span v-if="node.change" class="chip !text-[9px] shrink-0"
          :class="node.change === 'added' ? 'bg-ctp-green/15 text-ctp-green' : node.change === 'deleted' ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-blue/15 text-ctp-blue'">
          {{ node.change }}
        </span>
        <span v-if="addedCount || deletedCount" class="text-[9px] font-mono shrink-0">
          <span class="text-ctp-green">+{{ addedCount }}</span> <span class="text-ctp-red">-{{ deletedCount }}</span>
        </span>
        <span class="flex-1" />
        <button class="p-0.5 rounded hover:bg-ctp-surface0 text-ctp-overlay1 hover:text-ctp-text" @click="emit('close')">
          <XMarkIcon class="w-4 h-4" />
        </button>
      </div>

      <div class="flex-1 min-h-0 overflow-y-auto p-3 space-y-3 text-xs">
        <!-- 变更资产(strong/weak) -->
        <div v-if="changedAssets.length">
          <p class="text-[10px] text-ctp-overlay1 mb-1">{{ t('compGraph.changedAssets', { n: changedAssets.length }) }}</p>
          <div class="flex flex-wrap gap-1">
            <span v-for="a in changedAssets" :key="a.id" class="chip !text-[9px]"
              :class="a.strong ? 'bg-ctp-peach/15 text-ctp-peach' : 'bg-ctp-surface0 text-ctp-subtext0'"
              :title="a.strong ? t('compGraph.strongHint') : t('compGraph.weakHint')">
              {{ a.name }}<span v-if="!a.strong"> ~</span>
            </span>
          </div>
        </div>

        <!-- 文件关联(imports 邻接; 屏蔽数据资产关联) -->
        <div v-if="importsIn.length || importsOut.length">
          <p class="text-[10px] text-ctp-overlay1 mb-1 flex items-center gap-1">
            <LinkIcon class="w-3 h-3" />{{ t('compGraph.fileAssoc') }}
          </p>
          <div class="flex flex-wrap gap-1">
            <button v-for="f in importsIn" :key="`in-${f}`" class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-text"
              :title="t('compGraph.importIn')" @click="emit('locateFile', f)">
              ← {{ f.split('/').pop() }}
            </button>
            <button v-for="f in importsOut" :key="`out-${f}`" class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-text"
              :title="t('compGraph.importOut')" @click="emit('locateFile', f)">
              → {{ f.split('/').pop() }}
            </button>
          </div>
        </div>

        <!-- 全文件源码 + 行级 diff + 行级 AI 解读(工具条吸顶: 大文件滚动时按钮常驻) -->
        <div class="border-t border-ctp-surface0 pt-2">
          <div class="sticky top-0 z-10 -mt-3 -mx-3 px-3 pt-3 pb-1.5 mb-1.5 flex items-center gap-1.5 bg-ctp-mantle border-b border-ctp-surface0">
            <SparklesIcon class="w-3.5 h-3.5 text-ctp-mauve" />
            <span class="text-[10px] text-ctp-overlay1">{{ t('compGraph.lineNotes') }}</span>
            <span v-if="notesCached && Object.keys(notes).length" class="text-[9px] text-ctp-overlay0">{{ t('compGraph.cached') }}</span>
            <span class="flex-1" />
            <button v-if="!notesLoading && !Object.keys(notes).length && !loadError"
              class="btn !py-1 !px-2.5 !text-[10px]" @click="loadNotes(false)">
              <SparklesIcon class="w-3.5 h-3.5" />{{ t('compGraph.genNote') }}
            </button>
            <button class="p-0.5 rounded hover:bg-ctp-surface0 text-ctp-overlay1 hover:text-ctp-mauve"
              :title="t('compGraph.regenerate')" :disabled="notesLoading" @click="loadNotes(true)">
              <ArrowPathIcon class="w-3.5 h-3.5" :class="notesLoading ? 'animate-spin' : ''" />
            </button>
          </div>
          <p v-if="notesError" class="text-[11px] text-ctp-peach mb-1">{{ notesError }}</p>
          <div v-if="loading" class="text-[11px] text-ctp-overlay0 animate-pulse py-4 text-center">
            {{ t('app.loading') }} {{ notesElapsed }}s
          </div>
          <p v-else-if="srcTruncated" class="text-[10px] text-ctp-peach mb-1">{{ t('compGraph.srcTruncated') }}</p>
          <div v-else-if="loadError" class="text-[11px] text-ctp-peach py-2">{{ loadError }}</div>
          <div v-else class="rounded border border-ctp-surface0 overflow-x-auto font-mono text-[11px] leading-5">
            <div v-for="l in lines" :key="l.line" class="flex items-start group hover:bg-ctp-surface0/60"
              :class="lineCls(l)">
              <span class="w-10 shrink-0 text-right pr-2 select-none text-ctp-overlay0">{{ l.line }}</span>
              <span class="flex-1 whitespace-pre">{{ l.code }}</span>
              <span v-if="noteOf(l.line) || notesLoading"
                class="shrink-0 max-w-[45%] pl-2 text-[10px] not-italic text-ctp-mauve/90 border-l border-ctp-surface1 ml-2">
                {{ notesLoading ? '…' : noteOf(l.line) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div class="shrink-0 flex items-center gap-2 px-3 py-1.5 border-t border-ctp-surface0">
        <button class="text-[10px] text-ctp-mauve hover:underline flex items-center gap-1" @click="quoteDraft">
          <ClipboardIcon class="w-3 h-3" />{{ t('compGraph.quoteDraft') }}
        </button>
        <button class="text-[10px] text-ctp-overlay1 hover:text-ctp-text hover:underline" @click="copyLoc">
          {{ copied ? t('compGraph.copied') : t('compGraph.copyLoc') }}
        </button>
      </div>
    </div>
  </div>
</template>
