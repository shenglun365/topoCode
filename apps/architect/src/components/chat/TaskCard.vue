<template>
  <div
    class="rounded-lg border border-ctp-surface1 bg-ctp-mantle/60 px-3 py-2 text-[12px]"
    :class="statusTone"
  >
    <div class="flex items-center gap-2 flex-wrap">
      <span
        class="font-semibold cursor-pointer select-none"
        title="点击收起/展开卡片"
        @click="toggleCollapse"
      >{{ task.title || '任务' }}</span>
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
      <!-- 执行器设定(未开始时可换): cline/opencode/codex -->
      <span v-if="task.status === 'pending_confirm' || task.status === 'saved'" class="flex items-center gap-0.5">
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
      <!-- 默认保存: saved → 开始执行/忽略; 存量 pending_confirm → 确认/取消 -->
      <template v-if="task.status === 'saved'">
        <button
          class="btn-mini bg-ctp-green/20 text-ctp-green hover:bg-ctp-green/30 disabled:opacity-40"
          :disabled="acted"
          @click="act('confirm', task.id)"
        >▶ 开始执行</button>
        <button
          class="btn-mini bg-ctp-red/15 text-ctp-red hover:bg-ctp-red/25 disabled:opacity-40"
          :disabled="acted"
          @click="act('ignore', task.id)"
        >✕ 忽略</button>
      </template>
      <template v-else-if="task.status === 'pending_confirm'">
        <button
          class="btn-mini bg-ctp-green/20 text-ctp-green hover:bg-ctp-green/30 disabled:opacity-40"
          :disabled="acted"
          @click="act('confirm', task.id)"
        >✓ 确认执行</button>
        <button
          class="btn-mini bg-ctp-red/15 text-ctp-red hover:bg-ctp-red/25 disabled:opacity-40"
          :disabled="acted"
          @click="act('cancel', task.id)"
        >✕ 取消</button>
      </template>
      <!-- 执行中 → 停止 -->
      <button
        v-else-if="task.status === 'running' || task.status === 'waiting_input'"
        class="btn-mini bg-ctp-red/15 text-ctp-red hover:bg-ctp-red/25 disabled:opacity-40"
        :disabled="acted"
        @click="act('cancel', task.id)"
      >⏹ 停止</button>
      <!-- 完成 → 已阅(reviewing 消化出口; 幂等) -->
      <button
        v-else-if="task.status === 'done' && !task.dismissedAt"
        class="btn-mini bg-ctp-surface0/60 text-ctp-overlay0 hover:text-ctp-subtext1"
        title="回执已阅——不合并、不建下张卡(留痕可追溯)"
        @click="$emit('dismiss', task.id)"
      >✓ 已阅</button>
      <CollapseChevron class="ml-auto" :collapsed="collapsed" @toggle="toggleCollapse" />
    </div>
    <!-- 收起体: header(标题/状态/操作)恒可见; v-show 保留挂载——StreamItems 实时流不丢 -->
    <div v-show="!collapsed">
    <div v-if="task.branch" class="mt-1 text-[10px] text-ctp-overlay1 font-mono">
      分支 {{ task.branch }}
    </div>
    <!-- 验收配置(V1): 待确认态可设 P0 显式命令/超时/修复轮次 -->
    <div v-if="task.status === 'pending_confirm' || task.status === 'saved'" class="mt-1.5">
      <button
        class="flex items-center gap-1 text-[10px] text-ctp-overlay1 hover:text-ctp-subtext1"
        @click="vcOpen = !vcOpen"
      >
        <AdjustmentsHorizontalIcon class="w-3 h-3" />
        验收配置
        <span
          v-if="vcSaved"
          class="text-ctp-green"
        >✓ 已保存(启动时生效)</span>
        <span
          v-else-if="hasVc"
          class="font-mono text-ctp-overlay0"
        >· 已定制</span>
        <span
          v-else
          class="text-ctp-overlay0"
        >· 自动发现</span>
      </button>
      <div
        v-if="vcOpen"
        class="mt-1 space-y-1.5 rounded border border-ctp-surface1 bg-ctp-base/60 p-2"
      >
        <div class="flex gap-1.5">
          <label class="min-w-0 flex-1">
            <span class="text-[9px] text-ctp-overlay0">构建命令(可选)</span>
            <input
              v-model="vc.build"
              class="input !py-0.5 !px-1.5 !text-[10px] w-full font-mono"
              placeholder="npm run build"
            >
          </label>
          <label class="min-w-0 flex-1">
            <span class="text-[9px] text-ctp-overlay0">测试命令(可选)</span>
            <input
              v-model="vc.test"
              class="input !py-0.5 !px-1.5 !text-[10px] w-full font-mono"
              placeholder="npm run test"
            >
          </label>
        </div>
        <div class="flex items-center gap-2.5 flex-wrap text-[9px] text-ctp-overlay0">
          <label>超时倍率
            <input
              v-model.number="vc.timeoutMul"
              type="number"
              min="0.5"
              max="10"
              step="0.5"
              class="input !py-0.5 !px-1 !text-[10px] w-14"
            >
          </label>
          <label>修复轮次上限
            <input
              v-model.number="vc.maxAttempts"
              type="number"
              min="1"
              max="6"
              class="input !py-0.5 !px-1 !text-[10px] w-12"
            >
          </label>
          <label class="flex items-center gap-1">
            <input
              v-model="vc.autoRepair"
              type="checkbox"
              class="accent-ctp-mauve"
            >失败自动修复回注
          </label>
          <span class="flex-1" />
          <button
            class="btn-mini bg-ctp-blue/20 text-ctp-blue hover:bg-ctp-blue/30"
            :disabled="vcSaving"
            @click="saveVc"
          >{{ vcSaving ? '保存中…' : '保存' }}</button>
        </div>
        <p class="text-[9px] leading-relaxed text-ctp-overlay0">
          留空=自动发现(P0 配置 → P1 CI → P2 约定 → P3 启发)；验收结果进回执与矩阵。
        </p>
      </div>
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
    <StreamItems
      v-if="convId"
      :conv-id="convId"
      :task-id="task.id"
    />
    <div v-if="task.status === 'waiting_input'" class="mt-1 text-ctp-peach">
      ⏸ 等待你的输入——直接回复即转达
    </div>
    <div v-if="task.resultMd && isTerminal" class="mt-1 text-ctp-subtext0 line-clamp-6 whitespace-pre-wrap">{{ task.resultMd }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { AdjustmentsHorizontalIcon } from '@heroicons/vue/24/outline'
import { apiPost } from '@/services/api-client'
import { useCardCollapse } from '@/composables/useCardCollapse'
import CollapseChevron from './CollapseChevron.vue'
import StreamItems from './StreamItems.vue'

const props = defineProps<{ task: Record<string, any>; convId?: string }>()
const emit = defineEmits<{ (e: 'confirm' | 'cancel' | 'ignore' | 'dismiss', taskId: string): void; (e: 'set-executor', taskId: string, executorType: string): void }>()

// 连点防重: 首次点击即锁定(慢路径秒级——后端 confirm 含探针/runner start),
// 任务状态翻转(running/失败等)后解锁。后端同会话锁+幂等为最终兜底。
const acted = ref(false)
watch(() => props.task.status, () => { acted.value = false })
function act(kind: 'confirm' | 'cancel' | 'ignore', id: string) {
  if (acted.value) return
  acted.value = true
  emit(kind, id)
}

// ── 验收配置(V1): 仅 pending_confirm 可写, 启动时随 start payload 下发 ──
const vcOpen = ref(false)
const vcSaving = ref(false)
const vcSaved = ref(false)
const vc = reactive<Record<string, any>>({})
function syncVc() {
  const src = props.task?.verifyConfig || {}
  vc.build = src.build || ''
  vc.test = src.test || ''
  vc.timeoutMul = src.timeoutMul || undefined
  vc.maxAttempts = src.maxAttempts || undefined
  vc.autoRepair = src.autoRepair !== false
  vcSaved.value = false
}
watch(() => props.task?.verifyConfig, syncVc, { immediate: true, deep: true })
const hasVc = computed(() => !!(props.task?.verifyConfig
  && Object.keys(props.task.verifyConfig).length))
async function saveVc() {
  vcSaving.value = true
  try {
    const cfg: Record<string, any> = {}
    if (String(vc.build || '').trim()) cfg.build = String(vc.build).trim()
    if (String(vc.test || '').trim()) cfg.test = String(vc.test).trim()
    if (vc.timeoutMul && Number(vc.timeoutMul) !== 1) cfg.timeoutMul = Number(vc.timeoutMul)
    if (vc.maxAttempts && Number(vc.maxAttempts) !== 3) cfg.maxAttempts = Number(vc.maxAttempts)
    if (vc.autoRepair === false) cfg.autoRepair = false
    await apiPost(`/tasks/${props.task.id}/verify-config`, { verifyConfig: cfg })
    vcSaved.value = true
  } catch { /* 错误静默(下次保存可重试) */ } finally {
    vcSaving.value = false
  }
}

const STATUS_TEXT: Record<string, string> = {
  pending_confirm: '待确认',
  saved: '已保存',
  running: '执行中',
  waiting_input: '等待输入',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
  ignored: '已忽略',
}
const statusText = computed(() => STATUS_TEXT[props.task.status] || props.task.status)
const isTerminal = computed(() => ['done', 'failed', 'cancelled', 'ignored'].includes(props.task.status))

// 收起/展开(统一状态源): 终态自动收起(仿问询卡已答先例), 用户覆盖持久化可反选
const { isCollapsed: cardIsCollapsed, toggle: cardToggle } = useCardCollapse()
const cardKey = computed(() => `task:${props.task.id}`)
const collapsed = computed(() => cardIsCollapsed(cardKey.value, isTerminal.value))
function toggleCollapse() {
  cardToggle(cardKey.value, isTerminal.value)
}
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
