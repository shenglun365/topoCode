<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CodeBracketIcon, ExclamationTriangleIcon } from '@heroicons/vue/24/outline'
import { buildPlantUmlUrl, normalizeMermaid, renderMermaid } from '@/composables/useDiagramRenderer'
import type { DiagramLang } from '@/composables/useDiagramRenderer'
import { topoScriptSample } from '@/composables/useTopoScript'
import TopoScriptCanvas from './TopoScriptCanvas.vue'

const props = defineProps<{
  title: string
  diagrams: Partial<Record<DiagramLang, string>>
  badges?: { text: string; cls: string }[]
  playKey?: number
}>()

const { t } = useI18n()
const defaultLang = computed<DiagramLang>(() => (props.diagrams.toposcript ? 'toposcript' : 'mermaid'))

const langs: DiagramLang[] = ['mermaid', 'plantuml', 'toposcript']
const lang = ref<DiagramLang>(defaultLang.value)
const loading = ref(false)
const svg = ref('')
const error = ref('')
const showSource = ref(false)
const plantumlUrl = ref('')
const plantumlFailed = ref(false)
const playing = ref(false)

const code = computed(() => props.diagrams[lang.value] ?? '')
const currentCode = computed(() => (lang.value === 'toposcript' && !props.diagrams.toposcript ? topoScriptSample() : props.diagrams[lang.value] ?? ''))

watch(
  () => [lang.value, props.diagrams] as const,
  async () => {
    render()
  },
  { immediate: true },
)

let uid = 0
const cid = `dc-${Date.now()}-${++uid}`

async function render() {
  error.value = ''
  plantumlFailed.value = false
  showSource.value = false
  if (lang.value === 'toposcript') {
    playing.value = false
    return
  }
  if (lang.value === 'plantuml') {
    if (!code.value) return
    plantumlUrl.value = buildPlantUmlUrl(code.value)
    return
  }
  if (!code.value) return
  loading.value = true
  try {
    svg.value = await renderMermaid(normalizeMermaid(code.value), cid)
  } catch (e) {
    error.value = (e as Error).message || 'render failed'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.playKey,
  (v) => {
    if (v !== undefined && lang.value === 'toposcript') playing.value = true
  },
)

onBeforeUnmount(() => { playing.value = false })
</script>

<template>
  <!-- eslint-disable vue/no-v-html -->
  <div class="panel overflow-hidden">
    <div class="panel-header">
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
      </div>
    </div>

    <div class="p-3">
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
        v-else-if="lang === 'plantuml'"
        class="relative"
      >
        <div
          v-if="!code"
          class="text-xs text-ctp-overlay0 py-6 text-center"
        >
          {{ t('common.empty') }} (plantuml)
        </div>
        <div
          v-else-if="!plantumlFailed"
          class="min-h-[120px] flex items-center justify-center"
        >
          <img
            v-if="plantumlUrl"
            :src="plantumlUrl"
            class="max-w-full"
            :class="{ 'opacity-40': loading }"
            @error="plantumlFailed = true"
            @load="loading = false"
          >
        </div>
        <div
          v-if="plantumlFailed"
          class="flex flex-col items-center gap-2 py-4 text-ctp-red"
        >
          <ExclamationTriangleIcon class="w-5 h-5" />
          <span class="text-xs">{{ t('architecture.renderFailed') }} (plantuml-server 未就绪)</span>
        </div>
      </div>

      <div
        v-else
        class="relative"
      >
        <div
          v-if="loading"
          class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay1 z-10 bg-ctp-mantle/60 rounded"
        >
          {{ t('architecture.rendering') }}
        </div>
        <div
          v-if="error"
          class="text-xs text-ctp-red mb-2 flex items-center gap-1"
        >
          <ExclamationTriangleIcon class="w-4 h-4" />{{ t('architecture.renderFailed') }}
        </div>
        <div
          v-else-if="svg"
          class="diagram-svg"
          v-html="svg"
        />
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
  </div>
  <!-- eslint-enable vue/no-v-html -->
</template>

<style scoped>
.diagram-svg :deep(svg) {
  max-width: 100%;
  height: auto;
}
.diagram-svg :deep(.node rect),
.diagram-svg :deep(.node circle),
.diagram-svg :deep(.node polygon) {
  fill: #313244;
  stroke: #585b70;
}
.diagram-svg :deep(.edgePath .path),
.diagram-svg :deep(.edgeLabel) {
  stroke: #7f849c;
}
.diagram-svg :deep(.nodeLabel),
.diagram-svg :deep(.edgeLabel) {
  color: #cdd6f4;
  fill: #cdd6f4;
}
</style>
