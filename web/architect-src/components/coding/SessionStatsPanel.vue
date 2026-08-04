<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ChartBarIcon } from '@heroicons/vue/24/outline'
import type { TaskSessionStats } from '@/types'

const props = defineProps<{ stats?: TaskSessionStats | null }>()
const { t } = useI18n()

const s = () => props.stats ?? { requests: 0, tokensIn: 0, tokensOut: 0, bytesIn: 0, bytesOut: 0 }
</script>

<template>
  <div class="flex items-center gap-1.5">
    <ChartBarIcon class="w-3.5 h-3.5 text-ctp-mauve shrink-0" />
    <span class="text-[11px] font-medium text-ctp-subtext1 shrink-0">{{ t('execute.stats') }}</span>
    <span class="chip bg-ctp-surface0 text-[10px] shrink-0">{{ t('execute.statsReq', { n: s().requests }) }}</span>
    <span class="chip bg-ctp-surface0 text-[10px] shrink-0">{{ t('execute.statsTokens', { i: s().tokensIn, o: s().tokensOut }) }}</span>
    <span class="chip bg-ctp-surface0 text-[10px] shrink-0">{{ t('execute.statsBytes', { i: s().bytesIn, o: s().bytesOut }) }}</span>
  </div>
</template>
