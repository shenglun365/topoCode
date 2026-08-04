<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { DocumentTextIcon, ChevronDownIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'
import type { ArchChangeReport } from '@/services/arch-change-service'

const props = defineProps<{ report: ArchChangeReport | null }>()
const { t } = useI18n()

const collapsed = ref(false)
const open = () => {
  collapsed.value = !collapsed.value
}

const baseline = computed(() => props.report?.baseline)
const files = computed(() => props.report?.files)
const nodes = computed(() => props.report?.nodes)
const relations = computed(() => props.report?.relations)
const leafComponents = computed(() => props.report?.leafComponents ?? [])

const nodeCount = computed(() => nodes.value?.length ?? 0)
const relDepends = computed(() => relations.value?.filter((r) => r.kind === 'depends').length ?? 0)
const relCalls = computed(() => relations.value?.filter((r) => r.kind === 'calls').length ?? 0)

const fileTotal = computed(() => (files.value?.added ?? 0) + (files.value?.modified ?? 0) + (files.value?.deleted ?? 0))

function fmtDate(ts: number): string {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

function changeCls(c: string): string {
  return c === 'added' ? 'bg-ctp-green/15 text-ctp-green'
    : c === 'removed' ? 'bg-ctp-red/15 text-ctp-red'
      : c === 'modified' ? 'bg-ctp-peach/15 text-ctp-peach'
        : 'bg-ctp-surface0 text-ctp-subtext0'
}
</script>

<template>
  <div class="panel overflow-hidden">
    <button
      class="w-full flex items-center gap-2 px-4 py-3 text-left cursor-pointer"
      @click="open"
    >
      <DocumentTextIcon class="w-4 h-4 text-ctp-mauve shrink-0" />
      <span class="flex-1 text-sm font-medium text-ctp-text">{{ t('archMap.impactTitle') }}</span>
      <span
        class="chip bg-ctp-surface0 text-ctp-subtext0"
      >{{ fileTotal }} · {{ t('archChange.fileUnit') }}</span>
      <component
        :is="collapsed ? ChevronRightIcon : ChevronDownIcon"
        class="w-4 h-4 text-ctp-overlay1 shrink-0"
      />
    </button>

    <div
      v-if="!collapsed"
      class="border-t border-ctp-surface0 px-4 py-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3"
    >
      <!-- 基线版本信息 -->
      <div class="space-y-1.5">
        <div class="text-[11px] font-medium text-ctp-overlay1">
          {{ t('archChange.baselineInfo') }}
        </div>
        <div class="flex items-center gap-1.5 text-xs text-ctp-subtext0">
          <span class="chip bg-ctp-mauve/15 text-ctp-mauve shrink-0">{{ baseline?.version || '—' }}</span>
          <span class="font-mono truncate">{{ baseline?.commit || '—' }}</span>
        </div>
        <div class="flex items-center gap-1.5 text-[11px] text-ctp-subtext0">
          <span class="chip bg-ctp-surface0 shrink-0">{{ t('archChange.branch') }}</span>
          <span class="truncate">{{ baseline?.branch || '—' }}</span>
        </div>
        <div class="text-[11px] text-ctp-overlay1">
          {{ t('archChange.analyzedAt') }} {{ fmtDate(baseline?.analyzedAt ?? 0) }}
        </div>
        <div class="text-[11px] text-ctp-overlay1">
          {{ t('archChange.gitDate') }} {{ fmtDate(baseline?.gitDate ?? 0) }}
        </div>
      </div>

      <!-- 文件增删改 -->
      <div class="space-y-1.5">
        <div class="text-[11px] font-medium text-ctp-overlay1">
          {{ t('archChange.fileChange') }}
        </div>
        <div class="flex flex-wrap gap-1.5">
          <span class="chip bg-ctp-green/15 text-ctp-green">+{{ files?.added ?? 0 }}</span>
          <span class="chip bg-ctp-peach/15 text-ctp-peach">~{{ files?.modified ?? 0 }}</span>
          <span class="chip bg-ctp-red/15 text-ctp-red">−{{ files?.deleted ?? 0 }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ t('archChange.total') }} {{ fileTotal }}</span>
        </div>
        <div class="text-[11px] text-ctp-overlay1">
          {{ t('archChange.fileHint') }}
        </div>
      </div>

      <!-- 变更节点与关系数量 -->
      <div class="space-y-1.5">
        <div class="text-[11px] font-medium text-ctp-overlay1">
          {{ t('archChange.nodeRelation') }}
        </div>
        <div class="flex flex-wrap gap-1.5">
          <span class="chip bg-ctp-surface0 text-ctp-text">{{ t('archChange.node') }} {{ nodeCount }}</span>
          <span class="chip bg-ctp-sky/15 text-ctp-sky">{{ t('archChange.depends') }} {{ relDepends }}</span>
          <span class="chip bg-ctp-lavender/15 text-ctp-lavender">{{ t('archChange.calls') }} {{ relCalls }}</span>
        </div>
        <div class="text-[11px] text-ctp-overlay1">
          {{ t('archChange.nodeHint') }}
        </div>
      </div>

      <!-- 涉及的叶子组件 -->
      <div class="space-y-1.5">
        <div class="text-[11px] font-medium text-ctp-overlay1">
          {{ t('archChange.leafComponents') }}
        </div>
        <div
          v-if="leafComponents.length"
          class="flex flex-wrap gap-1"
        >
          <span
            v-for="name in leafComponents"
            :key="name"
            class="chip bg-ctp-blue/15 text-ctp-blue"
          >{{ name }}</span>
        </div>
        <div
          v-else
          class="text-[11px] text-ctp-overlay1"
        >
          —
        </div>
        <div class="text-[11px] text-ctp-overlay1">
          {{ t('archChange.leafHint') }}
        </div>
      </div>
    </div>

    <!-- 变更节点明细(展开态底部) -->
    <div
      v-if="!collapsed && nodes?.length"
      class="border-t border-ctp-surface0 px-4 py-3 flex flex-wrap gap-1.5"
    >
      <span
        v-for="n in nodes"
        :key="`${n.kind}-${n.id}`"
        class="chip"
        :class="changeCls(n.change)"
        :title="n.file"
      >
        {{ n.change === 'added' ? '+' : n.change === 'removed' ? '−' : n.change === 'modified' ? '~' : '·' }} {{ n.name }}
        <span class="text-[9px] opacity-70">{{ t(`archMap.kind.${n.kind}`) }}</span>
      </span>
    </div>
  </div>
</template>
