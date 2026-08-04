<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { GlobeAltIcon } from '@heroicons/vue/24/outline'
import PageHeader from '@/components/PageHeader.vue'
import { useArchMcpStore } from '@/stores/mcp-store'
import type { ExternalCallStatus } from '@/types'

const { t } = useI18n()
const mcp = useArchMcpStore()
mcp.load()

const callStatusColor: Record<ExternalCallStatus, string> = {
  ok: 'bg-ctp-green/15 text-ctp-green',
  pending: 'bg-ctp-sky/15 text-ctp-sky',
  blocked: 'bg-ctp-red/15 text-ctp-red',
}

const doneCount = computed(() => mcp.calls.filter((c) => c.status === 'ok').length)
</script>

<template>
  <div class="p-5 space-y-4">
    <PageHeader
      :title="t('mcp.title')"
      :desc="t('mcp.desc')"
      action
    >
      <template #action>
        <span
          v-if="mcp.calls.length"
          class="chip bg-ctp-surface0 text-ctp-subtext1"
        >{{ doneCount }}/{{ mcp.calls.length }} {{ t('mcp.done') }}</span>
      </template>
    </PageHeader>

    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <GlobeAltIcon class="w-4 h-4 text-ctp-sky" />{{ t('mcp.calls') }}
        </span>
        <span
          v-if="mcp.pendingCount"
          class="chip bg-ctp-sky/15 text-ctp-sky"
        >{{ mcp.pendingCount }} {{ t('mcp.pending') }}</span>
      </div>
      <div class="p-3 space-y-2">
        <div
          v-for="c in mcp.calls"
          :key="c.id"
          class="flex items-center gap-2 border border-ctp-surface0 rounded-lg px-3 py-2"
        >
          <span
            class="chip shrink-0"
            :class="callStatusColor[c.status]"
          >{{ t(`mcp.callStatus.${c.status}`) }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext1 shrink-0">{{ c.source }}</span>
          <code class="font-mono text-xs text-ctp-sapphire shrink-0">{{ c.tool }}</code>
          <span class="flex-1 min-w-0 text-xs text-ctp-subtext1 truncate">{{ c.detail }}</span>
          <span class="text-[10px] text-ctp-overlay1 shrink-0">{{ new Date(c.time).toLocaleTimeString() }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
