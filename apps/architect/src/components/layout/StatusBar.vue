<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useArchMcpStore } from '@/stores/mcp-store'

const { t } = useI18n()
const mcp = useArchMcpStore()
mcp.load()
</script>

<template>
  <footer class="h-7 shrink-0 flex items-center gap-4 px-4 bg-ctp-crust border-t border-ctp-surface0 text-[11px] text-ctp-overlay1">
    <span
      v-if="mcp.calls.length"
      class="chip bg-ctp-surface0 text-ctp-sky"
      :title="t('overview.externalCalls')"
    >
      {{ t('overview.externalCalls') }}: {{ mcp.calls.length }}<template v-if="mcp.pendingCount"> · {{ mcp.pendingCount }} {{ t('mcp.pending') }}</template>
    </span>
    <div class="flex-1" />
    <span>{{ t('app.name') }} · prototype v0.1</span>
  </footer>
</template>
