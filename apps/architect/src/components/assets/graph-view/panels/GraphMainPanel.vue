<script setup lang="ts">

/** MS6-W2-S2 自 SemanticGraphView 模板整块迁出(逐行未动)；状态经 SGV_WS_KEY 注入。 */

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowPathIcon, XMarkIcon, ArrowsPointingOutIcon, MinusIcon, InformationCircleIcon, SparklesIcon, DocumentTextIcon, ShareIcon, ViewfinderCircleIcon, ClipboardIcon, ChevronDownIcon, ChevronRightIcon, CheckIcon, PlusCircleIcon, TableCellsIcon, AdjustmentsHorizontalIcon, ListBulletIcon, LockClosedIcon, LockOpenIcon, FunnelIcon, FolderOpenIcon } from '@heroicons/vue/24/outline'
import GraphMatrixWindow from '../../GraphMatrixWindow.vue'
import AssetIndexWindow from '../../AssetIndexWindow.vue'
import FileIndexWindow from '../../FileIndexWindow.vue'
import TracePanel from './TracePanel.vue'
import { useSelectionActions, langOf } from '../useSelectionActions'
import LogicViewCard from './LogicViewCard.vue'
import LogicScopeModal from './LogicScopeModal.vue'
import TopoDiagram from '@topo/graph-kernel/vue/TopoDiagram.vue'

import type { SemanticGraphResult, SourceSnippet } from '@/services/semantic-asset-service'
import { useI18n } from 'vue-i18n'
import type { GraphTabDef } from '../graphTypes'
import type { SemanticTraceNode } from '@/services/semantic-asset-service'
import { kindChipClass as kindChipCls, KIND_CARD_CLASS } from '@/services/semantic-kind-style'
import { currentProjectParams } from '@/services/project-service'
import { useSgvWs } from '../key'
import { bringCardToFront, isCardTop } from '../cardZ'
import { invalidateAssets } from '@/pages/asset-workspace/invalidate-bus'

const props = defineProps<{ tab: GraphTabDef; diffFiles?: Set<string>; compNames?: Record<string, string> }>()
/** 逻辑视图资产卡浮窗开合 + 当前视图 id(logic tab=tab.viewId；范围解析后=新视图)。 */
const logicCardOpen = ref(false)
const logicCardViewId = ref('')
watch(() => props.tab, (tb) => { logicCardViewId.value = tb.viewId ?? '' }, { immediate: true })
const scopeOpen = ref(false)
function onScopeDone(viewIds: string[]) {
  scopeOpen.value = false
  invalidateAssets('job:induce_scope:done')   // 语义树「逻辑资产」分组刷新
  if (viewIds.length) {
    logicCardViewId.value = viewIds[0]!
    logicCardOpen.value = true
  }
}
const { t } = useI18n()


// ---- 链路 tab 浮卡「全链路」分区 ----
const tracePathsOpen = ref(false)
function tracePathText(p: { name?: string; assetName?: string }[]): string {
  return p.map((n) => n.assetName || n.name || '').join(' → ')
}
function highlightTracePath(p: SemanticTraceNode[]): void {
  const last = p[p.length - 1]
  if (last) traceLocate(last)   // 选中链终点(图面高亮+浮卡), 链路中心不变
}
const {
  FILE_BUDGET,
  MAX_SEGMENTS,
  activeFileTab,
  activeRelTab,
  activeTabSegs,
  applyFileScope,
  beginCardDrag,
  cardDragging,
  cardEl,
  cardFullscreen,
  cardLang,
  cardMin,
  cardPos,
  cardResetPos,
  cardResizing,
  cardSize,
  cardSrcOpen,
  cardStartResize,
  closeCardFullscreen,
  codeFontSize,
  collapsedSegs,
  copiedSeg,
  copySegLoc,
  detailBlock,
  diagRef,
  diagrams,
  edgeNotesLoading,
  fileIndex,
  fileScopeOpen,
  fileScopeSel,
  fileTabs,
  flashing,
  fullCode,
  fullCodeError,
  fullCodeLoading,
  fullCodeNotes,
  fullCodeNotesLoading,
  fullCodeOwners,
  fullCodePreRef,
  fullCodeSelfLines,
  graph,
  iconPulse,
  inEdges,
  indexOpen,
  isDiffNode,
  jumpToRelation,
  jumpToSegment,
  kindBgClass,
  kindChipClass,
  kindTextClass,
  lineNotesCount,
  lineNotesDegraded,
  lineNotesError,
  lineNotesFromCache,
  lineNotesLoading,
  lineNotesMaps,
  loadLineNotes,
  loading,
  matrixOpen,
  traceMode,
  tree: traceTree, paths: tracePaths, stats: traceStats,
  nodeBriefLoading,
  nodeBriefText,
  onDiagramReady,
  onFullCodeLineClick,
  onMatrixSelect,
  onNodeClick,
  overLimit,
  ownerName,
  regenerateLineNotes,
  regenerateNodeBrief,
  relTabEl,
  relTabSegs,
  scopeTotal,
  symDetail, symNoteLoading, generateSymbolNote,
  locate: traceLocate,
  scopedEdges,
  scopedNodes,
  segEls,
  segHighlighted,
  segments,
  sel,
  selAnchors,
  selDetail,
  selId,
  selRelations,
  setCardMin,
  settings,
  shortPath,
  tabClick,
  themeMode,
  themeVars,
  toggleFullCode,
  toggleSeg,
} = useSgvWs()

// ---- 卡片内容选中 → 引用到草稿 / 复制(代码段/全文/关系 tab/符号卡共用容器) ----
const selActionHost = ref<HTMLElement | null>(null)
/** 选区起点所在代码段(refSel 时选区仍在; 全文/rel tab/符号卡 → null, payload 用兜底)。 */
function selSeg(): { file: string; symbol: string } | null {
  const sel = window.getSelection()
  if (!sel || sel.rangeCount === 0) return null
  let el: HTMLElement | null = sel.getRangeAt(0).startContainer instanceof HTMLElement
    ? (sel.getRangeAt(0).startContainer as HTMLElement)
    : sel.getRangeAt(0).startContainer.parentElement
  while (el) {
    const f = el.getAttribute?.('data-seg-file')
    if (f) return { file: f, symbol: el.getAttribute('data-seg-symbol') || '' }
    el = el.parentElement
  }
  return null
}
const {
  barVisible: codeSelBar, barPos: codeSelBarPos, copied: codeSelCopied, copySel: codeSelCopy, refSel: codeSelRef,
} = useSelectionActions(selActionHost, () => {
  const seg = selSeg()
  const file = seg?.file || fullCode.value?.file || symDetail.value?.meta.file || ''
  const sym = symDetail.value
    ? symDetail.value.meta.qualifiedName
    : (seg?.symbol || selAnchors.value[0]?.symbol || '')
  return {
    projectId: currentProjectParams().project || '',
    compId: selDetail.value?.scopeKey || '',
    fileId: file || undefined,
    fileLabel: file ? file.split('/').pop() : undefined,
    assetId: symDetail.value ? undefined : (selId.value || undefined),
    assetName: symDetail.value ? undefined : (sel.value?.name || undefined),
    symbolName: sym || undefined,
  }
}, { lang: () => {
  const file = selSeg()?.file || fullCode.value?.file || symDetail.value?.meta.file || ''
  return file ? langOf(file) : undefined
} })
</script>

<template>
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
          ref="diagRef"
          class="h-full"
          :key="`${cardFullscreen ? 'fs' : 'inline'}`"
          :code="diagrams[cardLang]"
          :engine="cardLang"
          :theme="themeMode"
          :theme-variables="themeVars"
          security-level="loose"
          :auto-play="false"
          :zoom-fit-min-scale="0.3"
          :zoom-max-scale="24"
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

      <!-- 符号详情卡(链路 tab 符号节点): 元数据+代码段+AI 解读(缓存回显) -->
      <div
        v-if="symDetail && !cardMin"
        class="fixed z-50 w-[420px] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-3"
        :style="{ right: '1rem', top: '4rem' }"
      >
        <div class="mb-1 flex items-center gap-1.5">
          <span class="text-[11px] font-semibold text-ctp-text truncate" :title="symDetail.symbol">{{ symDetail.meta.name }}</span>
          <span class="chip !text-[9px] bg-ctp-overlay0/20 text-ctp-overlay1 shrink-0">{{ symDetail.meta.kind || 'symbol' }}</span>
          <span class="flex-1" />
          <button class="text-ctp-overlay0 hover:text-ctp-text p-0.5" @click="symDetail = null">✕</button>
        </div>
        <p class="mb-1.5 truncate font-mono text-[9px] text-ctp-overlay0" :title="`${symDetail.meta.file}:${symDetail.meta.startLine}-${symDetail.meta.endLine}`">
          {{ symDetail.meta.file }}:{{ symDetail.meta.startLine }}-{{ symDetail.meta.endLine }}
        </p>
        <pre v-if="symDetail.snippet" class="mb-2 max-h-56 overflow-auto rounded bg-ctp-crust/60 p-1.5 font-mono text-[9px] leading-4 text-ctp-subtext0">{{ symDetail.snippet }}</pre>
        <div class="flex items-start gap-1">
          <button class="btn btn-ghost !py-0.5 !px-1.5 !text-[9px] shrink-0" :disabled="symNoteLoading" @click="generateSymbolNote">
            <SparklesIcon class="w-3 h-3" :class="symNoteLoading ? 'animate-spin' : ''" />{{ t('assetMgmt.graph.trace.noteBtn') }}
          </button>
          <p v-if="symDetail.note" class="min-w-0 flex-1 text-[10px] leading-relaxed text-ctp-subtext1">{{ symDetail.note }}</p>
          <span v-else class="flex-1 text-[9px] text-ctp-overlay0">{{ t('assetMgmt.graph.trace.noteEmpty') }}</span>
        </div>
      </div>
      <!-- 选中节点详情：网页全局浮窗(可拖动/可拉伸/可最小化；最小化图标停靠图谱区右下) -->
      <div
        v-if="sel && !cardMin"
        ref="cardEl"
        class="card-root fixed flex flex-col max-w-[calc(100vw-1rem)] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
        :class="[
          isCardTop('asset') ? 'z-50' : 'z-40',   // 与逻辑资产卡点选互顶
          !cardPos ? 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2' : '',
          cardDragging ? 'cursor-grabbing' : '',
          cardResizing ? 'select-none' : '',
        ]"
        @mousedown.capture="bringCardToFront('asset')"
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
        <!-- 全链路分区(链路 tab 且选中=中心节点)：完整路径列表, 点击行侧栏高亮该链 -->
        <div
          v-if="traceMode && sel?.id === props.tab.assetId && tracePaths?.length"
          class="shrink-0 border-b border-ctp-surface0 px-3 py-1.5"
        >
          <button
            class="flex w-full items-center gap-1 text-[10px] text-ctp-mauve"
            @click="tracePathsOpen = !tracePathsOpen"
          >
            <ChevronRightIcon class="h-3 w-3" :class="tracePathsOpen ? 'rotate-90' : ''" />
            {{ t('assetMgmt.graph.trace.fullPaths') }}
            <span class="font-mono text-[9px] text-ctp-overlay0">
              {{ tracePaths.length }} · {{ traceStats?.nodes ?? 0 }}n
            </span>
            <span class="flex-1" />
            <span class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.graph.trace.fullPathsHint') }}</span>
          </button>
          <div v-if="tracePathsOpen" class="mt-1 max-h-36 space-y-0.5 overflow-y-auto">
            <button
              v-for="(p, i) in tracePaths" :key="i"
              class="block w-full truncate rounded px-1 py-0.5 text-left font-mono text-[9px] text-ctp-subtext0 hover:bg-ctp-surface0"
              :title="tracePathText(p)"
              @click="highlightTracePath(p)"
            >{{ i + 1 }}. {{ tracePathText(p) }}</button>
          </div>
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
        <div ref="selActionHost" class="relative flex-1 min-h-0 overflow-auto px-3 pb-3 pt-1 space-y-2">
          <!-- 选区浮条(引用到草稿/复制): useSelectionActions 定位选区下方 -->
          <div
            v-if="codeSelBar"
            data-sel-actions
            class="absolute z-20 flex items-center gap-0.5 rounded-md border border-ctp-surface1 bg-ctp-mantle px-1 py-0.5 shadow-lg"
            :style="{ left: codeSelBarPos.x + 'px', top: codeSelBarPos.y + 'px' }"
          >
            <button
              class="rounded px-1.5 py-0.5 text-[10px] text-ctp-blue hover:bg-ctp-surface0"
              @click.stop="codeSelRef"
            >{{ t('assetMgmt.graph.selActions.quote') }}</button>
            <button
              class="rounded px-1.5 py-0.5 text-[10px] text-ctp-subtext1 hover:bg-ctp-surface0"
              @click.stop="codeSelCopy"
            >{{ codeSelCopied ? t('assetMgmt.graph.selActions.copied') : t('assetMgmt.graph.selActions.copy') }}</button>
          </div>
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
            :class="row.assetId ? 'cursor-pointer hover:text-ctp-text' : ''"
            :title="row.assetId ? t('assetMgmt.graph.memberJump') : row.title"
            @click="row.assetId && (selId = row.assetId)"
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
            :data-seg-file="seg.file"
            :data-seg-symbol="seg.symbol || ''"
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
              :data-line="l.line"
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
      <!-- 逻辑入口·logic tab：打开既有逻辑资产卡(常驻，资产卡 icon 正上方) -->
      <button
        v-if="tab.kind === 'logic' && tab.viewId"
        class="absolute z-10 right-2 bottom-14 w-9 h-9 rounded-full border shadow-lg flex items-center justify-center transition-transform hover:scale-110"
        :class="[logicCardOpen
          ? 'border-ctp-mauve/60 bg-ctp-mauve/25 text-ctp-mauve'
          : 'border-ctp-mauve/40 bg-ctp-mauve/15 text-ctp-mauve']"
        :title="t('assetMgmt.logicViews.cardTitle')"
        @click="logicCardOpen = !logicCardOpen"
      >
        <ShareIcon class="w-5 h-5" />
      </button>
      <!-- 逻辑入口·实现级图谱：发起范围逻辑解析(显示范围资产→提纲/直接确认→解析) -->
      <button
        v-else-if="tab.kind !== 'logic' && scopedNodes.length"
        class="absolute z-10 right-2 bottom-14 w-9 h-9 rounded-full border shadow-lg flex items-center justify-center transition-transform hover:scale-110"
        :class="[scopeOpen
          ? 'border-ctp-mauve/60 bg-ctp-mauve/25 text-ctp-mauve'
          : 'border-ctp-mauve/40 bg-ctp-mauve/15 text-ctp-mauve']"
        :title="t('assetMgmt.logicViews.scopeEntry')"
        @click="scopeOpen = true"
      >
        <SparklesIcon class="w-5 h-5" />
      </button>
      <LogicScopeModal
        v-if="scopeOpen"
        :nodes="scopedNodes"
        :sel-id="selId"
        @close="scopeOpen = false"
        @done="onScopeDone"
      />
      <LogicViewCard
        v-if="logicCardOpen && logicCardViewId"
        :view-id="logicCardViewId"
        @close="logicCardOpen = false"
      />
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
      <!-- 链路跟踪侧栏(深度探索): 与邻域聚焦互斥, 点击资产节点与图面选中全联动 -->
      <TracePanel />
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
/* 图节点选中态：桃色强对比(浓光晕 + 加粗描边 + 半透明填充覆盖 + 文字加重)，
   绑定节点 DOM 切换；与未选节点的主题底色拉开层次，缩放后仍可一眼定位 */
/* 选中态改蓝色系淡色(原 peach 与变化节点浅橘黄同暖色系，文字难辨) */
:deep(.td-node-selected) {
  filter: drop-shadow(0 0 6px rgba(137, 180, 250, 1)) drop-shadow(0 0 14px rgba(137, 180, 250, 0.6));
}
:deep(.td-node-selected) path,
:deep(.td-node-selected) rect,
:deep(.td-node-selected) polygon,
:deep(.td-node-selected) circle,
:deep(.td-node-selected) ellipse {
  stroke: #89b4fa !important;
  stroke-width: 3px !important;
}
/* 主体形状(rect/polygon/ellipse/circle)叠加半透明桃色填充，与底色形成面级对比；
   path 仅描边(shape 边缘)，覆盖 fill 会使连线误染，故排除 */
:deep(.td-node-selected) rect,
:deep(.td-node-selected) polygon,
:deep(.td-node-selected) ellipse,
:deep(.td-node-selected) circle {
  fill: rgba(137, 180, 250, 0.16) !important;
}
:deep(.td-node-selected) text {
  fill: #89b4fa !important;
  font-weight: 700;
}
/* 对比变化节点视觉(与 useGraphRender DIFF_FILL/STROKE 同值，双保险兜底)：
   变更/新增/移除统一「需更新」浅橘黄底；弱关联(符号段未变)更浅一档；
   增删语义由左上信号点表达(纯色圆点，非节点形状描边)。
   circle:not(.td-node-signal)——信号点为运行时注入的专属元素，排除防描边误伤。 */
:deep(.td-node-diff-changed) rect,
:deep(.td-node-diff-changed) polygon,
:deep(.td-node-diff-changed) ellipse,
:deep(.td-node-diff-changed) circle:not(.td-node-signal) {
  fill: rgba(249, 226, 175, 0.30) !important;
  stroke: rgba(249, 226, 175, 0.8) !important;
  stroke-width: 1.5px !important;
}
:deep(.td-node-diff-weak) rect,
:deep(.td-node-diff-weak) polygon,
:deep(.td-node-diff-weak) ellipse,
:deep(.td-node-diff-weak) circle:not(.td-node-signal) {
  fill: rgba(249, 226, 175, 0.14) !important;
  stroke: rgba(249, 226, 175, 0.4) !important;
  stroke-width: 1.5px !important;
}
:deep(.td-node-diff-new) rect,
:deep(.td-node-diff-new) polygon,
:deep(.td-node-diff-new) ellipse,
:deep(.td-node-diff-new) circle:not(.td-node-signal) {
  fill: rgba(249, 226, 175, 0.30) !important;
  stroke: rgba(249, 226, 175, 0.8) !important;
  stroke-width: 1.5px !important;
}
:deep(.td-node-diff-removed) rect,
:deep(.td-node-diff-removed) polygon,
:deep(.td-node-diff-removed) ellipse,
:deep(.td-node-diff-removed) circle:not(.td-node-signal) {
  fill: rgba(249, 226, 175, 0.30) !important;
  stroke: rgba(249, 226, 175, 0.8) !important;
  stroke-width: 1.5px !important;
}
/* 档2 行级定位闪烁：合成节点(决策分支)点击 → 代码行滚动至视中并闪蓝 */
@keyframes line-focus-flash-kf {
  0% { background: rgba(137, 180, 250, 0.45); }
  100% { background: transparent; }
}
:deep(.line-focus-flash) {
  animation: line-focus-flash-kf 2.2s ease-out;
  border-radius: 2px;
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
