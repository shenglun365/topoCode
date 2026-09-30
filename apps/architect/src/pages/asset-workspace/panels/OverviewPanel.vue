<script setup lang="ts">

/** MS6-W1 自 AssetManagementWorkspace 模板整块迁出(逐行未动)；状态经 ASSET_WS_KEY 注入。 */

import { useI18n } from 'vue-i18n'
import { AdjustmentsHorizontalIcon, ArrowPathIcon, ArrowsRightLeftIcon, ChartBarSquareIcon, CubeTransparentIcon, ServerStackIcon, SparklesIcon, Squares2X2Icon, TrashIcon } from '@heroicons/vue/24/outline'
import { kindChipClass, levelChipClass } from '@/services/semantic-kind-style'
import { useAssetWorkspaceCtx } from '..'

const { t } = useI18n()
const {
  baselineDiffData,
  compCatalog,
  cmpTarget,
  commitOptions,
  baselineSha,
  compareData,
  compareError,
  compareHint,
  compareLoading,
  coverageInfo,
  diffLoading,
  extractPendingAndRecompare,
  extractingPending,
  pendingExtractable,
  frameworkInfo,
  fwLoading,
  fwSwitching,
  items,
  kind,
  kinds,
  levels,
  overviewStats,
  purging,
  runCompare,
  runPurge,
  statusCounts,
  switchTier,
  totalChanged,
} = useAssetWorkspaceCtx()
</script>

<template>
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
                      {{ overviewStats?.status?.active ?? 0 }}
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
                    <span class="chip bg-ctp-green/15 text-ctp-green">active · {{ overviewStats?.status?.active ?? 0 }}</span>
                    <span class="chip bg-ctp-yellow/15 text-ctp-yellow">stale · {{ overviewStats?.status?.stale ?? 0 }}</span>
                    <span class="chip bg-ctp-red/15 text-ctp-red">deleted · {{ overviewStats?.status?.deleted ?? 0 }}</span>
                    <span class="chip bg-ctp-overlay0/20 text-ctp-overlay1">needsUpdate · {{ overviewStats?.status?.needsUpdate ?? 0 }}</span>
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

            <!-- 基线对比（常驻信息卡 · 三视图 diff）：基准固定=KB 基线，目标可选(默认工作区) -->
            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <ArrowsRightLeftIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.diff.title') }}
                </span>
                <span class="flex items-center gap-1 flex-wrap">
                  <span
                    class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono !text-[9px]"
                    :title="t('assetMgmt.diff.cmpBaseHint')"
                  >{{ t('assetMgmt.diff.cmpBase') }}: {{ t('assetMgmt.diff.kbBaseline') }}{{ baselineSha ? ` (${baselineSha.slice(0, 8)})` : '' }}</span>
                  <span class="text-[10px] text-ctp-overlay0 shrink-0">→</span>
                  <select
                    v-model="cmpTarget"
                    class="input !py-0.5 !px-1.5 !text-[10px] w-auto max-w-[200px]"
                    :title="t('assetMgmt.diff.cmpTargetHint')"
                    @change="runCompare"
                  >
                    <option value="worktree">{{ t('assetMgmt.diff.worktree') }}</option>
                    <option v-for="c in commitOptions" :key="`t-${c.oid}`" :value="c.oid">{{ c.oid.slice(0, 8) }} {{ c.subject.slice(0, 26) }}</option>
                  </select>
                  <!-- 提取闭环：待提取文件按范围补提(仅工作区目标可用)，完成后自动重新对比 -->
                  <button
                    v-if="compareData && !compareData.noChanges && compareData.targetIsWorktree
                      && pendingExtractable.length && !extractingPending"
                    class="btn btn-xs btn-blue !py-0 !px-1.5 !text-[9px] shrink-0"
                    :title="pendingExtractable.length < compareData.assets.pending.count
                      ? t('assetMgmt.diff.extractRecompareHint', { n: pendingExtractable.length }) + ' ' + t('assetMgmt.diff.extractDiverged', { m: compareData.assets.pending.count - pendingExtractable.length })
                      : t('assetMgmt.diff.extractRecompareHint', { n: pendingExtractable.length })"
                    @click="extractPendingAndRecompare()"
                  >
                    <SparklesIcon class="w-2.5 h-2.5" />{{ t('assetMgmt.diff.extractRecompare', { n: pendingExtractable.length }) }}
                  </button>
                  <span v-if="extractingPending" class="inline-flex items-center gap-1 text-[10px] text-ctp-overlay0 shrink-0"><ArrowPathIcon class="w-3 h-3 animate-spin" />{{ t('assetMgmt.diff.extracting') }}</span>
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

              <!-- 对比结果明细：资产变化 + 组件变化(其他桶) + 跨域联系；基准固定基线，目标在卡头选择 -->
              <div class="px-3 pb-3 pt-2 mt-1 border-t border-ctp-surface0 space-y-2">
                <p v-if="compareLoading" class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.cmpRunning') }}</p>
                <p v-else-if="compareError" class="text-[10px] text-ctp-red">{{ compareError }}</p>
                <p v-if="!compareError && compareHint" class="text-[10px] text-ctp-peach">{{ compareHint }}</p>
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
