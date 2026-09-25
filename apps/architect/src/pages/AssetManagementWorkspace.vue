<script setup lang="ts">
/**
 * 资产管理工作区(MS6-W1 重构：逻辑层已拆至 ./asset-workspace/ 八域 composable)。
 * 本文件仅保留：视图辅助(kindIcon/copyAsset) + setup 生命周期接线(窗口事件/
 * 会话钩子注册/轮询接管/初始加载) + 模板。模板逐行未动。
 */
import { onMounted, onUnmounted } from 'vue'
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
import { useAssetWorkspace } from './asset-workspace'
import { OTHER_KEY } from './asset-workspace/useAssetCore'

const { t } = useI18n()

const { splitPct, dragging, boxRef: splitBoxRef, onDown: onSplitPointerDown } = useSplitPane({ initial: 50 })

const ws = useAssetWorkspace()
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

// ---- 视图辅助(模板直接消费) ----

function kindIcon(k: SemanticAsset['kind']) {
  if (k === 'process') return BoltIcon
  if (k === 'decision') return AdjustmentsHorizontalIcon
  if (k === 'contract') return ServerStackIcon
  if (k === 'state') return AdjustmentsHorizontalIcon
  return CubeTransparentIcon
}

async function copyAsset(a: SemanticAsset) {
  const lines = [`${a.name} (${a.kind})`, `ID: ${a.id}`, a.desc]
  if (a.astRefs?.length) {
    lines.push('')
    lines.push(...a.astRefs.slice(0, 10).map((r) => `${r.file}:L${r.startLine}-L${r.endLine} ${r.symbol}`))
  }
  await copyText(lines.join('\n'))
}

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
          <template v-if="tab === 'overview'">
            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <ServerStackIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.overview.title') }}
                </span>
              </div>
              <div class="p-3 space-y-2">
                <p class="text-xs text-ctp-subtext1 leading-relaxed">
                  {{ t('assetMgmt.overview.desc') }}
                </p>
              </div>
            </div>

            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <Squares2X2Icon class="w-4 h-4 text-ctp-peach" />{{ t('assetMgmt.overview.classificationTitle') }}
                </span>
              </div>
              <div class="p-3 space-y-2">
                <p class="text-[10px] text-ctp-subtext0 leading-relaxed">
                  {{ t('assetMgmt.overview.classificationDesc') }}
                </p>
                <div class="grid grid-cols-2 gap-2">
                  <div
                    v-for="k in kinds"
                    :key="k.value"
                    class="border border-ctp-surface0 rounded-md p-2"
                  >
                    <span
                      class="chip !text-[10px]"
                      :class="kindChipClass(k.value)"
                    >{{ k.label }}</span>
                    <div class="text-[9px] text-ctp-overlay0 mt-0.5">
                      {{ t(`assetMgmt.overview.kind.${k.value}`) }}
                    </div>
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-1 pt-1">
                  <span class="text-[10px] text-ctp-subtext1 shrink-0">{{ t('assetMgmt.overview.levelLabel') }}</span>
                  <span
                    v-for="l in levels"
                    :key="l.value"
                    class="chip"
                    :class="levelChipClass(l.value)"
                  >{{ l.label }}</span>
                </div>
                <p class="text-[10px] text-ctp-subtext0 leading-relaxed pt-1">
                  {{ t('assetMgmt.overview.tagHint') }}
                </p>
              </div>
            </div>

            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <CubeTransparentIcon class="w-4 h-4 text-ctp-mauve" />{{ t('assetMgmt.overview.countTitle') }}
                </span>
              </div>
              <div class="p-3 space-y-2.5">
                <div class="flex items-center gap-3">
                  <div class="border border-ctp-blue/20 rounded-lg px-3 py-2 flex-1">
                    <div class="text-lg font-semibold text-ctp-blue">
                      {{ overviewStats ? overviewStats.total : '—' }}
                    </div>
                    <div class="text-[9px] text-ctp-overlay0">
                      {{ t('assetMgmt.overview.total') }}
                    </div>
                  </div>
                  <div class="border border-ctp-surface0 rounded-lg px-3 py-2 flex-1">
                    <div class="text-lg font-semibold text-ctp-text">
                      {{ compCatalog.length }}
                    </div>
                    <div class="text-[9px] text-ctp-overlay0">
                      {{ t('assetMgmt.overview.components') }}
                    </div>
                  </div>
                  <div class="border border-ctp-green/20 rounded-lg px-3 py-2 flex-1">
                    <div class="text-lg font-semibold text-ctp-green">
                      {{ overviewStats?.status?.active ?? statusCounts.active ?? 0 }}
                    </div>
                    <div class="text-[9px] text-ctp-overlay0">
                      {{ t('assetMgmt.overview.active') }}
                    </div>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">
                    {{ t('assetMgmt.overview.byKind') }}
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="k in kinds"
                      :key="k.value"
                      class="chip"
                      :class="kindChipClass(k.value)"
                    >{{ k.label }} · {{ overviewStats?.byKind?.[k.value] ?? 0 }}</span>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">
                    {{ t('assetMgmt.overview.byLevel') }}
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="l in levels"
                      :key="l.value"
                      class="chip"
                      :class="levelChipClass(l.value)"
                    >{{ l.label }} · {{ overviewStats?.byLevel?.[l.value] ?? 0 }}</span>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">
                    {{ t('assetMgmt.overview.statusLabel') }}
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    <span class="chip bg-ctp-green/15 text-ctp-green">active · {{ overviewStats?.status?.active ?? statusCounts.active ?? 0 }}</span>
                    <span class="chip bg-ctp-yellow/15 text-ctp-yellow">stale · {{ overviewStats?.status?.stale ?? statusCounts.stale ?? 0 }}</span>
                    <span class="chip bg-ctp-red/15 text-ctp-red">deleted · {{ overviewStats?.status?.deleted ?? statusCounts.deleted ?? 0 }}</span>
                    <span class="chip bg-ctp-overlay0/20 text-ctp-overlay1">needsUpdate · {{ overviewStats?.status?.needsUpdate ?? statusCounts.needsUpdate ?? 0 }}</span>
                  </div>
                </div>

                <div class="border-t border-ctp-surface0 pt-2 flex items-center gap-2">
                  <button
                    class="btn btn-xs btn-ghost"
                    :disabled="purging"
                    @click="runPurge"
                  >
                    <TrashIcon class="w-3 h-3" />{{ purging ? t('assetMgmt.overview.purging') : t('assetMgmt.overview.purge') }}
                  </button>
                  <span class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.overview.purgeHint') }}</span>
                </div>
              </div>
            </div>

            <!-- M1 认知框架：三组默认预设 + 标准变更确认流（plan-C §3；框架即配置） -->
            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <AdjustmentsHorizontalIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.framework.title') }}
                </span>
                <span
                  v-if="frameworkInfo?.config?.frameworkVersion"
                  class="chip bg-ctp-surface0 text-ctp-overlay1 font-mono !text-[9px]"
                >v{{ frameworkInfo.config.frameworkVersion }}</span>
              </div>
              <div class="p-3 space-y-2">
                <div class="grid grid-cols-3 gap-2">
                  <button
                    v-for="tier in (['low', 'mid', 'high'] as const)"
                    :key="tier"
                    class="border rounded-md p-2 text-left transition-colors"
                    :class="frameworkInfo?.config?.activeTier === tier
                      ? 'border-ctp-blue/60 bg-ctp-blue/10'
                      : 'border-ctp-surface0 hover:border-ctp-blue/40'"
                    :disabled="fwLoading || fwSwitching"
                    @click="switchTier(tier)"
                  >
                    <div class="flex items-center gap-1.5">
                      <span class="text-[11px] font-semibold text-ctp-text">{{ t(`assetMgmt.framework.tier.${tier}`) }}</span>
                      <span
                        v-if="frameworkInfo?.config?.activeTier === tier"
                        class="chip !text-[8px] bg-ctp-blue/20 text-ctp-blue"
                      >{{ t('assetMgmt.framework.active') }}</span>
                    </div>
                    <div class="text-[9px] text-ctp-overlay0 mt-1 leading-snug">
                      {{ t(`assetMgmt.framework.tierDesc.${tier}`) }}
                    </div>
                    <div class="text-[9px] text-ctp-subtext0 mt-1 font-mono">
                      {{ frameworkInfo?.presets?.[tier]?.x?.length ?? '—' }} {{ t('assetMgmt.framework.kindsUnit') }} · {{ frameworkInfo?.presets?.[tier]?.y?.length ?? '—' }} {{ t('assetMgmt.framework.levelsUnit') }}
                    </div>
                  </button>
                </div>
                <p class="text-[9px] text-ctp-overlay0 leading-relaxed">
                  {{ t('assetMgmt.framework.hint') }}
                </p>
              </div>
            </div>

            <!-- M1 覆盖度（诚实呈现部分真相：plan-C §4.3） -->
            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <ChartBarSquareIcon class="w-4 h-4 text-ctp-green" />{{ t('assetMgmt.coverage.title') }}
                </span>
              </div>
              <div class="p-3 space-y-2">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="chip bg-ctp-green/15 text-ctp-green">{{ t('assetMgmt.coverage.extracted') }} · {{ coverageInfo?.extracted ?? '—' }}</span>
                  <span class="chip bg-ctp-yellow/15 text-ctp-yellow">{{ t('assetMgmt.coverage.stale') }} · {{ coverageInfo?.stale ?? '—' }}</span>
                  <span class="chip bg-ctp-surface0 text-ctp-subtext0">
                    {{ t('assetMgmt.coverage.components') }} · {{ coverageInfo?.componentsCovered ?? '—' }}/{{ coverageInfo?.componentsTotal ?? '—' }}
                  </span>
                </div>
                <div
                  v-if="coverageInfo?.components?.some((c) => c.coverage === 'none')"
                  class="space-y-0.5"
                >
                  <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.coverage.noneHint') }}</div>
                  <div class="flex flex-wrap gap-1">
                    <span
                      v-for="c in coverageInfo.components.filter((c) => c.coverage === 'none').slice(0, 8)"
                      :key="c.componentId"
                      class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1"
                    >{{ c.name }}</span>
                    <span
                      v-if="coverageInfo.components.filter((c) => c.coverage === 'none').length > 8"
                      class="text-[9px] text-ctp-overlay0"
                    >+{{ coverageInfo.components.filter((c) => c.coverage === 'none').length - 8 }}</span>
                  </div>
                </div>
                <p class="text-[9px] text-ctp-overlay0 leading-relaxed">
                  {{ t('assetMgmt.coverage.hint') }}
                </p>
              </div>
            </div>

            <!-- 基线变更（三视图 diff · 概览：变更文件清单） -->
            <div v-if="diffMode" class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <ArrowsRightLeftIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.diff.title') }}
                </span>
                <span class="flex items-center gap-1">
                  <span v-if="baselineDiffData?.aligned" class="chip bg-ctp-green/15 text-ctp-green">{{ t('assetMgmt.diff.aligned') }}</span>
                  <span v-else-if="baselineDiffData?.stale" class="chip bg-ctp-yellow/15 text-ctp-yellow">{{ t('assetMgmt.diff.stale', { n: totalChanged }) }}</span>
                  <span v-else class="chip bg-ctp-surface0 text-ctp-subtext0">{{ t('assetMgmt.diff.noBaseline') }}</span>
                </span>
              </div>
              <div v-if="diffLoading" class="p-3 text-[10px] text-ctp-overlay0">{{ t('assetMgmt.reconciling') }}</div>
              <div v-else-if="!baselineDiffData" class="p-3 text-[10px] text-ctp-overlay0">—</div>
              <div v-else-if="!totalChanged" class="p-3 text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.noChanges') }}</div>
              <div v-else class="p-3 grid grid-cols-3 gap-3">
                <div v-for="col in [
                  { key: 'added' as const, label: t('assetMgmt.diff.added'), tone: 'text-ctp-green', files: baselineDiffData.files.added },
                  { key: 'modified' as const, label: t('assetMgmt.diff.modified'), tone: 'text-ctp-yellow', files: baselineDiffData.files.modified },
                  { key: 'deleted' as const, label: t('assetMgmt.diff.deleted'), tone: 'text-ctp-red', files: baselineDiffData.files.deleted },
                ]" :key="col.key" class="min-w-0">
                  <div class="flex items-center gap-1 mb-1">
                    <span class="text-[10px] font-semibold" :class="col.tone">{{ col.label }}</span>
                    <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ col.files.length }}</span>
                  </div>
                  <div class="space-y-0.5 max-h-40 overflow-y-auto">
                    <div v-for="f in col.files.slice(0, 30)" :key="f" class="font-mono text-[9px] text-ctp-subtext0 truncate" :title="f">{{ f }}</div>
                    <div v-if="col.files.length > 30" class="text-[9px] text-ctp-overlay0">+{{ col.files.length - 30 }}</div>
                    <div v-if="!col.files.length" class="text-[9px] text-ctp-overlay0">—</div>
                  </div>
                </div>
              </div>
              <div v-if="baselineDiffData && baselineDiffData.dirty" class="px-3 pb-2 text-[9px] text-ctp-overlay0">
                {{ t('assetMgmt.diff.dirty') }}: {{ baselineDiffData.dirty }}
              </div>

              <!-- 对比结果明细：资产变化 + 组件变化(其他桶) + 跨域联系；起止 head 在顶部工具栏选择 -->
              <div class="px-3 pb-3 pt-2 mt-1 border-t border-ctp-surface0 space-y-2">
                <p v-if="compareLoading" class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.cmpRunning') }}</p>
                <p v-else-if="compareError" class="text-[10px] text-ctp-red">{{ compareError }}</p>
                <template v-else-if="compareData">
                  <p v-if="compareData.noChanges" class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.noChanges') }}</p>
                  <template v-else>
                    <div class="flex items-center gap-2 text-[10px] flex-wrap">
                      <span class="text-ctp-subtext1 font-semibold">{{ t('assetMgmt.diff.assetDelta') }}</span>
                      <span v-if="compareData.cached" class="chip !text-[8px] bg-ctp-surface0 text-ctp-overlay0">{{ t('assetMgmt.diff.cached') }}</span>
                      <span class="text-ctp-overlay1">{{ t('assetMgmt.diff.stableN', { n: compareData.assets.stable }) }}</span>
                      <span class="text-ctp-yellow">{{ t('assetMgmt.diff.changedN', { n: compareData.assets.changedTotal }) }}</span>
                      <span v-if="compareData.assets.newTotal" class="text-ctp-green">{{ t('assetMgmt.diff.newN', { n: compareData.assets.newTotal }) }}</span>
                      <span v-if="compareData.assets.removedTotal" class="text-ctp-red">{{ t('assetMgmt.diff.removedN', { n: compareData.assets.removedTotal }) }}</span>
                      <span v-if="compareData.assets.pending.count" class="text-ctp-peach">{{ t('assetMgmt.diff.pendingN', { n: compareData.assets.pending.count }) }}</span>
                      <span v-if="compareData.newFileCount" class="text-ctp-green">{{ t('assetMgmt.diff.pendingNew', { n: compareData.newFileCount }) }}</span>
                    </div>
                    <div class="space-y-0.5">
                      <div v-for="c in compareData.components" :key="c.id" class="flex items-center gap-2 text-[10px] min-w-0">
                        <span
                          class="truncate min-w-0 flex-1"
                          :class="c.id === '__other__' ? 'text-ctp-overlay1 italic' : 'text-ctp-text font-medium'"
                          :title="c.id === '__other__' ? t('assetMgmt.diff.otherBucketHint') : c.id"
                        >{{ c.name || t('assetMgmt.diff.otherBucket') }}</span>
                        <span class="text-ctp-green font-mono shrink-0">+{{ c.added }}</span>
                        <span class="text-ctp-yellow font-mono shrink-0">~{{ c.modified }}</span>
                        <span class="text-ctp-red font-mono shrink-0">-{{ c.deleted }}</span>
                      </div>
                    </div>
                    <!-- 资产明细：目标侧新增 / 需更新(side 标注) / 待提取文件 -->
                    <div v-if="compareData.assets.new.length" class="space-y-0.5">
                      <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.diff.newAssets') }}</div>
                      <div v-for="a in compareData.assets.new.slice(0, 20)" :key="a.id" class="flex items-center gap-2 text-[10px] min-w-0">
                        <span class="truncate min-w-0 flex-1 text-ctp-text" :title="a.id">{{ a.name }}</span>
                        <span class="chip !text-[8px] shrink-0" :class="kindChipClass(a.kind)">{{ t(`assetMgmt.kind.${a.kind}`) }}</span>
                        <span class="font-mono text-[9px] text-ctp-overlay0 shrink-0" :title="a.component">{{ a.component === '__other__' ? t('assetMgmt.diff.otherBucket') : a.component }}</span>
                      </div>
                    </div>
                    <div v-if="compareData.assets.changed.length" class="space-y-0.5">
                      <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.diff.changedAssets') }}</div>
                      <div v-for="a in compareData.assets.changed.slice(0, 20)" :key="a.id" class="flex items-center gap-2 text-[10px] min-w-0">
                        <span class="truncate min-w-0 flex-1 text-ctp-text" :title="a.id">{{ a.name }}</span>
                        <span
                          class="chip !text-[8px] shrink-0"
                          :class="a.strong ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-surface0 text-ctp-overlay1'"
                          :title="t(a.strong ? 'assetMgmt.diff.strongHitHint' : 'assetMgmt.diff.weakHitHint')"
                        >{{ t(a.strong ? 'assetMgmt.diff.strongHit' : 'assetMgmt.diff.weakHit') }}</span>
                        <span
                          class="chip !text-[8px] shrink-0"
                          :class="a.side === 'target' ? 'bg-ctp-green/15 text-ctp-green' : a.side === 'base' ? 'bg-ctp-blue/15 text-ctp-blue' : 'bg-ctp-peach/15 text-ctp-peach'"
                          :title="t(`assetMgmt.diff.side.${a.side || 'stale'}`)"
                        >{{ t(`assetMgmt.diff.side.${a.side || 'stale'}`) }}</span>
                        <span class="font-mono text-[9px] text-ctp-overlay0 shrink-0" :title="a.component">{{ a.component === '__other__' ? t('assetMgmt.diff.otherBucket') : a.component }}</span>
                      </div>
                      <div v-if="compareData.assets.changedWeak" class="text-[9px] text-ctp-overlay0">
                        {{ t('assetMgmt.diff.weakSummary', { strong: compareData.assets.changedStrong, weak: compareData.assets.changedWeak }) }}
                      </div>
                    </div>
                    <div v-if="compareData.assets.pending.count" class="space-y-0.5">
                      <div class="flex items-center gap-2">
                        <span class="text-[9px] text-ctp-peach">{{ t('assetMgmt.diff.pendingFiles', { n: compareData.assets.pending.count }) }}</span>
                        <button
                          v-if="compareData.targetIsWorktree && !extractingPending"
                          class="btn btn-xs btn-blue !py-0 !px-1.5 !text-[9px]"
                          :title="t('assetMgmt.diff.extractRecompareHint', { n: compareData.assets.pending.count })"
                          @click="extractPendingAndRecompare"
                        >
                          <SparklesIcon class="w-2.5 h-2.5" />{{ t('assetMgmt.diff.extractRecompare', { n: compareData.assets.pending.count }) }}
                        </button>
                        <span v-if="extractingPending" class="inline-flex items-center gap-1 text-[9px] text-ctp-overlay0"><ArrowPathIcon class="w-2.5 h-2.5 animate-spin" />{{ t('assetMgmt.diff.extracting') }}</span>
                      </div>
                      <div v-for="f in compareData.assets.pending.files.slice(0, 30)" :key="f" class="font-mono text-[9px] text-ctp-subtext0 truncate" :title="f">{{ f }}</div>
                      <div v-if="compareData.assets.pending.files.length > 30" class="text-[9px] text-ctp-overlay0">+{{ compareData.assets.pending.files.length - 30 }}</div>
                      <p v-if="!compareData.targetIsWorktree" class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.diff.pendingCommitHint') }}</p>
                    </div>
                    <div v-if="compareData.crossLinkCount" class="text-[9px] text-ctp-overlay0 leading-relaxed">
                      {{ t('assetMgmt.diff.crossLinks', { n: compareData.crossLinkCount } ) }}
                      <span
                        v-for="(l, i) in compareData.crossLinks.slice(0, 3)"
                        :key="i"
                        class="ml-1 font-mono text-ctp-subtext0"
                      >{{ l.fromName }}→{{ l.toName }}</span>
                    </div>
                  </template>
                </template>
              </div>
            </div>
          </template>

          <!-- 语义资产：按组件树文件树形式逐层展开(选 L0/L1 时以该层为初始列表) -->
          <template v-if="tab === 'semantic'">
            <template
              v-for="row in renderedTreeRows"
              :key="row.key"
            >
              <!-- 组件(目录)节点 -->
              <template v-if="row.t === 'comp'">
                <div
                  v-for="g in row.g ? [row.g] : []"
                  :key="row.key + ':h'"
                >
              <div
                class="flex items-center gap-1.5 px-1 pt-1.5 pb-0.5 tree-row"
                :style="{ paddingLeft: (row.depth * 12) + 'px' }"
              >
                <button
                  v-if="(compCollapsible.get(g.key) ?? false) || hasChildren(g.key) || (subtreeCount.get(g.key) ?? 0) > 0"
                  class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                  @click="toggleOpen(g.key)"
                >
                  <ChevronDownIcon
                    v-if="compExpandState(g.key)"
                    class="w-3 h-3"
                  />
                  <ChevronRightIcon
                    v-else
                    class="w-3 h-3"
                  />
                </button>
                <span
                  v-else
                  class="w-3.5 shrink-0"
                />
                <ServerStackIcon
                  v-if="g.key !== OTHER_KEY"
                  class="w-3 h-3 text-ctp-blue shrink-0"
                />
                <DocumentTextIcon
                  v-else
                  class="w-3 h-3 text-ctp-yellow shrink-0"
                />
                <span
                  v-if="g.hierLevel"
                  class="chip !text-[8px] bg-ctp-surface0 text-ctp-overlay1 shrink-0 font-mono"
                >{{ g.hierLevel }}</span>
                <span class="text-[10px] font-semibold text-ctp-subtext1 truncate" :title="compMetaText(g.key) || undefined">{{ g.name }}</span>
                <!-- KB 降级提示：组件树来自本地快照/资产 scopeKey，名称可能与 KB 目录不一致 -->
                <span
                  v-if="!compCatalog.length && g.key !== OTHER_KEY"
                  class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                  :title="t('assetMgmt.localSnapshotHint')"
                >{{ t('assetMgmt.localSnapshot') }}</span>
                <!-- 拷贝/引用 名称+ID：与 KB 组件目录严格同名同 ID，供资产管理对话精准对接 -->
                <template v-if="g.key !== OTHER_KEY">
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-green p-0.5 shrink-0"
                    :title="t('assetMgmt.compCopy')"
                    @click="copyCompRef(g.key, g.name, g.key)"
                  >
                    <CheckIcon
                      v-if="copiedKey === g.key"
                      class="w-3 h-3 text-ctp-green"
                    />
                    <ClipboardDocumentIcon
                      v-else
                      class="w-3 h-3"
                    />
                  </button>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-blue p-0.5 shrink-0"
                    :title="t('assetMgmt.compRef')"
                    @click="referenceComp(g.name, g.key)"
                  >
                    <ChatBubbleLeftRightIcon class="w-3 h-3" />
                  </button>
                </template>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ subtreeCount.get(g.key) ?? 0 }}</span>
                <!-- 基线对比 · 组件(子树)变化上卷：需更新/新增/移除 彩色计数 -->
                <template v-if="diffMode && diffRollup.get(g.key)">
                  <span
                    v-if="diffRollup.get(g.key)!.changed"
                    class="chip !text-[8px] bg-ctp-yellow/15 text-ctp-yellow shrink-0 font-mono"
                    :title="t('assetMgmt.diff.changedN', { n: diffRollup.get(g.key)!.changed })"
                  >{{ t('assetMgmt.diff.chipChanged', { n: diffRollup.get(g.key)!.changed }) }}</span>
                  <span
                    v-if="diffRollup.get(g.key)!.added"
                    class="chip !text-[8px] bg-ctp-green/15 text-ctp-green shrink-0 font-mono"
                    :title="t('assetMgmt.diff.newN', { n: diffRollup.get(g.key)!.added })"
                  >{{ t('assetMgmt.diff.chipAdded', { n: diffRollup.get(g.key)!.added }) }}</span>
                  <span
                    v-if="diffRollup.get(g.key)!.deleted"
                    class="chip !text-[8px] bg-ctp-red/15 text-ctp-red shrink-0 font-mono"
                    :title="t('assetMgmt.diff.removedN', { n: diffRollup.get(g.key)!.deleted })"
                  >{{ t('assetMgmt.diff.chipRemoved', { n: diffRollup.get(g.key)!.deleted }) }}</span>
                </template>
                <!-- 未归属组：截断提示 + 循环批量提取(后端作业，页面关闭不影响；每批 10) -->
                <template v-if="g.key === OTHER_KEY">
                  <span
                    v-if="unownedMeta?.truncated"
                    class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                    :title="t('assetMgmt.unowned.truncatedHint', { total: unownedMeta?.totalFiles ?? 0, owned: unownedMeta?.ownedCount ?? 0 })"
                  >{{ t('assetMgmt.unowned.truncated') }}</span>
                  <span
                    v-if="unownedExtracting"
                    class="chip !text-[9px] bg-ctp-blue/15 text-ctp-blue shrink-0 font-mono"
                    :title="unownedJobHint"
                  >{{ t('assetMgmt.unowned.extracting', { done: unownedJob?.done ?? 0, total: unownedJob?.total ?? 0 }) }}</span>
                  <button
                    v-if="unownedExtracting"
                    class="text-ctp-overlay0 hover:text-ctp-red p-0.5 shrink-0"
                    :title="t('assetMgmt.unowned.stop')"
                    @click="stopUnownedExtract"
                  >
                    <StopIcon class="w-3 h-3" />
                  </button>
                  <button
                    v-else
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5 shrink-0 disabled:opacity-40"
                    :disabled="unownedExtractingOne !== ''"
                    :title="t('assetMgmt.unowned.extractAllHint')"
                    @click="extractAllUnowned"
                  >
                    <SparklesIcon class="w-3 h-3" />
                  </button>
                </template>
                <template v-if="g.key !== OTHER_KEY">
                  <span
                    v-if="compCoverage(g.key)"
                    class="chip !text-[8px] shrink-0"
                    :class="compCoverage(g.key) === 'full' ? 'bg-ctp-green/15 text-ctp-green' : compCoverage(g.key) === 'partial' ? 'bg-ctp-yellow/15 text-ctp-yellow' : 'bg-ctp-surface0 text-ctp-overlay1'"
                  >{{ t(`assetMgmt.coverage.state.${compCoverage(g.key)}`) }}</span>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                    :title="t('assetMgmt.chatExtractHint')"
                    @click="askExtractComponent(g.key, g.name)"
                  >
                    <SparklesIcon class="w-3 h-3" />
                  </button>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                    :title="t('assetMgmt.graph.viewCompGraph')"
                    @click="openGraphTab('comp', g.key, g.name)"
                  >
                    <Squares2X2Icon class="w-3 h-3" />
                  </button>
                </template>
              </div>
                </div>
              </template>
              <!-- 文件节点：独有文件，折叠其下资产 -->
              <div
                v-else-if="row.t === 'file'"
                class="flex items-center gap-1.5 px-1 py-0.5 tree-row"
                :style="{ paddingLeft: (row.depth * 12) + 'px' }"
              >
                <button
                  v-if="row.n"
                  class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                  @click="toggleFileOpen(row.fk!)"
                >
                  <ChevronDownIcon
                    v-if="fileExpandState(row.fk!)"
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
                <DocumentTextIcon class="w-3 h-3 text-ctp-overlay1 shrink-0" />
                <span
                  class="font-mono text-[10px] text-ctp-subtext1 truncate"
                  :title="row.file"
                >{{ fileBase(row.file!) }}</span>
                <!-- 文件级语义图谱：该文件锚定的资产子图(有资产才可看) -->
                <button
                  v-if="row.n"
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5 shrink-0"
                  :title="t('assetMgmt.graph.viewFileGraph')"
                  @click="openGraphTab('file', row.file!, fileBase(row.file!))"
                >
                  <Squares2X2Icon class="w-3 h-3" />
                </button>
                <!-- 文件源码资产卡：复用图谱资产卡服务/缓存，列表内浮卡展示(无资产文件=纯源码浏览) -->
                <button
                  class="text-ctp-overlay0 hover:text-ctp-blue p-0.5 shrink-0"
                  :title="t('assetMgmt.fileCard.view')"
                  @click="openFileCard(row.file!)"
                >
                  <CodeBracketIcon class="w-3 h-3" />
                </button>
                <!-- 基线对比 · 文件级变化归属：需更新/新增/移除彩色计数 + 待提取/新增文件 -->
                <template v-if="diffMode && row.file">
                  <span
                    v-if="diffFileCounts.get(row.file)?.changed"
                    class="chip !text-[8px] bg-ctp-yellow/15 text-ctp-yellow shrink-0 font-mono"
                  >{{ t('assetMgmt.diff.chipChanged', { n: diffFileCounts.get(row.file)!.changed }) }}</span>
                  <span
                    v-if="diffFileCounts.get(row.file)?.added"
                    class="chip !text-[8px] bg-ctp-green/15 text-ctp-green shrink-0 font-mono"
                  >{{ t('assetMgmt.diff.chipAdded', { n: diffFileCounts.get(row.file)!.added }) }}</span>
                  <span
                    v-if="diffFileCounts.get(row.file)?.deleted"
                    class="chip !text-[8px] bg-ctp-red/15 text-ctp-red shrink-0 font-mono"
                  >{{ t('assetMgmt.diff.chipRemoved', { n: diffFileCounts.get(row.file)!.deleted }) }}</span>
                  <span
                    v-if="pendingFileSet.has(row.file)"
                    class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                    :title="t('assetMgmt.diff.pendingN', { n: compareData?.assets.pending.count ?? 0 })"
                  >{{ t('assetMgmt.diff.chipPending') }}</span>
                  <span
                    v-else-if="addedFileSet.has(row.file)"
                    class="chip !text-[8px] bg-ctp-green/15 text-ctp-green shrink-0"
                    :title="t('assetMgmt.diff.pendingNew', { n: compareData?.newFileCount ?? 0 })"
                  >{{ t('assetMgmt.diff.chipNewFile') }}</span>
                </template>
                <span
                  v-if="!row.unowned"
                  class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]"
                >{{ row.n }}</span>
                <!-- 未归属文件行：未提取标记 + 跨组件关联 chip + 单文件提取 -->
                <template v-if="row.unowned">
                  <span
                    v-if="row.extractable === false"
                    class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay0 shrink-0"
                    :title="t('assetMgmt.unowned.noSymbolsHint')"
                  >{{ t('assetMgmt.unowned.noSymbols') }}</span>
                  <span
                    v-else-if="!row.n"
                    class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1 shrink-0"
                  >{{ t('assetMgmt.unowned.noAssets') }}</span>
                  <span
                    v-if="row.n"
                    class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]"
                  >{{ row.n }}</span>
                  <span
                    v-if="unownedLinks.get(row.file || '')"
                    class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal shrink-0 cursor-help"
                    :title="unownedLinkTitle(unownedLinks.get(row.file || '')!)"
                  >{{ t('assetMgmt.unowned.related', { n: unownedLinks.get(row.file || '')!.crossCount }) }}</span>
                  <button
                    v-if="row.extractable !== false"
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5 shrink-0 disabled:opacity-40"
                    :disabled="unownedExtractingOne !== '' || unownedExtracting"
                    :title="t('assetMgmt.unowned.extractOne')"
                    @click="extractUnownedFile(row.file!)"
                  >
                    <SparklesIcon
                      class="w-3 h-3"
                      :class="{ 'animate-pulse text-ctp-mauve': unownedExtractingOne === row.file }"
                    />
                  </button>
                </template>
              </div>
              <!-- 资产卡片(挂文件下/组件直属) -->
              <div
                v-else
                class="mt-0.5 tree-row"
                :style="{ paddingLeft: (row.depth * 12) + 'px' }"
              >
                <div
                  v-for="a in row.a ? [row.a] : []"
                  :key="row.key"
                  class="border border-ctp-mauve/20 hover:border-ctp-mauve/40 rounded-lg overflow-hidden"
                >
                <div class="flex items-center gap-1.5 px-2 py-1.5">
                  <component
                    :is="kindIcon(a.kind)"
                    class="w-3.5 h-3.5 text-ctp-mauve shrink-0"
                  />
                  <span class="chip !text-[9px] shrink-0" :class="kindChipClass(a.kind)">
                    {{ t(`assetMgmt.kind.${a.kind}`) }}
                  </span>
                  <span
                    v-if="a.level"
                    class="chip !text-[9px] shrink-0"
                    :class="levelChipClass(a.level)"
                  >{{ t(`assetMgmt.level.${a.level}`) }}</span>
                  <span class="text-[11px] font-medium text-ctp-text truncate">{{ a.name }}</span>
                  <span
                    v-if="a.renamedFrom"
                    class="chip !text-[9px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                    :title="t('assetMgmt.canonicalHint')"
                  >{{ t('assetMgmt.renamed') }}: {{ a.renamedFrom }}</span>
                  <span
                    v-if="a.needsUpdate || a.status === 'stale'"
                    class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                  >{{ t('assetMgmt.needsUpdate') }}</span>
                  <span
                    v-else-if="a.status === 'deleted'"
                    class="chip !text-[9px] bg-ctp-red/15 text-ctp-red shrink-0"
                  >{{ t('assetMgmt.deleted') }}</span>
                  <span
                    v-else-if="a.change === 'added'"
                    class="chip !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0"
                  >{{ t('assetMgmt.added') }}</span>
                  <span
                    v-else-if="a.change === 'modified'"
                    class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                  >{{ t('assetMgmt.modified') }}</span>
                  <span
                    v-if="diffMode && changeMarkById.get(a.id)"
                    class="chip !text-[9px] shrink-0"
                    :class="changeMarkById.get(a.id) === 'added' ? 'bg-ctp-green/15 text-ctp-green' : changeMarkById.get(a.id) === 'deleted' ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-yellow/15 text-ctp-yellow'"
                    :title="diffMarkLabel(changeMarkById.get(a.id))"
                  >
                    <ArrowsRightLeftIcon class="w-2.5 h-2.5 inline -mt-0.5" />
                    {{ diffMarkLabel(changeMarkById.get(a.id)) }}
                  </span>
                  <!-- 未归属资产与组件内资产的跨组件关联：点击跳图谱聚焦，出入边即关联 -->
                  <span
                    v-if="unownedLinkByAssetId.get(a.id)"
                    class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal shrink-0 cursor-pointer hover:bg-ctp-teal/25"
                    :title="unownedLinkTitle(unownedLinkByAssetId.get(a.id)!)"
                    @click="openGraphTab('asset', a.id, a.name)"
                  >{{ t('assetMgmt.unowned.related', { n: unownedLinkByAssetId.get(a.id)!.crossCount }) }}</span>
                  <span class="flex-1" />
                  <span
                    class="text-[9px] text-ctp-overlay0 font-mono"
                    :title="[a.canonicalKey ? t('assetMgmt.canonicalHint') + ' · ' + a.canonicalKey : '', ...(a.nameAlias ?? []).map((x) => t('assetMgmt.renamed') + ': ' + x)].filter(Boolean).join('\n') || undefined"
                  >{{ a.id }}</span>
                  <span class="text-[9px] text-ctp-overlay0">{{ a.astRefs?.length ?? 0 }} AST</span>
                  <button
                    v-if="!usable(a)"
                    class="text-ctp-yellow hover:text-ctp-peach p-0.5"
                    :title="t('assetMgmt.refresh')"
                    @click="refreshOne(a)"
                  >
                    <ArrowPathIcon class="w-3 h-3" />
                  </button>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                    :title="t('assetMgmt.reference')"
                    @click="referenceAsset(a)"
                  >
                    <ScaleIcon class="w-3 h-3" />
                  </button>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                    :title="t('assetMgmt.graph.viewAssetGraph')"
                    @click="openGraphTab('asset', a.id, a.name)"
                  >
                    <Squares2X2Icon class="w-3 h-3" />
                  </button>
                  <button
                    v-if="a.kind === 'entity' || a.kind === 'state'"
                    class="text-ctp-overlay0 hover:text-ctp-teal p-0.5"
                    :title="t('assetMgmt.viewDiagram')"
                    @click="openAssetDiagram(a)"
                  >
                    <ChartBarSquareIcon class="w-3 h-3" />
                  </button>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                    :title="t('assetMgmt.copy')"
                    @click="copyAsset(a)"
                  >
                    <ClipboardDocumentIcon class="w-3 h-3" />
                  </button>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                    :title="t('assetMgmt.expand')"
                    @click="toggle(a.id)"
                  >
                    <ChevronDownIcon
                      v-if="expanded[a.id]"
                      class="w-3.5 h-3.5"
                    />
                    <ChevronRightIcon
                      v-else
                      class="w-3.5 h-3.5"
                    />
                  </button>
                </div>
                <p
                  v-if="!expanded[a.id] && a.desc"
                  class="px-2 pb-1.5 text-[10px] truncate text-ctp-teal cursor-pointer hover:text-ctp-sky"
                  :title="t('assetMgmt.descReadyHint')"
                  @click="toggle(a.id)"
                >{{ t('assetMgmt.descReady') }}</p>
                <p
                  v-else-if="!expanded[a.id]"
                  class="px-2 pb-1.5 text-[10px] line-clamp-2 whitespace-pre-wrap text-ctp-overlay0 italic cursor-pointer hover:text-ctp-subtext0"
                  :title="t('assetMgmt.descPendingHint')"
                  @click="toggle(a.id)"
                >
                  {{ t('assetMgmt.descPending') }}
                </p>
                <div
                  v-if="expanded[a.id]"
                  class="border-t border-ctp-mauve/15 px-2 py-1.5 space-y-1 text-[10px]"
                >
                  <div
                    v-if="detailLoading[a.id] && a.detail === undefined"
                    class="text-ctp-overlay0 animate-pulse"
                  >
                    {{ t('assetMgmt.detailLoading') }}
                  </div>
                  <div class="flex items-start gap-1.5">
                    <SparklesIcon class="w-3 h-3 shrink-0 mt-0.5 text-ctp-peach" />
                    <p
                      v-if="a.desc"
                      class="flex-1 m-0 whitespace-pre-wrap text-ctp-subtext1"
                    >{{ a.desc }}</p>
                    <button
                      v-else
                      class="btn btn-xs btn-ghost"
                      :disabled="!!descLoading[a.id]"
                      @click="genDesc(a)"
                    >{{ t('assetMgmt.genDesc') }}</button>
                  </div>
                  <div v-if="a.detail?.fields?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.fields') }}
                    </div>
                    <div
                      v-for="f in a.detail.fields"
                      :key="f.name"
                      class="pl-2"
                    >
                      <span class="font-mono text-ctp-text">{{ f.name }}</span><span class="text-ctp-overlay0">: {{ f.type ?? '—' }}</span> {{ f.semantic ? `— ${f.semantic}` : '' }}
                    </div>
                  </div>
                  <div v-if="a.detail?.steps?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.steps') }}
                    </div>
                    <div
                      v-for="(s, si) in a.detail.steps"
                      :key="si"
                      class="pl-2"
                    >
                      {{ s.order ?? si + 1 }}. {{ s.semantic }}
                    </div>
                  </div>
                  <div v-if="a.detail?.branches?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.branches') }}
                    </div>
                    <div
                      v-for="(b, bi) in a.detail.branches"
                      :key="bi"
                      class="pl-2"
                    >
                      <span class="font-mono text-ctp-text">if {{ b.condition ?? '?' }}</span> → {{ b.then ?? '—' }}<span v-if="b.else"> / else {{ b.else }}</span>
                    </div>
                  </div>
                  <div v-if="a.detail?.relations?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.relations') }}
                    </div>
                    <div
                      v-for="(r, ri) in a.detail.relations"
                      :key="ri"
                      class="pl-2"
                    >
                      <span class="chip !text-[8px] bg-ctp-surface0 text-ctp-overlay1">{{ r.type ?? 'ref' }}</span><span class="font-mono text-ctp-text">{{ r.target ?? '?' }}</span><span
                        v-if="r.methods?.length"
                        class="font-mono text-ctp-overlay0"
                      >{{ r.methods.join('/') }}</span><span
                        v-if="r.semantic"
                        class="text-ctp-subtext0"
                      > — {{ r.semantic }}</span>
                    </div>
                  </div>
                  <div v-if="a.detail?.states?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.states') }}
                    </div>
                    <div class="pl-2 flex flex-wrap gap-1">
                      <span
                        v-for="(st, si) in a.detail.states"
                        :key="si"
                        class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0"
                      >{{ st.name }}<template v-if="st.initial"> · {{ t('assetMgmt.stateInitial') }}</template><template v-if="st.final"> · {{ t('assetMgmt.stateFinal') }}</template></span>
                    </div>
                  </div>
                  <div v-if="a.detail?.transitions?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.transitions') }}
                    </div>
                    <div
                      v-for="(tr, ti) in a.detail.transitions"
                      :key="ti"
                      class="pl-2 font-mono text-ctp-overlay0"
                    >
                      {{ tr.from ?? '?' }} → {{ tr.to ?? '?' }}<template v-if="tr.event">
                        on {{ tr.event }}
                      </template><template v-if="tr.condition">
                        [{{ tr.condition }}]
                      </template>
                    </div>
                  </div>
                  <div v-if="a.detail?.configSource || a.detail?.constraints?.length || a.detail?.thresholds?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.constraints') }}
                    </div>
                    <div
                      v-if="a.detail?.configSource"
                      class="pl-2"
                    >
                      {{ t('assetMgmt.configSource') }}: <span class="font-mono text-ctp-overlay0">{{ a.detail.configSource }}</span>
                    </div>
                    <div
                      v-for="(c, ci) in (a.detail?.constraints ?? [])"
                      :key="`c${ci}`"
                      class="pl-2 font-mono text-ctp-text"
                    >
                      {{ c }}
                    </div>
                    <div
                      v-for="(th, thi) in (a.detail?.thresholds ?? [])"
                      :key="`t${thi}`"
                      class="pl-2"
                    >
                      <span class="font-mono text-ctp-text">{{ th.key ?? '?' }}</span><span class="text-ctp-overlay0"> = {{ th.value ?? '?' }}</span>
                    </div>
                  </div>
                  <div v-if="a.detail?.invariants?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.invariants') }}
                    </div>
                    <div
                      v-for="(iv, ii) in a.detail.invariants"
                      :key="ii"
                      class="pl-2 text-ctp-subtext0"
                    >
                      • {{ iv }}
                    </div>
                  </div>
                  <div v-if="(a.tags?.length || a.detail?.tags?.length)">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.tags') }}
                    </div>
                    <div class="pl-2 flex flex-wrap gap-1">
                      <span
                        v-for="(tg, tgi) in (a.tags ?? a.detail!.tags ?? [])"
                        :key="tgi"
                        class="chip !text-[8px] bg-ctp-blue/15 text-ctp-blue"
                      >{{ tg }}</span>
                    </div>
                  </div>
                  <div v-if="a.astRefs?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      AST
                    </div>
                    <div
                      v-for="(r, ri) in a.astRefs.slice(0, 8)"
                      :key="ri"
                      class="pl-2 font-mono text-ctp-overlay0"
                    >
                      {{ r.file }}:L{{ r.startLine }}-L{{ r.endLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span>
                    </div>
                  </div>
                </div>
              </div>
                </div>
            </template>
            <div
              v-if="renderedTreeRows.length < semanticTreeRows.length"
              ref="loadMoreSentinel"
              class="text-center text-[10px] text-ctp-overlay0 py-2 font-mono"
            >{{ t('assetMgmt.renderingMore', { done: renderedTreeRows.length, total: semanticTreeRows.length }) }}</div>
            <p
              v-if="!semanticTreeRows.length && !loading"
              class="text-xs text-ctp-overlay0 text-center py-8"
            >
              {{ t('assetMgmt.emptySemantic') }}
            </p>
          </template>

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

    <RequirementHistoryModal
      :open="historyOpen"
      :active-conv-id="conv.activeId"
      kind="asset"
      @import-new="onImportNewConversation"
      @close="historyOpen = false"
      @import="importHistory"
    />

    <!-- 清理语义资产确认：展示对需求池/未完成任务的影响范围 -->
    <div
      v-if="purgeOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div class="flex flex-col w-full max-w-2xl max-h-[85vh] rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden">
        <div class="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0">
          <TrashIcon class="w-4 h-4 text-ctp-red" />
          <h3 class="text-sm font-semibold text-ctp-text">
            {{ t('assetMgmt.purgeConfirm.title') }}
          </h3>
          <span class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.purgeConfirm.hint') }}</span>
        </div>

        <div class="flex-1 min-h-0 overflow-auto p-4 space-y-3">
          <p class="text-xs text-ctp-subtext1">
            {{ t('assetMgmt.purgeConfirm.summary', {
              candidates: purgeResult?.candidates ?? 0,
              reqCount: purgeResult?.impact?.reqCount ?? 0,
              taskCount: purgeResult?.impact?.taskCount ?? 0,
            }) }}
          </p>

          <div
            v-if="purgeResult?.impact?.requirements?.length"
            class="border border-ctp-peach/25 rounded-md p-2.5 space-y-1"
          >
            <div class="text-[10px] font-semibold text-ctp-peach">
              {{ t('assetMgmt.purgeConfirm.reqTitle', { n: purgeResult.impact.reqCount }) }}
            </div>
            <div
              v-for="r in purgeResult.impact.requirements"
              :key="r.id"
              class="text-[10px] text-ctp-subtext1"
            >
              <span class="font-mono text-ctp-overlay1">{{ r.id }}</span>
              · {{ r.title }}
              <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1">{{ r.location }}</span>
            </div>
            <p class="text-[9px] text-ctp-peach">
              {{ t('assetMgmt.purgeConfirm.reqRegen') }}
            </p>
          </div>

          <div
            v-if="purgeResult?.impact?.tasks?.length"
            class="border border-ctp-blue/25 rounded-md p-2.5 space-y-1"
          >
            <div class="text-[10px] font-semibold text-ctp-blue">
              {{ t('assetMgmt.purgeConfirm.taskTitle', { n: purgeResult.impact.taskCount }) }}
            </div>
            <div
              v-for="t in purgeResult.impact.tasks"
              :key="t.id"
              class="text-[10px] text-ctp-subtext1"
            >
              <span class="font-mono text-ctp-overlay1">{{ t.id }}</span>
              · {{ t.title }}
              <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1">{{ t.status }}</span>
            </div>
            <p class="text-[9px] text-ctp-blue">
              {{ t('assetMgmt.purgeConfirm.taskRegen') }}
            </p>
          </div>

          <p
            v-if="!purgeResult?.impact?.requirements?.length && !purgeResult?.impact?.tasks?.length"
            class="text-[10px] text-ctp-green"
          >
            {{ t('assetMgmt.purgeConfirm.noImpact') }}
          </p>
        </div>

        <div class="shrink-0 border-t border-ctp-surface0 px-4 py-2.5 flex justify-end gap-2">
          <button
            class="btn btn-ghost"
            :disabled="purgeBusy"
            @click="cancelPurge"
          >
            {{ t('assetMgmt.purgeConfirm.cancel') }}
          </button>
          <button
            class="btn btn-red"
            :disabled="purgeBusy"
            @click="confirmPurge"
          >
            {{ purgeBusy ? t('assetMgmt.purgeConfirm.deleting') : t('assetMgmt.purgeConfirm.confirm') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 静态资产图：entity → 类图(字段/方法)，state → 状态图(状态+迁移) -->
    <div
      v-if="diagramModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="diagramModalOpen = false"
    >
      <div class="flex flex-col w-full max-w-3xl h-[80vh] rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden">
        <div class="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-ctp-surface0">
          <ChartBarSquareIcon class="w-4 h-4 text-ctp-teal" />
          <h3 class="text-sm font-semibold text-ctp-text truncate">
            {{ diagramModalTitle }}
          </h3>
          <span class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diagramHint') }}</span>
          <span class="flex-1" />
          <button
            class="btn btn-ghost !py-1"
            @click="diagramModalOpen = false"
          >
            {{ t('assetMgmt.purgeConfirm.cancel') }}
          </button>
        </div>
        <div class="flex-1 min-h-0 p-3">
          <p
            v-if="diagramModalLoading"
            class="text-xs text-ctp-overlay1 text-center py-10"
          >
            {{ t('assetMgmt.diagramLoading') }}
          </p>
          <p
            v-else-if="!diagramModalItems.length"
            class="text-xs text-ctp-overlay0 text-center py-10"
          >
            {{ t('assetMgmt.diagramEmpty') }}
          </p>
          <template v-else>
            <div
              v-for="d in diagramModalItems"
              :key="d.assetId"
              class="h-full min-h-0"
            >
              <DiagramCard
                :title="`${d.name} (${t(`assetMgmt.diagramType.${d.type}`)})`"
                :diagrams="{ mermaid: d.mermaid }"
                :allowed-langs="['mermaid']"
              />
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 校验并提取 · 变化范围确认弹窗：先校验后执行(所见即所得，按快照执行) -->
    <div
      v-if="syncPlanOpen && syncPlan"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/70 p-4"
      @click.self="cancelSyncExtract"
    >
      <div class="panel max-w-lg w-full max-h-[80vh] flex flex-col">
        <div class="panel-header">
          <span class="flex items-center gap-2 text-sm font-semibold text-ctp-text">
            <ArrowPathIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.sync.planTitle') }}
          </span>
        </div>
        <div class="p-3 space-y-2 overflow-auto text-xs">
          <p class="text-ctp-subtext1">{{ t('assetMgmt.sync.planDesc') }}</p>
          <div class="grid grid-cols-2 gap-1.5">
            <div class="rounded-md bg-ctp-surface0/60 px-2.5 py-1.5 flex items-center justify-between">
              <span class="text-ctp-subtext0">{{ t('assetMgmt.sync.rowAdded') }}</span>
              <span class="font-mono text-ctp-green">{{ syncPlan.added }}</span>
            </div>
            <div class="rounded-md bg-ctp-surface0/60 px-2.5 py-1.5 flex items-center justify-between">
              <span class="text-ctp-subtext0">{{ t('assetMgmt.sync.rowModified') }}</span>
              <span class="font-mono text-ctp-yellow">{{ syncPlan.modified }}</span>
            </div>
            <div class="rounded-md bg-ctp-surface0/60 px-2.5 py-1.5 flex items-center justify-between">
              <span class="text-ctp-subtext0">{{ t('assetMgmt.sync.rowNever') }}</span>
              <span class="font-mono text-ctp-sky">{{ syncPlan.neverExtracted }}</span>
            </div>
            <div class="rounded-md bg-ctp-surface0/60 px-2.5 py-1.5 flex items-center justify-between">
              <span class="text-ctp-subtext0">{{ t('assetMgmt.sync.rowStale') }}</span>
              <span class="font-mono text-ctp-peach">{{ syncPlan.staleOnly }}</span>
            </div>
          </div>
          <div class="rounded-md border border-ctp-blue/30 bg-ctp-blue/10 px-2.5 py-1.5 flex items-center justify-between">
            <span class="text-ctp-text font-semibold">{{ t('assetMgmt.sync.rowTotal') }}</span>
            <span class="font-mono text-ctp-blue">{{ syncPlan.toExtract }}</span>
          </div>
          <p
            v-if="syncPlan.deleted || syncPlan.invalidated"
            class="text-ctp-overlay1"
          >{{ t('assetMgmt.sync.deletedNote', { d: syncPlan.deleted, n: syncPlan.invalidated }) }}</p>
          <p class="text-ctp-overlay0">{{ t('assetMgmt.sync.batchesNote', { n: syncPlan.batchesEstimate ?? Math.ceil(syncPlan.toExtract / 10) }) }}</p>
          <div v-if="syncPlan.files.length">
            <p class="text-ctp-overlay0 mb-1">{{ t('assetMgmt.sync.filesSample') }}</p>
            <div class="rounded-md bg-ctp-mantle border border-ctp-surface1 p-2 font-mono text-[10px] text-ctp-subtext1 max-h-32 overflow-auto space-y-0.5">
              <div v-for="f in syncPlan.files" :key="f">{{ f }}</div>
            </div>
          </div>
        </div>
        <div class="flex items-center justify-end gap-2 px-3 py-2 border-t border-ctp-surface0">
          <button
            class="btn btn-sm btn-ghost"
            @click="cancelSyncExtract"
          >{{ t('assetMgmt.sync.cancel') }}</button>
          <button
            class="btn btn-sm btn-primary"
            @click="confirmSyncExtract"
          >{{ t('assetMgmt.sync.confirm') }}</button>
        </div>
      </div>
    </div>
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
