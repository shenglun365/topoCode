<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  PlusIcon, ArrowRightIcon, BoltIcon, TrashIcon, PencilSquareIcon, ArrowPathRoundedSquareIcon, CubeIcon, LinkIcon,
} from '@heroicons/vue/24/outline'
import { ClipboardDocumentListIcon, CheckIcon } from '@heroicons/vue/24/outline'
import { useArchRequirementStore } from '@/stores/requirement-store'

const { t } = useI18n()
const store = useArchRequirementStore()
const route = useRoute()
const router = useRouter()

const tab = ref<'proposal' | 'pool'>('proposal')

watch(
  () => route.query.tab,
  (v) => {
    if (v === 'pool' || v === 'proposal') tab.value = v
  },
  { immediate: true },
)

const selectedPool = ref<string[]>([])

const kindColor: Record<string, string> = {
  'user-story': 'bg-ctp-sky/15 text-ctp-sky',
  fr: 'bg-ctp-mauve/15 text-ctp-mauve',
  nfr: 'bg-ctp-teal/15 text-ctp-teal',
}
const statusColor: Record<string, string> = {
  raw: 'bg-ctp-overlay0/20 text-ctp-overlay1',
  analyzing: 'bg-ctp-blue/15 text-ctp-blue',
  analyzed: 'bg-ctp-green/15 text-ctp-green',
  designed: 'bg-ctp-sky/15 text-ctp-sky',
  planned: 'bg-ctp-teal/15 text-ctp-teal',
  executing: 'bg-ctp-peach/15 text-ctp-peach',
  done: 'bg-ctp-green/15 text-ctp-green',
  cancelled: 'bg-ctp-red/15 text-ctp-red',
}
const prioColor: Record<string, string> = {
  P0: 'bg-ctp-red/15 text-ctp-red',
  P1: 'bg-ctp-peach/15 text-ctp-peach',
  P2: 'bg-ctp-overlay0/20 text-ctp-overlay1',
}
const prioOrder: Record<string, number> = { P0: 0, P1: 1, P2: 2 }

const proposals = computed(() => store.proposals)
const poolItems = computed(() =>
  [...store.poolItems].sort((a, b) => (prioOrder[a.priority] ?? 9) - (prioOrder[b.priority] ?? 9)),
)
const executedItems = computed(() => store.items.filter((r) => r.status === 'executing' || r.status === 'done'))

function openAnalysis(id: string) {
  router.push({ path: '/workbench/requirements/analysis', query: { id } })
}

/** 统一「需求分析」：进入工作区，先多选要分析的提案。 */
function analyzeNext() {
  router.push({ path: '/workbench/requirements/analysis', query: { pending: '1' } })
}

function openNew() {
  router.push({ path: '/workbench/requirements/analysis', query: { new: '1' } })
}

function switchTab(k: 'proposal' | 'pool') {
  tab.value = k
  router.replace({ query: { ...route.query, tab: k } })
}

function togglePool(id: string) {
  const i = selectedPool.value.indexOf(id)
  if (i >= 0) selectedPool.value.splice(i, 1)
  else selectedPool.value.push(id)
}

/** 需求池多选 → 进入任务执行并创建新会话，执行页创建表单默认勾选。 */
function executeFromPool() {
  if (!selectedPool.value.length) return
  router.push({ path: '/workbench/execute', query: { select: selectedPool.value.join(',') } })
}
</script>

<template>
  <div class="h-full flex flex-col">
    <div class="shrink-0 px-5 pt-5">
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-1 bg-ctp-crust/60 rounded-lg p-1 w-fit">
          <button
            v-for="tb in ([{ key: 'proposal', icon: ClipboardDocumentListIcon }, { key: 'pool', icon: CubeIcon }] as const)"
            :key="tb.key"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors"
            :class="tab === tb.key ? 'bg-ctp-surface1 text-ctp-text' : 'text-ctp-subtext0 hover:text-ctp-text'"
            @click="switchTab(tb.key)"
          >
            <component
              :is="tb.icon"
              class="w-4 h-4"
            />{{ t(`requirement.tab.${tb.key}`) }}
          </button>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <template v-if="tab === 'proposal'">
            <button
              class="btn btn-blue"
              :disabled="!proposals.length"
              @click="analyzeNext"
            >
              <BoltIcon class="w-4 h-4" />{{ t('requirement.analyze') }}
            </button>
            <button
              class="btn btn-green"
              @click="openNew"
            >
              <PlusIcon class="w-4 h-4" />{{ t('requirement.newRaw') }}
            </button>
          </template>
          <template v-else>
            <span class="text-[11px] text-ctp-overlay1">{{ t('requirement.selectedCount', { n: selectedPool.length }) }}</span>
            <button
              class="btn btn-primary"
              :disabled="!selectedPool.length"
              @click="executeFromPool"
            >
              <ArrowRightIcon class="w-4 h-4" />{{ t('requirement.executeFromPool') }}
            </button>
          </template>
        </div>
      </div>
    </div>

    <div class="flex-1 min-h-0 px-5 pb-5">
      <template v-if="tab === 'proposal'">
        <div
          class="h-full overflow-auto space-y-4"
        >
          <div class="panel overflow-hidden">
            <div class="panel-header">
              <span class="flex items-center gap-2">
                <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-peach" />{{ t('requirement.raw') }}
                <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ t('requirement.list.rawGroup') }}</span>
              </span>
              <span class="text-[11px] text-ctp-overlay1">{{ proposals.length }}</span>
            </div>
            <div class="p-3 space-y-2">
              <p class="text-[11px] text-ctp-subtext0 -mt-0.5">
                {{ t('requirement.rawHint') }}
              </p>
              <div
                v-for="r in proposals"
                :key="r.id"
                class="border border-ctp-surface0 rounded-lg p-3"
              >
                <div class="flex items-center gap-2">
                  <span class="text-[11px] font-mono text-ctp-overlay1">{{ r.id }}</span>
                  <span
                    class="chip"
                    :class="kindColor[r.kind]"
                  >{{ t(`requirement.kind.${r.kind}`) }}</span>
                  <span
                    class="chip"
                    :class="prioColor[r.priority]"
                  >{{ r.priority }}</span>
                  <span class="text-sm font-medium text-ctp-text truncate flex-1">{{ r.title }}</span>
                  <span
                    class="chip"
                    :class="statusColor[r.status]"
                  >{{ t(`requirement.status.${r.status}`) }}</span>
                </div>
                <p class="text-xs text-ctp-subtext0 mt-1.5 line-clamp-3">
                  {{ r.remarks ?? r.desc }}
                </p>
                <div
                  v-if="r.preferredAssetIds?.length"
                  class="flex flex-wrap items-center gap-1.5 mt-1.5"
                >
                  <span class="text-[10px] text-ctp-overlay1">{{ t('requirement.preferredAssets') }}:</span>
                  <span
                    v-for="a in r.preferredAssetIds"
                    :key="a"
                    class="chip bg-ctp-sky/15 text-ctp-sky font-mono"
                  >{{ a }}</span>
                </div>
                <div class="flex flex-wrap items-center gap-1.5 mt-1.5">
                  <span
                    v-if="r.relatedTo?.length"
                    class="chip bg-ctp-lavender/15 text-ctp-lavender"
                  ><LinkIcon class="w-3 h-3 inline" />{{ t('requirement.relatedTo') }}: {{ r.relatedTo.join(', ') }}</span>
                  <span
                    v-if="r.mergedInto"
                    class="chip bg-ctp-mauve/15 text-ctp-mauve"
                  ><LinkIcon class="w-3 h-3 inline" />{{ t('requirement.mergedInto') }} {{ r.mergedInto }}</span>
                </div>
                <div class="flex flex-wrap items-center gap-1.5 mt-2">
                  <button
                    class="btn btn-sm btn-ghost"
                    @click="openAnalysis(r.id)"
                  >
                    <PencilSquareIcon class="w-3.5 h-3.5" />{{ t('requirement.edit') }}
                  </button>
                  <button
                    class="btn btn-sm btn-ghost"
                    @click="store.cancel(r.id)"
                  >
                    <TrashIcon class="w-3.5 h-3.5" />{{ t('requirement.cancel') }}
                  </button>
                </div>
              </div>
              <p
                v-if="!proposals.length"
                class="text-xs text-ctp-overlay0 text-center py-6"
              >
                {{ t('common.empty') }}
              </p>
            </div>
          </div>
        </div>
      </template>

      <div
        v-else
        class="h-full overflow-auto space-y-4"
      >
        <div class="panel overflow-hidden">
          <div class="p-3 space-y-2">
            <p class="text-[11px] text-ctp-subtext0 -mt-0.5">
              {{ t('requirement.poolHint') }}
            </p>
            <div
              v-for="r in poolItems"
              :key="r.id"
              class="border border-ctp-surface0 rounded-lg p-3"
              :class="selectedPool.includes(r.id) ? 'ring-1 ring-ctp-green/40 border-ctp-green/40' : ''"
            >
              <div class="flex items-center gap-2">
                <input
                  type="checkbox"
                  class="accent-ctp-green shrink-0"
                  :checked="selectedPool.includes(r.id)"
                  :disabled="r.status === 'planned' || r.status === 'executing' || r.status === 'done'"
                  @change="togglePool(r.id)"
                >
                <span class="text-[11px] font-mono text-ctp-overlay1">{{ r.id }}</span>
                <span
                  class="chip"
                  :class="kindColor[r.kind]"
                >{{ t(`requirement.kind.${r.kind}`) }}</span>
                <span
                  class="chip"
                  :class="prioColor[r.priority]"
                >{{ r.priority }}</span>
                <span class="text-sm font-medium text-ctp-text truncate flex-1">{{ r.title }}</span>
                <span
                  v-if="r.routedBy === 'direct'"
                  class="chip bg-ctp-teal/15 text-ctp-teal"
                >{{ t('requirement.routedBy.direct') }}</span>
                <span
                  class="chip"
                  :class="statusColor[r.status]"
                >{{ t(`requirement.status.${r.status}`) }}</span>
                <button
                  class="btn btn-sm btn-ghost shrink-0"
                  :title="t('requirement.moveToProposal')"
                  :disabled="r.status === 'planned' || r.status === 'executing' || r.status === 'done'"
                  @click="store.moveToProposal(r.id)"
                >
                  <ArrowPathRoundedSquareIcon class="w-3.5 h-3.5" />
                </button>
                <button
                  class="btn btn-sm btn-ghost shrink-0"
                  :title="t('requirement.reanalyze')"
                  @click="openAnalysis(r.id)"
                >
                  <PencilSquareIcon class="w-3.5 h-3.5" />
                </button>
              </div>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
                <span
                  v-if="r.analysis?.functionalScope?.length"
                  class="chip bg-ctp-surface0 text-ctp-subtext1"
                >{{ t('requirement.functionalScope') }}: {{ r.analysis.functionalScope.slice(0, 3).join(' · ') }}</span>
                <span
                  v-if="r.analysis?.assetScope?.length"
                  class="chip bg-ctp-surface0 text-ctp-subtext1"
                >{{ t('requirement.assetScope') }}: {{ r.analysis.assetScope.map((a) => a.assetId).join(' · ') }}</span>
                <span
                  v-if="r.analysis?.specsMd"
                  class="chip bg-ctp-surface0 text-ctp-subtext1"
                >{{ t('requirement.report.specs') }}: {{ r.analysis.specsMd.split('\n').filter(Boolean).length }}</span>
                <span
                  v-if="r.analysis?.steps?.length"
                  class="chip bg-ctp-surface0 text-ctp-subtext1"
                >{{ r.analysis.steps.length }} {{ t('requirement.report.steps') }}</span>
                <span
                  v-if="r.analysis?.feasibility"
                  class="chip"
                  :class="r.analysis.feasibility.ok ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
                >{{ t(`requirement.feasibility${r.analysis.feasibility.ok ? 'Ok' : 'No'}`) }}</span>
              </div>
            </div>
            <p
              v-if="!poolItems.length"
              class="text-xs text-ctp-overlay0 text-center py-6"
            >
              {{ t('requirement.designEmpty') }}
            </p>
          </div>
        </div>

        <div class="panel overflow-hidden">
          <div class="panel-header">
            <span class="flex items-center gap-2">
              <CheckIcon class="w-3.5 h-3.5 text-ctp-green" />{{ t('requirement.list.executed') }}
              <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ t('requirement.list.executedGroup') }}</span>
            </span>
            <span class="text-[11px] text-ctp-overlay1">{{ executedItems.length }}</span>
          </div>
          <div class="p-3 space-y-2">
            <div
              v-for="r in executedItems"
              :key="r.id"
              class="border border-ctp-surface0 rounded-lg p-3"
            >
              <div class="flex items-center gap-2">
                <span class="text-[11px] font-mono text-ctp-overlay1">{{ r.id }}</span>
                <span
                  class="chip"
                  :class="kindColor[r.kind]"
                >{{ t(`requirement.kind.${r.kind}`) }}</span>
                <span
                  class="chip"
                  :class="prioColor[r.priority]"
                >{{ r.priority }}</span>
                <span class="text-sm font-medium text-ctp-text truncate flex-1">{{ r.title }}</span>
                <span
                  class="chip"
                  :class="statusColor[r.status]"
                >{{ t(`requirement.status.${r.status}`) }}</span>
              </div>
              <p class="text-xs text-ctp-subtext0 mt-1.5 line-clamp-3">
                {{ r.remarks ?? r.desc }}
              </p>
              <div class="flex flex-wrap items-center gap-1.5 mt-1.5">
                <span
                  v-if="r.planId"
                  class="chip bg-ctp-sky/15 text-ctp-sky font-mono"
                >{{ r.planId }}</span>
                <span
                  v-if="r.execId"
                  class="chip bg-ctp-surface0 text-ctp-mauve font-mono"
                >{{ r.execId }}</span>
              </div>
            </div>
            <p
              v-if="!executedItems.length"
              class="text-xs text-ctp-overlay0 text-center py-6"
            >
              {{ t('common.empty') }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
