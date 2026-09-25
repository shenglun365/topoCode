<script setup lang="ts">
/**
 * 资产管理工作区(MS6-W1 重构：逻辑层已拆至 ./asset-workspace/ 八域 composable)。
 * 本文件仅保留：视图辅助(kindIcon/copyAsset) + setup 生命周期接线(窗口事件/
 * 会话钩子注册/轮询接管/初始加载) + 模板。模板逐行未动。
 */
import { onMounted, onUnmounted, provide } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, ArrowPathIcon,
  CubeTransparentIcon, AdjustmentsHorizontalIcon, ServerStackIcon,
} from '@heroicons/vue/24/outline'
import { kindChipClass, levelChipClass } from '@/services/semantic-kind-style'
import FileSourceCard from '@/components/assets/FileSourceCard.vue'
import RequirementHistoryModal from '@/components/requirements/RequirementHistoryModal.vue'
import SemanticGraphView from '@/components/assets/SemanticGraphView.vue'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import ConversationDock from '@/components/chat/ConversationDock.vue'
import { useSplitPane } from '@/composables/useSplitPane'
import { copyText } from '@/utils/clipboard'
import type { SemanticAsset } from '@/types'
import { useAssetWorkspace, ASSET_WS_KEY } from './asset-workspace'
import OverviewPanel from './asset-workspace/panels/OverviewPanel.vue'
import SemanticTreePanel from './asset-workspace/panels/SemanticTreePanel.vue'
import WorkspaceModals from './asset-workspace/panels/WorkspaceModals.vue'
import { OTHER_KEY } from './asset-workspace/useAssetCore'

const { t } = useI18n()

const { splitPct, dragging, boxRef: splitBoxRef, onDown: onSplitPointerDown } = useSplitPane({ initial: 50 })

const ws = useAssetWorkspace()
provide(ASSET_WS_KEY, ws)
const conv = ws.conv
const {
  tab, kind, level, q, items, loading, statusCounts, expanded, overviewStats, purging,
  kinds, levels, statusText,
  compCatalog, loadCompCatalog, treeComps, compById, fileToComps,
  componentsOf, descendantsOf, hasChildren,
  scopeSel, compOpen, filterOpen, toggleComp, toggleOther, clearScope, toggleOpen,
  treeLevel, cycleTreeLevel, compChildrenOpen, compExpandState, fileExpandState,
  compContentOpen, compDirectOpen, fileAssetsOpen,
  compRows, compHierLevel, fileOpen, subtreeCount, compCollapsible, diffRollup,
  toggleFileOpen, fileBase, semanticTreeRows, scopeSummary, scopeParams,
  loadSemantic, loadOverview, fileCard, openFileCard, locateAsset,
  refreshStatus, refreshOne, usable, detailLoading, descLoading,
  renderCap, renderedTreeRows, semScrollEl, loadMoreSentinel,
  genDesc, toggle, hideFileless, onSearch, compMetaText, compRefText,
  historyOpen, turns, extractBusy, extractAbort,
  ensureAssetConversation, importHistory, onImportNewConversation,
  registerChatHook, askAgent, seedConventionIds,
  onConventionConfirm, onConventionIgnore, referenceComp, referenceAsset,
  diffMode, diffLoading, baselineDiffData, toggleDiffMode,
  cmpBase, cmpTarget, commitOptions, baselineSha, compareData, compareError, compareLoading,
  loadCommitOptions, runCompare,
  extractingPending, pendingExtractable, extractPendingAndRecompare,
  changeMarkById, diffFileCounts, pendingFileSet, addedFileSet,
  diffMarkLabel, changedFilesForGraph, totalChanged,
  frameworkInfo, coverageInfo, fwLoading, fwSwitching, fwPreview,
  loadFramework, loadCoverage, switchTier, askExtractComponent,
  compCoverage, copiedKey, copyCompRef,
  unownedFiles, unownedMeta, unownedLoading, unownedError,
  loadUnownedFiles, loadUnownedLinks,
  unownedExtractingOne, extractUnownedFile,
  unownedJob, unownedExtracting, unownedJobHint,
  extractAllUnowned, stopUnownedExtract,
  unownedLinks, unownedLinkOf, unownedLinkTitle, unownedLinkByAssetId,
  syncPlan, syncPlanOpen, syncPlanLoading, syncJob, syncExtracting,
  planSyncExtract, cancelSyncExtract, confirmSyncExtract, stopSyncExtract,
  purgeOpen, purgeResult, purgeBusy, runPurge, confirmPurge, cancelPurge,
  batchOpen, batchRunning, batchAction, batchLast, batchPreview, runBatch,
  graphTabs, activeGraphTab, openGraphTab, closeGraphTab,
  graphFileIndexes, graphCompNames,
  diagramModalOpen, diagramModalLoading, diagramModalItems, diagramModalTitle, openAssetDiagram,
} = ws

/** dock 内「刷新资产」卡事件(全局会话栏代发)。 */
function _onDockRefreshAsset(e: Event) {
  const id = (e as CustomEvent).detail as string
  refreshOne(items.value.find((x) => x.id === id) as SemanticAsset).catch(() => {})
}
function _onDockOpenAsset(e: Event) {
  const id = (e as CustomEvent).detail as string
  if (id) openGraphTab('asset', id, id)
}

// ---- setup 生命周期接线(状态/动作已全部在 composable，宿主只挂生命周期) ----
const _unregChatHook = registerChatHook()

onMounted(() => {
  window.addEventListener('arch:refresh-asset', _onDockRefreshAsset)
  window.addEventListener('arch:open-asset', _onDockOpenAsset)
})
onUnmounted(() => {
  _unregChatHook()
  window.removeEventListener('arch:refresh-asset', _onDockRefreshAsset)
  window.removeEventListener('arch:open-asset', _onDockOpenAsset)
  ws.disposeObserver()
  ws.stopUnownedJobPolling()
  ws.stopSyncJobPolling()
})

onMounted(async () => {
  await Promise.all([loadCompCatalog(), loadOverview(), loadSemantic(), refreshStatus(), loadFramework(), loadCoverage(), loadUnownedFiles(), loadUnownedLinks()])
  // 引导消息只在对话为空时种一次(turns 是全局 store, 页面反复挂载不重复种)
  if (turns.value.length === 0) {
    turns.value.push({ role: 'assistant', content: t('assetMgmt.welcome') })
  }
  // 批量提取是后端作业：页面重开(此前关闭)也要接管进度轮询
  void ws.pollUnownedJobOnce().then(() => {
    if (unownedJob.value?.running) ws.startUnownedJobPolling()
  })
  void ws.pollSyncJobOnce().then(() => {
    if (syncJob.value?.running) ws.startSyncJobPolling()
  })
})
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="shrink-0 px-5 pt-5">
      <div class="flex items-center gap-3">
        <h2 class="text-sm font-semibold text-ctp-text">
          {{ t('assetMgmt.title') }}
        </h2>
        <div class="flex items-center gap-1">
          <button
            v-for="tb in [{ id: 'overview' as const, label: t('assetMgmt.tab.overview') }, { id: 'semantic' as const, label: t('assetMgmt.tab.semantic') }, { id: 'graph' as const, label: t('assetMgmt.tab.graph') }]"
            :key="tb.id"
            class="btn btn-xs"
            :class="tab === tb.id ? 'btn-blue' : 'btn-ghost'"
            @click="tab = tb.id; onSearch()"
          >
            {{ tb.label }}
          </button>
        </div>
        <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[10px]">{{ statusText }}</span>
        <button
          class="btn btn-xs"
          :class="diffMode ? 'btn-blue' : 'btn-ghost'"
          :title="t('assetMgmt.diff.hint')"
          @click="toggleDiffMode"
        >
          <ArrowsRightLeftIcon class="w-3.5 h-3.5" :class="diffLoading ? 'animate-spin' : ''" />
          {{ t('assetMgmt.diff.toggle') }}
        </button>
        <span v-if="diffMode && baselineDiffData" class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[10px]">
          <template v-if="baselineDiffData.aligned">{{ t('assetMgmt.diff.aligned') }}</template>
          <template v-else-if="baselineDiffData.stale">{{ t('assetMgmt.diff.stale', { n: totalChanged }) }}</template>
          <template v-else>{{ t('assetMgmt.diff.noBaseline') }}</template>
        </span>
         <div class="flex-1" />
         <button
           class="btn btn-sm btn-ghost"
           @click="historyOpen = true"
         >
           <ClipboardDocumentListIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.historyButton') }}
         </button>
         <!-- 校验并提取：先校验变化量 → 确认 → 快照批量作业(后端，页面关闭不影响) -->
         <button
           class="btn btn-sm"
           :class="syncExtracting ? 'btn-primary' : 'btn-primary'"
           :disabled="syncPlanLoading || syncExtracting"
           :title="syncExtracting
             ? (syncJob?.current
                ? t('assetMgmt.sync.extractingCurrent', { saved: syncJob?.saved ?? 0, current: syncJob.current })
                : t('assetMgmt.sync.extractingHint', { saved: syncJob?.saved ?? 0 }))
             : t('assetMgmt.sync.hint')"
           @click="planSyncExtract"
         >
            <ArrowPathIcon
              class="w-3.5 h-3.5"
              :class="syncPlanLoading || syncExtracting ? 'animate-spin' : ''"
            />{{ syncExtracting
             ? t('assetMgmt.sync.extracting', { done: syncJob?.done ?? 0, total: syncJob?.total ?? 0 })
             : (syncPlanLoading ? t('assetMgmt.sync.planning') : t('assetMgmt.sync.button')) }}
         </button>
         <button
           v-if="syncExtracting"
           class="btn btn-sm btn-ghost"
           :title="t('assetMgmt.sync.stop')"
           @click="stopSyncExtract"
         >
           <StopIcon class="w-3.5 h-3.5" />
         </button>
       </div>
      <!-- 基线对比 · 对比起止 head 选择(任意 head 对 vs head/工作区；全 tab 可见) + 紧凑结果 -->
      <div v-if="diffMode" class="mt-2.5 flex items-center gap-1.5 flex-wrap">
        <span class="text-[10px] text-ctp-overlay0 shrink-0">{{ t('assetMgmt.diff.cmpBase') }}</span>
        <select
          v-model="cmpBase"
          class="input !py-0.5 !px-1.5 !text-[10px] min-w-0 max-w-[30%]"
          :title="t('assetMgmt.diff.cmpBaseHint')"
          @change="runCompare"
        >
          <option value="">{{ t('assetMgmt.diff.kbBaseline') }}{{ baselineSha ? ` (${baselineSha.slice(0, 8)})` : '' }}</option>
          <option v-for="c in commitOptions" :key="`b-${c.oid}`" :value="c.oid">{{ c.oid.slice(0, 8) }} {{ c.subject.slice(0, 26) }}</option>
        </select>
        <span class="text-ctp-overlay0 shrink-0">→</span>
        <select
          v-model="cmpTarget"
          class="input !py-0.5 !px-1.5 !text-[10px] min-w-0 max-w-[30%]"
          :title="t('assetMgmt.diff.cmpTargetHint')"
          @change="runCompare"
        >
          <option value="worktree">{{ t('assetMgmt.diff.worktree') }}</option>
          <option v-for="c in commitOptions" :key="`t-${c.oid}`" :value="c.oid">{{ c.oid.slice(0, 8) }} {{ c.subject.slice(0, 26) }}</option>
        </select>
        <!-- 重新对比按钮已删：选择即对比(@change)/提取闭环自带重比；工作区有新改动时重选目标即可触发 -->
        <span v-if="compareLoading" class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.cmpRunning') }}</span>
        <span v-else-if="compareError" class="text-[10px] text-ctp-red truncate max-w-[40%]" :title="compareError">{{ compareError }}</span>
        <!-- 结果数字不再重复在此：统一在下方「对比结果明细」统计行(缓存态/资产变化/待提取) -->
        <template v-else-if="compareData && !compareData.noChanges">
          <!-- 提取闭环(通用)：pending 中「目标侧内容==工作区内容」的子集可经工作区提取锚定；
               内容已分叉的自动排除(提取历史内容会覆盖现役资产摘要)。完成后自动重新对比 -->
          <button
            v-if="pendingExtractable.length && !extractingPending"
            class="btn btn-xs btn-blue !py-0.5 shrink-0"
            :title="pendingExtractable.length < compareData.assets.pending.count
              ? t('assetMgmt.diff.extractRecompareHint', { n: pendingExtractable.length }) + ' ' + t('assetMgmt.diff.extractDiverged', { m: compareData.assets.pending.count - pendingExtractable.length })
              : t('assetMgmt.diff.extractRecompareHint', { n: pendingExtractable.length })"
            @click="extractPendingAndRecompare"
          >
            <SparklesIcon class="w-3 h-3" />{{ t('assetMgmt.diff.extractRecompare', { n: pendingExtractable.length }) }}
          </button>
          <span v-if="extractingPending" class="inline-flex items-center gap-1 text-[10px] text-ctp-overlay0"><ArrowPathIcon class="w-3 h-3 animate-spin" />{{ t('assetMgmt.diff.extracting') }}</span>
        </template>
      </div>
    </div>

    <div
      ref="splitBoxRef"
      class="flex-1 min-h-0 flex px-5 pb-5 pt-4"
    >
      <!-- 左：资产管理内容区 -->
      <div
        class="min-h-0 panel overflow-hidden flex flex-col"
        :style="{ width: splitPct + '%' }"
      >
        <div class="panel-header shrink-0 relative !justify-start gap-1.5">
          <span class="flex items-center gap-2">
            <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-mauve" />{{ t(`assetMgmt.tab.${tab}`) }}
          </span>
          <input
            v-if="tab !== 'graph' && tab !== 'overview'"
            v-model="q"
            class="input !py-0.5 !px-2 !text-[11px] w-44 font-mono ml-3"
            :placeholder="t('assetMgmt.searchPlaceholder')"
            @keydown.enter="onSearch"
          >
          <select
            v-if="tab === 'semantic'"
            v-model="kind"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
            @change="onSearch"
          >
            <option value="">
              {{ t('assetMgmt.allKinds') }}
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
            v-if="tab === 'semantic'"
            v-model="level"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
            @change="onSearch"
          >
            <option value="">
              {{ t('assetMgmt.allLevels') }}
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
            v-if="tab === 'semantic'"
            class="input !py-0.5 !px-2 !text-[11px] w-auto cursor-pointer"
            :title="t('assetMgmt.treeLevelHint')"
            @click="cycleTreeLevel"
          >{{ t(`assetMgmt.treeLevel.${treeLevel}`) }}</button>
          <template v-if="tab === 'semantic'">
            <div
              class="inline-flex items-center h-[calc(1.5rem+2px)] rounded-md border border-ctp-surface1 bg-ctp-crust overflow-hidden"
              :title="t('assetMgmt.scopeGroupHint')"
            >
              <span class="inline-flex items-center px-2 text-[11px] text-ctp-text">{{ scopeSummary }}</span>
              <button
                class="btn btn-xs !rounded-none !border-l !border-ctp-surface1 self-stretch"
                :class="(filterOpen || scopeSel.length) ? 'btn-blue' : 'btn-ghost !text-ctp-text'"
                :title="scopeSel.length ? t('assetMgmt.filterActive', { n: scopeSel.length }) : t('assetMgmt.scopeGroupHint')"
                @click="filterOpen = !filterOpen; batchOpen = false"
              >
                <AdjustmentsHorizontalIcon class="w-3 h-3" />
              </button>
            </div>
            <button
              class="input !py-0.5 !px-2 !text-[11px] w-auto cursor-pointer inline-flex items-center justify-center h-[calc(1.5rem+2px)]"
              :class="batchOpen ? '!border-ctp-blue' : ''"
              :title="t('assetMgmt.batchClearAll')"
              @click="batchOpen = !batchOpen; filterOpen = false"
            >
              <TrashIcon class="w-3 h-3" />
            </button>

            <!-- 点击浮层：批量清除(物理删除 选定组件范围) -->
            <div
              v-if="batchOpen"
              class="absolute right-0 top-full mt-1 z-30 w-72 max-w-[90vw] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-2.5 space-y-2"
            >
              <div class="flex items-center justify-between">
                <span class="text-[10px] text-ctp-overlay1">{{ t('assetMgmt.batchHint') }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ scopeSummary }}</span>
              </div>
              <div class="flex items-center gap-1 pt-1">
                <button
                  class="btn btn-xs"
                  :class="batchAction === 'clear' ? 'btn-red' : 'btn-ghost'"
                  :disabled="batchRunning"
                  @click="runBatch('clear')"
                >
                  <TrashIcon class="w-3 h-3" />{{ batchAction === 'clear' ? t('assetMgmt.batchConfirm') : t('assetMgmt.batchClear') }}
                </button>
                <button
                  v-if="batchAction === 'clear'"
                  class="btn btn-xs btn-ghost"
                  @click="batchAction = ''; batchPreview = null"
                >
                  {{ t('assetMgmt.batchCancel') }}
                </button>
              </div>
              <div
                v-if="batchAction === 'clear'"
                class="border-t border-ctp-surface0 pt-1.5 space-y-1.5"
              >
                <p class="text-[10px] text-ctp-red">
                  {{ t('assetMgmt.batchConfirmClear') }}
                </p>
                <div
                  v-if="batchPreview"
                  class="space-y-1"
                >
                  <p class="text-[10px] text-ctp-subtext1">
                    {{ t('assetMgmt.batchClearImpact', {
                      candidates: batchPreview.count,
                      reqCount: batchPreview.impact?.reqCount ?? 0,
                      taskCount: batchPreview.impact?.taskCount ?? 0,
                    }) }}
                  </p>
                  <div
                    v-if="batchPreview.impact?.requirements?.length"
                    class="text-[9px] text-ctp-peach"
                  >
                    {{ t('assetMgmt.purgeConfirm.reqTitle', { n: batchPreview.impact.reqCount }) }}
                    <div class="flex flex-wrap gap-1 pt-0.5">
                      <span
                        v-for="r in batchPreview.impact.requirements"
                        :key="r.id"
                        class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1"
                      >{{ r.id }} · {{ r.title }}</span>
                    </div>
                  </div>
                  <div
                    v-if="batchPreview.impact?.tasks?.length"
                    class="text-[9px] text-ctp-blue"
                  >
                    {{ t('assetMgmt.purgeConfirm.taskTitle', { n: batchPreview.impact.taskCount }) }}
                    <div class="flex flex-wrap gap-1 pt-0.5">
                      <span
                        v-for="t in batchPreview.impact.tasks"
                        :key="t.id"
                        class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1"
                      >{{ t.id }} · {{ t.title }}</span>
                    </div>
                  </div>
                  <p
                    v-if="!batchPreview.impact?.requirements?.length && !batchPreview.impact?.tasks?.length"
                    class="text-[9px] text-ctp-green"
                  >
                    {{ t('assetMgmt.purgeConfirm.noImpact') }}
                  </p>
                </div>
              </div>
              <div
                v-if="batchRunning"
                class="text-[10px] text-ctp-overlay1"
              >
                {{ t('assetMgmt.batchRunning') }}
              </div>
              <div
                v-if="batchLast"
                class="text-[10px] text-ctp-subtext1"
              >
                {{ batchLast }}
              </div>
            </div>
            <div
              v-if="batchOpen"
              class="fixed inset-0 z-20"
              @click="batchOpen = false"
            />

            <!-- 点击浮层：组件范围筛选 -->
            <div
              v-if="filterOpen"
              class="absolute right-0 top-full mt-1 z-30 w-80 max-w-[90vw] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-2.5 space-y-2"
            >
              <div class="flex items-center justify-between">
                <span class="text-[10px] text-ctp-overlay1">{{ t('assetMgmt.compScope') }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ scopeSummary }}</span>
              </div>
              <div class="max-h-40 overflow-auto space-y-0.5">
                <div
                  v-for="r in compRows"
                  :key="r.comp.id"
                  class="flex items-center gap-1.5 min-w-0"
                  :style="{ paddingLeft: (r.depth * 14) + 'px' }"
                >
                  <button
                    v-if="hasChildren(r.comp.id)"
                    class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                    @click="toggleOpen(r.comp.id)"
                  >
                    <ChevronDownIcon
                      v-if="compOpen[r.comp.id] !== false"
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
                    :checked="scopeSel.includes(r.comp.id)"
                    @change="toggleComp(r.comp.id)"
                  >
                  <span class="text-[11px] text-ctp-subtext1 truncate">{{ r.comp.name }}</span>
                </div>
                <div class="flex items-center gap-1.5 min-w-0 pt-0.5">
                  <span class="w-4 shrink-0" />
                  <input
                    type="checkbox"
                    class="accent-ctp-yellow shrink-0"
                    :checked="scopeSel.includes(OTHER_KEY)"
                    @change="toggleOther"
                  >
                  <span class="text-[11px] text-ctp-subtext1">{{ t('assetMgmt.unownedFiles') }}</span>
                  <span class="text-[9px] text-ctp-overlay0 truncate">{{ t('assetMgmt.unowned.desc') }}</span>
                </div>
              </div>
              <label class="flex items-center gap-1.5 border-t border-ctp-surface0 pt-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  class="accent-ctp-blue shrink-0"
                  v-model="hideFileless"
                >
                <span class="text-[10px] text-ctp-subtext1">{{ t('assetMgmt.hideFileless') }}</span>
              </label>
              <div class="flex items-center justify-between border-t border-ctp-surface0 pt-1.5">
                <span class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.scopeHint') }}</span>
                <button
                  class="btn btn-xs btn-ghost"
                  @click="clearScope"
                >
                  {{ t('assetMgmt.clearScope') }}
                </button>
              </div>
            </div>

            <!-- 点击浮层外关闭 -->
            <div
              v-if="filterOpen"
              class="fixed inset-0 z-20"
              @click="filterOpen = false"
            />
          </template>
        </div>

        <!-- 语义层图谱(多资源 tab，从语义/组件列表打开) -->
        <div
          v-if="tab === 'graph'"
          class="flex-1 min-h-0 overflow-hidden flex flex-col"
        >
          <div
            v-if="!graphTabs.length"
            class="flex-1 min-h-0 flex items-center justify-center text-xs text-ctp-overlay0"
          >
            {{ t('assetMgmt.graph.noTab') }}
          </div>
          <template v-else>
            <div class="shrink-0 flex items-stretch border-b border-ctp-surface1 px-1 pt-1 overflow-x-auto">
              <button
                v-for="gt in graphTabs"
                :key="gt.id"
                class="group relative flex items-center gap-1.5 max-w-[200px] px-3 py-1.5 text-[11px] whitespace-nowrap rounded-t-lg border border-b-0 transition-colors shrink-0"
                :class="activeGraphTab === gt.id
                  ? 'bg-ctp-mantle text-ctp-text border-ctp-surface1 font-semibold'
                  : 'bg-ctp-surface0/50 text-ctp-subtext0 border-transparent hover:bg-ctp-surface0 hover:text-ctp-subtext1'"
                :title="gt.title"
                @click="activeGraphTab = gt.id"
              >
                <span class="truncate">{{ gt.title }}</span>
                <span
                  role="button"
                  class="flex items-center justify-center w-4 h-4 rounded text-ctp-overlay1 hover:text-ctp-red hover:bg-ctp-red/15 cursor-pointer shrink-0"
                  :title="t('assetMgmt.graph.closeTab')"
                  @click.stop="closeGraphTab(gt.id)"
                >
                  <XMarkIcon class="w-3 h-3" />
                </span>
              </button>
            </div>
            <div class="flex-1 min-h-0">
              <SemanticGraphView
                v-for="gt in graphTabs"
                v-show="activeGraphTab === gt.id"
                :key="gt.id"
                :tab="gt"
                :diff-files="changedFilesForGraph"
                :compare-data="compareData"
                :file-index="graphFileIndexes[gt.id] ?? []"
                :comp-names="graphCompNames"
                @close="closeGraphTab"
              />
            </div>
          </template>
        </div>
        <div
          v-else
          ref="semScrollEl"
          class="flex-1 min-h-0 overflow-auto p-2.5 space-y-1.5"
        >
          <!-- 未归属清单加载失败横幅：后端错误文案本身可行动(如建索引指引)，不静默吞掉 -->
          <div
            v-if="tab === 'semantic' && unownedError"
            class="flex items-center gap-2 rounded-lg border border-ctp-red/30 bg-ctp-red/10 px-3 py-2 text-[11px] text-ctp-red"
          >
            <span class="flex-1 min-w-0 break-all">{{ unownedError || t('assetMgmt.unowned.loadFailed') }}</span>
            <button
              class="shrink-0 text-ctp-subtext0 hover:text-ctp-text"
              :title="t('assetMgmt.unowned.retry')"
              @click="loadUnownedFiles()"
            >
              <ArrowPathIcon class="w-3.5 h-3.5" />
            </button>
            <button
              class="shrink-0 text-ctp-overlay0 hover:text-ctp-red"
              :title="t('assetMgmt.unowned.dismiss')"
              @click="unownedError = ''"
            >
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
          <!-- 资产概览：作用说明 + 分类/粒度/标签 + 现有资产数量 -->
          <OverviewPanel v-if="tab === 'overview'" />

          <!-- 语义资产：按组件树文件树形式逐层展开(选 L0/L1 时以该层为初始列表) -->
          <SemanticTreePanel v-if="tab === 'semantic'" />

          <!-- 组件资产：按 KB 组件树文件目录树形式逐层展开(选 L0/L1 时以该层为初始列表) -->
        </div>
      </div>

      <!-- 分割线 -->
      <div
        class="w-4 shrink-0 -mx-0.5 flex items-center justify-center cursor-col-resize select-none touch-none group"
        :class="dragging ? 'cursor-col-resize' : ''"
        @pointerdown="onSplitPointerDown"
      >
        <div
          class="h-12 w-0.5 rounded-full bg-ctp-overlay1/40 transition-colors group-hover:bg-ctp-blue/60"
          :class="dragging ? '!bg-ctp-blue/70' : ''"
        />
      </div>

      <!-- 右：全局会话栏·inline 停靠(P1 决策2: 唯一对话栏——本页停靠形态) -->
      <div class="flex min-h-0 min-w-0 flex-1 flex-col">
        <ConversationDock inline scope="asset" default-kind="asset" :skill-scenarios="['extract', 'plan', 'capability']" />
      </div>
    </div>

    <WorkspaceModals />
  </div>
  <FileSourceCard
    v-if="fileCard"
    :file="fileCard.file"
    :assets="fileCard.assets"
    :compare-data="compareData"
    @close="fileCard = null"
    @goto="locateAsset"
  />
</template>

<style scoped>
/* 树行离屏跳过布局/绘制(配合前缀窗口渲染): 浏览器不维护不可见行样式与合成 */
.tree-row {
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
</style>
