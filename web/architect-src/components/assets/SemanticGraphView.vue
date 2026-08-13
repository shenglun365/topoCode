<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, FunnelIcon, XMarkIcon, CheckIcon, ChevronDownIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { semanticGraphViewDiagrams, recommendedSemanticView } from '@/utils/diagram-gen'
import type { SemanticGraphViewId } from '@/utils/diagram-gen'
import type { AssetDetail, SemanticAsset, SemanticAssetKind, SemanticAssetLevel } from '@/types'
import type { SemanticGraphResult } from '@/services/semantic-asset-service'
import { semanticAssetService } from '@/services/semantic-asset-service'
import { kbAssetService } from '@/services/kb-assets'
import { useArchArchitectureStore } from '@/stores/architecture-store'

const { t } = useI18n()

/** 范围筛选(空=全部)：外部(资产列表)传入的组件范围，本地筛选未设置时生效。 */
const props = defineProps<{ scope?: string[] }>()

/** 「其它」哨兵：非组件文件(scope_type != comm)的资产。 */
const OTHER_KEY = '__other__'

const kind = ref<SemanticAssetKind | ''>('')
const level = ref<SemanticAssetLevel | ''>('')
/** 图类型视图(空=自动按类别/粒度推荐)。 */
const view = ref<SemanticGraphViewId | ''>('')
const graph = ref<SemanticGraphResult | null>(null)
const loading = ref(false)
const selId = ref('')
const selDetail = ref<SemanticAsset | null>(null)
/** 节点关键字搜索(前端过滤当前图谱节点)。 */
const nodeQ = ref('')
const nodeOpen = ref(false)
/** 聚焦半径(跳数)。 */
const focusHops = ref(1)
/** 信息卡拖动位置(null=默认右下)。 */
const cardPos = ref<{ x: number; y: number } | null>(null)
const cardEl = ref<HTMLElement | null>(null)
let cardDragging = false
let cardStartX = 0
let cardStartY = 0
let cardStartPos = { x: 0, y: 0 }

/** 本地按组件设定范围(空 = 沿用外部范围)。 */
const localScope = ref<string[]>([])
const scopeOpen = ref(false)
/** 弹出层锚点与定位(固定定位到 body，避免被左列表/容器裁剪遮挡)。 */
const scopeAnchor = ref<HTMLElement | null>(null)
const scopePos = ref({ left: 0, top: 0 })

/** 组件目录(树)筛选：与语义资产筛选一致(组件目录优先，架构模型兜底)。 */
const compCatalog = ref<{ id: string; name: string; parentId?: string }[]>([])
const compLoading = ref(false)
const compOpen = reactive<Record<string, boolean>>({})

const compRows = computed(() => {
  const rows: { id: string; name: string; parentId?: string; depth: number }[] = []
  const walk = (parentId: string | undefined, depth: number) => {
    for (const c of compCatalog.value) {
      if (c.parentId !== parentId) continue
      rows.push({ id: c.id, name: c.name, parentId: c.parentId, depth })
      if (compOpen[c.id] !== false) walk(c.id, depth + 1)
    }
  }
  walk(undefined, 0)
  return rows
})

function hasChildren(id: string): boolean {
  return compCatalog.value.some((c) => c.parentId === id)
}

function toggleOpen(id: string) {
  compOpen[id] = compOpen[id] !== false ? false : true
}

function descendantsOf(id: string): string[] {
  const out: string[] = []
  const stack = [id]
  while (stack.length) {
    const cur = stack.pop()!
    for (const c of compCatalog.value) {
      if (c.parentId === cur) {
        out.push(c.id)
        stack.push(c.id)
      }
    }
  }
  return out
}

async function loadComps() {
  compLoading.value = true
  try {
    let list: AssetDetail[] = []
    try {
      list = await kbAssetService.searchComponents('')
    } catch {
      list = []
    }
    if (list.length) {
      compCatalog.value = list.map((c) => ({
        id: c.assetId, name: c.name || c.assetId, parentId: c.parentId ?? undefined,
      }))
    } else {
      if (!arch.model) await arch.loadFromSnapshot().catch(() => {})
      compCatalog.value = arch.components.map((c) => ({
        id: c.id, name: c.name || c.id, parentId: c.parentId ?? undefined,
      }))
    }
  } finally {
    compLoading.value = false
  }
}

function toggleScopeComp(id: string) {
  const ids = [id, ...descendantsOf(id)]
  const s = new Set(localScope.value)
  const on = s.has(id)
  for (const i of ids) {
    if (on) s.delete(i)
    else s.add(i)
  }
  localScope.value = [...s]
}

function toggleScopeOther() {
  const s = new Set(localScope.value)
  if (s.has(OTHER_KEY)) s.delete(OTHER_KEY)
  else s.add(OTHER_KEY)
  localScope.value = [...s]
}

function clearLocalScope() {
  localScope.value = []
}

function openScope() {
  if (scopeOpen.value) {
    scopeOpen.value = false
    return
  }
  if (scopeAnchor.value) {
    const r = scopeAnchor.value.getBoundingClientRect()
    const w = 288
    scopePos.value = {
      left: Math.max(8, Math.min(r.left, window.innerWidth - w - 8)),
      top: r.bottom + 4,
    }
  }
  scopeOpen.value = true
}

function closeScope() {
  scopeOpen.value = false
}

function onViewportChange() {
  if (scopeOpen.value) scopeOpen.value = false
}

/** 生效范围：本地设置优先，否则沿用外部传入范围。 */
const effectiveScope = computed<string[] | undefined>(() => {
  if (localScope.value.length) return localScope.value
  if (props.scope?.length) return props.scope
  return undefined
})

const arch = useArchArchitectureStore()

const kinds: { value: SemanticAssetKind; label: string }[] = [
  { value: 'asset', label: t('assetMgmt.kind.asset') },
  { value: 'process', label: t('assetMgmt.kind.process') },
  { value: 'decision', label: t('assetMgmt.kind.decision') },
  { value: 'contract', label: t('assetMgmt.kind.contract') },
  { value: 'state', label: t('assetMgmt.kind.state') },
]

const levels: { value: SemanticAssetLevel; label: string }[] = [
  { value: 'business', label: t('assetMgmt.level.business') },
  { value: 'interaction', label: t('assetMgmt.level.interaction') },
  { value: 'algorithm', label: t('assetMgmt.level.algorithm') },
  { value: 'infra', label: t('assetMgmt.level.infra') },
]

const viewOptions: { value: SemanticGraphViewId | ''; label: string }[] = [
  { value: '', label: t('assetMgmt.graph.viewAuto') },
  { value: 'flow', label: t('assetMgmt.graph.viewFlow') },
  { value: 'class', label: t('assetMgmt.graph.viewClass') },
  { value: 'er', label: t('assetMgmt.graph.viewEr') },
  { value: 'seq', label: t('assetMgmt.graph.viewSeq') },
  { value: 'state', label: t('assetMgmt.graph.viewState') },
  { value: 'activity', label: t('assetMgmt.graph.viewActivity') },
  { value: 'mindmap', label: t('assetMgmt.graph.viewMindmap') },
]

/** 生效图类型：手动选择优先，否则按类别/粒度自动推荐。 */
const effectiveView = computed<SemanticGraphViewId>(() => (
  view.value || recommendedSemanticView(kind.value || undefined, level.value || undefined)
))

const nodeOptions = computed(() => (graph.value?.nodes ?? []).map((n) => ({
  id: n.id, label: `${n.name} · ${n.id}`,
})))

/** 按关键字过滤节点(name/id/kind/desc 小写包含匹配)。 */
const filteredNodeOptions = computed(() => {
  const q = nodeQ.value.trim().toLowerCase()
  if (!q) return nodeOptions.value
  const byId = new Map((graph.value?.nodes ?? []).map((n) => [n.id, n]))
  return nodeOptions.value.filter((o) => {
    if (o.label.toLowerCase().includes(q)) return true
    const n = byId.get(o.id)
    if (!n) return false
    return (n.kind || '').toLowerCase().includes(q)
      || (n.desc || '').toLowerCase().includes(q)
  })
})

const sel = computed(() => (graph.value?.nodes ?? []).find((n) => n.id === selId.value) ?? null)

/** 聚焦子图：选中节点 + N 跳邻居(边两端都在子集内)。 */
const focusedSub = computed<{ nodes: SemanticGraphResult['nodes']; edges: SemanticGraphResult['edges'] } | null>(() => {
  if (!selId.value || !graph.value) return null
  const allNodes = graph.value.nodes
  const allEdges = graph.value.edges
  if (!allNodes.some((n) => n.id === selId.value)) return null
  const ids = new Set<string>([selId.value])
  for (let hop = 0; hop < focusHops.value; hop++) {
    const add: string[] = []
    for (const e of allEdges) {
      if (ids.has(e.from) && allNodes.some((n) => n.id === e.to)) add.push(e.to)
      if (ids.has(e.to) && allNodes.some((n) => n.id === e.from)) add.push(e.from)
    }
    for (const a of add) ids.add(a)
  }
  return {
    nodes: allNodes.filter((n) => ids.has(n.id)),
    edges: allEdges.filter((e) => ids.has(e.from) && ids.has(e.to)),
  }
})

const diagrams = computed<Partial<Record<'mermaid' | 'plantuml', string>>>(() => {
  if (!graph.value) return {}
  const sub = focusedSub.value
  const nodes = sub ? sub.nodes : graph.value.nodes
  const edges = sub ? sub.edges : graph.value.edges
  return semanticGraphViewDiagrams(effectiveView.value, nodes, edges)
})

async function load() {
  loading.value = true
  try {
    graph.value = await semanticAssetService.graph(kind.value || undefined, effectiveScope.value, level.value || undefined)
    if (selId.value && !(graph.value?.nodes ?? []).some((n) => n.id === selId.value)) {
      selId.value = ''
      selDetail.value = null
    }
  } catch {
    graph.value = null
  } finally {
    loading.value = false
  }
}

function onKind() {
  selId.value = ''
  selDetail.value = null
  load()
}

watch(() => props.scope, () => {
  // 外部范围变化仅在本地未设范围时跟随；否则本地筛选优先。
  if (!localScope.value.length) {
    selId.value = ''
    selDetail.value = null
    load()
  }
})

watch(localScope, () => {
  selId.value = ''
  selDetail.value = null
  load()
})

function pickNode(id: string) {
  selId.value = id
  nodeOpen.value = false
  nodeQ.value = ''
  selDetail.value = null
  if (!id) return
  semanticAssetService.detail(id)
    .then((d) => { selDetail.value = d ?? null })
    .catch(() => { selDetail.value = null })
}

function clearSel() {
  selId.value = ''
  selDetail.value = null
  nodeOpen.value = false
  nodeQ.value = ''
}

function onNodeBlur() {
  setTimeout(() => { nodeOpen.value = false }, 120)
}

// ---- 信息卡拖动(默认右下，可拖到任意位置；双击标题复位) ----
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

function cardEndDrag() {
  cardDragging = false
}

function cardResetPos() {
  cardPos.value = null
}

/** 选中节点的代码锚点(优先资产详情 AST 引用，图谱锚点兜底)。 */
const selAnchors = computed<{ file: string; startLine: number; symbol: string }[]>(() => {
  if (!sel.value) return []
  const refs = selDetail.value?.astRefs ?? []
  if (refs.length) return refs
  return (graph.value?.anchors ?? [])
    .filter((a) => a.assetId === sel.value!.id)
    .map((a) => ({ file: a.file, startLine: a.line, symbol: a.symbol }))
})

onMounted(async () => {
  await loadComps()
  await load()
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="shrink-0 flex items-center gap-2 px-1 pt-1 flex-wrap">
      <select
        v-model="kind"
        class="input !py-0.5 !px-2 !text-[11px] w-auto"
        @change="onKind"
      >
        <option value="">
          {{ t('assetMgmt.graph.allKinds') }}
        </option>
        <option
          v-for="k in kinds"
          :key="k.value"
          :value="k.value"
        >
          {{ k.label }}
        </option>
      </select>
      <select
        v-model="level"
        class="input !py-0.5 !px-2 !text-[11px] w-auto"
        @change="onKind"
      >
        <option value="">
          {{ t('assetMgmt.graph.allLevels') }}
        </option>
        <option
          v-for="l in levels"
          :key="l.value"
          :value="l.value"
        >
          {{ l.label }}
        </option>
      </select>
      <select
        v-model="view"
        class="input !py-0.5 !px-2 !text-[11px] w-auto"
        :title="t('assetMgmt.graph.viewHint')"
      >
        <option
          v-for="v in viewOptions"
          :key="v.value"
          :value="v.value"
        >
          {{ v.label }}
        </option>
      </select>
      <button
        ref="scopeAnchor"
        class="btn btn-xs btn-ghost"
        :title="t('assetMgmt.graph.scopeFilter')"
        @click="openScope"
      >
        <FunnelIcon class="w-3 h-3" />
        <span class="text-[11px]">{{ t('assetMgmt.graph.scopeLabel') }}</span>
        <span
          v-if="effectiveScope"
          class="ml-0.5 max-w-[90px] truncate text-[10px] text-ctp-blue"
        >{{ effectiveScope.length }} {{ t('assetMgmt.graph.scopeCount') }}</span>
      </button>
      <Teleport to="body">
        <div
          v-if="scopeOpen"
          class="fixed inset-0 z-40"
          @mousedown.self="closeScope"
        />
        <div
          v-if="scopeOpen"
          class="fixed z-50 w-72 max-h-80 overflow-auto rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-2 space-y-1.5"
          :style="{ left: scopePos.left + 'px', top: scopePos.top + 'px' }"
        >
          <div class="flex items-center justify-between">
            <span class="text-[10px] text-ctp-overlay1">{{ t('assetMgmt.graph.scopeFilter') }}</span>
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0"
              :title="t('assetMgmt.graph.scopeClear')"
              @click="clearLocalScope"
            >
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
          <p class="text-[9px] text-ctp-overlay0 px-0.5">
            {{ t('assetMgmt.graph.scopeHint') }}
          </p>
          <template v-if="compLoading">
            <div class="text-[10px] text-ctp-overlay0 px-0.5">
              {{ t('assetMgmt.graph.scopeLoading') }}
            </div>
          </template>
          <template v-else>
            <div
              v-for="r in compRows"
              :key="r.id"
              class="flex items-center gap-1.5 min-w-0"
              :style="{ paddingLeft: (r.depth * 12) + 'px' }"
            >
              <button
                v-if="hasChildren(r.id)"
                class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                @click="toggleOpen(r.id)"
              >
                <ChevronDownIcon
                  v-if="compOpen[r.id] !== false"
                  class="w-3 h-3"
                />
                <ChevronRightIcon
                  v-else
                  class="w-3 h-3"
                />
              </button>
              <span
                v-else
                class="w-4 shrink-0"
              />
              <input
                type="checkbox"
                class="accent-ctp-blue shrink-0"
                :checked="localScope.includes(r.id)"
                @change="toggleScopeComp(r.id)"
              >
              <span class="text-[11px] text-ctp-subtext1 truncate">{{ r.name }}</span>
            </div>
            <div
              v-if="!compRows.length"
              class="text-[10px] text-ctp-overlay0 px-0.5"
            >
              {{ t('assetMgmt.graph.scopeEmpty') }}
            </div>
            <div class="flex items-center gap-1.5 min-w-0 pt-0.5 border-t border-ctp-surface0">
              <span class="w-4 shrink-0" />
              <input
                type="checkbox"
                class="accent-ctp-mauve shrink-0"
                :checked="localScope.includes(OTHER_KEY)"
                @change="toggleScopeOther"
              >
              <span class="text-[11px] text-ctp-subtext1">{{ t('assetMgmt.graph.scopeOther') }}</span>
            </div>
          </template>
          <div
            v-if="effectiveScope?.length"
            class="flex items-center gap-1 pt-1 border-t border-ctp-surface0"
          >
            <CheckIcon class="w-3 h-3 text-ctp-green" />
            <span class="text-[10px] text-ctp-green">{{ t('assetMgmt.graph.scopeApplied', { n: effectiveScope.length }) }}</span>
          </div>
        </div>
      </Teleport>
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
      <div
        v-if="graph?.nodes.length"
        class="relative"
      >
        <input
          v-model="nodeQ"
          class="input !py-0.5 !px-2 !text-[11px] w-52"
          :placeholder="t('assetMgmt.graph.nodeSearch')"
          @focus="nodeOpen = true"
          @input="nodeOpen = true"
          @blur="onNodeBlur"
          @keydown.esc="nodeOpen = false"
        >
        <button
          v-if="sel"
          class="absolute right-1 top-1/2 -translate-y-1/2 text-ctp-overlay0 hover:text-ctp-text p-0.5"
          :title="t('assetMgmt.graph.clearFocus')"
          @mousedown.prevent
          @click="clearSel"
        >
          <XMarkIcon class="w-3 h-3" />
        </button>
        <div
          v-if="nodeOpen && (filteredNodeOptions.length || nodeQ.trim())"
          class="absolute right-0 top-full z-20 mt-1 w-64 max-h-64 overflow-auto rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl py-1"
        >
          <button
            v-for="o in filteredNodeOptions"
            :key="o.id"
            class="block w-full text-left px-2 py-1 text-[11px] text-ctp-subtext1 hover:bg-ctp-surface0 truncate"
            @mousedown.prevent
            @click="pickNode(o.id)"
          >
            {{ o.label }}
          </button>
          <div
            v-if="!filteredNodeOptions.length"
            class="px-2 py-1 text-[10px] text-ctp-overlay0"
          >
            {{ t('assetMgmt.graph.nodeNoMatch') }}
          </div>
        </div>
      </div>
      <span class="flex-1" />
      <span
        v-if="graph"
        class="text-[10px] text-ctp-overlay0 font-mono"
      >{{ graph.nodes.length }} {{ t('assetMgmt.graph.nodes') }} · {{ graph.edges.length }} {{ t('assetMgmt.graph.edges') }} · {{ graph.anchors.length }} {{ t('assetMgmt.graph.anchors') }}</span>
    </div>

    <div
      v-if="sel"
      class="shrink-0 flex items-center gap-1.5 px-1 pt-1 flex-wrap"
    >
      <span class="text-[10px] text-ctp-overlay1 shrink-0">{{ t('assetMgmt.graph.focusLabel') }}</span>
      <span class="chip bg-ctp-surface0 text-ctp-text font-mono text-[10px] max-w-[260px] truncate">{{ sel.name }} · {{ sel.id }}</span>
      <span
        class="chip !text-[9px] shrink-0"
        :class="{
          'bg-ctp-mauve/15 text-ctp-mauve': sel.kind === 'asset',
          'bg-ctp-blue/15 text-ctp-blue': sel.kind === 'process',
          'bg-ctp-green/15 text-ctp-green': sel.kind === 'decision',
          'bg-ctp-yellow/15 text-ctp-yellow': sel.kind === 'contract',
              'bg-ctp-sky/15 text-ctp-sky': sel.kind === 'state',
        }"
      >{{ t(`assetMgmt.kind.${sel.kind}`) }}</span>
      <button
        class="btn btn-xs !py-0.5"
        :class="focusHops === 1 ? 'btn-blue' : 'btn-ghost'"
        @click="focusHops = 1"
      >
        1 {{ t('assetMgmt.graph.hop') }}
      </button>
      <button
        class="btn btn-xs !py-0.5"
        :class="focusHops === 2 ? 'btn-blue' : 'btn-ghost'"
        @click="focusHops = 2"
      >
        2 {{ t('assetMgmt.graph.hop') }}
      </button>
      <span
        class="text-[10px] text-ctp-overlay0 font-mono shrink-0"
      >{{ focusedSub?.nodes.length ?? 0 }} {{ t('assetMgmt.graph.nodes') }} · {{ focusedSub?.edges.length ?? 0 }} {{ t('assetMgmt.graph.edges') }}</span>
      <span class="flex-1" />
      <button
        class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
        :title="t('assetMgmt.graph.clearFocus')"
        @click="clearSel"
      >
        <XMarkIcon class="w-3.5 h-3.5" />
      </button>
    </div>

    <p class="shrink-0 text-[9px] text-ctp-overlay0 px-1">
      {{ t('assetMgmt.graph.hint') }}
    </p>

    <div class="flex-1 min-h-0 relative">
      <div
        v-if="loading"
        class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0"
      >
        {{ t('assetMgmt.graph.loading') }}
      </div>
      <div
        v-else-if="!graph || !graph.nodes.length"
        class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0"
      >
        {{ t('assetMgmt.graph.empty') }}
      </div>

      <DiagramCard
        v-else
        class="h-full"
        :title="t('assetMgmt.graph.title')"
        :diagrams="diagrams"
        :default-lang="'mermaid'"
      />

      <!-- 选中节点详情(默认右下，可拖动改变位置；双击标题复位) -->
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
              'bg-ctp-mauve/15 text-ctp-mauve': sel.kind === 'asset',
              'bg-ctp-blue/15 text-ctp-blue': sel.kind === 'process',
              'bg-ctp-green/15 text-ctp-green': sel.kind === 'decision',
              'bg-ctp-yellow/15 text-ctp-yellow': sel.kind === 'contract',
              'bg-ctp-sky/15 text-ctp-sky': sel.kind === 'state',
            }"
          >{{ t(`assetMgmt.kind.${sel.kind}`) }}</span>
          <span
            v-if="sel.canonicalKey"
            class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1 font-mono shrink-0"
            :title="t('assetMgmt.canonicalHint')"
          >{{ sel.canonicalKey.slice(0, 10) }}…</span>
          <span class="flex-1" />
          <button
            class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
            :title="t('assetMgmt.graph.clearFocus')"
            @click="clearSel"
          >
            <XMarkIcon class="w-3.5 h-3.5" />
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
