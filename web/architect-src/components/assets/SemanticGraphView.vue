<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, XMarkIcon, ArrowsPointingOutIcon } from '@heroicons/vue/24/outline'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { semanticGraphViewDiagrams, supportedViewsFor, viewUnavailableReasons } from '@/utils/diagram-gen'
import type { SemanticGraphViewId } from '@/utils/diagram-gen'
import type { SemanticAsset, SemanticAssetLevel } from '@/types'
import type { SemanticGraphResult } from '@/services/semantic-asset-service'
import { semanticAssetService } from '@/services/semantic-asset-service'

const { t } = useI18n()

/** 图谱资源 tab 定义(由外部资产列表/组件列表打开)。 */
export interface GraphTabDef {
  id: string
  kind: 'all' | 'comp' | 'asset'
  title: string
  compId?: string
  assetId?: string
}

const props = defineProps<{ tab: GraphTabDef }>()
const emit = defineEmits<{ close: [id: string] }>()

const level = ref<SemanticAssetLevel | ''>('')
/** 图类型视图(空=按数据区间自动推荐)。 */
const view = ref<SemanticGraphViewId | ''>('')
const graph = ref<SemanticGraphResult | null>(null)
const loading = ref(false)
const selId = ref('')
const selDetail = ref<SemanticAsset | null>(null)
/** 粒度控制：业务(仅 business 级) / 全部。组件级默认业务。 */
const businessOnly = ref(props.tab.kind === 'comp')
/** DiagramCard 实例(ref：headerless 时由本工具栏接管语言/源码/全屏)。 */
const cardRef = ref<InstanceType<typeof DiagramCard> | null>(null)
/** 当前渲染语言(默认 mermaid)。 */
const cardLang = ref<'mermaid' | 'plantuml'>('mermaid')
const cardSrcOpen = ref(false)
const diagramLangs = computed(() => [{ id: 'mermaid' as const, label: 'mermaid' }, { id: 'plantuml' as const, label: 'plantuml' }])
function setCardLang(l: 'mermaid' | 'plantuml') {
  cardLang.value = l
  cardRef.value?.setLang(l)
}
function toggleCardSource() {
  cardSrcOpen.value = !cardSrcOpen.value
  cardRef.value?.toggleSource()
}
function openCardFullscreen() {
  cardRef.value?.openFullscreen()
}
/** 信息卡拖动位置。 */
const cardPos = ref<{ x: number; y: number } | null>(null)
const cardEl = ref<HTMLElement | null>(null)
let cardDragging = false
let cardStartX = 0
let cardStartY = 0
let cardStartPos = { x: 0, y: 0 }

/** 数据区间粒度：粒度下拉选择优先，否则业务开关决定(business=业务，否则全部)。 */
const effectiveLevel = computed<SemanticAssetLevel | ''>(() => {
  if (level.value) return level.value
  return businessOnly.value ? 'business' : ''
})

/** 生效节点集：按粒度过滤(业务=仅 business 级) + 单资产视图聚焦。 */
const scopedNodes = computed(() => (graph.value?.nodes ?? []).filter((n) => {
  if (effectiveLevel.value && n.level !== effectiveLevel.value) return false
  return true
}))

const scopedEdges = computed(() => {
  const ids = new Set(scopedNodes.value.map((n) => n.id))
  return (graph.value?.edges ?? []).filter((e) => ids.has(e.from) && ids.has(e.to))
})

/** 图类型：手动选择优先，否则按数据区间自动推荐第一个支持的。 */
const viewOptions = computed<{ value: SemanticGraphViewId; label: string }[]>(() => {
  const supported = supportedViewsFor(effectiveLevel.value, scopedNodes.value)
  const labels: Record<SemanticGraphViewId, string> = {
    flow: t('assetMgmt.graph.viewFlow'),
    class: t('assetMgmt.graph.viewClass'),
    er: t('assetMgmt.graph.viewEr'),
    seq: t('assetMgmt.graph.viewSeq'),
    state: t('assetMgmt.graph.viewState'),
    activity: t('assetMgmt.graph.viewActivity'),
    mindmap: t('assetMgmt.graph.viewMindmap'),
  }
  return supported.map((v) => ({ value: v, label: labels[v] }))
})

/** 因数据不适合而被隐藏的视图及其原因(工具提示说明「为何不可选」)。 */
const hiddenViewHints = computed<string[]>(() => {
  const reasons = viewUnavailableReasons(effectiveLevel.value, scopedNodes.value)
  const labels: Record<SemanticGraphViewId, string> = {
    flow: t('assetMgmt.graph.viewFlow'),
    class: t('assetMgmt.graph.viewClass'),
    er: t('assetMgmt.graph.viewEr'),
    seq: t('assetMgmt.graph.viewSeq'),
    state: t('assetMgmt.graph.viewState'),
    activity: t('assetMgmt.graph.viewActivity'),
    mindmap: t('assetMgmt.graph.viewMindmap'),
  }
  return (Object.keys(reasons) as SemanticGraphViewId[]).map((v) => `${labels[v]}：${reasons[v]}`)
})

const effectiveView = computed<SemanticGraphViewId>(() => {
  if (view.value && viewOptions.value.some((o) => o.value === view.value)) return view.value
  return viewOptions.value[0]?.value ?? 'flow'
})

/** 选中节点(单资产视图的焦点 / 节点点击)。 */
const sel = computed(() => (graph.value?.nodes ?? []).find((n) => n.id === selId.value) ?? null)

const diagrams = computed<Partial<Record<'mermaid' | 'plantuml', string>>>(() => {
  if (!graph.value) return {}
  return semanticGraphViewDiagrams(effectiveView.value, scopedNodes.value, scopedEdges.value)
})

async function load() {
  loading.value = true
  try {
    const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
    const focus = props.tab.kind === 'asset' ? props.tab.assetId : undefined
    graph.value = await semanticAssetService.graph(undefined, scope, undefined, { focus, hops: 1 })
    // 单资产视图：加载后聚焦目标资产。
    if (props.tab.kind === 'asset' && props.tab.assetId) {
      selId.value = props.tab.assetId
    } else if (selId.value && !(graph.value?.nodes ?? []).some((n) => n.id === selId.value)) {
      selId.value = ''
      selDetail.value = null
    }
  } catch {
    graph.value = null
  } finally {
    loading.value = false
  }
}

watch(() => props.tab, () => {
  selId.value = props.tab.kind === 'asset' ? (props.tab.assetId ?? '') : ''
  selDetail.value = null
  businessOnly.value = props.tab.kind === 'comp'
  level.value = ''
  view.value = ''
  load()
})

function clearSel() {
  selId.value = ''
  selDetail.value = null
}

/** 选中节点的代码锚点。 */
const selAnchors = computed<{ file: string; startLine: number; symbol: string }[]>(() => {
  if (!sel.value) return []
  const refs = selDetail.value?.astRefs ?? []
  if (refs.length) return refs
  return (graph.value?.anchors ?? [])
    .filter((a) => a.assetId === sel.value!.id)
    .map((a) => ({ file: a.file, startLine: a.line, symbol: a.symbol }))
})

// ---- 信息卡拖动 ----
function cardStartDrag(e: MouseEvent) {
  if (e.button !== 0) return
  const el = cardEl.value
  if (!el) return
  const target = e.target as HTMLElement
  if (target.closest('button, a, input, select')) return
  cardDragging = true
  cardStartX = e.clientX
  cardStartY = e.clientY
  cardStartPos = { x: el.offsetLeft, y: el.offsetTop }
  e.preventDefault()
}
function cardDrag(e: MouseEvent) {
  if (!cardDragging) return
  cardPos.value = {
    x: cardStartPos.x + (e.clientX - cardStartX),
    y: cardStartPos.y + (e.clientY - cardStartY),
  }
}
function cardEndDrag() { cardDragging = false }
function cardResetPos() { cardPos.value = null }

onMounted(async () => {
  await load()
})
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <!-- 工具栏(单行)：粒度 + 图类型 + 视图上下文(单资产焦点/关联级别) + 统计 + 操作 -->
    <div class="shrink-0 flex items-center gap-1.5 px-1 pt-1 pb-1 border-b border-ctp-surface0 overflow-x-auto">
      <select
        v-model="level"
        class="input !py-0.5 !px-2 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.levelHint')"
      >
        <option value="">{{ t('assetMgmt.graph.allLevels') }}</option>
        <option value="business">{{ t('assetMgmt.graph.business') }}</option>
        <option value="logic">{{ t('assetMgmt.graph.logic') }}</option>
        <option value="implementation">{{ t('assetMgmt.graph.implementation') }}</option>
      </select>
      <button
        class="btn btn-xs shrink-0"
        :class="businessOnly ? 'btn-blue' : 'btn-ghost'"
        :title="t('assetMgmt.graph.businessOnlyHint')"
        @click="businessOnly = !businessOnly; level = ''"
      >
        {{ businessOnly ? t('assetMgmt.graph.business') : t('assetMgmt.graph.all') }}
      </button>
      <div class="w-px h-4 bg-ctp-surface1 shrink-0" />
      <select
        v-model="view"
        class="input !py-0.5 !px-2 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.viewHint')"
      >
        <option
          v-for="o in viewOptions"
          :key="o.value"
          :value="o.value"
        >
          {{ o.label }}
        </option>
      </select>
      <span
        v-if="hiddenViewHints.length"
        class="shrink-0 text-[10px] text-ctp-overlay1 cursor-help"
        :title="hiddenViewHints.join('\n')"
      >ⓘ {{ t('assetMgmt.graph.unavailableHint') }}</span>
      <!-- 单资产视图上下文：聚焦资产(1 跳) -->
      <template v-if="props.tab.kind === 'asset' && sel">
        <div class="w-px h-4 bg-ctp-surface1 shrink-0" />
        <button
          class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
          :title="t('assetMgmt.graph.clearFocus')"
          @click="clearSel"
        >
          <XMarkIcon class="w-3 h-3" />
        </button>
      </template>
      <span class="flex-1" />
      <span
        v-if="graph"
        class="text-[10px] text-ctp-overlay0 font-mono shrink-0"
      >{{ scopedNodes.length }} {{ t('assetMgmt.graph.nodes') }} · {{ scopedEdges.length }} {{ t('assetMgmt.graph.edges') }}</span>
      <div
        v-if="graph"
        class="flex items-center gap-0.5 shrink-0"
      >
        <button
          v-for="l in diagramLangs"
          :key="l.id"
          class="px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer"
          :class="cardLang === l.id
            ? 'bg-ctp-blue/15 text-ctp-blue ring-1 ring-ctp-blue/30'
            : 'text-ctp-subtext0 hover:bg-ctp-surface0'"
          :title="l.label"
          @click="setCardLang(l.id)"
        >
          {{ l.label }}
        </button>
        <button
          class="btn btn-ghost !py-0.5 text-[11px]"
          :title="t('assetMgmt.graph.source')"
          @click="toggleCardSource"
        >
          {{ cardSrcOpen ? t('assetMgmt.graph.diagram') : 'src' }}
        </button>
        <button
          class="btn btn-ghost !py-0.5 text-[11px]"
          :title="t('assetMgmt.graph.fullscreen')"
          @click="openCardFullscreen"
        >
          <ArrowsPointingOutIcon class="w-3.5 h-3.5" />
        </button>
      </div>
      <button
        class="btn btn-xs btn-ghost"
        :disabled="loading"
        :title="t('assetMgmt.graph.reload')"
        @click="load"
      >
        <ArrowPathIcon
          class="w-3 h-3"
          :class="loading ? 'animate-spin' : ''"
        />
      </button>
      <button
        class="btn btn-xs btn-ghost"
        :title="t('assetMgmt.graph.closeTab')"
        @click="emit('close', props.tab.id)"
      >
        <XMarkIcon class="w-3 h-3" />
      </button>
    </div>

    <div class="flex-1 min-h-0 relative">
      <div
        v-if="loading"
        class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0"
      >
        {{ t('assetMgmt.graph.loading') }}
      </div>
      <div
        v-else-if="!graph || !scopedNodes.length"
        class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0"
      >
        {{ t('assetMgmt.graph.empty') }}
      </div>

      <DiagramCard
        v-else
        ref="cardRef"
        class="h-full"
        :title="t('assetMgmt.graph.title')"
        :diagrams="diagrams"
        :default-lang="'mermaid'"
        :allowed-langs="['mermaid', 'plantuml']"
        headerless
      />

      <!-- 选中节点详情(可拖动) -->
      <div
        v-if="sel"
        ref="cardEl"
        class="absolute z-10 w-80 max-w-[calc(100%-1rem)] max-h-[60%] overflow-auto rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-3 space-y-2"
        :class="[!cardPos ? 'right-2 bottom-2' : '', cardDragging ? 'cursor-grabbing select-none' : '']"
        :style="cardPos ? { left: cardPos.x + 'px', top: cardPos.y + 'px' } : {}"
        :title="t('assetMgmt.graph.cardResetPos')"
        @mousemove="cardDrag"
        @mouseup="cardEndDrag"
        @mouseleave="cardEndDrag"
        @dblclick="cardResetPos"
      >
        <div
          class="flex items-center gap-1.5 cursor-move"
          @mousedown="cardStartDrag"
        >
          <span class="text-[11px] font-semibold text-ctp-text truncate">{{ sel.name }}</span>
          <span
            class="chip !text-[9px] shrink-0"
            :class="{
              'bg-ctp-mauve/15 text-ctp-mauve': sel.kind === 'entity',
              'bg-ctp-yellow/15 text-ctp-yellow': sel.kind === 'contract',
              'bg-ctp-sky/15 text-ctp-sky': sel.kind === 'state',
              'bg-ctp-peach/15 text-ctp-peach': sel.kind === 'rule',
              'bg-ctp-blue/15 text-ctp-blue': sel.kind === 'process',
              'bg-ctp-green/15 text-ctp-green': sel.kind === 'decision',
            }"
          >{{ t(`assetMgmt.kind.${sel.kind}`) }}</span>
          <span class="flex-1" />
          <button
            class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
            :title="t('assetMgmt.graph.clearFocus')"
            @click="clearSel"
          >
            <XMarkIcon class="w-3 h-3" />
          </button>
        </div>
        <p class="text-[10px] text-ctp-subtext0 whitespace-pre-wrap">
          {{ selDetail?.desc || sel.desc }}
        </p>
        <template v-if="selDetail?.detail">
          <div v-if="selDetail.detail.fields?.length">
            <div class="font-medium text-[10px] text-ctp-mauve mb-0.5">
              {{ t('assetMgmt.fields') }}
            </div>
            <div
              v-for="f in selDetail.detail.fields"
              :key="f.name"
              class="pl-2 text-[10px]"
            >
              <span class="font-mono text-ctp-text">{{ f.name }}</span><span class="text-ctp-overlay0">: {{ f.type ?? '—' }}</span>
            </div>
          </div>
          <div v-if="selDetail.detail.steps?.length">
            <div class="font-medium text-[10px] text-ctp-mauve mb-0.5">
              {{ t('assetMgmt.steps') }}
            </div>
            <div
              v-for="(s, si) in selDetail.detail.steps"
              :key="si"
              class="pl-2 text-[10px]"
            >
              {{ s.order ?? si + 1 }}. {{ s.semantic }}
            </div>
          </div>
          <div v-if="selDetail.detail.branches?.length">
            <div class="font-medium text-[10px] text-ctp-mauve mb-0.5">
              {{ t('assetMgmt.branches') }}
            </div>
            <div
              v-for="(b, bi) in selDetail.detail.branches"
              :key="bi"
              class="pl-2 text-[10px]"
            >
              <span class="font-mono text-ctp-text">if {{ b.condition ?? '?' }}</span> → {{ b.then ?? '—' }}
            </div>
          </div>
        </template>
        <div v-if="selAnchors.length">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5">
            {{ t('assetMgmt.graph.anchor') }}
          </div>
          <div
            v-for="(r, ri) in selAnchors"
            :key="ri"
            class="pl-2 font-mono text-[9px] text-ctp-overlay0"
          >
            {{ r.file }}:L{{ r.startLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span>
          </div>
        </div>
        <div
          v-else
          class="text-[10px] text-ctp-overlay0"
        >
          {{ t('assetMgmt.graph.noDetail') }}
        </div>
      </div>
    </div>
  </div>
</template>
