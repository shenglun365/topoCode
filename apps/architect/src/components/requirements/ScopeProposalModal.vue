<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import type { ScopeProposal, ScopeProposalItem } from '@/types'

/**
 * 方向1：交互式数据资产范围圈定 —— 展示 LLM 提议的 core/related 范围(含业务理由)、
 * 与上版的迭代 diff(新增/移除/升级/降级)、待新建资产与覆盖说明。确认后 emit apply。
 */

const props = defineProps<{ open: boolean; proposal: ScopeProposal | null; loading: boolean }>()
const emit = defineEmits<{ close: []; apply: [ScopeProposal] }>()

const { t } = useI18n()

const core = computed(() => props.proposal?.proposal.filter((p) => p.role === 'core') ?? [])
const related = computed(() => props.proposal?.proposal.filter((p) => p.role === 'related') ?? [])

const diffTags = computed<Record<string, string>>(() => ({
  added: t('scope.diff.added'),
  removed: t('scope.diff.removed'),
  promoted: t('scope.diff.promoted'),
  demoted: t('scope.diff.demoted'),
}))

/** 该项在本次迭代 diff 中的标签集合。 */
function tagsOf(item: ScopeProposalItem): string[] {
  const d = props.proposal?.diff
  if (!d) return []
  const tags: string[] = []
  if (d.added.some((x) => x.assetId === item.assetId && x.assetType === item.assetType)) tags.push('added')
  if (d.promoted.some((x) => x.assetId === item.assetId && x.assetType === item.assetType)) tags.push('promoted')
  if (d.demoted.some((x) => x.assetId === item.assetId && x.assetType === item.assetType)) tags.push('demoted')
  if (d.removed.some((x) => x.assetId === item.assetId && x.assetType === item.assetType)) tags.push('removed')
  return tags
}

const tagColor: Record<string, string> = {
  added: 'bg-ctp-green/15 text-ctp-green',
  removed: 'bg-ctp-red/15 text-ctp-red',
  promoted: 'bg-ctp-blue/15 text-ctp-blue',
  demoted: 'bg-ctp-yellow/15 text-ctp-yellow',
}

function groupByType(items: ScopeProposalItem[]): { type: string; items: ScopeProposalItem[] }[] {
  const m = new Map<string, ScopeProposalItem[]>()
  for (const it of items) {
    if (!m.has(it.assetType)) m.set(it.assetType, [])
    m.get(it.assetType)!.push(it)
  }
  return [...m.entries()].map(([type, list]) => ({ type, items: list }))
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
  >
    <div class="flex flex-col w-full max-w-3xl max-h-[85vh] rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden">
      <div class="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0">
        <SparklesIcon class="w-4 h-4 text-ctp-blue" />
        <h3 class="text-sm font-semibold text-ctp-text">
          {{ t('scope.title') }}
        </h3>
        <span class="text-[10px] text-ctp-overlay0 hidden md:inline">{{ t('scope.hint') }}</span>
        <span class="flex-1" />
        <button
          class="btn btn-xs btn-ghost"
          @click="emit('close')"
        >
          <XMarkIcon class="w-3.5 h-3.5" />{{ t('scope.close') }}
        </button>
      </div>

      <div class="flex-1 min-h-0 overflow-auto p-4 space-y-4">
        <div
          v-if="loading"
          class="text-xs text-ctp-overlay0 text-center py-10"
        >
          {{ t('scope.running') }}
        </div>
        <p
          v-else-if="!proposal"
          class="text-xs text-ctp-overlay0 text-center py-10"
        >
          {{ t('scope.empty') }}
        </p>

        <template v-else>
          <div
            v-for="(g, gi) in groupByType(core)"
            :key="`core-${gi}`"
            class="space-y-1.5"
          >
            <div class="flex items-center gap-2">
              <span class="chip bg-ctp-green/15 text-ctp-green !text-[10px] shrink-0">{{ t('scope.core') }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[10px] font-mono shrink-0">{{ g.type }}</span>
              <span class="text-[10px] text-ctp-overlay0">{{ g.items.length }}</span>
            </div>
            <div
              v-for="(it, i) in g.items"
              :key="i"
              class="border border-ctp-surface0 rounded-md px-2.5 py-1.5 flex items-start gap-2"
            >
              <span class="text-[11px] font-mono text-ctp-text shrink-0">{{ it.assetId }}</span>
              <span class="text-[11px] text-ctp-subtext1 truncate">{{ it.businessReason || '—' }}</span>
              <span class="flex-1" />
              <span
                v-for="(tg, ti) in tagsOf(it)"
                :key="ti"
                class="chip !text-[9px] shrink-0"
                :class="tagColor[tg]"
              >{{ diffTags[tg] }}</span>
            </div>
          </div>

          <div
            v-for="(g, gi) in groupByType(related)"
            :key="`rel-${gi}`"
            class="space-y-1.5"
          >
            <div class="flex items-center gap-2">
              <span class="chip bg-ctp-blue/15 text-ctp-blue !text-[10px] shrink-0">{{ t('scope.related') }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[10px] font-mono shrink-0">{{ g.type }}</span>
              <span class="text-[10px] text-ctp-overlay0">{{ g.items.length }}</span>
            </div>
            <div
              v-for="(it, i) in g.items"
              :key="i"
              class="border border-ctp-surface0 rounded-md px-2.5 py-1.5 flex items-start gap-2"
            >
              <span class="text-[11px] font-mono text-ctp-text shrink-0">{{ it.assetId }}</span>
              <span class="text-[11px] text-ctp-subtext1 truncate">{{ it.businessReason || '—' }}</span>
              <span class="flex-1" />
              <span
                v-for="(tg, ti) in tagsOf(it)"
                :key="ti"
                class="chip !text-[9px] shrink-0"
                :class="tagColor[tg]"
              >{{ diffTags[tg] }}</span>
            </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div
              v-if="proposal.coverage?.length"
              class="border border-ctp-surface0 rounded-md p-2.5"
            >
              <div class="text-[10px] font-semibold text-ctp-subtext1 mb-1">
                {{ t('scope.coverage') }}
              </div>
              <ul class="space-y-0.5">
                <li
                  v-for="(c, i) in proposal.coverage"
                  :key="i"
                  class="text-[10px] text-ctp-subtext0 list-disc list-inside"
                >
                  {{ c }}
                </li>
              </ul>
            </div>
            <div
              v-if="proposal.missing?.length"
              class="border border-ctp-yellow/20 rounded-md p-2.5"
            >
              <div class="text-[10px] font-semibold text-ctp-yellow mb-1">
                {{ t('scope.missing') }}
              </div>
              <ul class="space-y-0.5">
                <li
                  v-for="(m, i) in proposal.missing"
                  :key="i"
                  class="text-[10px] text-ctp-subtext0 list-disc list-inside"
                >
                  {{ m }}
                </li>
              </ul>
            </div>
          </div>

          <p class="text-[9px] text-ctp-overlay0">
            {{ t('scope.catalogHint') }}：{{ proposal.catalog?.length ?? 0 }} 项
          </p>
        </template>
      </div>

      <div class="shrink-0 border-t border-ctp-surface0 px-4 py-2.5 flex justify-end gap-2">
        <button
          class="btn btn-ghost"
          @click="emit('close')"
        >
          {{ t('scope.close') }}
        </button>
        <button
          class="btn btn-blue"
          :disabled="!proposal"
          @click="proposal && emit('apply', proposal)"
        >
          {{ t('scope.apply') }}
        </button>
      </div>
    </div>
  </div>
</template>
