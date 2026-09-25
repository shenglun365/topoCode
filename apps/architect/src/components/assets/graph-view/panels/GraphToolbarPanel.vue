<script setup lang="ts">

/** MS6-W2-S2 自 SemanticGraphView 模板整块迁出(逐行未动)；状态经 SGV_WS_KEY 注入。 */

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowPathIcon, XMarkIcon, ArrowsPointingOutIcon, MinusIcon, InformationCircleIcon, SparklesIcon, DocumentTextIcon, ViewfinderCircleIcon, ClipboardIcon, ChevronDownIcon, CheckIcon, PlusCircleIcon, TableCellsIcon, AdjustmentsHorizontalIcon, ListBulletIcon, LockClosedIcon, LockOpenIcon, FunnelIcon, FolderOpenIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import type { GraphTabDef } from '../../SemanticGraphView.vue'
import { useSgvWs } from '../key'

const props = defineProps<{ tab: GraphTabDef; diffFiles?: Set<string> }>()
const { t } = useI18n()
const {
  cardLang,
  cardSrcOpen,
  clearSel,
  diagramLangs,
  diffBucketCounts,
  diffKindById,
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
  setCardLang,
  startEnhanceDesc,
  toggleCardSource,
  toggleEdgeLegend,
  toggleEdgeType,
  toggleFocusLock,
  toggleIndex,
  toggleMatrix,
  viewOptions,
  viewSel,
  weakCount,
} = useSgvWs()
const emit = defineEmits<{ close: [id: string] }>()
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
