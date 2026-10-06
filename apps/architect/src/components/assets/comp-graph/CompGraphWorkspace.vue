<script setup lang="ts">
/**
 * 组件图谱工作区(资产地图第四 tab)：组件级全局图 → 下钻文件级结构图。
 * - 组件图: catalog 组件节点+dependsOn 边+变更徽标(对比选择器口径);
 *   点击节点出组件卡, 卡上「进入组件」下钻。
 * - 文件图: 左侧组件树多选(默认=下钻组件, 可追加范围) + imports 结构边;
 *   点击文件节点出文件卡(全文件+行级 diff+行级 AI 解读)。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowUturnLeftIcon, CubeTransparentIcon, DocumentTextIcon, FolderIcon } from '@heroicons/vue/24/outline'
import TopoDiagram from '@topo/graph-kernel/vue/TopoDiagram.vue'
import type { NodeClickEvent } from '@topo/graph-kernel/plugins/types.ts'
import type { AssetCompareResult } from '@/services/semantic-asset-service'
import {
  semanticAssetService,
  type CompGraphData, type FileGraphData,
  type CompGraphNode, type FileGraphNode,
} from '@/services/semantic-asset-service'
import { compGraphMermaid, fileGraphMermaid } from './mermaid'
import CompTreePicker from './CompTreePicker.vue'
import CompCard from './CompCard.vue'
import FileNodeCard from './FileNodeCard.vue'

const props = defineProps<{
  /** 对比选择器口径(与资产 diff 全局联动); 空态=基线→工作区。 */
  compareData?: AssetCompareResult | null
}>()

const { t } = useI18n()

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

const compMermaid = computed(() => compGraphMermaid(compData.value?.nodes ?? [], compData.value?.edges ?? []))
const fileMermaid = computed(() => fileGraphMermaid(fileData.value?.nodes ?? [], fileData.value?.edges ?? []))

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
  <div class="flex-1 min-h-0 flex">
    <!-- 文件模式: 左侧范围树 -->
    <div v-if="mode === 'file'" class="w-60 shrink-0 border-r border-ctp-surface0 bg-ctp-mantle/60">
      <CompTreePicker v-model="scopeIds" :nodes="compData?.nodes ?? []" />
    </div>

    <div class="flex-1 min-w-0 flex flex-col">
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
        <span v-if="compareData?.base" class="text-[9px] font-mono text-ctp-overlay0 truncate"
          :title="`${base.slice(0, 10)} → ${target === 'worktree' ? t('assetMgmt.diff.worktree') : target.slice(0, 10)}`">
          {{ base.slice(0, 7) }}→{{ target === 'worktree' ? '⌂' : target.slice(0, 7) }}
        </span>
        <span class="flex-1" />
        <span v-if="compData?.noChanges" class="text-[9px] text-ctp-overlay0">{{ t('compGraph.noChanges') }}</span>
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
        <TopoDiagram
          v-else
          class="absolute inset-0"
          :code="mode === 'comp' ? compMermaid.code : fileMermaid.code"
          engine="mermaid"
          theme="dark"
          :zoom-fit-min-scale="0.25"
          :zoom-max-scale="8"
          @node-click="onNodeClick"
        />
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
