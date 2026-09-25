<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, provide } from 'vue'
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
import GraphToolbarPanel from './graph-view/panels/GraphToolbarPanel.vue'
import GraphMainPanel from './graph-view/panels/GraphMainPanel.vue'
import { SGV_WS_KEY } from './graph-view/key'

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
const ws = Object.assign({}, D.data, D.detail, D.code, D.render)
provide(SGV_WS_KEY, ws)
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
} = ws

onMounted(async () => {
  await load()
})
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <GraphToolbarPanel :tab="props.tab" @close="(id: string) => emit('close', id)" />
    <GraphMainPanel :tab="props.tab" :diff-files="props.diffFiles" :comp-names="props.compNames" />
  </div>
</template>
