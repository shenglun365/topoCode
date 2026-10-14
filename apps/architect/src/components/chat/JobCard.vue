<script setup lang="ts">
// cv-283 直通作业卡(JobCard): 与 TaskCard 同族——直通模式与 architect 指派
// 模式的任务卡归一(用户裁决: proxy 卡升级同构)。数据源=消息 meta 作业快照
// (jobId/jobState/executorType/mode, items.py 统一投影 type=job), 活动态由
// 宿主经 proxy-state REST 覆写(liveState)。控制: ⏸暂停(abort 保会话)/
// ⏹结束会话(finish)——复用 cv-275 proxy-stop 分型端点; 补充指引=直接发消息
// (steer 语义, 会话存活时自动转达)。
import { computed, ref } from 'vue'
import ExecutorProcessStrip from './ExecutorProcessStrip.vue'
import ExecutionDetailWindow from './ExecutionDetailWindow.vue'

const props = defineProps<{
  payload: { jobId?: string; jobState?: string; executorType?: string;
             mode?: string; fingerprint?: string }
  liveState?: string      // 活动态覆写(running|idle|ended|'')
  stopping?: boolean
  convId?: string         // cv-285 执行详情窗数据源
  /** cv-285e 过程流(store 单源, SSE 实时): 轨迹/turnCount 并入本卡 */
  proc?: { process?: Array<{ at: number; s: string }>; lastText?: string;
           lastTool?: string; toolCount?: number; inputTokens?: number;
           outputTokens?: number; turnCount?: number; folded?: boolean } | null
}>()

const emit = defineEmits<{ stop: [mode?: 'abort' | 'finish'] }>()

const state = computed(() => props.liveState || props.payload.jobState || 'running')
const stateView = computed(() => ({
  running: { label: '执行中', cls: 'bg-ctp-green/15 text-ctp-green', icon: '⚙️' },
  idle: { label: '空闲(发消息继续)', cls: 'bg-ctp-yellow/15 text-ctp-yellow', icon: '⏸' },
  ended: { label: '已结束', cls: 'bg-ctp-overlay0/15 text-ctp-overlay0', icon: '⏹' },
}[state.value] || { label: state.value, cls: 'bg-ctp-surface1 text-ctp-subtext0', icon: '⚙️' }))

const alive = computed(() => state.value !== 'ended')
// cv-285 执行详情窗(组件内自持挂载)
const showDetail = ref(false)
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
      <!-- cv-285 执行详情窗入口(双源之二: 直通作业) -->
      <button
        v-if="payload.jobId"
        class="text-ctp-overlay0 hover:text-ctp-blue transition-colors p-0.5 shrink-0"
        title="放大查看执行详情 — 控制(暂停/继续/停止/转达)"
        @click="showDetail = true"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607ZM10.5 7.5v6m3-3h-6" /></svg>
      </button>
      <!-- 2610 cv-15: 按钮跟随状态——running=暂停+结束(可后续会话恢复);
           idle=仅结束会话(暂停无意义, 发消息即继续); ended=无按钮 -->
      <button
        v-if="state === 'running'"
        class="btn btn-xs btn-ghost shrink-0"
        :disabled="stopping"
        title="暂停本轮执行——会话保留，发消息即恢复"
        @click="emit('stop', 'abort')"
      >⏸ 暂停</button>
      <button
        v-if="state === 'running' || state === 'idle'"
        class="btn btn-xs btn-ghost shrink-0"
        :disabled="stopping"
        :title="state === 'idle'
          ? '结束直通会话——下条消息将开启全新会话'
          : '结束本轮与会话'"
        @click="emit('stop', 'finish')"
      >{{ stopping ? '处理中…' : state === 'idle' ? '⏹ 结束会话' : '⏹ 结束' }}</button>
    </div>
    <!-- cv-285e: 过程条并入任务卡(轨迹/turnCount/文本尾, SSE 实时)——feed 底部独立条已撤 -->
    <ExecutorProcessStrip
      v-if="proc"
      class="mt-1"
      dense
      :stoppable="false"
      :folded="state !== 'running' || !!proc.folded"
      :process="proc.process || []"
      :last-text="proc.lastText || ''"
      :last-tool="proc.lastTool || ''"
      :tool-count="proc.toolCount || 0"
      :turn-count="proc.turnCount || 0"
      :input-tokens="proc.inputTokens || 0"
      :output-tokens="proc.outputTokens || 0"
    />
    <div
      v-if="alive"
      class="mt-1 text-[10px] text-ctp-overlay0"
    >补充对话指引：直接在输入框发消息（会话存活时自动转达执行器）；🔍 可开执行详情窗。</div>
    <!-- cv-285 执行详情窗(组件内自持挂载) -->
    <ExecutionDetailWindow
      v-if="showDetail"
      :job-id="payload.jobId"
      :conv-id="convId"
      @close="showDetail = false"
    />
  </div>
</template>
