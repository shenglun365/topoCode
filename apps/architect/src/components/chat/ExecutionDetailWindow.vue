<script setup lang="ts">
// cv-285 执行详情窗(方案甲: 双源 taskId|jobId 统一窗体)——任务行与直通作业
// 同一详情形状 + 单一控制面(pause/resume/stop/input, POST /execution/control)。
// 数据=GET /execution/detail 统一视图模型(exec_control 单源适配)。
// 入口: TaskCard/JobCard 组件内放大钮(组件层自持, 零宿主胶水)。
import { computed, ref, watch } from 'vue'
import { apiGet, apiPost } from '@/services/api-client'
import { useConversationStore } from '@/stores/conversation-store'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import ExecutorProcessStrip from './ExecutorProcessStrip.vue'

const props = defineProps<{
  convId?: string
  taskId?: string
  jobId?: string
}>()

const emit = defineEmits<{ close: [] }>()

interface Detail {
  source: string
  title: string
  status: string
  instruction?: string
  resultMd?: string
  specVer?: number
  executorType?: string
  branch?: string
  workspace?: string
  progress?: { toolCount?: number; msgCount?: number }
  jobId?: string
  runnerStatus?: string
  sessionRef?: string
  reqId?: string
}

const detail = ref<Detail | null>(null)
const errMsg = ref('')
const actionBusy = ref('')
const supplement = ref('')
const supplementMsg = ref('')

async function load() {
  errMsg.value = ''
  if (!props.convId || (!props.taskId && !props.jobId)) return
  try {
    const q = new URLSearchParams({ convId: props.convId })
    if (props.taskId) q.set('taskId', props.taskId)
    if (props.jobId) q.set('jobId', props.jobId)
    detail.value = await apiGet<Detail>(`/execution/detail?${q.toString()}`)
  } catch (e) {
    errMsg.value = e instanceof Error ? e.message : String(e)
  }
}
watch(() => [props.convId, props.taskId, props.jobId],
  () => { void load() }, { immediate: true })

// 控制钮可见性=状态机单谓词(避免散落 v-if)
const alive = computed(() =>
  ['running', 'waiting_input', 'pending_confirm'].includes(detail.value?.status || ''))
const failed = computed(() => detail.value?.status === 'failed')
const userTerminal = computed(() =>
  ['cancelled', 'ignored'].includes(detail.value?.status || ''))
const userTerminalIgnored = computed(() => detail.value?.status === 'ignored')
const canPause = computed(() =>
  alive.value && !!detail.value?.jobId && detail.value?.runnerStatus === 'running')
const canStop = computed(() => alive.value)
// cv-285e: 过程流(store 单源, SSE 实时)——直通会话窗口内嵌渲染
const _convStore = useConversationStore()
const proc = computed(() => _convStore.proxyProgressOf(props.convId))

async function control(action: string, text = '') {
  if (actionBusy.value) return
  actionBusy.value = action
  try {
    const res = await apiPost<{ ok?: boolean; error?: string; retried?: boolean }>(
      '/execution/control', {
        convId: props.convId, action,
        taskId: props.taskId || '', jobId: props.jobId || '', text,
      })
    if (res && res.ok === false) {
      // cv-285c: 后端拒绝显式透出(此前静默"已转达")
      supplementMsg.value = `⚠ ${res.error || '操作失败'}`
      return
    }
    if (action === 'stop' || res?.retried) await load()
    if (action === 'input') {
      supplementMsg.value = res?.retried
        ? (text ? '已附带补充并重试执行' : '已重新执行')
        : '已转达'
    }
  } catch (e) {
    supplementMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    actionBusy.value = ''
  }
}

async function sendSupplement() {
  if (userTerminalIgnored.value || actionBusy.value) return
  await control('input', supplement.value)
  supplement.value = ''
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6"
      @click.self="emit('close')"
    >
      <div class="flex w-[85vw] max-w-5xl max-h-[85vh] flex-col rounded-lg border border-ctp-surface1 bg-ctp-base shadow-2xl">
        <div class="flex shrink-0 flex-wrap items-center gap-2 border-b border-ctp-surface1 px-4 py-2.5">
          <span class="text-xs font-semibold text-ctp-peach">执行详情</span>
          <span class="max-w-60 truncate text-xs font-medium text-ctp-text">{{ detail?.title || '…' }}</span>
          <span
            v-if="detail?.executorType"
            class="chip !text-[10px] bg-ctp-surface1 text-ctp-subtext0 font-mono"
          >{{ detail.executorType }}</span>
          <span
            v-if="detail?.source === 'task' && detail?.specVer"
            class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve font-mono"
            title="本任务绑定需求规约(建卡时固化)"
          >规约 v{{ detail.specVer }}</span>
          <span
            v-if="detail?.workspace"
            class="chip !text-[9px] font-mono"
            :class="detail.workspace === 'worktree'
              ? 'bg-ctp-blue/15 text-ctp-blue' : 'bg-ctp-mauve/15 text-ctp-mauve'"
          >{{ detail.workspace === 'worktree' ? '隔离 worktree' : '融合模式' }}</span>
          <span
            v-if="detail?.branch"
            class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0 font-mono"
          >{{ detail.branch }}</span>
          <span
            v-if="detail"
            class="chip !text-[10px] font-mono"
            :class="alive ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-overlay0/15 text-ctp-overlay0'"
          >{{ detail.runnerStatus || detail.status }}{{ detail.progress?.toolCount ? ` · 工具 ×${detail.progress.toolCount}` : '' }}</span>
          <span class="flex-1" />
          <!-- cv-285e: 暂停/停止上移头部(关闭钮左侧) -->
          <button
            v-if="canPause"
            class="btn btn-xs btn-ghost"
            :disabled="!!actionBusy"
            title="暂停本轮执行——会话保留，发消息即恢复"
            @click="control('pause')"
          >⏸ 暂停</button>
          <button
            v-if="canStop"
            class="btn btn-xs btn-ghost text-ctp-red!"
            :disabled="!!actionBusy"
            title="停止——结束作业(保留分支与改动)"
            @click="control('stop')"
          >⏹ 停止</button>
          <button class="btn btn-xs btn-ghost" @click="emit('close')">✕ 关闭</button>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          <div
            v-if="errMsg"
            class="text-[11px] text-ctp-red"
          >⚠ {{ errMsg }}</div>
          <!-- cv-285e: 执行过程内嵌(过程渲染单源 strip, dense 无框; SSE 经 store 实时) -->
          <div
            v-if="detail?.source === 'job' && proc"
            class="mb-3"
          >
            <ExecutorProcessStrip
              dense
              :stoppable="false"
              :folded="false"
              :process="proc.process || []"
              :last-text="proc.lastText || ''"
              :last-tool="proc.lastTool || ''"
              :tool-count="proc.toolCount || 0"
              :turn-count="proc.turnCount || 0"
              :input-tokens="proc.inputTokens || 0"
              :output-tokens="proc.outputTokens || 0"
            />
          </div>
          <template v-if="detail">
            <div
              v-if="detail.instruction"
              class="mb-3"
            >
              <div class="mb-1 text-[11px] font-medium text-ctp-subtext1">任务指令</div>
              <div class="rounded-md border border-ctp-surface1 bg-ctp-mantle/60 px-3 py-2">
                <ChatMessageBlocks :content="detail.instruction" />
              </div>
            </div>
            <div
              v-if="detail.resultMd"
              class="mb-3"
            >
              <div class="mb-1 text-[11px] font-medium text-ctp-subtext1">结果</div>
              <div class="rounded-md border border-ctp-surface1 bg-ctp-mantle/60 px-3 py-2">
                <ChatMessageBlocks :content="detail.resultMd" />
              </div>
            </div>
          </template>
        </div>
        <div
          v-if="detail"
          class="shrink-0 border-t border-ctp-surface1 px-4 py-2"
        >
          <!-- cv-285e: 转达/继续合并为一钮——空消息=继续执行(原样重试) -->
          <div class="flex items-center gap-2">
            <input
              v-model="supplement"
              class="min-w-0 flex-1 rounded-md border border-ctp-surface1 bg-ctp-mantle px-2.5 py-1.5 text-[11px] text-ctp-text outline-none focus:border-ctp-blue disabled:opacity-40"
              :disabled="userTerminalIgnored"
              :placeholder="userTerminalIgnored
                ? '任务已忽略——不可转达'
                : alive
                  ? '转达给执行器（留空 = 继续执行）'
                  : failed || detail?.status === 'cancelled'
                    ? '补充后转达 = 附补充重试（留空 = 原样重执行）'
                    : '可补充说明（留空 = 直接执行）'"
              @keydown.enter="sendSupplement"
            >
            <button
              class="btn btn-xs btn-blue shrink-0"
              :disabled="!!actionBusy || userTerminalIgnored"
              :title="alive ? '转达；留空即继续执行' : '重试执行；有文本则作为补充随指令下发'"
              @click="sendSupplement"
            >{{ alive ? '转达 / 继续' : '执行' }}</button>
          </div>
          <div
            v-if="supplementMsg"
            class="mt-1 text-[10px] text-ctp-overlay0"
          >{{ supplementMsg }}</div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
