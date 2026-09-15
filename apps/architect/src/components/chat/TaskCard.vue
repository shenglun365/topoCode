<template>
  <div
    class="rounded-lg border border-ctp-surface1 bg-ctp-mantle/60 px-3 py-2 text-[12px]"
    :class="statusTone"
  >
    <div class="flex items-center gap-2 flex-wrap">
      <span class="font-semibold">{{ task.title || '任务' }}</span>
      <span class="chip !text-[10px] bg-ctp-surface1 text-ctp-subtext0 font-mono">{{ task.executorType || 'opencode' }}</span>
      <span
        v-if="task.specVer > 0"
        class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve font-mono"
        title="本任务绑定需求规约(建卡时固化), 执行指令含方案/边界/验收"
      >规约 v{{ task.specVer }}</span>
      <span class="chip !text-[10px]" :class="statusChip">{{ statusText }}</span>
      <span
        v-if="progress && task.status === 'running'"
        class="font-mono text-ctp-subtext0 animate-pulse"
        :title="`消息 ×${progress.msgCount ?? 0} · ${new Date(progress.at || 0).toLocaleTimeString()}`"
      >⚙ ×{{ progress.toolCount ?? 0 }}</span>
      <span class="flex-1" />
      <!-- 执行器设定(待确认时可换): cline/opencode/codex -->
      <span v-if="task.status === 'pending_confirm'" class="flex items-center gap-0.5">
        <button
          v-for="ex in ['opencode', 'cline', 'codex']"
          :key="ex"
          class="chip !text-[9px] font-mono transition-colors"
          :class="(task.executorType || 'opencode') === ex
            ? 'bg-ctp-sky/20 text-ctp-sky' : 'bg-ctp-surface0/60 text-ctp-overlay0 hover:text-ctp-subtext1'"
          :title="`用 ${ex} 执行${ex === 'cline' ? '(嵌入式通用 agent)' : ex === 'opencode' ? '(serve 模式)' : '(app-server)'}`"
          @click="$emit('set-executor', task.id, ex)"
        >{{ ex }}</button>
      </span>
      <!-- 轻门禁: 待确认 → 确认/取消 -->
      <template v-if="task.status === 'pending_confirm'">
        <button
          class="btn-mini bg-ctp-green/20 text-ctp-green hover:bg-ctp-green/30"
          @click="$emit('confirm', task.id)"
        >✓ 确认执行</button>
        <button
          class="btn-mini bg-ctp-red/15 text-ctp-red hover:bg-ctp-red/25"
          @click="$emit('cancel', task.id)"
        >✕ 取消</button>
      </template>
      <!-- 执行中 → 停止 -->
      <button
        v-else-if="task.status === 'running' || task.status === 'waiting_input'"
        class="btn-mini bg-ctp-red/15 text-ctp-red hover:bg-ctp-red/25"
        @click="$emit('cancel', task.id)"
      >⏹ 停止</button>
    </div>
    <div v-if="task.branch" class="mt-1 text-[10px] text-ctp-overlay1 font-mono">
      分支 {{ task.branch }}
    </div>
    <!-- 执行过程(准流式): 工具轨迹 + 滚动文本尾, 随 SSE progress 实时变化 -->
    <div
      v-if="isLive && progress && (progress.lastText || progress.lastTool || (progress.process || []).length)"
      class="mt-1.5 rounded border border-ctp-surface1 bg-ctp-base/70 px-2 py-1.5"
    >
      <div class="flex items-center gap-1.5">
        <span class="font-mono text-[10px] text-ctp-blue animate-pulse">● {{ progress.lastTool || '执行中' }}</span>
        <span class="font-mono text-[9px] text-ctp-overlay0">
          工具 ×{{ progress.toolCount ?? 0 }}<template v-if="progress.inputTokens"> · {{ fmtTok(progress.inputTokens) }}→{{ fmtTok(progress.outputTokens) }} tok</template>
        </span>
      </div>
      <div
        v-if="progress.lastText"
        class="mt-1 font-mono text-[10px] leading-relaxed text-ctp-subtext1 whitespace-pre-wrap line-clamp-5"
      >{{ progress.lastText }}</div>
      <div v-if="(progress.process || []).length" class="mt-1 flex flex-wrap gap-1">
        <span
          v-for="(p, i) in processTail"
          :key="i"
          class="chip !text-[9px] font-mono bg-ctp-surface0/70 text-ctp-overlay1"
        >{{ p.s }}</span>
      </div>
    </div>
    <div v-if="task.status === 'waiting_input'" class="mt-1 text-ctp-peach">
      ⏸ 等待你的输入——直接回复即转达
    </div>
    <div v-if="task.resultMd && isTerminal" class="mt-1 text-ctp-subtext0 line-clamp-6 whitespace-pre-wrap">{{ task.resultMd }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ task: Record<string, any> }>()
defineEmits<{ (e: 'confirm' | 'cancel', taskId: string): void; (e: 'set-executor', taskId: string, executorType: string): void }>()

const STATUS_TEXT: Record<string, string> = {
  pending_confirm: '待确认',
  running: '执行中',
  waiting_input: '等待输入',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
}
const statusText = computed(() => STATUS_TEXT[props.task.status] || props.task.status)
const isTerminal = computed(() => ['done', 'failed', 'cancelled'].includes(props.task.status))
const progress = computed(() => (typeof props.task.progress === 'object' && props.task.progress) || null)
const isLive = computed(() => ['running', 'waiting_input'].includes(props.task.status))
const processTail = computed(() => ((props.task.progress?.process) || []).slice(-8))
function fmtTok(n: any): string {
  const v = Number(n) || 0
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
}
const statusTone = computed(() => ({
  pending_confirm: 'border-ctp-yellow/30',
  running: 'border-ctp-blue/30',
  waiting_input: 'border-ctp-peach/40',
  done: 'border-ctp-green/30',
  failed: 'border-ctp-red/30',
  cancelled: 'opacity-60',
}[props.task.status] || ''))
const statusChip = computed(() => ({
  pending_confirm: 'bg-ctp-yellow/15 text-ctp-yellow',
  running: 'bg-ctp-blue/15 text-ctp-blue',
  waiting_input: 'bg-ctp-peach/15 text-ctp-peach',
  done: 'bg-ctp-green/15 text-ctp-green',
  failed: 'bg-ctp-red/15 text-ctp-red',
  cancelled: 'bg-ctp-surface1 text-ctp-overlay0',
}[props.task.status] || 'bg-ctp-surface1 text-ctp-subtext0'))
</script>
