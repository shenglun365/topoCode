<script setup lang="ts">

/** MS6-W1 自 AssetManagementWorkspace 模板整块迁出(逐行未动)；状态经 ASSET_WS_KEY 注入。 */

import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, ArrowsRightLeftIcon, ChartBarSquareIcon, ChatBubbleLeftRightIcon, CheckIcon, ChevronDownIcon, ChevronRightIcon, ClipboardDocumentIcon, CodeBracketIcon, DocumentTextIcon, ScaleIcon, ServerStackIcon, SparklesIcon, Squares2X2Icon, StopIcon } from '@heroicons/vue/24/outline'
import { kindChipClass, levelChipClass } from '@/services/semantic-kind-style'
import { useAssetWorkspaceCtx } from '..'

const { t } = useI18n()
const {
  OTHER_KEY,
  addedFileSet,
  askExtractComponent,
  changeMarkById,
  compCatalog,
  compCollapsible,
  compCoverage,
  compExpandState,
  compMetaText,
  compareData,
  copiedKey,
  copyAsset,
  copyCompRef,
  descLoading,
  detailLoading,
  diffFileCounts,
  diffMarkLabel,
  diffMode,
  diffRollup,
  expanded,
  extractAllUnowned,
  extractUnownedFile,
  fileBase,
  fileCard,
  fileExpandState,
  genDesc,
  hasChildren,
  items,
  kind,
  kindIcon,
  level,
  loadMoreSentinel,
  loading,
  openAssetDiagram,
  openFileCard,
  openGraphTab,
  pendingFileSet,
  referenceAsset,
  referenceComp,
  refreshOne,
  renderedTreeRows,
  semanticTreeRows,
  stopUnownedExtract,
  subtreeCount,
  toggle,
  toggleFileOpen,
  toggleOpen,
  unownedExtracting,
  unownedExtractingOne,
  unownedJob,
  unownedJobHint,
  unownedLinkByAssetId,
  unownedLinkTitle,
  unownedLinks,
  unownedMeta,
  usable,
} = useAssetWorkspaceCtx()
</script>

<template>
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

<style scoped>
/* 树行离屏跳过布局/绘制(配合前缀窗口渲染): 浏览器不维护不可见行样式与合成
   (MS6-W1-S2 自 AMW SFC 迁入——scoped 样式不穿透子组件, 必须随 .tree-row 元素所在面板) */
.tree-row {
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
</style>
