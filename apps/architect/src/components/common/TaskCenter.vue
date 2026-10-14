<script setup lang="ts">
import { computed } from 'vue'
import type { SemanticJob } from './task-center'
import { useTaskCenter } from './task-center'

const { visible, jobs, active, cancelling, close, cancel, remove, clearFinished, labelOf, stateOf, pctOf }
  = useTaskCenter()
const stateText = (j: SemanticJob): string =>
  cancelling.value.has(j.id) && (j.state === 'queued' || j.state === 'running')
    ? '停止中…' : stateOf(j)

/** 终态作业可删除；进行中仅可停止。 */
const isFinal = (j: SemanticJob): boolean => j.state !== 'queued' && j.state !== 'running'
const finishedCount = computed(() => jobs.value.filter(isFinal).length)

const STATE_CLS: Record<string, string> = {
  queued: 'text-ctp-overlay1',
  running: 'text-ctp-sky',
  done: 'text-ctp-green',
  failed: 'text-ctp-red',
  cancelled: 'text-ctp-peach',
  lost: 'text-ctp-yellow',
}
const CARD_CLS: Record<string, string> = {
  failed: 'border-ctp-red/40',
  lost: 'border-ctp-yellow/40',
}

function fmtTime(ts?: number): string {
  if (!ts) return ''
  const d = new Date(ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}
</script>

<template>
  <div
    v-if="visible"
    class="fixed bottom-8 right-3 z-[2200] flex max-h-[60vh] w-[340px] flex-col rounded-lg border border-ctp-surface0 bg-ctp-mantle shadow-2xl"
  >
    <div class="flex items-center gap-2 border-b border-ctp-surface0 px-3 py-2">
      <span class="text-[13px] font-semibold text-ctp-text">任务中心</span>
      <span class="flex-1 text-xs text-ctp-overlay1">运行 {{ active.length }} · 共 {{ jobs.length }}</span>
      <button
        v-if="finishedCount"
        class="rounded px-1.5 py-0.5 text-[11px] text-ctp-overlay1 hover:bg-ctp-surface0 hover:text-ctp-text"
        title="清除全部已结束记录"
        @click="clearFinished()"
      >清除已结束</button>
      <button class="text-ctp-overlay1 hover:text-ctp-text" title="收起" @click="close">—</button>
    </div>
    <!-- 列表视口限高≈5 条卡片：默认只见最新 5 条，向下滚动看更旧历史 -->
    <div class="max-h-[20.5rem] overflow-y-auto p-1.5">
      <div v-if="!jobs.length" class="py-5 text-center text-xs text-ctp-overlay1">暂无作业</div>
      <div
        v-for="j in jobs" :key="j.id"
        class="mb-1.5 rounded-md border bg-ctp-crust/60 p-1.5 pl-2.5 text-xs"
        :class="CARD_CLS[j.state] || 'border-ctp-surface0'"
      >
        <div class="flex items-center gap-1.5">
          <span class="font-semibold text-ctp-text">{{ labelOf(j) }}</span>
          <span class="text-[11px]" :class="STATE_CLS[j.state] || 'text-ctp-overlay1'">{{ stateText(j) }}</span>
          <span class="flex-1 text-right text-[11px] tabular-nums text-ctp-overlay0">{{ fmtTime(j.startedAt || j.createdAt) }}</span>
          <button
            v-if="!isFinal(j)"
            class="text-[10px] text-ctp-overlay1 hover:text-ctp-red"
            title="停止"
            @click="cancel(j.id)"
          >■</button>
          <button
            v-else
            class="text-[13px] leading-none text-ctp-overlay1 hover:text-ctp-red"
            title="删除记录"
            @click="remove(j.id)"
          >×</button>
        </div>
        <div v-if="j.state === 'running' || j.state === 'queued'" class="my-1 h-1 overflow-hidden rounded-full bg-ctp-surface0">
          <div class="h-full bg-ctp-blue transition-all duration-500" :style="{ width: pctOf(j) + '%' }" />
        </div>
        <div class="mt-0.5 flex gap-2 text-[11px] text-ctp-overlay1">
          <span v-if="j.progress?.total" class="tabular-nums">{{ j.progress?.done ?? 0 }}/{{ j.progress.total }}</span>
          <span v-if="j.progress?.saved !== undefined">已存 {{ j.progress.saved }}</span>
          <span v-if="j.progress?.current" class="tc-current" :title="j.progress.current">
            {{ j.progress.current }}
          </span>
          <span v-else-if="j.state === 'done' && j.result?.summary" class="text-ctp-green">{{ j.result.summary }}</span>
          <span v-else-if="j.state === 'failed' && j.result?.summary" class="text-ctp-red">{{ j.result.summary }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tc-current {
  max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  direction: rtl; text-align: left;
}
</style>
