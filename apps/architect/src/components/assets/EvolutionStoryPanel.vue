<script setup lang="ts">
/**
 * 演化播放面板 —— 任意 base..head ref 对 → 统一图 JSON 存在性投影播放。
 * 数据链：BE evolution-frames(build_graph_frames: canonical 并集 + 每帧存在性)
 * → TopoStory graph 形态（一次 elk 布局 + 单 svg 常驻 + 存在性切换）。
 * 不变节点像素级静止，新增淡入/消失淡出/modified 脉冲；视角恒定。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import TopoStory from '@topo/graph-kernel/vue/TopoStory.vue'
import { ArrowPathIcon, PlayIcon, ArrowsPointingOutIcon } from '@heroicons/vue/24/outline'
import { projectService } from '@/services/project-service'
import type { GraphFrameDataInput } from '@topo/engine'
import type { EvolutionFrames } from '@/types'

defineProps<{ category?: 'structure' | 'dependency' | 'calls' }>()
const { t } = useI18n()

const rootRef = ref<HTMLElement | null>(null)
const baseRef = ref('baseline')
const headRef = ref('HEAD')
/** 帧粒度: 组件依赖(宏观) / 变更文件(下沉, numstat 三色——帧间差异显著, 补间素材层)。 */
const layer = ref<'component' | 'file'>('component')
const loading = ref(false)
const error = ref('')
const data = ref<EvolutionFrames | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await projectService.evolutionFrames(baseRef.value, headRef.value, layer.value)
    data.value = r
    if (!r?.frames?.length) error.value = t('archChange.evolutionEmpty')
  } catch (e: any) {
    error.value = e?.message || t('archChange.evolutionFail')
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)

/** BE 统一 JSON → 播放组件输入（形状同构直传）。 */
const graphData = computed<GraphFrameDataInput | null>(() => {
  const d = data.value
  if (!d?.canonical || !d.frames?.length) return null
  return {
    canonical: {
      nodes: d.canonical.nodes.map((n) => ({ key: n.key, label: n.label, container: n.container })),
      edges: d.canonical.edges.map((e) => ({ key: e.key, from: e.from, to: e.to })),
      containers: d.canonical.containers ?? [],
    },
    frames: d.frames.map((f) => ({ id: f.id, label: f.label, nodes: f.nodes, edges: f.edges, modified: f.modified })),
  }
})
const theme = computed<'light' | 'dark'>(() =>
  document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark')

/** 播放层错误不再静默(空画布无解释)：构建失败上屏。 */
function onStoryError(e: { message: string }) {
  error.value = error.value ? error.value : `${t('archChange.evolutionFail')}: ${e.message}`
}

/** 画布自检(DOM 侧对账)：单 svg 常驻形态下 svg=1、画布尺寸即可判渲染健康。 */
const diag = ref('')
let diagTimer: ReturnType<typeof setInterval> | null = null
function runDiag() {
  const canvas = rootRef.value?.querySelector('.topo-story__canvas')
  if (!canvas) { diag.value = ''; return }
  const svgs = canvas.querySelectorAll('svg')
  const r = svgs[0]?.getBoundingClientRect()
  diag.value = [
    `svg=${svgs.length}`,
    svgs[0] && r ? `scene=${Math.round(r.width)}x${Math.round(r.height)}` : 'scene=无',
    `canvas=${Math.round(canvas.getBoundingClientRect().width)}x${Math.round(canvas.getBoundingClientRect().height)}`,
  ].join(' · ')
}
function toggleFullscreen() {
  const el = rootRef.value
  if (!el) return
  if (document.fullscreenElement) void document.exitFullscreen()
  else void el.requestFullscreen?.()
  // 兜底: headless/部分浏览器 fullscreenchange 时序不定 → 主动触发 resize 让 TopoStory refit
  setTimeout(() => window.dispatchEvent(new Event('resize')), 350)
}

onMounted(() => {
  diagTimer = setInterval(runDiag, 3000)
})
onUnmounted(() => { if (diagTimer) clearInterval(diagTimer) })
</script>

<template>
  <div ref="rootRef" class="panel overflow-hidden">
    <div class="panel-header">
      <span class="flex items-center gap-2 text-xs text-ctp-subtext0">
        <span class="w-2 h-2 rounded-full bg-ctp-teal" />{{ t('archChange.evolution') }}
      </span>
      <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ data?.frames?.length ?? 0 }}</span>
      <span class="text-[10px] text-ctp-overlay0">{{ t('archChange.evoScopeNote') }}</span>
      <span class="flex-1" />
      <button
        class="btn btn-ghost !px-1.5 !py-0.5 !text-[10px]"
        :title="t('archChange.evoFullscreen')"
        @click="toggleFullscreen"
      ><ArrowsPointingOutIcon class="w-3.5 h-3.5" /></button>
    </div>

    <!-- ref 对选择: baseline/version/branch/commit 前缀/HEAD -->
    <div class="flex items-center gap-2 px-4 pb-3 text-[11px]">
      <span class="text-ctp-overlay1 shrink-0">{{ t('archChange.evoFrom') }}</span>
      <input
        v-model="baseRef"
        class="input !py-1 !px-2 !text-[11px] w-44 font-mono"
        :placeholder="t('archChange.evoRefHint')"
        @keyup.enter="load"
      />
      <span class="text-ctp-overlay1 shrink-0">{{ t('archChange.evoTo') }}</span>
      <input
        v-model="headRef"
        class="input !py-1 !px-2 !text-[11px] w-44 font-mono"
        :placeholder="t('archChange.evoRefHint')"
        @keyup.enter="load"
      />
      <div class="flex rounded-lg bg-ctp-crust/60 p-0.5">
        <button
          v-for="ly in ([['component', 'archChange.evoLayerComponent'], ['file', 'archChange.evoLayerFile']] as const)"
          :key="ly[0]"
          class="px-2.5 py-1 rounded-md text-[11px] transition-colors"
          :class="layer === ly[0] ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
          @click="layer = ly[0]; load()"
        >{{ t(ly[1]) }}</button>
      </div>
      <button class="btn btn-primary !py-1 !px-3 !text-[11px]" :disabled="loading" @click="load">
        <ArrowPathIcon v-if="loading" class="w-3 h-3 animate-spin" />
        <PlayIcon v-else class="w-3 h-3" />
        {{ loading ? t('archChange.evoWorking') : t('archChange.evoGenerate') }}
      </button>
      <span class="text-ctp-overlay0">{{ t('archChange.evoRefHint') }}</span>
    </div>

    <div v-if="error" class="px-4 pb-3 text-[11px] text-ctp-peach">{{ error }}</div>
    <div v-if="diag" class="px-4 pb-2 font-mono text-[10px] text-ctp-overlay0">{{ diag }}</div>
    <TopoStory
      v-if="!error && graphData && graphData.frames.length >= 2"
      :graph="graphData"
      direction="LR"
      :auto-play="true"
      :step-ms="1600"
      @error="onStoryError"
    />
    <div v-else-if="!error" class="px-4 py-8 text-center text-[11px] text-ctp-overlay1">
      {{ t('archChange.evolutionNeedTwo') }}
    </div>
  </div>
</template>

<style scoped>
:fullscreen {
  background: var(--ctp-base, #1e1e2e);
  padding: 16px;
  overflow: auto;
}
:fullscreen .topo-story__canvas {
  height: calc(100vh - 140px);
}
</style>
