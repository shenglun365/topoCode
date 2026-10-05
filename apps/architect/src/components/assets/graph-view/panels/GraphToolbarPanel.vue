<script setup lang="ts">

/** MS6-W2-S2 自 SemanticGraphView 模板整块迁出(逐行未动)；状态经 SGV_WS_KEY 注入。 */

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowPathIcon, XMarkIcon, ArrowsPointingOutIcon, MinusIcon, InformationCircleIcon, SparklesIcon, DocumentTextIcon, ViewfinderCircleIcon, ClipboardIcon, ChevronDownIcon, CheckIcon, PlusCircleIcon, TableCellsIcon, AdjustmentsHorizontalIcon, ListBulletIcon, LockClosedIcon, LockOpenIcon, FunnelIcon, FolderOpenIcon, WrenchScrewdriverIcon, EllipsisHorizontalIcon, ArrowDownTrayIcon, SignalIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import type { GraphTabDef } from '../graphTypes'
import { useSgvWs } from '../key'

const props = defineProps<{ tab: GraphTabDef; diffFiles?: Set<string> }>()
const { t } = useI18n()
const {
  cardLang,
  cardSrcOpen,
  clearSel,
  diagramLangs,
  diffKindById,
  diffSignalsById,
  diffTotals,
  diffNodeCount,
  diffOnly,
  edgeLegendOpen,
  edgeTypeColor,
  edgeTypeCounts,
  edgeTypeLabel,
  edgeTypeOff,
  enhanceProgress,
  enhanceRunning,
  expandFeedback,
  expandSelected,
  expandable,
  expanding,
  fileIndex,
  fileScopeOpen,
  fileScopeSel,
  focusHops,
  focusLock,
  focusMode,
  graph,
  graphRev,
  revSyncing,
  updateRevAssets,
  diagrams,
  hiddenViewHints,
  includeIndirect,
  indexOpen,
  kindFilter,
  kindOptions,
  legendBtnRef,
  legendPos,
  level,
  levelOptions,
  load,
  loading,
  matrixOpen,
  openCardFullscreen,
  overLimit,
  scopeAssets,
  sel,
  selId,
  setCardLang,
  startEnhanceDesc,
  toggleCardSource,
  toggleEdgeLegend,
  toggleEdgeType,
  toggleFocusLock,
  toggleIndex,
  toggleMatrix,
  traceMode,
  traceToggle,
  viewOptions,
  viewSel,
} = useSgvWs()
const emit = defineEmits<{ close: [id: string] }>()

// ---- 顶栏收纳菜单（工具▾ / ⋯ / 变化图例）：Teleport 浮层，定位/外点关闭与边类型图例同模式 ----
const toolsOpen = ref(false)
const toolsPos = ref({ top: 0, left: 0 })
const toolsBtnRef = ref<HTMLElement | null>(null)
const TOOLS_W = 192
function placeMenu(btn: HTMLElement | null, w: number, alignRight: boolean): { top: number; left: number } {
  if (!btn) return { top: 0, left: 8 }
  const r = btn.getBoundingClientRect()
  let left = alignRight ? r.right - w : r.left
  left = Math.max(8, Math.min(left, window.innerWidth - 8 - w))
  return { top: r.bottom + 4, left }
}
function toggleTools() {
  if (!toolsOpen.value) toolsPos.value = placeMenu(toolsBtnRef.value, TOOLS_W, false)
  toolsOpen.value = !toolsOpen.value
}
const moreOpen = ref(false)
const morePos = ref({ top: 0, left: 0 })
const moreBtnRef = ref<HTMLElement | null>(null)
const MORE_W = 168
function toggleMore() {
  if (!moreOpen.value) morePos.value = placeMenu(moreBtnRef.value, MORE_W, true)
  moreOpen.value = !moreOpen.value
}
const diffLegendOpen = ref(false)
const diffLegendPos = ref({ top: 0, left: 0 })
const diffLegendBtnRef = ref<HTMLElement | null>(null)
const DIFF_LEGEND_W = 216
function toggleDiffLegend() {
  if (!diffLegendOpen.value) diffLegendPos.value = placeMenu(diffLegendBtnRef.value, DIFF_LEGEND_W, true)
  diffLegendOpen.value = !diffLegendOpen.value
}
function onMenuDocClick(e: MouseEvent) {
  const t = e.target
  if (!(t instanceof Node)) return
  for (const [open, btn, sel] of [
    [toolsOpen, toolsBtnRef, '[data-tools-menu]'],
    [moreOpen, moreBtnRef, '[data-more-menu]'],
    [diffLegendOpen, diffLegendBtnRef, '[data-diff-legend]'],
  ] as const) {
    if (!open.value) continue
    if (btn.value?.contains(t)) continue
    if (document.querySelector(sel)?.contains(t)) continue
    open.value = false
  }
}
onMounted(() => document.addEventListener('click', onMenuDocClick, true))
onBeforeUnmount(() => document.removeEventListener('click', onMenuDocClick, true))

const MENU_ITEM = 'w-full flex items-center gap-2 px-2 py-1 rounded text-[11px] hover:bg-ctp-surface0 text-left'
const sigAddedCount = computed(() => [...diffSignalsById.value.values()].filter((x) => x.hasAdded).length)
const sigDeletedCount = computed(() => [...diffSignalsById.value.values()].filter((x) => x.hasDeleted).length)

/** 图谱导出(R1)：DSL 源码文本下载(渲染图导出走画布内 SVG/PNG)。 */
function exportGraph(): void {
  try {
    const data = diagrams.value[cardLang.value] || ''
    const ext = cardLang.value === 'plantuml' ? 'puml' : cardLang.value
    const blob = new Blob([data], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `asset-graph-${new Date().toISOString().slice(0, 10)}.${ext}`
    a.click()
    URL.revokeObjectURL(url)
  } catch { /* 导出失败静默 */ }
}
</script>

<template>
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
      <!-- 工具▾：邻域聚焦/拓展关联/关系矩阵/资产索引/文件范围索引/关系图例 收纳 -->
      <div class="w-px h-4 bg-ctp-surface1 shrink-0" />
      <div ref="toolsBtnRef" class="shrink-0">
        <button
          class="btn btn-ghost !py-0.5 !text-[11px] shrink-0 flex items-center gap-0.5"
          :class="(focusMode || matrixOpen || indexOpen || edgeTypeOff.size) ? 'btn-primary' : ''"
          :title="t('assetMgmt.graph.toolsMenu')"
          @click="toggleTools"
        >
          <WrenchScrewdriverIcon class="w-3.5 h-3.5" /><ChevronDownIcon class="w-3 h-3" />
        </button>
      </div>
      <Teleport to="body">
        <div
          v-if="toolsOpen"
          data-tools-menu
          class="fixed z-50 rounded-lg border border-ctp-surface1 bg-ctp-mantle shadow-lg p-1 space-y-0.5"
          :style="{ top: toolsPos.top + 'px', left: toolsPos.left + 'px', width: TOOLS_W + 'px' }"
        >
          <button :class="MENU_ITEM" @click="focusMode = !focusMode; if (focusMode) traceMode = false">
            <ViewfinderCircleIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.graph.focusMenu') }}
            <span v-if="focusMode" class="ml-auto text-ctp-blue">●</span>
          </button>
          <button
            :class="[MENU_ITEM, selId ? '' : 'opacity-50 cursor-not-allowed']"
            :disabled="!selId"
            @click="traceToggle(); toolsOpen = false"
          >
            <SignalIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.graph.trace.menu') }}
            <span v-if="traceMode" class="ml-auto text-ctp-mauve">●</span>
          </button>
          <button :class="[MENU_ITEM, expandable ? '' : 'opacity-50 cursor-not-allowed']" :disabled="!expandable || expanding" @click="expandSelected(); toolsOpen = false">
            <PlusCircleIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.graph.expandMenu') }}
          </button>
          <button :class="MENU_ITEM" @click="toggleMatrix(); toolsOpen = false">
            <TableCellsIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.matrix.title') }}
            <span v-if="matrixOpen" class="ml-auto text-ctp-blue">●</span>
          </button>
          <button :class="MENU_ITEM" @click="toggleIndex(); toolsOpen = false">
            <ListBulletIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.index.title') }}
            <span v-if="indexOpen" class="ml-auto text-ctp-blue">●</span>
          </button>
          <button v-if="overLimit" :class="MENU_ITEM" @click="fileScopeOpen = !fileScopeOpen; toolsOpen = false">
            <FolderOpenIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.fileIndex.pickTitle') }}
            <span v-if="fileScopeOpen || fileScopeSel.length" class="ml-auto text-ctp-blue">●</span>
          </button>
          <button ref="legendBtnRef" :class="MENU_ITEM" @click="toggleEdgeLegend(); toolsOpen = false">
            <AdjustmentsHorizontalIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.graph.edgeLegend') }}
            <span v-if="edgeTypeOff.size" class="ml-auto text-ctp-blue">●</span>
          </button>
        </div>
      </Teleport>
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
      <span
        v-if="expandFeedback"
        class="shrink-0 text-[10px] text-ctp-teal font-medium cursor-default"
      >{{ expandFeedback }}</span>
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
        <!-- 变化图例聚合：总数 chip → 浮层列四桶明细 -->
        <button
          ref="diffLegendBtnRef"
          class="chip bg-ctp-yellow/15 text-ctp-yellow font-mono text-[9px] shrink-0 cursor-pointer hover:bg-ctp-yellow/25"
          :title="t('assetMgmt.graph.diffLegendHint')"
          @click="toggleDiffLegend"
        >{{ t('assetMgmt.graph.diffTotal') }} {{ diffTotals.chip }}</button>
        <Teleport to="body">
          <div
            v-if="diffLegendOpen"
            data-diff-legend
            class="fixed z-50 rounded-lg border border-ctp-surface1 bg-ctp-mantle shadow-lg p-2 space-y-1"
            :style="{ top: diffLegendPos.top + 'px', left: diffLegendPos.left + 'px', width: DIFF_LEGEND_W + 'px' }"
          >
            <div class="flex items-center gap-1.5 text-[11px]">
              <span class="w-2.5 h-2.5 rounded-sm bg-ctp-yellow/50" />
              <span>{{ t('assetMgmt.graph.legendChanged') }}</span>
              <span class="ml-auto text-ctp-overlay0 font-mono">{{ diffTotals.changedLike }}</span>
            </div>
            <div class="flex items-center gap-1.5 text-[11px]">
              <span class="w-2.5 h-2.5 rounded-sm bg-ctp-yellow/25" />
              <span>{{ t('assetMgmt.graph.legendWeak') }}</span>
              <span class="ml-auto text-ctp-overlay0 font-mono">{{ diffTotals.weak }}</span>
            </div>
            <div class="flex items-center gap-1.5 text-[11px]">
              <span class="w-2 h-2 rounded-full bg-ctp-green" />
              <span>{{ t('assetMgmt.graph.legendAddedSig') }}</span>
              <span class="ml-auto text-ctp-overlay0 font-mono">{{ sigAddedCount }}</span>
            </div>
            <div class="flex items-center gap-1.5 text-[11px]">
              <span class="w-2 h-2 rounded-full bg-ctp-red" />
              <span>{{ t('assetMgmt.graph.legendDeletedSig') }}</span>
              <span class="ml-auto text-ctp-overlay0 font-mono">{{ sigDeletedCount }}</span>
            </div>
          </div>
        </Teleport>
      </template>
      <span
        v-if="graph && props.diffFiles && diffNodeCount"
        class="chip bg-ctp-yellow/15 text-ctp-yellow font-mono text-[9px] shrink-0"
        :title="t('assetMgmt.diff.hint')"
      >{{ diffNodeCount }} {{ t('assetMgmt.graph.nodes') }} · diff</span>
      <!-- 视角动态对齐基线对比目标(无手选)；非工作区视角提供数据更新入口(基线对比提取通道) -->
      <button
        v-if="graph && graphRev !== 'workspace'"
        class="btn btn-xs btn-ghost shrink-0 flex items-center gap-1"
        :disabled="revSyncing"
        :title="t('assetMgmt.graph.revSyncHint')"
        @click="updateRevAssets"
      >
        <ArrowPathIcon class="w-3 h-3" :class="revSyncing ? 'animate-spin' : ''" />{{ t('assetMgmt.graph.revSync') }}
      </button>
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
      <!-- ⋯ 溢出菜单：增强描述 / 导出 DSL / 刷新 / 关闭 -->
      <div ref="moreBtnRef" class="shrink-0">
        <button
          class="btn btn-xs btn-ghost"
          :title="t('assetMgmt.graph.moreMenu')"
          @click="toggleMore"
        >
          <EllipsisHorizontalIcon class="w-4 h-4" />
        </button>
      </div>
      <Teleport to="body">
        <div
          v-if="moreOpen"
          data-more-menu
          class="fixed z-50 rounded-lg border border-ctp-surface1 bg-ctp-mantle shadow-lg p-1 space-y-0.5"
          :style="{ top: morePos.top + 'px', left: morePos.left + 'px', width: MORE_W + 'px' }"
        >
          <button :class="MENU_ITEM" :disabled="enhanceRunning || loading" @click="startEnhanceDesc(); moreOpen = false">
            <SparklesIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.graph.enhanceDesc') }}
          </button>
          <button :class="MENU_ITEM" @click="exportGraph(); moreOpen = false">
            <ArrowDownTrayIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.graph.exportDsl') }}
          </button>
          <button :class="MENU_ITEM" :disabled="loading" @click="load(); moreOpen = false">
            <ArrowPathIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.graph.reload') }}
          </button>
          <button :class="[MENU_ITEM, 'text-ctp-red']" @click="emit('close', props.tab.id); moreOpen = false">
            <XMarkIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.graph.closeTab') }}
          </button>
        </div>
      </Teleport>
    </div>
</template>
<style scoped>
@keyframes icon-pulse-kf {
  0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(250, 179, 135, 0); }
  50% { transform: scale(1.22); box-shadow: 0 0 0 8px rgba(250, 179, 135, 0.28); }
}
.icon-pulse {
  animation: icon-pulse-kf 1s ease-in-out 3;
}
</style>
