<script setup lang="ts">

/** MS6-W1 自 AssetManagementWorkspace 模板整块迁出(逐行未动)；状态经 ASSET_WS_KEY 注入。 */

import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, ChartBarSquareIcon, TrashIcon } from '@heroicons/vue/24/outline'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import FileSourceCard from '@/components/assets/FileSourceCard.vue'
import RequirementHistoryModal from '@/components/requirements/RequirementHistoryModal.vue'
import { useAssetWorkspaceCtx } from '..'

const { t } = useI18n()
const {
  cancelPurge,
  cancelSyncExtract,
  compareData,
  confirmPurge,
  confirmSyncExtract,
  conv,
  diagramModalItems,
  diagramModalLoading,
  diagramModalOpen,
  diagramModalTitle,
  fileCard,
  historyOpen,
  importHistory,
  items,
  locateAsset,
  onImportNewConversation,
  purgeBusy,
  purgeOpen,
  purgeResult,
  syncPlan,
  syncPlanOpen,
} = useAssetWorkspaceCtx()
</script>

<template>
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
</template>
