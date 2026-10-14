<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useArchMcpStore } from '@/stores/mcp-store'
import { useTaskCenter } from '@/components/common/task-center'
import TaskCenter from '@/components/common/TaskCenter.vue'

const { t } = useI18n()
const mcp = useArchMcpStore()
mcp.load()
// 任务中心 tag：活跃作业数徽标，点击呼出/收起浮窗面板
const { visible, active, toggle } = useTaskCenter()
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
    <button
      class="tc-tag"
      :class="{ on: active.length }"
      :title="active.length ? `任务中心：${active.length} 个进行中` : '任务中心'"
      @click="toggle"
    >
      <span v-if="active.length" class="tc-dot" />
      任务中心<template v-if="active.length"> · {{ active.length }}</template>
    </button>
    <span>{{ t('app.name') }} · prototype v0.1</span>
  </footer>
  <TaskCenter />
</template>

<style scoped>
.tc-tag {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 1px 8px; border-radius: 9999px; cursor: pointer;
  background: rgb(13 17 23 / 60%); border: 1px solid transparent;
  color: inherit; font-size: 11px; line-height: 16px;
}
.tc-tag:hover { border-color: rgb(50 58 70 / 90%); color: rgb(207 214 228); }
.tc-tag.on { color: rgb(125 180 230); }
.tc-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: #5aa2dd; animation: tc-pulse 1.2s ease-in-out infinite;
}
@keyframes tc-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
</style>
