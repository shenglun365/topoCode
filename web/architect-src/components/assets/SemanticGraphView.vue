<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { semanticGraphToMermaid, semanticGraphToPlantUml } from '@/utils/diagram-gen'
import type { SemanticAsset, SemanticAssetKind, SemanticAssetLevel } from '@/types'
import type { SemanticGraphResult } from '@/services/semantic-asset-service'
import { semanticAssetService } from '@/services/semantic-asset-service'

const { t } = useI18n()

/** 范围筛选(空=全部)：与语义资产列表共用组件树多选，控制图谱显示范围。 */
const props = defineProps<{ scope?: string[] }>()

const kind = ref<SemanticAssetKind | ''>('')
const level = ref<SemanticAssetLevel | ''>('')
const graph = ref<SemanticGraphResult | null>(null)
const loading = ref(false)
const selId = ref('')
const selDetail = ref<SemanticAsset | null>(null)

const kinds: { value: SemanticAssetKind; label: string }[] = [
  { value: 'structure', label: t('assetMgmt.kind.structure') },
  { value: 'behavior', label: t('assetMgmt.kind.behavior') },
  { value: 'rule', label: t('assetMgmt.kind.rule') },
  { value: 'contract', label: t('assetMgmt.kind.contract') },
]

const levels: { value: SemanticAssetLevel; label: string }[] = [
  { value: 'high', label: t('assetMgmt.level.high') },
  { value: 'medium', label: t('assetMgmt.level.medium') },
  { value: 'low', label: t('assetMgmt.level.low') },
]

const nodeOptions = computed(() => (graph.value?.nodes ?? []).map((n) => ({
  id: n.id, label: `${n.name} · ${n.id}`,
})))

const sel = computed(() => (graph.value?.nodes ?? []).find((n) => n.id === selId.value) ?? null)

const diagrams = computed<Partial<Record<'mermaid' | 'plantuml', string>>>(() => {
  if (!graph.value) return {}
  return {
    mermaid: semanticGraphToMermaid(graph.value.nodes, graph.value.edges),
    plantuml: semanticGraphToPlantUml(graph.value.nodes, graph.value.edges),
  }
})

async function load() {
  loading.value = true
  try {
    graph.value = await semanticAssetService.graph(kind.value || undefined, props.scope?.length ? props.scope : undefined, level.value || undefined)
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
  selId.value = ''
  selDetail.value = null
  load()
})

async function onSelect(id: string) {
  if (!id) {
    selDetail.value = null
    return
  }
  selDetail.value = null
  try {
    selDetail.value = (await semanticAssetService.detail(id)) ?? null
  } catch {
    selDetail.value = null
  }
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

onMounted(load)
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
      <button
        class="btn btn-xs btn-ghost"
        :disabled="loading"
        @click="load"
      >
        <ArrowPathIcon
          class="w-3 h-3"
          :class="loading ? 'animate-spin' : ''"
        />{{ t('assetMgmt.graph.reload') }}
      </button>
      <select
        v-if="nodeOptions.length"
        v-model="selId"
        class="input !py-0.5 !px-2 !text-[11px] w-auto max-w-[220px]"
        :title="t('assetMgmt.graph.nodeSelectHint')"
        @change="onSelect(selId)"
      >
        <option value="">
          {{ t('assetMgmt.graph.nodeSelect') }}
        </option>
        <option
          v-for="o in nodeOptions"
          :key="o.id"
          :value="o.id"
        >
          {{ o.label }}
        </option>
      </select>
      <span class="flex-1" />
      <span
        v-if="graph"
        class="text-[10px] text-ctp-overlay0 font-mono"
      >{{ graph.nodes.length }} {{ t('assetMgmt.graph.nodes') }} · {{ graph.edges.length }} {{ t('assetMgmt.graph.edges') }} · {{ graph.anchors.length }} {{ t('assetMgmt.graph.anchors') }}</span>
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

      <!-- 选中节点详情 -->
      <div
        v-if="sel"
        class="absolute right-2 bottom-2 z-10 w-80 max-w-[calc(100%-1rem)] max-h-[60%] overflow-auto rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-3 space-y-2"
      >
        <div class="flex items-center gap-1.5">
          <span class="text-[11px] font-semibold text-ctp-text truncate">{{ sel.name }}</span>
          <span
            class="chip !text-[9px] shrink-0"
            :class="{
              'bg-ctp-mauve/15 text-ctp-mauve': sel.kind === 'structure',
              'bg-ctp-blue/15 text-ctp-blue': sel.kind === 'behavior',
              'bg-ctp-green/15 text-ctp-green': sel.kind === 'rule',
              'bg-ctp-yellow/15 text-ctp-yellow': sel.kind === 'contract',
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
            @click="selId = ''; selDetail = null"
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
