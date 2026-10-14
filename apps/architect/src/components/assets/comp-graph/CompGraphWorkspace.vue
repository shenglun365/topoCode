<script setup lang="ts">
/**
 * 组件图谱工作区(资产地图第四 tab)：组件级全局图 → 下钻文件级结构图。
 * - 组件图: catalog 组件节点+dependsOn 边+变更徽标(对比选择器口径);
 *   点击节点出组件卡, 卡上「进入组件」下钻。
 * - 文件图: 左侧组件树多选(默认=下钻组件, 可追加范围) + imports 结构边;
 *   点击文件节点出文件卡(全文件+行级 diff+行级 AI 解读)。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUturnLeftIcon, CubeTransparentIcon, DocumentTextIcon, FolderIcon, FunnelIcon } from '@heroicons/vue/24/outline'
import TopoDiagram from '@topo/graph-kernel/vue/TopoDiagram.vue'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'
import type { NodeClickEvent } from '@topo/graph-kernel/plugins/types.ts'
import type { AssetCompareResult } from '@/services/semantic-asset-service'
import {
  semanticAssetService,
  type CompGraphData, type FileGraphData,
} from '@/services/semantic-asset-service'
import { compGraphMermaid, fileGraphMermaid } from './mermaid'
import { useCoreRules } from '@/pages/asset-workspace/useCoreRules'
import { applyCoreHighlight, coreNodeMatcher } from '../coreMarks'
import CompTreePicker from './CompTreePicker.vue'
import CompCard from './CompCard.vue'
import FileNodeCard from './FileNodeCard.vue'

const props = defineProps<{
  /** 对比选择器口径(与资产 diff 全局联动); 空态=基线→工作区。 */
  compareData?: AssetCompareResult | null
}>()

const { t } = useI18n()

const themeMode = computed<'dark' | 'light'>(() =>
  (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'light') ? 'light' : 'dark')
const themeVars = computed(() => themeVariablesFor(themeMode.value))

// ---- 2610 核心资产守护: 标记域 + 仅核心过滤 + svg 高亮(comp/file 层标记) ----
const coreRules = useCoreRules()
onMounted(() => { void coreRules.refresh() })
const coreOnly = ref(false)
const coreMatcher = computed(() => coreRules.coreMatcher.value)
const coreCompCount = computed(() =>
  (compData.value?.nodes ?? []).filter((n) => coreMatcher.value(n.id)).length)
const coreFileCount = computed(() =>
  (fileData.value?.nodes ?? []).filter((n) => coreMatcher.value(n.id)).length)
/** 仅核心节点集(数据级过滤, 焦点下钻组件豁免——下钻图不留空)。 */
const compNodesCore = computed(() => {
  const ns = compData.value?.nodes ?? []
  if (!coreOnly.value) return ns
  const hit = ns.filter((n) => coreMatcher.value(n.id))
  return hit.length ? hit : ns
})
const compEdgesCore = computed(() => {
  if (!coreOnly.value) return compData.value?.edges ?? []
  const ids = new Set(compNodesCore.value.map((n) => n.id))
  return (compData.value?.edges ?? []).filter((e) => ids.has(e.from) && ids.has(e.to))
})
const fileNodesCore = computed(() => {
  const ns = fileData.value?.nodes ?? []
  if (!coreOnly.value) return ns
  const hit = ns.filter((n) => coreMatcher.value(n.id))
  return hit.length ? hit : ns
})
const fileEdgesCore = computed(() => {
  if (!coreOnly.value) return fileData.value?.edges ?? []
  const ids = new Set(fileNodesCore.value.map((n) => n.id))
  return (fileData.value?.edges ?? []).filter((e) => ids.has(e.from) && ids.has(e.to))
})

const compMermaid = computed(() => compGraphMermaid(compNodesCore.value, compEdgesCore.value))
const fileMermaid = computed(() => fileGraphMermaid(fileNodesCore.value, fileEdgesCore.value))
/** 范围选择浮层(文件模式, header 下拉)。 */
const scopeOpen = ref(false)

type Mode = 'comp' | 'file'
const mode = ref<Mode>('comp')
const compData = ref<CompGraphData | null>(null)
const fileData = ref<FileGraphData | null>(null)
const loading = ref(false)
const error = ref('')
/** 文件模式范围(默认=下钻组件, 树上可追加)。 */
const scopeIds = ref<string[]>([])
const selComp = ref('')
const selFile = ref('')
const compIdMap = ref<Record<string, string>>({})
const fileIdMap = ref<Record<string, string>>({})

const base = computed(() => props.compareData?.base || '')
const target = computed(() => props.compareData?.target || 'worktree')

/** 组件变更文件清单(展开 changedFiles; 组件级接口直接携带)。 */
const changedFilesBy = computed<Record<string, Record<string, string[]>>>(() => {
  const out: Record<string, Record<string, string[]>> = {}
  for (const n of compData.value?.nodes ?? []) out[n.id] = n.changedFiles || {}
  return out
})


const statsText = computed(() => {
  if (mode.value === 'comp') {
    const n = compData.value?.nodes.length ?? 0
    const e = compData.value?.edges.length ?? 0
    return t('compGraph.statsComp', { n, e })
  }
  const n = fileData.value?.nodes.length ?? 0
  const e = fileData.value?.edges.length ?? 0
  return t('compGraph.statsFile', { n, e })
})

async function loadComp() {
  loading.value = true
  error.value = ''
  try {
    compData.value = (await semanticAssetService.compGraph(base.value, target.value)) ?? null
    compIdMap.value = compMermaid.value.idMap
  } catch (e: any) {
    error.value = e?.message || 'failed'
  } finally {
    loading.value = false
  }
}

async function loadFile() {
  loading.value = true
  error.value = ''
  try {
    fileData.value = (await semanticAssetService.fileGraph(scopeIds.value, base.value, target.value)) ?? null
    fileIdMap.value = fileMermaid.value.idMap
  } catch (e: any) {
    error.value = e?.message || 'failed'
  } finally {
    loading.value = false
  }
}

/** 2610 核心资产守护: svg 后处理——comp/file 层标记命中节点黄描边+★(幂等)。
 *  idMap 反查(mermaid 净化 id → 节点 id); mermaid 异步渲染, nextTick + 400ms 兜底。 */
function applyCorePass() {
  const run = () => {
    const svg = document.querySelector('.topo-diagram svg') as SVGSVGElement | null
    const matcher = coreMatcher.value
    if (!svg || !matcher) return
    const idMap = mode.value === 'comp' ? compMermaid.value.idMap : fileMermaid.value.idMap
    const rev = new Map<string, string>()
    for (const [mk, nid] of Object.entries(idMap)) { if (!rev.has(nid)) rev.set(nid, mk) }
    applyCoreHighlight(svg, (g) => {
      const mid = g.id.match(/flowchart-(.+?)-\d+$/)?.[1] ?? g.id
      const txt = (g.textContent ?? '').trim()
      const key = mid in idMap ? mid : (rev.get(txt) ?? '')
      return key ? (idMap[key] ?? '') : ''
    }, matcher)
  }
  void nextTick(run)
  setTimeout(run, 400)
}
watch([compMermaid, fileMermaid, coreMatcher, mode], () => applyCorePass())

/** 渲染完成后扫描 DOM: 实际节点 class 与背景色(对照生成侧 class 附着)。 */
function scanRenderedNodes(tag: string) {
  void nextTick(() => setTimeout(() => {
    const nodes = [...document.querySelectorAll('.topo-diagram svg g.node')]
    const rows = nodes.slice(0, 12).map((n) => ({
      cls: (n.getAttribute('class') || '').replace('node ', ''),
      fill: (n.querySelector('rect, path, polygon') as SVGElement | null)
        ?.getAttribute('style')?.match(/fill:([^;]+)/)?.[1]?.trim() ?? '',
    }))
    const dist: Record<string, number> = {}
    for (const r of rows) dist[r.cls + '→' + r.fill] = (dist[r.cls + '→' + r.fill] || 0) + 1
  }, 300))
}

function onNodeClick(ev: NodeClickEvent) {
  const id = String((ev as { id?: string; nodeId?: string }).id
    ?? (ev as { nodeId?: string }).nodeId ?? '')
  if (mode.value === 'comp') {
    const real = compIdMap.value[id]
    if (real) selComp.value = selComp.value === real ? '' : real
  } else {
    const real = fileIdMap.value[id]
    if (real) selFile.value = selFile.value === real ? '' : real
  }
}

function enterFile(id: string) {
  selComp.value = ''
  scopeIds.value = [id]
  mode.value = 'file'
}

function backToComp() {
  mode.value = 'comp'
  selFile.value = ''
  fileData.value = null
}

watch(scopeIds, () => { if (mode.value === 'file') void loadFile() })
watch(() => props.compareData, () => {
  // 对比选择器变化 → 图谱口径联动重算
  if (mode.value === 'comp') void loadComp()
  else void loadFile()
})

onMounted(loadComp)

const selCompNode = computed(() => compData.value?.nodes.find((n) => n.id === selComp.value) ?? null)
const selFileNode = computed(() => fileData.value?.nodes.find((n) => n.id === selFile.value) ?? null)
const fileImportsIn = computed(() =>
  (fileData.value?.edges ?? []).filter((e) => e.to === selFile.value).map((e) => e.from))
const fileImportsOut = computed(() =>
  (fileData.value?.edges ?? []).filter((e) => e.from === selFile.value).map((e) => e.to))
const fileChangedAssets = computed(() =>
  (fileData.value?.changedAssets?.[selFile.value] ?? []) as never as {
    id: string; name: string; kind: string; strong: boolean; side: string
  }[])
const scopeNames = computed(() =>
  scopeIds.value.map((id) =>
    fileData.value?.components.find((c) => c.id === id)?.name
    ?? compData.value?.nodes.find((n) => n.id === id)?.name ?? id).join(', '))
</script>

<template>
  <div class="flex-1 min-h-0 flex flex-col">
    <div class="flex-1 min-w-0 flex flex-col min-h-0">
      <!-- 顶栏: 标题/面包屑 + 统计 + 返回 -->
      <div class="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-ctp-surface0 text-xs">
        <CubeTransparentIcon v-if="mode === 'comp'" class="w-4 h-4 text-ctp-mauve shrink-0" />
        <FolderIcon v-else class="w-4 h-4 text-ctp-sapphire shrink-0" />
        <template v-if="mode === 'comp'">
          <span class="text-ctp-text font-medium">{{ t('compGraph.title') }}</span>
        </template>
        <template v-else>
          <button class="text-ctp-sky hover:underline flex items-center gap-1" @click="backToComp">
            <ArrowUturnLeftIcon class="w-3.5 h-3.5" />{{ t('compGraph.title') }}
          </button>
          <span class="text-ctp-overlay0">/</span>
          <span class="text-ctp-text truncate max-w-[18rem]" :title="scopeNames">{{ scopeNames }}</span>
        </template>
        <span class="text-[10px] text-ctp-overlay0">{{ statsText }}</span>
        <label
          class="inline-flex cursor-pointer items-center gap-1 text-[10px]"
          :class="coreOnly ? 'text-ctp-yellow' : 'text-ctp-overlay0'"
          :title="t('assetMgmt.graph.coreOnlyHint')"
        >
          <input v-model="coreOnly" type="checkbox" class="accent-ctp-yellow">
          <span class="text-ctp-yellow">★</span>{{ t('assetMgmt.graph.coreOnly') }}
          <span
            v-if="(mode === 'comp' ? coreCompCount : coreFileCount)"
            class="chip bg-ctp-yellow/15 text-ctp-yellow !text-[9px] font-mono"
          >{{ mode === 'comp' ? coreCompCount : coreFileCount }}</span>
        </label>
        <span v-if="compareData?.base" class="text-[9px] font-mono text-ctp-overlay0 truncate"
          :title="`${base.slice(0, 10)} → ${target === 'worktree' ? t('assetMgmt.diff.worktree') : target.slice(0, 10)}`">
          {{ base.slice(0, 7) }}→{{ target === 'worktree' ? '⌂' : target.slice(0, 7) }}
        </span>
        <span class="flex-1" />
        <span v-if="mode === 'file'" class="relative shrink-0">
          <button
            class="btn !py-0.5 !px-2 !text-[10px]"
            :class="scopeOpen ? 'btn-blue' : 'btn-ghost'"
            @click="scopeOpen = !scopeOpen"
          >
            <FunnelIcon class="w-3 h-3" />{{ t('compGraph.scopeBtn') }}
            <span class="chip bg-ctp-mauve/15 text-ctp-mauve !text-[9px]">{{ scopeIds.length }}</span>
          </button>
          <div
            v-if="scopeOpen"
            class="absolute right-0 top-7 z-30 w-72 h-80 flex flex-col rounded-lg border border-ctp-surface1 bg-ctp-base shadow-xl"
          >
            <CompTreePicker v-model="scopeIds" :nodes="compData?.nodes ?? []" />
          </div>
          <div v-if="scopeOpen" class="fixed inset-0 z-20" @click="scopeOpen = false" />
        </span>
        <span v-if="fileData?.truncated" class="text-[9px] text-ctp-peach">
          {{ t('compGraph.truncated', { total: fileData.totalFiles ?? fileData.nodes.length, max: fileData.maxFileNodes ?? 200 }) }}
        </span>
        <span v-else-if="compData?.noChanges" class="text-[9px] text-ctp-overlay0">{{ t('compGraph.noChanges') }}</span>
      </div>

      <!-- 画布 -->
      <div class="flex-1 min-h-0 relative">
        <div v-if="loading" class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0 animate-pulse">
          {{ t('app.loading') }}
        </div>
        <div v-else-if="error" class="absolute inset-0 flex items-center justify-center text-xs text-ctp-peach px-6 text-center">
          {{ error }}
        </div>
        <div v-else-if="mode === 'comp' && !(compData?.nodes.length)"
          class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0">
          {{ t('compGraph.empty') }}
        </div>
        <div v-else class="h-full relative">
          <TopoDiagram
            class="h-full"
            :code="mode === 'comp' ? compMermaid.code : fileMermaid.code"
            engine="mermaid"
            :theme="themeMode"
            :theme-variables="themeVars"
            security-level="loose"
            :zoom-fit-min-scale="0.3"
            :zoom-max-scale="24"
            @node-click="onNodeClick"
            @ready="() => scanRenderedNodes(mode === 'comp' ? 'comp' : 'file')"
          />
        </div>
        <p class="absolute left-2 bottom-2 text-[9px] text-ctp-overlay0 pointer-events-none">
          {{ t('compGraph.legend') }}
          <span class="text-ctp-green">■</span>{{ t('compGraph.legendAdded') }}
          <span class="text-ctp-blue ml-1">■</span>{{ t('compGraph.legendModified') }}
          <span class="text-ctp-red ml-1">■</span>{{ t('compGraph.legendDeleted') }}
        </p>
      </div>
    </div>

    <!-- 组件资产卡 -->
    <CompCard
      v-if="mode === 'comp' && selCompNode"
      :key="selCompNode.id"
      :node="selCompNode"
      :changed-files="changedFilesBy[selCompNode.id] || {}"
      :all-nodes="compData?.nodes ?? []"
      @close="selComp = ''"
      @enter="enterFile"
      @locate="(id: string) => { selComp = id }"
    />
    <!-- 文件资产卡 -->
    <FileNodeCard
      v-if="mode === 'file' && selFileNode"
      :key="selFileNode.id"
      :node="selFileNode"
      :compare-base="base"
      :compare-target="target"
      :imports-in="fileImportsIn"
      :imports-out="fileImportsOut"
      :changed-assets="fileChangedAssets"
      @close="selFile = ''"
      @locate-file="(p: string) => { selFile = p }"
    />
  </div>
</template>
