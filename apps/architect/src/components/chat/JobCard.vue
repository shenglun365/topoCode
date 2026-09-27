<script setup lang="ts">
// cv-283 直通作业卡(JobCard): 与 TaskCard 同族——直通模式与 architect 指派
// 模式的任务卡归一(用户裁决: proxy 卡升级同构)。数据源=消息 meta 作业快照
// (jobId/jobState/executorType/mode, items.py 统一投影 type=job), 活动态由
// 宿主经 proxy-state REST 覆写(liveState)。控制: ⏸暂停(abort 保会话)/
// ⏹结束会话(finish)——复用 cv-275 proxy-stop 分型端点; 补充指引=直接发消息
// (steer 语义, 会话存活时自动转达)。
import { computed } from 'vue'

const props = defineProps<{
  payload: { jobId?: string; jobState?: string; executorType?: string;
             mode?: string; fingerprint?: string }
  liveState?: string      // 活动态覆写(running|idle|ended|'')
  stopping?: boolean
}>()

const emit = defineEmits<{ stop: [] }>()

const state = computed(() => props.liveState || props.payload.jobState || 'running')
const stateView = computed(() => ({
  running: { label: '执行中', cls: 'bg-ctp-green/15 text-ctp-green', icon: '⚙️' },
  idle: { label: '已暂停 · 会话保留', cls: 'bg-ctp-yellow/15 text-ctp-yellow', icon: '⏸' },
  ended: { label: '已结束', cls: 'bg-ctp-overlay0/15 text-ctp-overlay0', icon: '⏹' },
}[state.value] || { label: state.value, cls: 'bg-ctp-surface1 text-ctp-subtext0', icon: '⚙️' }))

const alive = computed(() => state.value !== 'ended')
</script>

<template>
  <div class="rounded-lg border border-ctp-surface1 bg-ctp-mantle/60 px-3 py-2 text-[12px] mb-2"
       :class="alive ? 'border-ctp-teal/30' : ''">
    <div class="flex items-center gap-2 flex-wrap">
      <span class="text-[13px] shrink-0">{{ stateView.icon }}</span>
      <span class="font-semibold">编码执行器会话</span>
      <span
        v-if="payload.executorType"
        class="chip !text-[10px] bg-ctp-surface1 text-ctp-subtext0 font-mono"
      >{{ payload.executorType }}</span>
      <span
        v-if="payload.mode"
        class="chip !text-[9px] font-mono"
        :class="payload.mode === 'worktree'
          ? 'bg-ctp-blue/15 text-ctp-blue' : 'bg-ctp-mauve/15 text-ctp-mauve'"
      >{{ payload.mode === 'worktree' ? '隔离 worktree' : '融合模式' }}</span>
      <span
        class="chip !text-[10px] font-mono"
        :class="stateView.cls"
      >{{ stateView.label }}</span>
      <span class="flex-1" />
      <button
        v-if="alive"
        class="btn btn-xs btn-ghost shrink-0"
        :disabled="stopping"
        title="暂停本轮执行——会话保留，发消息即恢复"
        @click="emit('stop')"
      >{{ stopping ? '处理中…' : '⏸ 暂停 / ⏹ 结束' }}</button>
    </div>
    <div
      v-if="alive"
      class="mt-1 text-[10px] text-ctp-overlay0"
    >补充对话指引：直接在输入框发消息（会话存活时自动转达执行器）；过程详见下方执行器输出与控制条。</div>
  </div>
</template>
