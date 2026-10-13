<script setup lang="ts">
/**
 * 核心资产评估卡(2610 P2)——执行终态自动落地的评估性结论(非阻断)。
 *
 * 三联动: 结构化文字(裁决/命中清单+规约) + 组件影响半径(结构) +
 * 触及文件/资产坐标(代码锚点, stale 徽标)。数据=payload(items 统一投影)。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ShieldCheckIcon } from '@heroicons/vue/24/outline'

interface Mark { id: string; type: string; title: string; level: string; rules: string }
interface AssetHit { id: string; name: string; kind: string; status: string }
interface CompHit { id: string; name: string; depsOut: number; depsIn: number }

const props = defineProps<{
  payload: { verdict?: string; totalChanged?: number; hitChanged?: number
             marks?: Mark[]; hitFiles?: string[]
             assetImpact?: AssetHit[]; componentRadius?: CompHit[]; source?: string }
}>()

const { t } = useI18n()

const verdictView = computed(() => ({
  light: { label: t('session.assess.light'), cls: 'bg-ctp-green/15 text-ctp-green' },
  medium: { label: t('session.assess.medium'), cls: 'bg-ctp-yellow/15 text-ctp-yellow' },
  heavy: { label: t('session.assess.heavy'), cls: 'bg-ctp-red/15 text-ctp-red' },
}[props.payload.verdict || 'light'] || { label: props.payload.verdict, cls: '' }))

const typeLabel = (s: string) => t(`session.marks.type.${s}`) || s
</script>

<template>
  <div class="mb-2 rounded-lg border border-ctp-teal/30 bg-ctp-mantle/60 px-3 py-2 text-[12px]">
    <div class="flex flex-wrap items-center gap-2">
      <ShieldCheckIcon class="h-3.5 w-3.5 shrink-0 text-ctp-teal" />
      <span class="font-semibold">{{ t('session.assess.title') }}</span>
      <span class="chip !text-[10px] shrink-0" :class="verdictView.cls">🛡 {{ verdictView.label }}</span>
      <span class="chip !text-[10px] shrink-0 bg-ctp-surface0 text-ctp-subtext0">
        {{ t('session.assess.summary', { total: payload.totalChanged ?? 0, hit: payload.hitChanged ?? 0 }) }}
      </span>
      <span class="flex-1" />
      <span v-if="payload.source" class="shrink-0 font-mono text-[9px] text-ctp-overlay0">{{ payload.source }}</span>
    </div>

    <!-- 命中标记 + 绑定规约(文字) -->
    <ul v-if="payload.marks?.length" class="mt-1.5 space-y-1">
      <li v-for="m in payload.marks" :key="m.id"
          class="flex items-start gap-1.5 rounded bg-ctp-surface0/50 px-2 py-1">
        <span class="chip !text-[9px] shrink-0 font-mono"
          :class="m.level === 'critical' ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-teal/15 text-ctp-teal'"
        >{{ m.level === 'critical' ? '🔴' : '★' }} {{ typeLabel(m.type) }}</span>
        <div class="min-w-0 flex-1">
          <span class="font-medium">{{ m.title }}</span>
          <p v-if="m.rules" class="whitespace-pre-wrap text-[11px] text-ctp-subtext0">{{ m.rules }}</p>
        </div>
      </li>
    </ul>

    <!-- 三联动: 组件影响半径(结构) + 资产(代码锚点, stale 徽标) + 文件坐标 -->
    <div class="mt-1.5 grid gap-1.5 md:grid-cols-2">
      <div v-if="payload.componentRadius?.length">
        <p class="mb-0.5 text-[9px] font-medium uppercase tracking-wider text-ctp-overlay1">
          {{ t('session.assess.radius') }}</p>
        <div class="flex flex-wrap gap-1">
          <span v-for="c in payload.componentRadius" :key="c.id"
                class="chip !text-[10px] bg-ctp-mauve/15 text-ctp-mauve"
                :title="c.id"
          >{{ c.name }} <span class="font-mono opacity-70">↑{{ c.depsIn }} ↓{{ c.depsOut }}</span></span>
        </div>
      </div>
      <div v-if="payload.assetImpact?.length">
        <p class="mb-0.5 text-[9px] font-medium uppercase tracking-wider text-ctp-overlay1">
          {{ t('session.assess.assets') }}</p>
        <div class="flex flex-wrap gap-1">
          <span v-for="a in payload.assetImpact" :key="a.id"
                class="chip !text-[10px]"
                :class="a.status === 'stale' ? 'bg-ctp-yellow/15 text-ctp-yellow' : 'bg-ctp-surface0 text-ctp-subtext1'"
                :title="a.id + (a.status === 'stale' ? ' · stale(需 reconcile)' : '')"
          >{{ a.name }}<span v-if="a.status === 'stale'" class="font-mono opacity-70">·stale</span></span>
        </div>
      </div>
    </div>
    <p v-if="payload.hitFiles?.length" class="mt-1.5 truncate font-mono text-[10px] text-ctp-overlay0"
       :title="payload.hitFiles.join('\n')">
      {{ payload.hitFiles.slice(0, 6).join(' · ') }}{{ payload.hitFiles.length > 6 ? ' …' : '' }}
    </p>
    <p class="mt-1 text-[10px] text-ctp-overlay0">{{ t('session.assess.hint') }}</p>
  </div>
</template>
