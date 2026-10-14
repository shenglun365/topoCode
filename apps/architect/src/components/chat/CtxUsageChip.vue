<script setup lang="ts">
/**
 * 上下文用量 chip(纯展示) — 发送按钮旁的容量提示。
 * 数据来源: 后端回合落账 conversations.meta.ctxUsage(cognition/ctx_usage)。
 * - budget>0: 标签「~已用 (百分比)」, hover 给绝对值; ≥80% 黄 / ≥95% 红
 * - budget=0(容量探测不到): 标签「~已用」
 * - 无数据时由父级 v-if 不渲染
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CtxUsage } from '@/types'

const props = defineProps<{ usage: CtxUsage }>()
const { t } = useI18n()

const WARN_RATIO = 0.8
const CRIT_RATIO = 0.95

function fmtTok(n: number): string {
  const v = Number(n) || 0
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
}

const hasBudget = computed(() => (props.usage?.budget || 0) > 0)
const pct = computed(() => hasBudget.value
  ? Math.min(100, Math.round((props.usage.used / props.usage.budget) * 100))
  : 0)
const tone = computed(() =>
  !hasBudget.value ? 'text-ctp-overlay0'
    : pct.value >= CRIT_RATIO * 100 ? 'text-ctp-red'
      : pct.value >= WARN_RATIO * 100 ? 'text-ctp-yellow'
        : 'text-ctp-overlay0')
const title = computed(() => hasBudget.value
  ? t('requirement.chat.ctxUsageTitle', { used: fmtTok(props.usage.used), budget: fmtTok(props.usage.budget) })
  : t('requirement.chat.ctxUsageTitleNoBudget', { used: fmtTok(props.usage.used) }))
const label = computed(() => `~${fmtTok(props.usage.used)}${hasBudget.value ? ` (${pct.value}%)` : ''}`)
</script>

<template>
  <span
    class="flex items-center shrink-0 font-mono text-[10px] cursor-help select-none"
    :class="tone"
    :title="title"
  >⌁ {{ label }}</span>
</template>
