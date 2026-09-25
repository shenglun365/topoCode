<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { kindChipClass as kindChipCls, KIND_CARD_CLASS } from '@/services/semantic-kind-style'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, XMarkIcon, ArrowsPointingOutIcon, MinusIcon, InformationCircleIcon, SparklesIcon, DocumentTextIcon, ViewfinderCircleIcon, ClipboardIcon, ChevronDownIcon, CheckIcon, PlusCircleIcon, TableCellsIcon, AdjustmentsHorizontalIcon, ListBulletIcon, LockClosedIcon, LockOpenIcon, FunnelIcon, FolderOpenIcon } from '@heroicons/vue/24/outline'
import GraphMatrixWindow from './GraphMatrixWindow.vue'
import AssetIndexWindow from './AssetIndexWindow.vue'
import FileIndexWindow from './FileIndexWindow.vue'
import TopoDiagram from '@topo/graph-kernel/vue/TopoDiagram.vue'
import { makeButton } from '@topo/graph-kernel/plugins/ui.ts'
import type { NodeClickEvent } from '@topo/graph-kernel/plugins/types.ts'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'
import { semanticGraphViewDiagrams, semanticViewClickIds, recommendedSemanticView, semanticNodeLabelText, supportedViewsFor, viewUnavailableReasons } from '@/utils/diagram-gen'
import { useArchSettingsStore } from '@/stores/settings-store'
import type { SemanticGraphViewId } from '@/utils/diagram-gen'
import type { SemanticAsset, SemanticAssetLevel, SemanticAssetKind, GraphFileEntry } from '@/types'
import type { SemanticGraphResult, SourceSnippet } from '@/services/semantic-asset-service'
import { semanticAssetService, type AssetCompareResult } from '@/services/semantic-asset-service'
import { copyText } from '@/utils/clipboard'

const { t } = useI18n()
import { useGraphData } from './graph-view/useGraphData'
import { useGraphDetail } from './graph-view/useGraphDetail'
import { useGraphCode } from './graph-view/useGraphCode'
import { useGraphRender } from './graph-view/useGraphRender'
import type { WsDeps } from './graph-view/graphTypes'

/** 图谱资源 tab 定义(由外部资产列表/组件列表打开)。 */
export interface GraphTabDef {
  id: string
  kind: 'all' | 'comp' | 'asset' | 'file'
  title: string
  compId?: string
  assetId?: string
  /** kind='file'：锚定该文件的资产子图。 */
  fileId?: string
}

const props = defineProps<{
  tab: GraphTabDef
  diffFiles?: Set<string>
  compareData?: AssetCompareResult | null
  /** 当前 tab 范围的文件索引(all/comp tab 由父级预算)；>500 资产时启用手动圈定。 */
  fileIndex?: GraphFileEntry[]
  /** 组件 id → 名称(文件索引分组展示)。 */
  compNames?: Record<string, string>
}>()
const emit = defineEmits<{ close: [id: string] }>()

/** 图谱规模闸门：范围资产超此值不自动渲染，须经文件索引手动圈定(≤预算)。 */

// ---- MS6-W2: 逻辑层四域(graph-view/)——本文件保留 props/emit/模板/样式 ----
const D: WsDeps = { props, emit, settings: useArchSettingsStore() }
D.data = useGraphData(D)
D.detail = useGraphDetail(D)
D.code = useGraphCode(D)
D.render = useGraphRender(D)
const {
  CARD_MIN_KEY,
  CARD_SIZE_KEY,
  DIFF_FILL,
  DIFF_STROKE,
  EDGE_TYPE_COLOR,
  EDGE_TYPE_TEXT,
  FILE_BUDGET,
  FOCUS_LOCK_KEY,
  FONT_STEPS,
  FULL_FILE_LIMIT,
  KIND_BG,
  KIND_CHIP,
  KIND_TEXT,
  LEGEND_W,
  MAX_SEGMENTS,
  SEG_SNIPPET_LIMIT,
  activeFileTab,
  activeRelTab,
  activeTabSegs,
  anchorFiles,
  animating,
  applyDiffNodeStyles,
  applyFileScope,
  applyNodeTooltips,
  applySelectedNodeStyle,
  availableLevels,
  beginCardDrag,
  cardDrag,
  cardDragging,
  cardEl,
  cardEndDrag,
  cardFullscreen,
  cardLang,
  cardMin,
  cardPos,
  cardResetPos,
  cardResizing,
  cardSize,
  cardSizeInit,
  cardSrcOpen,
  cardStartPos,
  cardStartResize,
  cardStartX,
  cardStartY,
  centerSelectedNode,
  clearSel,
  clickIds,
  closeCardFullscreen,
  codeFontSize,
  collapsedSegs,
  copiedSeg,
  copySegLoc,
  detailBlock,
  diagRef,
  diagramLangs,
  diagrams,
  diffBucketCounts,
  diffKindById,
  diffNodeCount,
  diffNodeIds,
  diffOnly,
  edgeLegendOpen,
  edgeNotesLoading,
  edgeNotesMap,
  edgeTypeColor,
  edgeTypeCounts,
  edgeTypeLabel,
  edgeTypeOff,
  effectiveLevel,
  effectiveView,
  enhancePoll,
  enhanceProgress,
  enhanceRunning,
  ensureRelTab,
  expandFeedback,
  expandFeedbackTimer,
  expandSelected,
  expandUnknown,
  expandable,
  expandedTabs,
  expanding,
  fileIndex,
  fileScopeKey,
  fileScopeOpen,
  fileScopeSel,
  fileTabs,
  flashAnchor,
  flashOnNext,
  flashSeg,
  flashTimer,
  flashing,
  focusHops,
  focusLock,
  focusMode,
  focusRelTab,
  fullCode,
  fullCodeError,
  fullCodeLoading,
  fullCodeNotes,
  fullCodeNotesLoading,
  fullCodeOwners,
  fullCodePreRef,
  fullCodeSelfLines,
  graph,
  hiddenViewHints,
  iconPulse,
  iconPulseTimer,
  inEdges,
  inEdgesLoading,
  includeIndirect,
  indexOpen,
  injectReplayBtn,
  isDiffNode,
  jumpToRelation,
  jumpToSegment,
  kindBgClass,
  kindChipClass,
  kindFilter,
  kindNodes,
  kindOptions,
  kindTextClass,
  lastShownView,
  legendBtnRef,
  legendPos,
  level,
  levelOptions,
  lineNotesCount,
  lineNotesDegraded,
  lineNotesError,
  lineNotesFromCache,
  lineNotesLoading,
  lineNotesMaps,
  load,
  loadCardSize,
  loadFullCodeFor,
  loadFullCodeNotes,
  loadLineNotes,
  loading,
  lockAnchor,
  matrixOpen,
  nearestMappedAsset,
  nodeBriefLoading,
  nodeBriefText,
  nodeTooltipText,
  nodeVisibleInViewport,
  onDiagramReady,
  onFullCodeLineClick,
  onLegendDocClick,
  onMatrixSelect,
  onNodeClick,
  openCardFullscreen,
  overLimit,
  ownerName,
  pendingExpand,
  prefetchExpand,
  rebuildSegments,
  regenerateLineNotes,
  regenerateNodeBrief,
  relTabEl,
  relTabLoading,
  relTabSegs,
  relTabs,
  replayGraph,
  replayTick,
  resetSegCollapse,
  resizeEdge,
  resizeStart,
  resolveNodeIdFromEl,
  saveCardSize,
  scopeAssets,
  scopeTotal,
  scopedEdges,
  scopedNodes,
  segEls,
  segHighlighted,
  segSeq,
  segments,
  sel,
  selAnchors,
  selDetail,
  selId,
  selRelations,
  selectedNodeEl,
  setCardLang,
  setCardMin,
  settings,
  shortPath,
  snippetOptsFor,
  softRefreshGraph,
  startEnhanceDesc,
  switchFileTab,
  tabClick,
  themeMode,
  themeVars,
  toggleCardSource,
  toggleEdgeLegend,
  toggleEdgeType,
  toggleFocusLock,
  toggleFullCode,
  toggleIndex,
  toggleMatrix,
  toggleSeg,
  triggerFlash,
  view,
  viewOptions,
  viewSel,
  visitedTabs,
  weakCount,
} = Object.assign({}, D.data, D.detail, D.code, D.render)

onMounted(async () => {
  await load()
})
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <!-- 工具栏(单行)：粒度 + 图类型 + 视图上下文(单资产焦点/关联级别) + 统计 + 操作 -->
    <div class="shrink-0 flex items-center gap-1 px-1 pt-1 pb-1 border-b border-ctp-surface0 overflow-x-auto">
      <select
        v-model="kindFilter"
        class="input !py-0.5 !px-2 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.kindHint')"
      >
        <option value="">{{ t('assetMgmt.graph.allKinds') }}</option>
        <option v-for="o in kindOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <select
        v-model="level"
        class="input !py-0.5 !px-2 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.levelHint')"
      >
        <option value="">{{ t('assetMgmt.graph.allLevels') }}</option>
        <option v-for="o in levelOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <div class="w-px h-4 bg-ctp-surface1 shrink-0" />
      <select
        v-model="viewSel"
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
        class="shrink-0 text-[11px] text-ctp-overlay1 cursor-help px-0.5"
        :title="hiddenViewHints.join('\n')"
      >ⓘ</span>
      <!-- 邻域聚焦：只渲染选中资产周围 N 跳子图(缓解大图拥挤/过宽/过长) -->
      <div class="w-px h-4 bg-ctp-surface1 shrink-0" />
      <button
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="focusMode ? 'btn-primary' : ''"
        :title="t('assetMgmt.graph.focusHint')"
        @click="focusMode = !focusMode"
      >
        <ViewfinderCircleIcon class="w-3.5 h-3.5" />
      </button>
      <select
        v-if="focusMode"
        v-model.number="focusHops"
        class="input !py-0.5 !px-1.5 !text-[11px] w-auto shrink-0"
        :title="t('assetMgmt.graph.focusHops')"
      >
        <option v-for="h in [1, 2, 3]" :key="h" :value="h">{{ h }} {{ t('assetMgmt.graph.hop') }}</option>
      </select>
      <!-- 范围锁定：锁定时切换选中节点不跟随刷新关系视角；解锁恢复漫游 -->
      <button
        v-if="focusMode"
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="focusLock ? 'btn-primary' : ''"
        :title="focusLock ? t('assetMgmt.graph.focusLockOn') : t('assetMgmt.graph.focusLockHint')"
        @click="toggleFocusLock"
      >
        <LockClosedIcon v-if="focusLock" class="w-3.5 h-3.5" />
        <LockOpenIcon v-else class="w-3.5 h-3.5" />
      </button>
      <!-- 拓展关联：基于选中节点扩展 1 跳关联(增量合并，可累积)；无未拓展关联时置灰 -->
      <button
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="expandable ? '' : 'opacity-50 cursor-not-allowed'"
        :disabled="!expandable || expanding"
        :title="expandable ? t('assetMgmt.graph.expandHint') : t('assetMgmt.graph.expandDisabledHint')"
        @click="expandSelected"
      >
        <PlusCircleIcon class="w-3.5 h-3.5" />
      </button>
      <span
        v-if="expandFeedback"
        class="shrink-0 text-[10px] text-ctp-teal font-medium cursor-default"
      >{{ expandFeedback }}</span>
      <!-- 关系矩阵浮窗：文件×文件密度 + 节点级非对称全矩阵，数据跟随当前图谱口径 -->
      <button
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="matrixOpen ? 'btn-primary' : ''"
        :title="t('assetMgmt.matrix.title')"
        @click="toggleMatrix"
      >
        <TableCellsIcon class="w-3.5 h-3.5" />
      </button>
      <button
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="indexOpen ? 'btn-primary' : ''"
        :title="t('assetMgmt.index.title')"
        @click="toggleIndex"
      >
        <ListBulletIcon class="w-3.5 h-3.5" />
      </button>
      <!-- 文件范围索引(仅超限 tab)：圈定 ≤500 资产的文件集合后重查图谱 -->
      <button
        v-if="overLimit"
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="fileScopeOpen || fileScopeSel.length ? 'btn-primary' : ''"
        :title="fileScopeSel.length
          ? t('assetMgmt.fileIndex.titleActive', { files: fileScopeSel.length, n: scopeAssets })
          : t('assetMgmt.fileIndex.pickTitle')"
        @click="fileScopeOpen = !fileScopeOpen"
      >
        <FolderOpenIcon class="w-3.5 h-3.5" />
      </button>
      <!-- 边类型图例 + 显隐过滤；间接边开关(浮层 Teleport 到 body，不撑开工具栏) -->
      <button
        ref="legendBtnRef"
        class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center"
        :class="edgeTypeOff.size ? 'btn-primary' : ''"
        :title="t('assetMgmt.graph.edgeLegend')"
        @click="toggleEdgeLegend"
      >
        <AdjustmentsHorizontalIcon class="w-3.5 h-3.5" />
      </button>
      <Teleport to="body">
        <div
          v-if="edgeLegendOpen"
          data-edge-legend
          class="fixed z-50 w-44 rounded-lg border border-ctp-surface1 bg-ctp-mantle shadow-lg p-2 space-y-0.5"
          :style="{ top: legendPos.top + 'px', left: legendPos.left + 'px' }"
        >
          <label
            v-for="[k, n] in edgeTypeCounts"
            :key="k"
            class="flex items-center gap-1.5 px-1 py-0.5 rounded cursor-pointer hover:bg-ctp-surface0 text-[11px]"
          >
            <input
              type="checkbox"
              class="accent-ctp-mauve"
              :checked="!edgeTypeOff.has(k)"
              @change="toggleEdgeType(k)"
            >
            <span :class="edgeTypeColor(k)">{{ edgeTypeLabel(k) }}</span>
            <span class="ml-auto text-ctp-overlay0">{{ n }}</span>
          </label>
          <label class="flex items-center gap-1.5 px-1 py-0.5 rounded cursor-pointer hover:bg-ctp-surface0 text-[11px] border-t border-ctp-surface0 mt-1 pt-1.5">
            <input
              v-model="includeIndirect"
              type="checkbox"
              class="accent-ctp-teal"
            >
            <span class="text-ctp-subtext0">{{ t('assetMgmt.graph.indirectEdges') }}</span>
          </label>
        </div>
      </Teleport>
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
      <!-- 对比变化图例 + 仅看变化(资产级口径来自 asset-compare；无对比数据时退化为文件级 diff 徽标) -->
      <template v-if="diffKindById.size">
        <button
          class="btn btn-ghost btn-xs shrink-0"
          :class="diffOnly ? 'btn-primary' : ''"
          :title="t('assetMgmt.graph.diffOnlyHint')"
          @click="diffOnly = !diffOnly"
        >
          <FunnelIcon class="w-3 h-3" />{{ t('assetMgmt.graph.diffOnly') }}
        </button>
        <span class="chip bg-ctp-yellow/15 text-ctp-yellow font-mono text-[9px] shrink-0" :title="t('assetMgmt.graph.legendChanged')">{{ t('assetMgmt.diff.changedN', { n: diffBucketCounts.changed }) }}</span>
        <span class="chip bg-ctp-green/15 text-ctp-green font-mono text-[9px] shrink-0" :title="t('assetMgmt.graph.legendNew')">{{ t('assetMgmt.diff.newN', { n: diffBucketCounts.new }) }}</span>
        <span v-if="diffBucketCounts.removed" class="chip bg-ctp-red/15 text-ctp-red font-mono text-[9px] shrink-0" :title="t('assetMgmt.graph.legendRemoved')">{{ t('assetMgmt.diff.removedN', { n: diffBucketCounts.removed }) }}</span>
        <span v-if="weakCount" class="chip bg-ctp-surface0 text-ctp-overlay1 font-mono text-[9px] shrink-0" :title="t('assetMgmt.graph.legendWeak')">{{ t('assetMgmt.diff.weakN', { n: weakCount }) }}</span>
      </template>
      <span
        v-if="graph && props.diffFiles && diffNodeCount"
        class="chip bg-ctp-yellow/15 text-ctp-yellow font-mono text-[9px] shrink-0"
        :title="t('assetMgmt.diff.hint')"
      >{{ diffNodeCount }} {{ t('assetMgmt.graph.nodes') }} · diff</span>
      <div
        v-if="graph"
        class="flex items-center gap-0.5 shrink-0"
      >
        <button
          v-for="l in diagramLangs"
          :key="l.id"
          class="px-1.5 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer"
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
        class="btn btn-xs"
        :class="enhanceRunning ? 'btn-primary' : 'btn-ghost'"
        :disabled="enhanceRunning || loading"
        :title="enhanceRunning
          ? t('assetMgmt.graph.enhanceRunning', { d: enhanceProgress.done, t: enhanceProgress.total })
          : t('assetMgmt.graph.enhanceDesc')"
        @click="startEnhanceDesc"
      >
        <SparklesIcon
          class="w-3 h-3"
          :class="enhanceRunning ? 'animate-spin' : ''"
        />{{ enhanceRunning ? `${enhanceProgress.done}/${enhanceProgress.total}` : '' }}
      </button>
      <button
        class="btn btn-xs btn-ghost"
        :disabled="loading"
        :title="t('assetMgmt.graph.reload')"
        @click="load()"
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
      <!-- 规模闸门：范围超限且未圈定文件 → 引导打开文件索引 -->
      <div
        v-else-if="overLimit && !fileScopeSel.length"
        class="absolute inset-0 flex flex-col items-center justify-center gap-2.5 text-xs text-ctp-overlay0 px-6"
      >
        <FolderOpenIcon class="w-8 h-8 text-ctp-overlay0/60" />
        <p class="max-w-sm text-center leading-relaxed">
          {{ t('assetMgmt.fileIndex.overHint', { total: scopeTotal, budget: FILE_BUDGET }) }}
        </p>
        <button class="btn btn-primary btn-xs shrink-0" @click="fileScopeOpen = true">
          {{ t('assetMgmt.fileIndex.pickTitle') }}
        </button>
      </div>
      <div
        v-else-if="!graph || !scopedNodes.length"
        class="absolute inset-0 flex items-center justify-center text-xs text-ctp-overlay0"
      >
        {{ props.tab.kind === 'asset'
          ? t('assetMgmt.graph.emptyAsset')
          : props.tab.kind === 'file' ? t('assetMgmt.graph.emptyFile') : t('assetMgmt.graph.empty') }}
      </div>

      <div
        v-else
        class="h-full relative"
        :class="cardFullscreen ? 'fixed inset-0 z-20 bg-ctp-mantle p-2' : ''"
      >
        <pre
          v-if="cardSrcOpen"
          class="h-full m-0 overflow-auto rounded-lg bg-ctp-mantle border border-ctp-surface1 p-3 font-mono text-[11px] leading-relaxed whitespace-pre text-ctp-subtext0"
        >{{ diagrams[cardLang] }}</pre>
        <TopoDiagram
          v-else
          ref="diagRef"
          class="h-full"
          :key="`${cardFullscreen ? 'fs' : 'inline'}-${replayTick}`"
          :code="diagrams[cardLang]"
          :engine="cardLang"
          :theme="themeMode"
          :theme-variables="themeVars"
          security-level="loose"
          :zoom-fit-min-scale="0.3"
          :zoom-max-scale="24"
          :auto-play="animating"
          @ready="onDiagramReady"
          @node-click="onNodeClick"
        />
        <button
          v-if="cardFullscreen"
          class="btn btn-ghost btn-xs absolute top-2 right-2 z-10"
          :title="t('assetMgmt.graph.closeFullscreen')"
          @click="closeCardFullscreen"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>

      <!-- 选中节点详情：网页全局浮窗(可拖动/可拉伸/可最小化；最小化图标停靠图谱区右下) -->
      <div
        v-if="sel && !cardMin"
        ref="cardEl"
        class="card-root fixed z-40 flex flex-col max-w-[calc(100vw-1rem)] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
        :class="[
          !cardPos ? 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2' : '',
          cardDragging ? 'cursor-grabbing' : '',
          cardResizing ? 'select-none' : '',
        ]"
        :style="{
          width: cardSize.w + 'px',
          // 卡片非代码文字随全局 UI 字号等比(--card-scale = 全局字号/16，与 --ui-scale 同步缩放)，
          // 基准字号在 scoped .card-root 覆盖中已整体放大两号；代码(pre/code)仍用 codeFontSize。
          '--card-scale': String((Number(settings.fontSize) || 16) / 16),
          ...(cardSize.h ? { height: cardSize.h + 'px' } : {}),
          ...(cardPos ? { left: cardPos.x + 'px', top: cardPos.y + 'px' } : {}),
        }"
        :title="t('assetMgmt.graph.cardResetPos')"
      >
        <div
          class="flex items-center gap-1.5 cursor-move shrink-0 px-3 pt-2.5 pb-1"
          @mousedown="beginCardDrag"
          @dblclick="cardResetPos"
        >
          <span class="text-[11px] font-semibold text-ctp-text truncate">{{ sel.name }}</span>
          <span
            class="chip !text-[9px] shrink-0"
            :class="kindChipCls(sel.kind)"
           >{{ t(`assetMgmt.kind.${sel.kind}`) }}</span>
           <span
             v-if="isDiffNode(sel.id)"
             class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
             :title="t('assetMgmt.diff.hint')"
           >{{ t('assetMgmt.diff.modified') }}</span>
           <span class="flex-1" />
           <button
             class="btn btn-ghost !py-0 !px-1.5 !text-[9px] shrink-0"
             :class="fullCode ? '!text-ctp-sky' : ''"
            :disabled="fullCodeLoading"
            :title="t('assetMgmt.graph.fullCode')"
            @click="toggleFullCode"
          >
            <DocumentTextIcon
              class="w-3 h-3"
              :class="fullCodeLoading ? 'animate-pulse' : ''"
            />{{ t('assetMgmt.graph.fullCode') }}
          </button>
          <button
            class="btn btn-ghost !py-0 !px-1.5 !text-[9px] shrink-0"
            :class="lineNotesCount || fullCodeNotesLoading || lineNotesLoading ? '!text-ctp-mauve' : ''"
            :disabled="lineNotesLoading || fullCodeNotesLoading"
            :title="lineNotesError ? t('assetMgmt.graph.lineNotesFailed') : t('assetMgmt.graph.lineNotes')"
            @click="loadLineNotes()"
          >
            <SparklesIcon
              class="w-3 h-3"
              :class="(lineNotesLoading || fullCodeNotesLoading) ? 'animate-spin' : ''"
            />{{ lineNotesCount
              ? `${t('assetMgmt.graph.lineNotes')} · ${lineNotesCount}`
              : t('assetMgmt.graph.lineNotes') }}
          </button>
          <template v-if="lineNotesCount">
            <span
              v-if="lineNotesFromCache"
              class="chip !text-[8px] bg-ctp-surface0 text-ctp-subtext0 shrink-0"
              :title="t('assetMgmt.graph.lineNotesCachedTip')"
            >{{ t('assetMgmt.graph.lineNotesCached') }}</span>
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0"
              :disabled="lineNotesLoading || fullCodeNotesLoading"
              :title="t('assetMgmt.graph.lineNotesForce')"
              @click="regenerateLineNotes"
            >
              <ArrowPathIcon
                class="w-3 h-3"
                :class="(lineNotesLoading || fullCodeNotesLoading) ? 'animate-spin' : ''"
              />
            </button>
          </template>
          <button
            class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
            :title="t('assetMgmt.graph.minimize')"
            @click="setCardMin(true)"
          >
            <MinusIcon class="w-3.5 h-3.5" />
          </button>
        </div>
        <!-- 文件 tab(常驻)：固定标题栏下方，不随代码滚动；访问历史 + 关系资产文件 -->
        <div v-if="fileTabs.length" class="shrink-0 flex items-center gap-1 flex-wrap px-3 pt-0.5 pb-1">
          <button
            v-for="f in fileTabs"
            :key="f.kind + f.file"
            class="chip !text-[9px] font-mono max-w-[45%] truncate cursor-pointer"
            :class="activeFileTab === f.file
              ? (f.kind === 'rel' ? '!bg-ctp-peach/15 !text-ctp-peach' : '!bg-ctp-mauve/15 !text-ctp-mauve')
              : 'bg-ctp-surface0 !text-ctp-subtext0 hover:!text-ctp-text'"
            :title="f.kind === 'rel' && f.rel ? `${f.rel.targetName} · ${f.rel.relText} · ${f.file}` : `${f.assetName} · ${f.file}`"
            @click="tabClick(f)"
          >{{ f.label }}</button>
        </div>
        <div class="flex-1 min-h-0 overflow-auto px-3 pb-3 pt-1 space-y-2">
        <!-- 完整代码视图：单文件全文 + 文件内多资产锚点高亮(点击切资产，同文件不刷新卡) -->
        <template v-if="fullCode">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 flex items-center gap-1 truncate">
            {{ t('assetMgmt.graph.fullCode') }}
            <span
              class="text-ctp-overlay1 font-normal truncate"
              :title="fullCode.file"
            >{{ shortPath(fullCode.file) }}</span>
            <span class="flex-1" />
            <span
              v-if="fullCodeOwners.size"
              class="text-[9px] text-ctp-sky shrink-0"
              :title="t('assetMgmt.graph.fullCodeOwnersHint')"
            >{{ t('assetMgmt.graph.fullCodeOwners', { n: fullCodeOwners.size }) }}</span>
          </div>
          <pre
            v-if="fullCode.lines?.length"
            ref="fullCodePreRef"
            class="m-0 overflow-auto rounded border border-ctp-surface1 bg-ctp-surface0 p-2 font-mono leading-relaxed"
            :style="{ fontSize: codeFontSize + 'px' }"
          ><template
            v-for="(l, fli) in fullCode.lines"
            :key="`f:${fli}`"
><div
  :data-full-line="l.line"
  class="flex flex-wrap items-baseline gap-1.5"
  :class="[
    l.kind === 'add' ? 'bg-ctp-green/15 rounded-sm' : l.kind === 'del' ? 'bg-ctp-red/15 rounded-sm' : '',
    fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId ? 'cursor-pointer' : '',
  ]"
  :title="fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId
    ? `${ownerName(fullCodeOwners.get(l.line)!)} · ${t('assetMgmt.graph.fullCodeClickHint')}` : ''"
  @click="onFullCodeLineClick(l.line)"
><span class="select-none text-ctp-overlay0 shrink-0 w-12 text-right">{{ l.kind === 'del' ? `-${l.baseLine ?? l.line}` : `${l.kind === 'add' ? '+' : ''}${l.targetLine ?? l.line}` }}</span> <span
              :class="fullCodeOwners.has(l.line) && fullCodeOwners.get(l.line) !== selId
                ? ['text-ctp-sky', 'bg-ctp-sky/15', 'font-semibold rounded-sm px-0.5', 'hover:bg-ctp-sky/25']
                : fullCodeSelfLines.has(l.line)
                  ? [kindTextClass, kindBgClass, 'font-semibold rounded-sm px-0.5', flashing ? 'anchor-flash' : '']
                  : 'text-ctp-subtext0'"
            >{{ l.code }}</span><span
              v-if="fullCodeNotes[l.line]"
              class="ml-auto shrink-0 max-w-[48%] truncate text-right italic"
              :class="fullCodeSelfLines.has(l.line) ? kindTextClass : 'text-ctp-overlay1'"
              :title="fullCodeNotes[l.line]"
            >{{ fullCodeNotes[l.line] }}</span></div></template></pre>
          <div
            v-else
            class="text-[10px] text-ctp-overlay0"
          >
            {{ t('common.loading') }}
          </div>
          <div
            v-if="fullCodeError"
            class="text-[9px] text-ctp-peach pt-0.5"
          >
            {{ t('assetMgmt.graph.lineNotesFailed') }}
          </div>
        </template>
        <!-- 分段视图：简介 → 结构化 detail → 代码段(手风琴+复制) → 锚点导航 → 关系 -->
        <template v-else>
        <!-- 节点简介(代码级、grounded；生成中回退原 desc) -->
        <p class="text-[10px] leading-relaxed text-ctp-subtext0 whitespace-pre-wrap">
          <SparklesIcon
            v-if="nodeBriefText || nodeBriefLoading"
            class="w-3 h-3 inline text-ctp-mauve mr-0.5 -mt-0.5"
          />
          {{ (nodeBriefLoading && !nodeBriefText) ? (selDetail?.desc || sel.desc) : (nodeBriefText || selDetail?.desc || sel.desc) }}
          <button
            v-if="nodeBriefText"
            class="inline text-ctp-overlay0 hover:text-ctp-text align-middle"
            :title="t('assetMgmt.graph.briefForce')"
            :disabled="nodeBriefLoading"
            @click="regenerateNodeBrief"
          >
            <ArrowPathIcon
              class="w-2.5 h-2.5 inline"
              :class="nodeBriefLoading ? 'animate-spin' : ''"
            />
          </button>
        </p>
        <!-- C1 结构化 detail(按类别：字段/步骤/状态) -->
        <div v-if="detailBlock" class="space-y-0.5">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5">{{ detailBlock.title }}</div>
          <div
            v-for="(row, ri) in detailBlock.rows"
            :key="ri"
            class="pl-2 font-mono text-[10px] text-ctp-subtext0 truncate"
            :title="row.title"
          >{{ row.text }}</div>
        </div>
        <!-- 关系延伸 tab 内容：相关资产锚点代码预览(点击名称跳转选中该资产) -->
        <div v-if="activeRelTab" ref="relTabEl" class="space-y-1">
          <div class="flex items-center gap-1 mb-0.5">
            <span
              class="font-medium text-[10px] text-ctp-peach truncate cursor-pointer hover:underline"
              :title="t('assetMgmt.graph.jumpAnchor')"
              @click="jumpToRelation(activeRelTab)"
            >{{ activeRelTab.targetName }}</span>
            <span class="text-[9px] text-ctp-overlay1 truncate">
              {{ activeRelTab.relText }} · {{ shortPath(activeRelTab.file) }}:L{{ activeRelTab.line }}
            </span>
            <span class="flex-1" />
          </div>
          <pre
            v-if="relTabSegs[activeRelTab.file]?.lines?.length"
            class="m-0 overflow-auto rounded border border-ctp-surface1 bg-ctp-surface0 p-2 font-mono leading-relaxed max-h-52"
            :style="{ fontSize: codeFontSize + 'px' }"
          ><template
            v-for="l in (relTabSegs[activeRelTab.file] as SourceSnippet)!.lines"
            :key="l.line"
  ><div class="flex flex-wrap items-baseline gap-1.5"><span class="select-none text-ctp-overlay0 shrink-0">{{ l.line }}</span> <span
            :data-anchor-line="((relTabSegs[activeRelTab.file] as SourceSnippet)!.highlight ?? []).map(Number).includes(l.line)
              || Number((relTabSegs[activeRelTab.file] as SourceSnippet)!.anchorLine || 0) === l.line ? '1' : null"
            :class="((relTabSegs[activeRelTab.file] as SourceSnippet)!.highlight ?? []).map(Number).includes(l.line)
              || Number((relTabSegs[activeRelTab.file] as SourceSnippet)!.anchorLine || 0) === l.line
              ? [kindTextClass, kindBgClass, 'font-semibold rounded-sm px-0.5', flashing ? 'anchor-flash' : '']
              : 'text-ctp-subtext0'"
          >{{ l.code }}</span></div></template></pre>
          <div v-else class="text-[10px] text-ctp-overlay0">{{ t('common.loading') }}</div>
        </div>
        <!-- 多代码段(主体；>1 段时手风琴折叠，默认仅首段展开；跨文件时仅显示当前 tab 文件) -->
        <div
          v-for="{ seg, si } in activeTabSegs"
          :key="`${seg.file}:${seg.startLine}:${si}`"
          :ref="(el) => { segEls[si] = el as HTMLElement | null }"
          class="space-y-1"
        >
          <!-- 段头：可点击折叠(>1 段) + 复制位置(C2) -->
          <div
            class="flex items-center gap-1 mb-0.5"
            :class="segments.length > 1 ? 'cursor-pointer select-none' : ''"
            :title="segments.length > 1 ? t('assetMgmt.graph.jumpAnchor') : ''"
            @click="segments.length > 1 && toggleSeg(si)"
          >
            <ChevronDownIcon
              v-if="segments.length > 1"
              class="w-3 h-3 shrink-0 transition-transform"
              :class="collapsedSegs.has(si) ? '-rotate-90' : ''"
            />
            <span class="font-medium text-[10px] text-ctp-mauve truncate" :title="`${seg.file}:${seg.startLine}${seg.symbol ? ' · ' + seg.symbol : ''}`">
              {{ t('assetMgmt.graph.sourceCode') }}
              <span class="text-ctp-overlay1 font-normal">{{ shortPath(seg.file) }}:L{{ seg.startLine }}<span v-if="seg.symbol"> · {{ seg.symbol }}</span></span>
            </span>
            <span
              v-if="seg.snippet?.diffBase"
              class="chip !text-[8px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
              :title="t('assetMgmt.graph.diffViewHint')"
            >diff</span>
            <span class="flex-1" />
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5 shrink-0"
              :title="t('assetMgmt.graph.copyLoc')"
              :disabled="!seg.snippet"
              @click.stop="copySegLoc(seg, si)"
            >
              <CheckIcon v-if="copiedSeg === si" class="w-3 h-3 text-ctp-green" />
              <ClipboardIcon v-else class="w-3 h-3" />
            </button>
          </div>
          <!-- 代码体(折叠时隐藏) -->
          <template v-if="!collapsedSegs.has(si)">
          <pre
            v-if="seg.snippet?.lines?.length"
            class="m-0 overflow-auto rounded border border-ctp-surface1 bg-ctp-surface0 p-2 font-mono leading-relaxed"
            :class="cardSize.h ? '' : 'max-h-52'"
            :style="{ fontSize: codeFontSize + 'px' }"
          ><template
            v-for="(l, li) in seg.snippet.lines"
            :key="`${si}:${li}`"
  ><div
    class="flex flex-wrap items-baseline gap-1.5"
    :class="l.kind === 'add' ? ['bg-ctp-green/15', 'rounded-sm'] : l.kind === 'del' ? ['bg-ctp-red/15', 'rounded-sm'] : ''"
  ><span class="select-none text-ctp-overlay0 shrink-0 w-12 text-right">{{ l.kind === 'del' ? `-${l.baseLine ?? l.line}` : `${l.kind === 'add' ? '+' : ''}${l.targetLine ?? l.line}` }}</span> <span
              :data-anchor-line="segHighlighted(seg, l.line) ? '1' : null"
              :class="segHighlighted(seg, l.line)
                ? [kindTextClass, kindBgClass, 'font-semibold rounded-sm px-0.5', flashing ? 'anchor-flash' : '']
                : 'text-ctp-subtext0'"
            >{{ l.code }}</span><span
              v-if="lineNotesMaps[si]?.[l.line]"
              class="ml-auto shrink-0 max-w-[48%] truncate text-right italic"
              :class="segHighlighted(seg, l.line) ? kindTextClass : 'text-ctp-overlay1'"
              :title="lineNotesMaps[si]?.[l.line]"
            >{{ lineNotesMaps[si]?.[l.line] }}</span></div></template></pre>
          <div
            v-else-if="seg.loading"
            class="text-[10px] text-ctp-overlay0"
          >
            {{ t('common.loading') }}
          </div>
          </template>
        </div>
        <!-- 锚点导航(>1 段时快速定位)；跨文件锚点以桃色+标注区分 -->
        <div v-if="selAnchors.length && segments.length > 1">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 pt-1">
            {{ t('assetMgmt.graph.anchor') }}
          </div>
          <div
            v-for="(r, ri) in selAnchors.slice(0, MAX_SEGMENTS)"
            :key="ri"
            class="pl-2 font-mono text-[10px] hover:text-ctp-text cursor-pointer transition-colors truncate flex items-center gap-1"
            :class="r.file !== selAnchors[0]?.file ? 'text-ctp-peach' : 'text-ctp-overlay0'"
            :title="`${r.file} · ${r.file !== selAnchors[0]?.file
              ? `${t('assetMgmt.graph.crossFileAnchor')} · ${t('assetMgmt.graph.jumpAnchor')}`
              : t('assetMgmt.graph.jumpAnchor')}`"
            @click="jumpToSegment(ri)"
          >
            {{ shortPath(r.file) }}:L{{ r.startLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span>
            <span
              v-if="r.file !== selAnchors[0]?.file"
              class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
            >{{ t('assetMgmt.graph.crossFile') }}</span>
          </div>
        </div>
        <!-- 关系(证据式描述；点击跳转对方资产) -->
        <div v-if="selRelations.length || edgeNotesLoading">
          <div class="font-medium text-[10px] text-ctp-mauve mb-0.5 flex items-center gap-1">
            {{ t('assetMgmt.relations') }}
            <ArrowPathIcon
              v-if="edgeNotesLoading"
              class="w-2.5 h-2.5 animate-spin text-ctp-overlay0"
            />
          </div>
          <div
            v-for="r in selRelations"
            :key="r.key"
            class="pl-2 text-[10px] text-ctp-overlay0 hover:text-ctp-text cursor-pointer transition-colors"
            :title="t('assetMgmt.graph.jumpAnchor')"
            @click="jumpToRelation(r)"
          >
            <span class="text-ctp-subtext0">{{ r.targetName }}</span>
            <span class="text-ctp-overlay1"> · {{ r.desc || r.type }}</span>
          </div>
          <!-- 入边(被谁引用) -->
          <template v-if="inEdges.length">
            <div class="text-[9px] text-ctp-overlay1 pt-1">
              {{ t('assetMgmt.graph.inEdges') }}
            </div>
            <div
              v-for="r in inEdges"
              :key="r.fromId"
              class="pl-2 text-[10px] text-ctp-overlay0 hover:text-ctp-text cursor-pointer transition-colors"
              :title="r.desc || ''"
              @click="jumpToRelation({ targetId: r.fromId })"
            >
              <span class="text-ctp-subtext0">{{ r.fromName }}</span>
              <span class="text-ctp-overlay1"> · {{ r.desc || r.type || t('assetMgmt.graph.usesMe') }}</span>
            </div>
          </template>
        </div>
        </template>
        <div
          v-if="lineNotesDegraded"
          class="text-[9px] text-ctp-overlay0 pt-0.5"
        >
          {{ t('assetMgmt.graph.lineNotesDegraded') }}
        </div>
        <div
          v-if="lineNotesError"
          class="text-[9px] text-ctp-peach pt-0.5"
        >
          {{ t('assetMgmt.graph.lineNotesFailed') }}
        </div>
        </div>
        <!-- 四边独立拉伸把手(上下左右；hover 显隐提示) -->
        <div class="card-edge card-edge-n" @mousedown="cardStartResize($event, 'n')" @dblclick.stop />
        <div class="card-edge card-edge-s" @mousedown="cardStartResize($event, 's')" @dblclick.stop />
        <div class="card-edge card-edge-w" @mousedown="cardStartResize($event, 'w')" @dblclick.stop />
        <div class="card-edge card-edge-e" @mousedown="cardStartResize($event, 'e')" @dblclick.stop />
      </div>

      <!-- 最小化态：停靠图谱区右下；信息刷新时闪动缩放 ~3s 提示(不自动展开) -->
      <button
        v-if="sel && cardMin"
        class="absolute z-10 right-2 bottom-2 w-9 h-9 rounded-full border shadow-lg flex items-center justify-center transition-transform hover:scale-110"
        :class="[kindChipClass, iconPulse ? 'icon-pulse' : '']"
        :title="`${sel.name} · ${t('assetMgmt.graph.restore')}`"
        @click="setCardMin(false)"
      >
        <InformationCircleIcon class="w-5 h-5" />
      </button>
      <!-- 关系矩阵浮窗：数据实时跟随当前图谱口径(聚焦/拓展/过滤)；点节点头回写选中全联动 -->
      <GraphMatrixWindow
        v-if="matrixOpen"
        :nodes="scopedNodes"
        :edges="scopedEdges"
        :anchors="graph?.anchors ?? []"
        :sel-id="selId"
        @select="onMatrixSelect"
        @close="matrixOpen = false"
      />
      <!-- 资产节点索引浮窗：按索引探索图谱，点击行与图谱/资产卡/锚点全联动 -->
      <AssetIndexWindow
        v-if="indexOpen"
        :nodes="scopedNodes"
        :edges="scopedEdges"
        :anchors="graph?.anchors ?? []"
        :sel-id="selId"
        @select="onMatrixSelect"
        @close="indexOpen = false"
      />
      <!-- 文件范围索引浮窗：>500 资产的 tab 须在此圈定文件集合(多选/整组/预算) -->
      <FileIndexWindow
        v-if="fileScopeOpen"
        :entries="fileIndex"
        :selected="fileScopeSel"
        :budget="FILE_BUDGET"
        :total="scopeTotal"
        :comp-names="props.compNames"
        :forced="overLimit && !fileScopeSel.length"
        @apply="applyFileScope"
        @close="fileScopeOpen = false"
      />
    </div>
  </div>
</template>

<style scoped>
@keyframes anchor-flash-kf {
  0%, 55% { background-color: rgba(250, 179, 135, 0.28); }
  100% { background-color: transparent; }
}
.anchor-flash {
  animation: anchor-flash-kf 1.7s ease-out 1;
  border-radius: 2px;
}
@keyframes icon-pulse-kf {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(250, 179, 135, 0); }
  50% { transform: scale(1.22); box-shadow: 0 0 0 8px rgba(250, 179, 135, 0.28); }
}
.icon-pulse {
  animation: icon-pulse-kf 1s ease-in-out 3;
}
/* 图节点选中态：桃色强对比(浓光晕 + 加粗描边 + 半透明填充覆盖 + 文字加重)，
   绑定节点 DOM 切换；与未选节点的主题底色拉开层次，缩放后仍可一眼定位 */
:deep(.td-node-selected) {
  filter: drop-shadow(0 0 6px rgba(250, 179, 135, 1)) drop-shadow(0 0 14px rgba(250, 179, 135, 0.6));
}
:deep(.td-node-selected) path,
:deep(.td-node-selected) rect,
:deep(.td-node-selected) polygon,
:deep(.td-node-selected) circle,
:deep(.td-node-selected) ellipse {
  stroke: #fab387 !important;
  stroke-width: 3px !important;
}
/* 主体形状(rect/polygon/ellipse/circle)叠加半透明桃色填充，与底色形成面级对比；
   path 仅描边(shape 边缘)，覆盖 fill 会使连线误染，故排除 */
:deep(.td-node-selected) rect,
:deep(.td-node-selected) polygon,
:deep(.td-node-selected) ellipse,
:deep(.td-node-selected) circle {
  fill: rgba(250, 179, 135, 0.16) !important;
}
:deep(.td-node-selected) text {
  fill: #fab387 !important;
  font-weight: 700;
}
/* 对比变化节点着色(asset-compare 资产级口径)：以浅色底填充为主(比描边醒目)，
   透明度压低保证节点文字可读；辅以同色细描边勾勒轮廓。
   强关联=黄底 · 弱关联=灰浅底(段未变) · 目标侧新增=绿底 · 目标侧移除=红底+虚线。
   (运行时另注入同值内联样式兜底，双保险) */
:deep(.td-node-diff-changed) rect,
:deep(.td-node-diff-changed) polygon,
:deep(.td-node-diff-changed) ellipse,
:deep(.td-node-diff-changed) circle {
  fill: rgba(249, 226, 175, 0.30) !important;
  stroke: rgba(249, 226, 175, 0.8) !important;
  stroke-width: 1.5px !important;
}
:deep(.td-node-diff-weak) rect,
:deep(.td-node-diff-weak) polygon,
:deep(.td-node-diff-weak) ellipse,
:deep(.td-node-diff-weak) circle {
  fill: rgba(136, 137, 163, 0.16) !important;
  stroke: rgba(136, 137, 163, 0.5) !important;
  stroke-width: 1.5px !important;
}
:deep(.td-node-diff-new) rect,
:deep(.td-node-diff-new) polygon,
:deep(.td-node-diff-new) ellipse,
:deep(.td-node-diff-new) circle {
  fill: rgba(166, 227, 161, 0.24) !important;
  stroke: rgba(166, 227, 161, 0.75) !important;
  stroke-width: 1.5px !important;
}
:deep(.td-node-diff-removed) rect,
:deep(.td-node-diff-removed) polygon,
:deep(.td-node-diff-removed) ellipse,
:deep(.td-node-diff-removed) circle {
  fill: rgba(243, 139, 168, 0.24) !important;
  stroke: rgba(243, 139, 168, 0.8) !important;
  stroke-width: 1.5px !important;
  stroke-dasharray: 6 3 !important;
}
/* 资产卡四边独立拉伸把手(上下左右)：透明热区，hover 显提示条 */
.card-edge {
  position: absolute;
  z-index: 10;
  transition: background-color 0.15s;
}
.card-edge:hover {
  background-color: rgba(136, 137, 163, 0.35);
}
.card-edge-n,
.card-edge-s {
  left: 0;
  right: 0;
  height: 6px;
  cursor: ns-resize;
}
.card-edge-n { top: 0; }
.card-edge-s { bottom: 0; }
.card-edge-e,
.card-edge-w {
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
}
.card-edge-w { left: 0; }
.card-edge-e { right: 0; }
/* 资产卡：非代码文字在基准上整体放大两号(8→10 / 9→11 / 10→12 / 11→13)，
   并随全局 UI 字号等比(--card-scale = 全局字号/16，与 --ui-scale 同步缩放)；
   代码(pre/code)仍用 codeFontSize，不在此列。特异性高于 global.css 的 --ui-scale 覆盖，卡片内优先生效。 */
.card-root .text-\[8px\],  .card-root .\!text-\[8px\]  { font-size: calc(10px * var(--card-scale, 1)) !important; }
.card-root .text-\[9px\],  .card-root .\!text-\[9px\]  { font-size: calc(11px * var(--card-scale, 1)) !important; }
.card-root .text-\[10px\], .card-root .\!text-\[10px\] { font-size: calc(12px * var(--card-scale, 1)) !important; }
.card-root .text-\[11px\], .card-root .\!text-\[11px\] { font-size: calc(13px * var(--card-scale, 1)) !important; }
</style>
