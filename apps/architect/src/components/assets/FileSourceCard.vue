<template>
  <!-- 文件源码资产卡：语义资产列表打开的独立浮卡(无图谱画布 → 无节点联动)。
       复用图谱资产卡的同批服务与缓存：source-snippet / line-notes(assetId 键,
       与图谱卡共享落库缓存) / desc / PseudoExplainer 伪码组件。 -->
  <div class="fixed inset-0 z-50 flex items-center justify-center">
    <div
      class="absolute inset-0 bg-ctp-crust/60"
      @click="emit('close')"
    />
    <div class="relative z-10 w-[min(880px,94vw)] max-h-[86vh] flex flex-col rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden">
      <!-- 头部：文件名 + 资产数 + 关闭 -->
      <div class="flex items-center gap-1.5 px-3 pt-2.5 pb-1.5 border-b border-ctp-surface0 shrink-0">
        <CodeBracketIcon class="w-3.5 h-3.5 text-ctp-blue shrink-0" />
        <span
          class="font-mono text-[11px] font-semibold text-ctp-text truncate"
          :title="file"
        >{{ shortPath(file) }}</span>
        <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0 shrink-0 font-mono">{{ assets.length }}</span>
        <span class="flex-1" />
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

        <!-- 功能摘要(空则按需生成；与列表/图谱共用 desc 缓存) -->
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

          <!-- 伪码说明(与图谱资产卡同一组件/缓存) -->
          <PseudoExplainer
            :key="sel.id"
            :asset-id="sel.id"
            :initial="sel.pseudo || ''"
          />

          <!-- 源码段(逐锚点) + 逐行解读(line-notes 与图谱卡共享 assetId 键缓存) -->
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
            </div>
            <pre class="m-0 px-2 py-1.5 text-[10px] leading-[1.5] font-mono overflow-x-auto bg-ctp-crust"><span
  v-for="l in seg.snippet?.lines ?? []"
  :key="l.line"
  class="block"
  :class="notes[i]?.[l.line] ? 'text-ctp-text' : 'text-ctp-subtext0'"
><span class="inline-block w-8 select-none text-right mr-2 text-ctp-overlay0">{{ l.line }}</span>{{ l.code }}</span></pre>
            <div
              v-if="notes[i] && Object.keys(notes[i]).length"
              class="px-2 py-1 space-y-0.5 border-t border-ctp-surface0"
            >
              <div
                v-for="(note, ln) in notes[i]"
                :key="ln"
                class="flex items-start gap-1.5 text-[10px]"
              >
                <span class="font-mono text-ctp-mauve shrink-0">L{{ ln }}</span>
                <span class="text-ctp-subtext1">{{ note }}</span>
              </div>
            </div>
            <div
              v-if="notesState[i]?.error"
              class="px-2 py-1 text-[9px] text-ctp-red"
            >{{ t('assetMgmt.graph.lineNotesFailed') }} · {{ notesState[i]!.error }}</div>
            <div
              v-else-if="notesState[i]?.degraded"
              class="px-2 py-1 text-[9px] text-ctp-yellow"
            >{{ t('assetMgmt.graph.lineNotesDegraded') }}</div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CodeBracketIcon, MapPinIcon, SparklesIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import { semanticAssetService, type SourceSnippet } from '@/services/semantic-asset-service'
import type { SemanticAsset } from '@/types'
import { kindChipClass, levelChipClass } from '@/services/semantic-kind-style'
import PseudoExplainer from './PseudoExplainer.vue'

const props = defineProps<{ file: string; assets: SemanticAsset[] }>()
const emit = defineEmits<{ close: []; goto: [id: string] }>()
const { t } = useI18n()

const selId = ref(props.assets[0]?.id ?? '')
const sel = computed(() => props.assets.find((a) => a.id === selId.value) ?? null)
const descLoading = ref(false)

/** 源码路径展示：去开头 ./ 后从头省略目录段(保尾部)，完整路径悬停展示。 */
function shortPath(p: string): string {
  let s = p.replace(/^\.\//, '')
  if (s.length <= 44) return s
  const parts = s.split('/')
  while (parts.length > 1 && parts.join('/').length > 44) parts.shift()
  s = '…/' + parts.join('/')
  return s
}

interface Seg { file: string; startLine: number; endLine: number; symbol: string; snippet: SourceSnippet | null }
const segs = ref<Seg[]>([])
const notes = reactive<Record<number, Record<number, string>>>({})
const notesState = reactive<Record<number, { loading?: boolean; cached?: boolean; degraded?: boolean; error?: string; done?: boolean }>>({})

watch(selId, () => { void rebuild() }, { immediate: true })

/** 重建源码段：取选中资产在本文件的锚点，逐段拉符号体源码窗口。 */
async function rebuild() {
  segs.value = []
  for (const k of Object.keys(notes)) delete notes[Number(k)]
  for (const k of Object.keys(notesState)) delete notesState[Number(k)]
  const a = sel.value
  if (!a) return
  const refs = (a.astRefs ?? []).filter((r) => r.file === props.file)
  segs.value = refs.map((r) => ({
    file: r.file, startLine: r.startLine, endLine: r.endLine, symbol: r.symbol, snippet: null,
  }))
  for (let i = 0; i < segs.value.length; i++) {
    const s = segs.value[i]!
    s.snippet = (await semanticAssetService.sourceSnippet(
      s.file, s.startLine, s.symbol || undefined, 10, 10, 400,
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
