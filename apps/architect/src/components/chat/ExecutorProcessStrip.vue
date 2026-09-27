<script setup lang="ts">
/**
 * ExecutorProcessStrip · 执行器过程条(cv-268 共享组件)
 *
 * 统一渲染三执行器(cline/opencode/codex)的执行过程感知——数据源为 SSE
 * progress 事件经 store 落的过程态(process 环形尾/lastText/lastTool/tokens):
 * - 任务卡(TaskCard): isLive 期间内嵌过程段(存量位)
 * - 直通消息区尾部: 活跃流式期间显示, turn_done 后折叠一行摘要(用户裁定)
 * 未来过程显示优化(时间轴/参数展开/耗时)统一在本组件内迭代。
 */
const props = withDefaults(defineProps<{
  /** 工具轨迹环形尾([{at, s}]) */
  process?: Array<{ at: number; s: string }>
  /** 活动文本预览(滚动尾) */
  lastText?: string
  /** 最近工具名 */
  lastTool?: string
  toolCount?: number
  inputTokens?: number
  outputTokens?: number
  /** 折叠态: 单行摘要(本轮工具次数), 不展开轨迹与文本 */
  folded?: boolean
  /** 紧凑模式(任务卡内嵌): 去外框 */
  dense?: boolean
}>(), {
  process: () => [],
  lastText: '',
  lastTool: '',
  toolCount: 0,
  inputTokens: 0,
  outputTokens: 0,
  folded: false,
  dense: false,
})

import { computed } from 'vue'

const tail = computed(() => (props.process || []).slice(-8))

function fmtTok(n: any): string {
  const v = Number(n) || 0
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
}
</script>

<template>
  <!-- 折叠态: 单行摘要(turn_done 后) -->
  <div v-if="folded" class="font-mono text-[9px] text-ctp-overlay0">
    ⚙ 本轮共 {{ toolCount }} 次工具调用
  </div>
  <div v-else-if="lastText || lastTool || process.length"
       class="rounded border border-ctp-surface1 bg-ctp-base/70 px-2 py-1.5"
       :class="dense ? '' : 'mt-1.5'">
    <div class="flex items-center gap-1.5">
      <span class="font-mono text-[10px] text-ctp-blue animate-pulse">● {{ lastTool || '执行中' }}</span>
      <span class="font-mono text-[9px] text-ctp-overlay0">
        工具 ×{{ toolCount }}<template v-if="inputTokens"> · {{ fmtTok(inputTokens) }}→{{ fmtTok(outputTokens) }} tok</template>
      </span>
    </div>
    <div
      v-if="lastText"
      class="mt-1 font-mono text-[10px] leading-relaxed text-ctp-subtext1 whitespace-pre-wrap line-clamp-5"
    >{{ lastText }}</div>
    <div v-if="tail.length" class="mt-1 flex flex-wrap gap-1">
      <span
        v-for="(p, i) in tail"
        :key="i"
        class="chip !text-[9px] font-mono bg-ctp-surface0/70 text-ctp-overlay1"
      >{{ p.s }}</span>
    </div>
  </div>
</template>
