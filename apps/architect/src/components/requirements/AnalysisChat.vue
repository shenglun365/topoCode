<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, provide, reactive, ref, watch } from 'vue'
import { kindChipClass } from '@/services/semantic-kind-style'
import { useI18n } from 'vue-i18n'
import { DocumentTextIcon, ArrowPathIcon, PaperAirplaneIcon, ChatBubbleLeftRightIcon, PencilSquareIcon, SparklesIcon, BookOpenIcon, CheckIcon, QuestionMarkCircleIcon, ClipboardDocumentCheckIcon, ClipboardDocumentIcon, TrashIcon, CubeTransparentIcon, BoltIcon, AdjustmentsHorizontalIcon, ChevronDownIcon, ChevronRightIcon, StopIcon, ArrowTopRightOnSquareIcon, WrenchScrewdriverIcon, XMarkIcon, ExclamationCircleIcon, AtSymbolIcon, CpuChipIcon } from '@heroicons/vue/24/outline'
import type { KbAnalysisTurn } from '@/services/kb-analysis-agent'
import type { AcceptanceFact, AcceptanceReportDetail, ContractItem } from '@/services/contract-service'
import type { NamingConvention } from '@/services/naming-service'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import TaskCard from '@/components/chat/TaskCard.vue'
import ChoicesCard from '@/components/chat/ChoicesCard.vue'
import AssetsPanel from '@/components/chat/AssetsPanel.vue'
import CtxUsageChip from '@/components/chat/CtxUsageChip.vue'
import CollapseChevron from '@/components/chat/CollapseChevron.vue'
import ChevronSvg from '@/components/chat/ChevronSvg.vue'
import { useCardCollapse } from '@/composables/useCardCollapse'
import { parseSpecPayload, assembleSpecView } from '@/services/spec-view'
import { apiPost, apiGet, apiPut } from '@/services/api-client'
import type { CtxUsage, SemanticAsset } from '@/types'
import type { ToolTrailItem } from '@/composables/useChatProgress'
import { copyText } from '@/utils/clipboard'

import { useChatCards } from './chat-view/useChatCards'
import { useChatInput } from './chat-view/useChatInput'
import { useChatRoute } from './chat-view/useChatRoute'
import { useChatDigest } from './chat-view/useChatDigest'
import { useChatSend } from './chat-view/useChatSend'
import { useChatActions } from './chat-view/useChatActions'
import { useChatProposal } from './chat-view/useChatProposal'
import { useChatContract } from './chat-view/useChatContract'
import type { ChatDeps } from './chat-view/chatTypes'
import { WS_KEY } from './chat-view/key'

const props = defineProps<{
  turns: KbAnalysisTurn[]
  busy: boolean
  /** 忙碌态动态文案(如「正在调用工具 kb.asset.search…」)；缺省用静态「知识库检索中…」。 */
  busyLabel?: string
  /** 本轮工具轨迹(tool_call/tool_result 驱动，useChatProgress 维护)；浮层展示。 */
  toolTrail?: ToolTrailItem[]
  /** 外部引用预填(组件「引用名称+ID」快捷按钮)：nonce 变化即把 text 追加进输入框。 */
  insertDraft?: { text: string; nonce: number } | null
  /** 对话标题(缺省「需求分析对话」；资产管理等复用场景可覆盖)。 */
  title?: string
  /** 头部标题可编辑: 悬停显示 手动修改/自动摘要 按钮(宿主接线保存/摘要)。 */
  editable?: boolean
  /** 自动摘要进行中(按钮转圈)。 */
  titleSummarizing?: boolean
  /** 绘图增强(IR→代码)：开启后 agent 经 diagram.build 工具生成语法正确的图。 */
  diagramSkill?: boolean
  /** 归档只读: 禁用输入与发送(读取/复制/提炼仍可用)。 */
  readOnly?: boolean
  /** running 归属(S2): {role:'coding', executorId, status} 有活跃作业时非空。 */
  jobState?: { role: string; executorId?: string; status?: string; progress?: { toolCount?: number; msgCount?: number; at?: number } } | null
  /** 已绑定执行器 id(S2/S3): 空=未绑定——Coding 切换钮首击触发分配(bind-coding)。 */
  boundExecutorId?: string
  /** 执行器注册表(启用项): 工具栏选择钮清单与完整名称显示。 */
  executors?: Array<{ id: string; type?: string; default?: boolean }>
  /** 执行器白名单模型名列表(≥2 时显示模型 chip)。 */
  executorModels?: string[]
  /** 当前会话模型(空=默认)。 */
  executorModel?: string
  /** v2 分析挡位(strict/quick): 快捷挡直切钮展示并可切换(上抛宿主 → REST 即时生效)。 */
  analysisMode?: 'strict' | 'quick'
  /** 需求澄清挡位(cv-190): auto(自动, 缺口驱动) | forced(强制, 先澄清后落卡)。 */
  clarifyMode?: 'auto' | 'forced'
  /** worktree 隔离模式(cv-202): false=就地(缺省) | true=显式要求隔离执行。 */
  isolated?: boolean
  /** 会话是否已存在: false=空白对话(记录未创建)——挡位是会话级字段无处可写, 直切钮禁用+提示。 */
  hasSession?: boolean
  /** 会话 id(语境摘要 REST 用); 空=无会话。 */
  convId?: string
  /** 知识资产面板(输入框上方折叠条): 缺省显示; 会话中心已移至左栏, 传 false 隐藏。 */
  showAssetsPanel?: boolean
  /** v2 coding subagent 任务清单(arch_tasks, 倒序; TaskCard 渲染 + 语境路由用)。 */
  tasks?: Array<Record<string, any>>
  /** 上下文用量账目(宿主自 activeMeta.meta.ctxUsage 下发; 空=从未对话不渲染)。 */
  ctxUsage?: CtxUsage | null
}>()

const emit = defineEmits<{
  /** 发送(语境路由): text 已剥离内联 @前缀; attachTo=转达任务卡, agent=一次性指派执行器, digest=语境摘要。 */
  send: [p: { text: string; attachTo?: string; agent?: string; digest?: string; synthetic?: boolean }]
  /** 分析挡位切换(strict/quick) → 宿主上抛 REST。 */
  'set-analysis-mode': [mode: 'strict' | 'quick']
  'set-clarify-mode': [mode: 'auto' | 'forced']
  'set-isolated': [on: boolean]
  /** 工具栏执行器选择: 上抛宿主执行绑定(未绑=bind; 已绑切换=克隆新会话)。 */
  'bind-executor': [executorId: string]
  'task-confirm': [taskId: string]
  'task-cancel': [taskId: string]
  'task-ignore': [taskId: string]
  'task-dismiss': [taskId: string]
  'task-executor': [p: { taskId: string; executorType: string }]
  'local-cmd': [name: string]
  'bind-coding': []
  'set-model': [model: string]
  rename: [title: string]
  'summarize-title': []
  answers: [answers: Record<string, string>]
  'confirm-draft': []
  'delete-turn': [index: number]
  'rollback-to': [index: number]
  'feed-turn': [p: { index: number; id?: string; summarize?: boolean }]
  'refresh-asset': [assetId: string]
  'toggle-diagram-skill': [enabled: boolean]
  'contract-confirm': [id: string]
  'contract-delete': [id: string]
  'contract-edit-save': [id: string, patch: Record<string, unknown>]
  'spec-apply': [p: { index: number; payload: Record<string, unknown> }]
  'convention-confirm': [id: string]
  'convention-ignore': [id: string]
  'goto-acceptance': []
  stop: []
}>()

// ── 头部标题行内编辑 ──
// ── 语境摘要(转达下发): 摘要模式选史 → REST 生成 → 可编辑草稿卡 → 发送/自动通过 ──

// ---- MS6-W3: 逻辑层8域(chat-view/)——本文件保留 props/emit/模板 ----
const { t } = useI18n()
const D: ChatDeps = { props, emit }
D.cards = useChatCards(D)
D.input = useChatInput(D)
D.route = useChatRoute(D)
D.digest = useChatDigest(D)
D.send = useChatSend(D)
D.actions = useChatActions(D)
D.proposal = useChatProposal(D)
D.contract = useChatContract(D)
const ws = Object.assign({}, D.cards, D.input, D.route, D.digest, D.send, D.actions, D.proposal, D.contract)
provide(WS_KEY, ws)
const {
  DIGEST_AUTO_KEY,
  INLINE_AGENTS,
  LOCAL_CMD_LIST,
  MAX_ROWS,
  MIN_ROWS,
  _ACTIVE_TASK_STATUS,
  _cardKey,
  activeTask,
  answeredByFlow,
  answers,
  approvalDone,
  assetKey,
  assetKindIcon,
  assetKindLabel,
  assetSummary,
  assetUsable,
  autoResize,
  canDigest,
  cancelDeleteTurn,
  choiceDrafts,
  choicesAnswered,
  choicesCards,
  clarifyForced,
  clarifyTitle,
  clearChoiceDraft,
  cmdFilter,
  cmdMenuOpen,
  commitTitleEdit,
  confirmDeleteTurn,
  confirmDigest,
  confirmMerge,
  confirmProposal,
  confirmingProposalId,
  contractBehaviorText,
  contractEditOpen,
  contractEditText,
  contractStatusCls,
  contractStatusLabel,
  contractTargetText,
  copiedTimer,
  copiedTurn,
  copyAsset,
  copyTurn,
  defaultExecutor,
  deletePending,
  diffSummary,
  digestAutoSend,
  digestBusy,
  digestDraft,
  digestMode,
  digestTargetTitle,
  draftTimers,
  editingTitle,
  effectiveRoute,
  ensureProposalState,
  executorFull,
  executorLabel,
  exitDigest,
  expandedAssets,
  feedBusyIdx,
  generateDigest,
  hasSpecCardFor,
  inlineAgent,
  input,
  inputMetrics,
  inputPlaceholder,
  inputRef,
  inputResizeObserver,
  isolatedOn,
  isolatedTitle,
  lastAppliedHeight,
  lastAssistantAgent,
  loadChoiceDrafts,
  mCollapsed,
  manualHeight,
  matchLocalCmd,
  mergeBusyIdx,
  mergedDone,
  modelMenuOpen,
  onAutoSendToggle,
  onChoicesReply,
  onCmdMenuKeydown,
  onContractConfirm,
  onContractDelete,
  onConventionConfirm,
  onConventionIgnore,
  onGotoAcceptance,
  onInputKeydown,
  onModelClick,
  onMsgCopy,
  onRefreshAsset,
  onSpecApply,
  onTitleInput,
  openAssetRef,
  openContractEdit,
  pickCmd,
  pickExecutor,
  pickModel,
  pickRoute,
  proposalChecked,
  proposalDone,
  proposalState,
  proposalStored,
  quickLocked,
  quickOn,
  quickTitle,
  reasoningOpen,
  removeTurn,
  reqActiveTask,
  resetInputHeight,
  respondApproval,
  roSuppress,
  routeBtnClass,
  routeDetail,
  routeMenuOpen,
  routeOverride,
  runLocalCmd,
  runMergePrecheck,
  runProposal,
  saveContractEdit,
  scheduleDraftSave,
  scrollRef,
  selIds,
  send,
  sendDigest,
  showToast,
  specAppliedIdx,
  specBusyIdx,
  specCard,
  specCardCollapsed,
  specDraftIdx,
  specDraftView,
  specPayloadOf,
  specSuperseded,
  specSupersededVer,
  specVer,
  stageClass,
  startTitleEdit,
  statusStrip,
  submitAnswers,
  taskById,
  taskTitleOf,
  titleDraft,
  toastText,
  toastTimer,
  toastVisible,
  toggleAsset,
  toggleClarifyMode,
  toggleDigestMode,
  toggleIsolated,
  toggleM,
  toggleQuickMode,
  toggleReasoning,
  toggleSel,
  toggleSpecCard,
  trailOpen,
} = ws

onUnmounted(() => {
  if (copiedTimer.value) clearTimeout(copiedTimer.value)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<template>
  <div class="relative flex flex-col h-full min-h-0 border border-ctp-surface0 rounded-lg overflow-hidden bg-ctp-crust/30">
    <!-- 布局: 标题+状态区靠左(状态类动态增长只向右扩); 收件人组(ml-auto)恒靠右,
         位置不随会话生命周期变化 -->
    <div class="panel-header relative shrink-0">
      <span class="flex min-w-0 items-center gap-2">
        <ChatBubbleLeftRightIcon class="w-4 h-4 shrink-0 text-ctp-blue" />
        <input
          v-if="editingTitle"
          v-model="titleDraft"
          class="input w-full min-w-0 max-w-72 !px-1.5 !py-0.5 text-xs"
          @keydown.enter.prevent="commitTitleEdit"
          @keydown.esc="editingTitle = false"
          @blur="commitTitleEdit"
        >
        <span
          v-else
          class="group/t flex min-w-0 items-center gap-1"
        >
          <span class="min-w-0 truncate">{{ title ?? t('requirement.chat.title') }}</span>
          <span
            v-if="editable"
            class="hidden shrink-0 items-center gap-0.5 group-hover/t:flex"
          >
            <button
              class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface0 hover:text-ctp-blue"
              :title="t('session.actions.rename')"
              @click="startTitleEdit"
            >
              <PencilSquareIcon class="h-3 w-3" />
            </button>
            <button
              class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface0 hover:text-ctp-blue"
              :title="t('session.actions.summarize')"
              @click="emit('summarize-title')"
            >
              <SparklesIcon class="h-3 w-3" :class="titleSummarizing ? 'animate-pulse' : ''" />
            </button>
          </span>
        </span>
        <!-- 状态类(reqId/运行中/停止): 跟随标题向右增长, 不影响收件人组 -->
        <slot name="header-extra" />
      </span>
      <!-- 模型 chip(语境路由 chip 移至输入区) -->
      <span class="ml-auto flex shrink-0 items-center gap-1">
        <slot name="header-inline" />
        <span
          v-if="props.boundExecutorId && (props.executorModels?.length ?? 0) >= 2"
          class="chip cursor-pointer select-none !text-[10px] font-mono transition-colors"
          :class="props.executorModel
            ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-surface0/60 text-ctp-overlay0 hover:text-ctp-subtext1'"
          :title="t('session.target.modelHint')"
          @click="onModelClick"
        >{{ props.executorModel || t('session.target.modelDefault') }}</span>
        <span
          v-if="modelMenuOpen && (props.executorModels?.length ?? 0) >= 2"
          class="absolute right-0 top-full z-50 mt-1 flex w-44 flex-col gap-0.5 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1 shadow-lg"
        >
          <button
            v-for="m in ['', ...(props.executorModels || [])]"
            :key="m || '__default__'"
            class="rounded px-2 py-1 text-left text-[11px] font-mono transition-colors"
            :class="m === (props.executorModel || '')
              ? 'bg-ctp-blue/15 text-ctp-blue' : 'text-ctp-subtext1 hover:bg-ctp-surface0'"
            @click="pickModel(m)"
          >{{ m || t('session.target.modelDefault') }}</button>
        </span>
      </span>
    </div>

    <!-- coding 视图执行进展行(SSE 实时, 不落库): 工具调用/消息计数 + 状态 -->
    <div
      v-if="props.jobState?.role === 'coding'"
      class="flex items-center gap-2 border-b border-ctp-surface0 bg-ctp-mantle/40 px-3 py-1 text-[10px] shrink-0"
    >
      <span
        class="inline-flex items-center gap-1"
        :class="props.jobState.status === 'waiting_input' ? 'text-ctp-peach' : 'text-ctp-blue animate-pulse'"
      >▶ {{ props.jobState.executorId || 'coding' }} · {{ props.jobState.status === 'waiting_input' ? '等待回复' : '执行中' }}</span>
      <span v-if="(props.jobState as any).progress" class="font-mono text-ctp-subtext0">
        ⚙ 工具 ×{{ (props.jobState as any).progress.toolCount ?? 0 }} · 消息 ×{{ (props.jobState as any).progress.msgCount ?? 0 }}
      </span>
      <span v-else class="text-ctp-overlay0">暂无进展数据(回合级事件到达时更新)</span>
      <span class="flex-1" />
      <span v-if="(props.jobState as any).progress?.at" class="text-ctp-overlay0 font-mono">{{ new Date((props.jobState as any).progress.at).toLocaleTimeString() }}</span>
    </div>

    <div
      ref="scrollRef"
      class="flex-1 min-h-[320px] overflow-auto p-3 space-y-2.5"
    >
      <!-- 摘要模式操作栏: 点选消息 → 生成摘要(草稿卡/自动通过) -->
      <div
        v-if="digestMode"
        class="flex items-center gap-2 rounded-md border border-ctp-teal/30 bg-ctp-teal/10 px-2.5 py-1.5 text-[11px] text-ctp-teal"
      >
        <ClipboardDocumentIcon class="w-3.5 h-3.5 shrink-0" />
        <span>摘要模式: 点击消息选取/取消（已选 {{ selIds.size }} 条）</span>
        <span class="flex-1" />
        <button
          class="btn btn-xs btn-primary"
          :disabled="!selIds.size || digestBusy"
          @click="generateDigest"
        >{{ digestBusy ? '生成中…' : '生成摘要' }}</button>
        <button
          class="btn btn-xs btn-ghost"
          @click="toggleDigestMode"
        >取消</button>
      </div>
        <div
          v-for="(m, i) in turns"
          v-show="!((m as any).meta?.synthetic)"
          :key="i"
          :id="(m as any).id ? `msg-${(m as any).id}` : undefined"
          class="animate-fade-up flex items-start gap-2 rounded-lg scroll-mt-2"
          :class="selIds.has((m as any).id) ? 'ring-1 ring-ctp-blue' : (digestMode ? 'cursor-pointer hover:ring-1 hover:ring-ctp-blue/40' : '')"
          @copy="onMsgCopy"
          @click="toggleSel(m)"
        >
        <div
          class="flex-1 min-w-0 rounded-lg rounded-tl-none px-3 py-2 text-xs bg-ctp-surface0/80"
          :class="m.role === 'user' ? 'ring-1 ring-ctp-sky/20' : ''"
        >
          <!-- 产出者标注(读侧归因): architect 外循环 / 具体执行器(泵以 agent=executor_type 落库) -->
          <div
            v-if="m.role === 'assistant'"
            class="mb-1 flex items-center gap-1 text-[9px]"
            :class="(m as any).agent ? 'text-ctp-teal' : 'text-ctp-overlay0'"
          >
            <CpuChipIcon class="w-3 h-3 shrink-0" />
            <span class="font-mono">{{ (m as any).agent || 'architect' }}</span>
          </div>
          <!-- A6.2 守门: 渲染只经统一投影(m.item), 禁历史卡片键/执行器类型分支 -->
          <ChoicesCard
            v-if="m.item?.type === 'choices'"
            class="mb-2"
            :payload="(m.item!.payload || {}) as any"
            :disabled="props.readOnly || props.busy"
            :used="choicesAnswered.has(String(m.id || m.item?.id || ''))
              || answeredByFlow.has(String(m.id || m.item?.id || ''))"
            :draft="choiceDrafts[String(m.id || m.item?.id || '')]"
            @draft-change="(d: any) => scheduleDraftSave(String(m.id || m.item?.id || ''), d)"
            @reply="(text: string) => onChoicesReply(String(m.id || m.item?.id || ''), text)"
          />
          <TaskCard
            v-if="m.item?.type === 'task' && taskById(m.item.payload?.taskId)"
            :conv-id="convId"
            :task="taskById(m.item.payload?.taskId)!"
            class="mb-2"
            @confirm="(id: string) => emit('task-confirm', id)"
            @cancel="(id: string) => emit('task-cancel', id)"
            @ignore="(id: string) => emit('task-ignore', id)"
            @dismiss="(id: string) => emit('task-dismiss', id)"
            @set-executor="(id: string, ex: string) => emit('task-executor', { taskId: id, executorType: ex })"
          />
          <div
            v-if="m.item?.type === 'approval'"
            class="mb-2 flex items-center gap-2 rounded-md border border-ctp-yellow/30 bg-ctp-yellow/10 px-2.5 py-1.5"
          >
            <ExclamationCircleIcon class="w-4 h-4 shrink-0 text-ctp-yellow" />
            <span class="text-[11px] text-ctp-yellow flex-1 min-w-0 truncate">
              {{ approvalDone[m.id] === 'approved' ? '✓ 已批准' : approvalDone[m.id] === 'rejected' ? '✗ 已拒绝' : `工具 ${m.item.payload?.approvalRequestId || ''} 请求执行，等待确认` }}
            </span>
            <template v-if="!approvalDone[m.id]">
              <button
                class="btn btn-primary !py-0.5 !px-2 !text-[10px] shrink-0"
                @click="respondApproval(m, true)"
              >批准</button>
              <button
                class="btn !py-0.5 !px-2 !text-[10px] shrink-0"
                @click="respondApproval(m, false)"
              >拒绝</button>
            </template>
          </div>
          <div class="flex items-center gap-1.5 mb-1">
            <svg
              v-if="m.role === 'user'"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="w-4 h-4 text-ctp-sky"
            >
              <circle
                cx="12"
                cy="8"
                r="4"
              />
              <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
            </svg>
            <span
              v-else-if="(m as any).agent"
              class="chip !text-[9px] bg-ctp-peach/15 text-ctp-peach font-mono"
              :title="`coding subagent(${(m as any).agent})产出`"
            >⚙ {{ (m as any).agent }}</span>
            <span
              v-else
              class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve"
            >
              <BookOpenIcon class="w-2.5 h-2.5 inline" />{{ t('requirement.chat.kb') }}
            </span>
            <span
              v-if="m.stage"
              class="chip !text-[9px]"
              :class="stageClass(m.stage)"
            >{{ t(`session.stage.${m.stage}`) }}</span>
            <span class="flex-1" />
            <button
              v-if="m.reasoning"
              class="text-ctp-overlay0 hover:text-ctp-sky transition-colors p-0.5 flex items-center gap-1 text-[10px]"
              :title="t('requirement.chat.toggleReasoning')"
              @click="toggleReasoning(i)"
            >
              <svg
                class="w-3 h-3"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              ><path d="M12 3a3 3 0 0 0-3 3v12a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" /><path d="M19 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" /><path d="M5 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" /></svg>
              <ChevronDownIcon
                v-if="reasoningOpen[i]"
                class="w-3 h-3"
              />
              <ChevronRightIcon
                v-else
                class="w-3 h-3"
              />
              {{ t('requirement.chat.reasoning') }}
            </button>
            <button
              class="text-ctp-overlay0 hover:text-ctp-blue transition-colors p-0.5"
              :title="t('requirement.chat.copyTurn')"
              :disabled="busy"
              @click="copyTurn(i)"
            >
              <ClipboardDocumentIcon
                v-if="copiedTurn !== i"
                class="w-3 h-3"
              />
              <CheckIcon
                v-else
                class="w-3 h-3 text-ctp-green"
              />
            </button>
            <button
              v-if="m.role === 'assistant' && !m.item"
              class="text-ctp-overlay0 hover:text-ctp-mauve transition-colors p-0.5"
              :title="t('session.subs.feedHint')"
              :disabled="feedBusyIdx === i"
              @click="emit('feed-turn', { index: i, id: (m as any).id })"
            >
              <PaperAirplaneIcon class="w-3 h-3 rotate-90" />
            </button>
            <button
              v-if="m.role === 'assistant' && !m.item"
              class="text-ctp-overlay0 hover:text-ctp-yellow transition-colors p-0.5"
              :title="t('session.subs.feedSummaryHint')"
              :disabled="feedBusyIdx === i"
              @click="emit('feed-turn', { index: i, id: (m as any).id, summarize: true })"
            >
              <SparklesIcon class="w-3 h-3" />
            </button>
            <button
              class="text-ctp-overlay0 hover:text-ctp-red transition-colors p-0.5"
              :title="t('requirement.chat.deleteTurn')"
              :disabled="busy"
              @click="removeTurn(i)"
            >
              <TrashIcon class="w-3 h-3" />
            </button>
            <button
              class="text-ctp-overlay0 hover:text-ctp-peach transition-colors p-0.5"
              title="回退到此 — 之后消息作废(运行中任务须先停止)"
              :disabled="busy"
              @click="emit('rollback-to', i)"
            >
              <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6" /><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" /></svg>
            </button>
          </div>

          <div
            v-if="m.reasoning && reasoningOpen[i]"
            class="mb-2 rounded-md border border-ctp-sky/20 bg-ctp-sky/5 px-2.5 py-2 text-[11px] text-ctp-subtext0 whitespace-pre-wrap max-h-64 overflow-auto"
          >
            <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-ctp-sky mb-1">
              <BookOpenIcon class="w-3 h-3" />{{ t('requirement.chat.reasoning') }}
            </div>
            {{ m.reasoning }}
          </div>
          <!-- 完成卡合并入口(环节十五): git 事实检视(主目录推进/分支内容/可否直并) -->
          <div
            v-if="m.item?.type === 'turn_completed' && m.item?.status === 'done' && m.item?.payload?.taskId"
            class="mt-1.5 flex items-center gap-2"
          >
            <button
              class="flex items-center gap-1.5 text-[10px] text-ctp-green hover:text-ctp-teal transition-colors"
              :disabled="mergeBusyIdx === i"
              title="合并入口检查 — 主目录是否有推进/是否可直接合并"
              @click="runMergePrecheck(i, m.item.payload?.taskId)"
            >
              <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M6 21V9a9 9 0 0 0 9 9" /></svg>
              合并检查
            </button>
            <button
              v-if="!mergedDone[i]"
              class="flex items-center gap-1.5 text-[10px] text-ctp-blue hover:text-ctp-sky transition-colors"
              :disabled="mergeBusyIdx === i"
              title="确认合并 — 门禁通过后执行(ff 仅快进; 主目录有推进时提示先 rebase)"
              @click="confirmMerge(i, m.item.payload?.taskId)"
            >
              <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
              确认合并
            </button>
            <span v-else class="text-[10px] text-ctp-green">✓ 已合并</span>
            <span v-if="mergeBusyIdx === i" class="text-[10px] text-ctp-overlay0">处理中…</span>
          </div>
          <!-- 转达摘要回执: 折叠卡(留"给执行器发过什么"的感知, 点开看全文; 默认收起) -->
          <div
            v-if="m.item?.type === 'digest'"
            class="rounded-md border border-ctp-teal/25 bg-ctp-teal/5 px-2.5 py-1.5"
          >
            <div
              class="flex items-center gap-1.5 text-[10px] text-ctp-teal cursor-pointer select-none"
              @click="toggleM(m, true)"
            >
              <ClipboardDocumentIcon class="w-3 h-3" />
              转达摘要 · {{ m.item.payload?.chars ?? m.content.length }} 字
              <ChevronSvg class="ml-auto" :collapsed="mCollapsed(m, true)" />
            </div>
            <div
              v-if="!mCollapsed(m, true)"
              class="mt-1.5 whitespace-pre-wrap text-[11px] leading-relaxed text-ctp-subtext1"
            >{{ m.content }}</div>
          </div>
          <!-- 规约草稿视图(cv-248): 正文规约 schema 载荷按 MD 分节渲染——
               载荷形态决定渲染形态, 与 specReady 卡同源(spec-view)。 -->
          <div
            v-if="specDraftIdx.has(i)"
            class="rounded-lg border border-ctp-surface1 bg-ctp-mantle/60 px-3 py-2"
          >
            <div class="mb-1 flex items-center gap-2">
              <span class="font-semibold text-ctp-text">{{ specDraftView(i).title || '需求规约（未落库）' }}</span>
              <span
                v-if="specDraftView(i).priority"
                class="chip !text-[9px] bg-ctp-peach/15 text-ctp-peach"
              >{{ specDraftView(i).priority }}</span>
              <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay0">未落库</span>
              <CollapseChevron class="ml-auto" :collapsed="mCollapsed(m)" @toggle="toggleM(m)" />
            </div>
            <div v-show="!mCollapsed(m)">
              <ChatMessageBlocks :content="specDraftView(i).body" />
            </div>
          </div>
          <ChatMessageBlocks
            v-else-if="!(m.role === 'assistant' && !m.item && specDraftIdx.has(i))
              && m.item?.type !== 'spec' && m.item?.type !== 'task_status'
              && m.item?.type !== 'choices'"
            :content="m.content"
          />

          <!-- 需求卡(cv-203/205 方案 A): 独立卡片消息 = 唯一宿主——
               标题/优先级/正文取提案载荷(m.proposal), 状态徽标联动任务;
               同消息的 S5 提案卡不再渲染(去重) -->
          <div
            v-if="m.item?.type === 'spec'"
            class="mt-2 rounded-lg border border-ctp-blue/30 bg-ctp-blue/5 px-3 py-2.5"
          >
            <div class="flex items-center gap-1.5 mb-1.5 flex-wrap">
              <button
                class="flex items-center gap-1 shrink-0"
                :title="specCardCollapsed(m) ? '展开需求内容' : '收起需求内容'"
                @click="toggleSpecCard(m)"
              >
                <span class="text-[11px] font-medium" :class="specSuperseded(m) ? 'text-ctp-overlay0' : 'text-ctp-blue'">{{ specSuperseded(m) ? '需求卡·历史快照' : '需求卡' }}</span>
              </button>
              <span class="font-mono text-[10px] text-ctp-overlay1">{{ m.item.payload?.requirementId }}</span>
              <span
                class="chip !px-1.5 !text-[9px] font-mono shrink-0"
                :class="specSuperseded(m) ? 'bg-ctp-surface0 text-ctp-overlay0' : 'bg-ctp-mauve/15 text-ctp-mauve'"
              >v{{ specVer(m) }}</span>
              <span
                v-if="specCard(m).title"
                class="text-xs font-medium truncate max-w-60"
                :class="specSuperseded(m) ? 'text-ctp-overlay1 line-through decoration-ctp-overlay0/40' : ''"
              >{{ specCard(m).title }}</span>
              <span
                v-if="specCard(m).priority && !specSuperseded(m)"
                class="chip !px-1.5 !text-[9px] bg-ctp-surface0 text-ctp-subtext0 shrink-0"
              >{{ specCard(m).priority }}</span>
              <span
                v-if="specSuperseded(m)"
                class="text-[9px] px-1.5 py-0.5 rounded-full bg-ctp-overlay0/15 text-ctp-overlay0 font-medium"
              >已被 v{{ specSupersededVer(m) }} 取代 · 仅参考</span>
              <span
                v-else-if="specCard(m).active"
                class="text-[9px] px-1.5 py-0.5 rounded-full bg-ctp-blue/15 text-ctp-blue font-medium"
              >执行中</span>
              <span
                v-else
                class="text-[9px] px-1.5 py-0.5 rounded-full bg-ctp-green/15 text-ctp-green font-medium"
              >已存入待执行</span>
              <span
                v-if="m.item.payload?.updated && !specSuperseded(m)"
                class="text-[10px] text-ctp-overlay0"
              >已更新 → v{{ m.item.payload?.ver }}</span>
              <span
                v-if="m.item.payload?.noDesign && !specSuperseded(m)"
                class="text-[10px] text-ctp-yellow"
              >⚠️ 缺实现方案</span>
              <CollapseChevron
                class="ml-auto"
                :collapsed="specCardCollapsed(m)"
                @toggle="toggleSpecCard(m)"
              />
            </div>
            <div
              v-show="!specCardCollapsed(m)"
              class="text-[11px] leading-relaxed max-h-72 overflow-auto [&_h2]:mt-2 [&_h2]:mb-1 [&_h2]:text-[11px] [&_h2]:font-semibold [&_p]:my-1 [&_ul]:my-1 [&_li]:ml-4"
              :class="specSuperseded(m) ? 'text-ctp-overlay0' : 'text-ctp-subtext1'"
            >
              <ChatMessageBlocks :content="specCard(m).body" />
            </div>
            <div v-if="!specSuperseded(m)" class="mt-2 flex items-center gap-2">
              <button
                class="btn btn-xs btn-primary"
                :disabled="busy || specCard(m).active"
                :title="specCard(m).active
                  ? `该需求已有进行中的任务（${specCard(m).activeStatus}）——不可重复执行`
                  : '按规约启动 coding subagent（就地执行，直接写入项目目录）'"
                @click="emit('send', { text: '/执行' })"
              >{{ specCard(m).active ? '执行中' : '执行' }}</button>
              <span
                v-if="specCard(m).active"
                class="text-[10px] text-ctp-overlay0"
              >任务进行中——完成后可再次发起</span>
              <span
                v-else
                class="text-[10px] text-ctp-overlay0"
              >启动 coding subagent（就地执行）</span>
            </div>
            <div v-else class="mt-1.5 text-[10px] text-ctp-overlay0">
              历史版本快照——执行请使用最新版需求卡（上下文交接始终取台账最新规约）
            </div>
          </div>

          <!-- 任务状态卡(cv-203 裁决): 状态/进度独立专用消息——单卡原位更新,
               不与文本回执混流(启动/进度/终态共用同一张卡) -->
          <div
            v-if="m.item?.type === 'task_status'"
            class="mt-1.5 rounded-md border px-2.5 py-1.5 flex items-start gap-2"
            :class="statusStrip(m.item).cls"
          >
            <span class="text-[13px] leading-5 shrink-0">{{ statusStrip(m.item).icon }}</span>
            <div
              v-show="!mCollapsed(m)"
              class="flex-1 min-w-0 text-[11px] leading-relaxed [&_p]:my-0"
            >
              <ChatMessageBlocks :content="m.content" />
            </div>
            <CollapseChevron
              class="ml-auto"
              :collapsed="mCollapsed(m)"
              @toggle="toggleM(m)"
            />
          </div>

          <!-- 规约 JSON 落库按钮(字段签名识别, 任何含载荷的助手消息) -->
          <div
            v-if="!m.item && specPayloadOf(i)"
            class="mt-2 flex items-center gap-2"
          >
            <button
              class="btn btn-xs"
              :class="specAppliedIdx.has(i) ? 'btn-green' : 'btn-primary'"
              :disabled="specBusyIdx === i || specAppliedIdx.has(i)"
              title="按原文确定性落库为需求(零模型转写)"
              @click="onSpecApply(i)"
            >{{ specAppliedIdx.has(i) ? '✓ ' + t('session.actions.applySpec') : (specBusyIdx === i ? '…' : t('session.actions.applySpec')) }}</button>
            <span class="text-[10px] text-ctp-overlay0">{{ t('session.actions.applySpecHint') }}</span>
          </div>

          <div
            v-if="m.assets?.length"
            class="mt-2 space-y-1.5"
          >
            <div class="flex items-center gap-1.5">
              <span class="text-[10px] uppercase tracking-wide text-ctp-mauve">{{ t('requirement.chat.assetsGroup', { n: m.assets.length }) }}</span>
              <CollapseChevron class="ml-auto" :collapsed="mCollapsed(m)" @toggle="toggleM(m)" />
            </div>
            <div
              v-show="!mCollapsed(m)"
              class="space-y-1.5"
            >
            <div
              v-for="(a, ai) in m.assets"
              :key="a.id"
              class="border border-ctp-mauve/25 bg-ctp-mauve/5 rounded-lg overflow-hidden"
            >
              <div class="flex items-center gap-1.5 px-2 py-1.5">
                <component
                  :is="assetKindIcon(a.kind)"
                  class="w-3.5 h-3.5 text-ctp-mauve shrink-0"
                />
                <span class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve shrink-0">
                  {{ assetKindLabel(a.kind) }}
                </span>
                <span
                  class="text-[11px] font-medium text-ctp-text truncate cursor-pointer hover:text-ctp-blue"
                  :title="t('requirement.chat.assetOpen')"
                  @click="openAssetRef(a.id)"
                >{{ a.name }}</span>
                <span
                  v-if="a.needsUpdate || a.status === 'stale'"
                  class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                >{{ t('requirement.chat.assetNeedsUpdate') }}</span>
                <span
                  v-else-if="a.status === 'deleted'"
                  class="chip !text-[9px] bg-ctp-red/15 text-ctp-red shrink-0"
                >{{ t('requirement.chat.assetDeleted') }}</span>
                <span
                  v-else-if="a.change === 'modified'"
                  class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                >{{ t('requirement.chat.assetModified') }}</span>
                <span
                  v-else-if="a.change === 'added'"
                  class="chip !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0"
                >{{ t('requirement.chat.assetAdded') }}</span>
                <span class="flex-1" />
                <span class="text-[9px] text-ctp-overlay0 whitespace-nowrap">{{ assetSummary(a) }}</span>
                <button
                  v-if="!assetUsable(a)"
                  class="text-ctp-yellow hover:text-ctp-peach transition-colors p-0.5"
                  :title="t('requirement.chat.assetRefresh')"
                  :disabled="busy"
                  @click="onRefreshAsset(a)"
                >
                  <ArrowPathIcon class="w-3 h-3" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve transition-colors p-0.5"
                  :title="t('requirement.chat.assetCopy')"
                  @click="copyAsset(a)"
                >
                  <ClipboardDocumentIcon class="w-3 h-3" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve transition-colors p-0.5"
                  :title="t('requirement.chat.assetExpand')"
                  @click="toggleAsset(i, ai)"
                >
                  <ChevronDownIcon
                    v-if="expandedAssets[assetKey(i, ai)]"
                    class="w-3.5 h-3.5"
                  />
                  <ChevronRightIcon
                    v-else
                    class="w-3.5 h-3.5"
                  />
                </button>
              </div>
              <p class="px-2 pb-1.5 text-[10px] text-ctp-subtext0 line-clamp-2 whitespace-pre-wrap">
                {{ a.desc }}
              </p>
              <div
                v-if="expandedAssets[assetKey(i, ai)]"
                class="border-t border-ctp-mauve/15 px-2 py-1.5 space-y-1.5"
              >
                <div
                  v-if="a.detail?.fields?.length"
                  class="text-[10px] text-ctp-subtext0"
                >
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('requirement.chat.assetFields') }}</div>
                  <div
                    v-for="f in a.detail.fields"
                    :key="f.name"
                    class="pl-2"
                  ><span class="font-mono text-ctp-text">{{ f.name }}</span><span class="text-ctp-overlay0">: {{ f.type ?? '—' }}</span> {{ f.semantic ? `— ${f.semantic}` : '' }}</div>
                </div>
                <div
                  v-if="a.detail?.steps?.length"
                  class="text-[10px] text-ctp-subtext0"
                >
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('requirement.chat.assetSteps') }}</div>
                  <div
                    v-for="(s, si) in a.detail.steps"
                    :key="si"
                    class="pl-2"
                  >{{ s.order ?? si + 1 }}. {{ s.semantic }} <span v-if="s.astRefs?.length" class="text-ctp-overlay0">(@{{ s.astRefs[0].file }}:L{{ s.astRefs[0].startLine }})</span></div>
                </div>
                <div
                  v-if="a.detail?.branches?.length"
                  class="text-[10px] text-ctp-subtext0"
                >
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('requirement.chat.assetBranches') }}</div>
                  <div
                    v-for="(b, bi) in a.detail.branches"
                    :key="bi"
                    class="pl-2"
                  ><span class="font-mono text-ctp-text">if {{ b.condition ?? '?' }}</span> → {{ b.then ?? '—' }}<span v-if="b.else"> / else {{ b.else }}</span></div>
                </div>
                <div
                  v-if="a.astRefs?.length"
                  class="text-[10px] text-ctp-overlay0"
                >
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('requirement.chat.astAnchor') }}</div>
                  <div
                    v-for="(r, ri) in a.astRefs.slice(0, 8)"
                    :key="ri"
                    class="pl-2 font-mono"
                  >{{ r.file }}:L{{ r.startLine }}-L{{ r.endLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span></div>
                </div>
              </div>
            </div>
            </div>
          </div>

          <!-- 契约条目固化卡（🧾 期望固化：逐条确认/修改/删；判定动作在验收区块） -->
          <div
            v-if="m.contracts?.length"
            class="mt-2 space-y-1.5"
          >
            <div class="flex items-center gap-1.5">
              <span class="text-[10px] uppercase tracking-wide text-ctp-teal">{{ t('requirement.chat.contractsGroup', { n: m.contracts.length }) }}</span>
              <CollapseChevron class="ml-auto" :collapsed="mCollapsed(m, false, 'contracts')" @toggle="toggleM(m, false, 'contracts')" />
            </div>
            <div
              v-show="!mCollapsed(m, false, 'contracts')"
              class="space-y-1.5"
            >
            <div
              v-for="c in m.contracts"
              :key="c.id"
              class="border border-ctp-teal/25 bg-ctp-teal/5 rounded-lg overflow-hidden"
            >
              <div class="flex items-center gap-1.5 px-2 py-1.5">
                <span class="chip !text-[9px] shrink-0" :class="kindChipClass(c.kind)">
                  {{ t(`assetMgmt.kind.${c.kind}`) }} · {{ c.level }}
                </span>
                <span class="font-mono text-[10px] text-ctp-subtext0 shrink-0">{{ c.id }}</span>
                <span
                  v-if="c.intentOnly"
                  class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                >{{ t('requirement.chat.contractIntentOnly') }}</span>
                <span
                  v-if="c.staleByFramework"
                  class="chip !text-[9px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                >{{ t('requirement.chat.contractStale') }}</span>
                <span class="flex-1" />
                <span class="chip !text-[9px] shrink-0" :class="contractStatusCls(c.status)">
                  {{ contractStatusLabel(c.status) }}
                </span>
              </div>
              <div class="px-2 pb-1.5 space-y-1 text-[11px]">
                <div class="text-ctp-text">
                  <span class="text-[9px] uppercase tracking-wide text-ctp-overlay0">{{ t('requirement.chat.contractTarget') }}</span>
                  <span class="font-mono">{{ contractTargetText(c) }}</span>
                </div>
                <div v-if="contractBehaviorText(c)" class="text-ctp-subtext0">{{ contractBehaviorText(c) }}</div>
                <div
                  v-if="c.origin?.quote"
                  class="text-[10px] text-ctp-overlay0 border-l-2 border-ctp-teal/30 pl-1.5 italic"
                >「{{ c.origin.quote }}」
                </div>
                <div
                  v-for="(z, zi) in c.zAxis ?? []"
                  :key="zi"
                  class="text-[10px] text-ctp-subtext0"
                >Z[{{ z.category }}] {{ z.text }}
                </div>
                <div
                  v-if="c.acceptance?.criteria"
                  class="text-[10px] text-ctp-subtext0"
                >
                  <span class="text-ctp-overlay0">{{ t('requirement.chat.contractAcceptance') }}</span> {{ c.acceptance.criteria }}
                </div>
                <!-- 修改模式（仅 draft） -->
                <div v-if="contractEditOpen[c.id]" class="pt-1">
                  <textarea
                    v-model="contractEditText[c.id]"
                    rows="8"
                    class="input !text-[10px] font-mono"
                    :placeholder="t('requirement.chat.contractEditHint')"
                  />
                  <div class="flex gap-1.5 mt-1">
                    <button class="btn btn-xs btn-green" @click="saveContractEdit(c)">{{ t('common.save') }}</button>
                    <button class="btn btn-xs btn-ghost" @click="contractEditOpen[c.id] = false">{{ t('common.cancel') }}</button>
                  </div>
                </div>
                 <!-- 操作（仅 draft：确认/修改/删——判定统一在验收区块） -->
                 <div v-else-if="c.status === 'draft' && !busy" class="flex gap-1.5 pt-0.5">
                   <button class="btn btn-xs btn-green" @click="onContractConfirm(c)">
                     <CheckIcon class="w-3 h-3" />{{ t('requirement.chat.contractConfirm') }}
                   </button>
                   <button class="btn btn-xs btn-ghost" @click="openContractEdit(c)">{{ t('requirement.chat.contractEdit') }}</button>
                   <button class="btn btn-xs btn-ghost text-ctp-red" @click="onContractDelete(c)">
                     <TrashIcon class="w-3 h-3" />{{ t('requirement.chat.contractDelete') }}
                   </button>
                 </div>
               </div>
             </div>
            </div>
          </div>

          <!-- 命名规约归纳提议卡（agent 检测命名模式 → pending 提案；确认固化/忽略） -->
          <div
            v-if="m.conventions?.length"
            class="mt-2 space-y-1.5"
          >
            <div
              v-for="cv in m.conventions"
              :key="cv.id"
              class="border border-ctp-mauve/25 bg-ctp-mauve/5 rounded-lg overflow-hidden"
            >
              <div class="flex items-center gap-1.5 px-2 py-1.5">
                <BookOpenIcon class="w-3.5 h-3.5 text-ctp-mauve shrink-0" />
                <span class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve shrink-0">
                  {{ t('naming.tabConventions') }}
                </span>
                <span class="font-mono text-[10px] text-ctp-subtext0 shrink-0">{{ cv.id }}</span>
                <span class="flex-1" />
                <span class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0">
                  {{ t('naming.status.pending') }}
                </span>
                <CollapseChevron :collapsed="mCollapsed(m, false, cv.id)" @toggle="toggleM(m, false, cv.id)" />
              </div>
              <div
                v-show="!mCollapsed(m, false, cv.id)"
                class="px-2 pb-1.5 space-y-1 text-[11px]"
              >
                <div class="text-ctp-text">{{ cv.ruleText }}</div>
                <div class="flex flex-wrap items-center gap-1.5">
                  <span
                    v-for="s in cv.scenarios"
                    :key="s"
                    class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1"
                  >{{ t(`naming.scenario.${s}`) }}</span>
                </div>
                <p class="text-[10px] text-ctp-overlay0">{{ t('naming.proposeHint') }}</p>
                <div v-if="cv.status === 'pending' && !busy" class="flex gap-1.5 pt-0.5">
                  <button class="btn btn-xs btn-green" @click="onConventionConfirm(cv)">
                    <CheckIcon class="w-3 h-3" />{{ t('naming.confirmRule') }}
                  </button>
                  <button class="btn btn-xs btn-ghost" @click="onConventionIgnore(cv)">{{ t('naming.ignoreRule') }}</button>
                </div>
              </div>
            </div>
          </div>

          <!-- S5 需求提案卡（req.propose 产出：需求+方案+评估 → 前往需求方案）
               cv-205 方案 A: 需求唯一宿主 = spec 消息卡——同需求存在 spec 卡时
               提案卡不渲染(含实时挂载时序窗口); 仅非 spec 流/旧数据兜底 -->
          <div
            v-if="m.proposal && m.item?.type !== 'spec' && !hasSpecCardFor(m.proposal.id)"
            class="mt-2 border border-ctp-green/30 bg-ctp-green/5 rounded-lg overflow-hidden"
          >
            <div class="flex items-center gap-1.5 px-2 py-1.5">
              <SparklesIcon class="w-3.5 h-3.5 text-ctp-green shrink-0" />
              <span class="chip !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0">
                {{ t('assetChat.proposal.title') }}
              </span>
              <span class="font-mono text-[10px] text-ctp-subtext0 shrink-0">{{ m.proposal.id }}</span>
              <span class="text-xs font-medium truncate">{{ m.proposal.title }}</span>
              <span
                class="chip !px-1.5 !text-[9px] bg-ctp-surface0 text-ctp-subtext0 shrink-0"
              >{{ m.proposal.priority }}</span>
              <span class="flex-1" />
              <span
                v-if="proposalDone(m)"
                class="chip !px-1.5 !text-[9px] bg-ctp-surface0 text-ctp-overlay0 shrink-0"
              >已完成</span>
              <template v-else-if="proposalStored(m)">
                <span
                  class="chip !px-1.5 !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0"
                >
                  <CheckIcon class="w-3 h-3" />{{ t('assetChat.extractPlan.confirmedChip') }}
                </span>
                <button
                  class="btn btn-xs btn-blue"
                  :disabled="busy"
                  title="按会话绑定执行器建实施任务卡——任务卡上确认后 coding subagent 启动"
                  @click="runProposal"
                >
                  <BoltIcon class="w-3 h-3" />运行
                </button>
              </template>
              <button
                v-else
                class="btn btn-xs btn-green"
                :disabled="confirmingProposalId === m.proposal.id"
                :title="t('assetChat.extractPlan.confirmHint')"
                @click="confirmProposal(m)"
              >
                <CheckIcon class="w-3 h-3" />{{ confirmingProposalId === m.proposal.id ? t('assetChat.extractPlan.confirming') : t('assetChat.extractPlan.confirm') }}
              </button>
              <CollapseChevron :collapsed="mCollapsed(m)" @toggle="toggleM(m)" />
            </div>
            <div
              v-show="!mCollapsed(m)"
              class="px-2 pb-2 text-[11px] text-ctp-subtext1 max-h-40 overflow-auto markdown-body"
              style="white-space: pre-wrap"
            >{{ (m.proposal.desc || '').slice(0, 600) }}{{ (m.proposal.desc || '').length > 600 ? '…' : '' }}</div>
          </div>

          <!-- A5 差异报告通知卡（验收触发后：摘要 + 前往验收；判定统一在验收区块） -->
          <div
            v-if="m.acceptance"
            class="mt-2 border border-ctp-sky/25 bg-ctp-sky/5 rounded-lg overflow-hidden"
          >
            <div class="flex items-center gap-1.5 px-2 py-1.5">
              <ClipboardDocumentCheckIcon class="w-3.5 h-3.5 text-ctp-sky shrink-0" />
              <span class="chip !text-[9px] bg-ctp-sky/15 text-ctp-sky shrink-0">
                {{ t('localAcceptance.tabTitle') }}
              </span>
              <span class="font-mono text-[10px] text-ctp-subtext0 shrink-0">{{ m.acceptance.report.id }}</span>
              <span
                v-if="m.acceptance.report.packageId"
                class="font-mono text-[10px] text-ctp-overlay0 shrink-0"
              >{{ m.acceptance.report.packageId }}</span>
              <span class="flex-1" />
              <button class="btn btn-xs btn-blue" @click="onGotoAcceptance">
                <ArrowTopRightOnSquareIcon class="w-3 h-3" />{{ t('requirement.chat.gotoAcceptance') }}
              </button>
              <CollapseChevron :collapsed="mCollapsed(m)" @toggle="toggleM(m)" />
            </div>
            <div
              v-show="!mCollapsed(m)"
              class="px-2 pb-2 space-y-1.5 text-[11px]"
            >
              <div class="flex items-center gap-3">
                <span class="text-ctp-subtext0">
                  L1/L2 {{ t('requirement.chat.passRate') }}:
                  <span class="font-medium text-ctp-text">{{ diffSummary(m.acceptance).rate }}</span>
                </span>
                <span class="text-ctp-subtext0">
                  {{ t('requirement.chat.awaitingHuman') }}:
                  <span class="font-medium" :class="diffSummary(m.acceptance).awaiting > 0 ? 'text-ctp-yellow' : 'text-ctp-green'">
                    {{ diffSummary(m.acceptance).awaiting }}
                  </span>
                </span>
              </div>
              <template v-if="diffSummary(m.acceptance).top.length">
                <div class="text-[10px] uppercase tracking-wide text-ctp-sky">{{ t('requirement.chat.topDiffs') }}</div>
                <div
                  v-for="f in diffSummary(m.acceptance).top"
                  :key="f.id"
                  class="flex items-start gap-1.5"
                >
                  <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1 shrink-0">{{ f.checkLayer }}</span>
                  <span
                    class="chip !text-[9px] shrink-0"
                    :class="f.verdict === 'fail' ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-yellow/15 text-ctp-yellow'"
                  >{{ t(`localAcceptance.${f.verdict}`) }}</span>
                  <span class="text-ctp-subtext0 break-all">{{ f.evidence?.detail || '—' }}</span>
                </div>
              </template>
              <p class="text-[10px] text-ctp-overlay0">{{ t('requirement.chat.acceptanceCardHint') }}</p>
            </div>
          </div>

          <div
            v-if="m.questions"
            class="mt-2 border border-ctp-blue/25 bg-ctp-blue/5 rounded-lg p-2 space-y-2"
          >
            <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-ctp-blue">
              <QuestionMarkCircleIcon class="w-3 h-3" />{{ t('requirement.chat.questions') }}
              <CollapseChevron class="ml-auto" :collapsed="mCollapsed(m)" @toggle="toggleM(m)" />
            </div>
            <div
              v-show="!mCollapsed(m)"
              class="space-y-2"
            >
              <div
                v-for="(q, qi) in m.questions"
                :key="q.key"
                class="space-y-1"
              >
                <label class="text-[11px] font-medium text-ctp-text">{{ qi + 1 }}. {{ q.label }}</label>
                <input
                  v-if="q.type === 'text'"
                  v-model="answers[q.key]"
                  class="input !py-1 !text-xs"
                  :placeholder="q.hint"
                >
                <div
                  v-else-if="q.type === 'select' && q.options?.length"
                  class="flex flex-wrap gap-1"
                >
                  <button
                    v-for="o in q.options"
                    :key="o"
                    class="btn btn-xs"
                    :class="answers[q.key] === o ? 'btn-blue' : 'btn-ghost'"
                    @click="answers[q.key] = o"
                  >
                    {{ o }}
                  </button>
                </div>
                <p
                  v-if="q.hint && q.type !== 'text'"
                  class="text-[10px] text-ctp-overlay0"
                >
                  {{ q.hint }}
                </p>
              </div>
            </div>
            <button
              class="btn btn-sm btn-blue !py-1"
              :disabled="busy"
              @click="submitAnswers"
            >
              <CheckIcon class="w-3 h-3" />{{ t('requirement.chat.submitAnswers') }}
            </button>
          </div>

          <div
            v-if="m.formDraft"
            class="mt-2 border border-ctp-green/30 bg-ctp-green/5 rounded-lg p-2 space-y-1.5"
          >
            <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-ctp-green">
              <ClipboardDocumentCheckIcon class="w-3 h-3" />{{ t('requirement.chat.draftTitle') }}
              <CollapseChevron class="ml-auto" :collapsed="mCollapsed(m)" @toggle="toggleM(m)" />
            </div>
            <div v-show="!mCollapsed(m)" class="space-y-1.5">
            <p class="text-[11px] text-ctp-text font-medium">
              {{ m.formDraft.title }}
            </p>
            <div class="flex flex-wrap gap-1">
              <span class="chip bg-ctp-surface0 text-ctp-subtext1 text-[10px]">{{ t('requirement.assetScope') }}: {{ m.formDraft.assetScope.length }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1 text-[10px]">{{ t('requirement.basicMd') }}: {{ m.formDraft.basicMd.trim() ? '✓' : '—' }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1 text-[10px]">{{ t('requirement.estMin') }}: {{ m.formDraft.estMin }}m</span>
            </div>
            <p
              v-if="m.formDraft.assessmentSummary"
              class="text-[10px] text-ctp-subtext1 line-clamp-2"
            >
              {{ m.formDraft.assessmentSummary }}
            </p>
            <p class="text-[10px] text-ctp-overlay0 line-clamp-2">
              {{ m.formDraft.implementationPath }}
            </p>
            <button
              class="btn btn-sm btn-green !py-1"
              :disabled="busy"
              @click="emit('confirm-draft')"
            >
              <CheckIcon class="w-3 h-3" />{{ t('requirement.chat.confirmDraft') }}
            </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 语境摘要草稿卡: 可编辑 → 发送给执行器 / 重新生成 / 取消; 可勾选以后自动通过 -->
      <div
        v-if="digestDraft !== null"
        class="rounded-lg border border-ctp-teal/30 bg-ctp-teal/5 px-3 py-2.5"
      >
        <div class="flex items-center gap-1.5 text-[11px] font-medium text-ctp-teal">
          <ClipboardDocumentIcon class="w-3.5 h-3.5" />
          <span>转达摘要（可编辑）— 将发给执行器「{{ digestTargetTitle }}」</span>
        </div>
        <textarea
          v-model="digestDraft"
          rows="5"
          class="input mt-2 text-xs"
        />
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <button
            class="btn btn-xs btn-primary"
            :disabled="busy || !digestDraft.trim()"
            title="把摘要随转达发给执行器"
            @click="confirmDigest"
          >发送给执行器</button>
          <button
            class="btn btn-xs btn-ghost"
            :disabled="digestBusy"
            @click="generateDigest"
          >{{ digestBusy ? '生成中…' : '重新生成' }}</button>
          <button
            class="btn btn-xs btn-ghost"
            @click="exitDigest"
          >取消</button>
          <span class="flex-1" />
          <label
            class="flex cursor-pointer items-center gap-1 text-[10px] text-ctp-overlay0"
            title="勾选后: 生成摘要不再人工审核, 直接发给执行器"
          >
            <input
              type="checkbox"
              :checked="digestAutoSend"
              @change="onAutoSendToggle"
            >以后自动通过
          </label>
        </div>
      </div>

      <div
        v-if="busy"
        class="flex items-center gap-2 text-xs text-ctp-blue animate-pulse"
      >
        <ArrowPathIcon class="w-3.5 h-3.5 animate-spin" />{{ props.busyLabel || t('requirement.chat.thinking') }}
        <button
          v-if="toolTrail && toolTrail.length"
          class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[10px] shrink-0 animate-none cursor-pointer"
          :title="t('requirement.chat.trail')"
          @click="trailOpen = true"
        >
          <WrenchScrewdriverIcon class="w-3 h-3 inline -mt-0.5" />
          {{ t('requirement.chat.trail') }} ×{{ toolTrail.length }}
        </button>
      </div>
    </div>

    <transition
      enter-active-class="transition-opacity duration-200"
      leave-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="toastVisible"
        class="absolute left-1/2 -translate-x-1/2 bottom-20 z-30 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-ctp-base border border-ctp-green/40 text-xs text-ctp-green shadow-lg"
      >
        <CheckIcon class="w-3.5 h-3.5" />{{ toastText }}
      </div>
    </transition>

    <div class="flex items-center gap-1 border-t border-ctp-surface0 px-2.5 py-1.5 shrink-0">
      <!-- 快捷挡直切(闪电): 选中=蓝色填充 / 未选中=置灰半透明(悬停恢复); 空白对话禁用(title 说明原因) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="quickOn ? 'btn-blue' : 'btn-ghost opacity-50 hover:opacity-100'"
        :disabled="quickLocked"
        :title="quickTitle"
        @click="toggleQuickMode"
      >
        <BoltIcon class="w-3.5 h-3.5" />
      </button>
      <!-- 需求澄清挡位(cv-190): 自动(缺口驱动, 置灰) / 强制(先问后落卡, 高亮) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="clarifyForced ? 'btn-teal' : 'btn-ghost opacity-50 hover:opacity-100'"
        :disabled="quickLocked"
        :title="clarifyTitle"
        @click="toggleClarifyMode"
      >
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" /></svg>
      </button>
      <!-- worktree 隔离挡位(cv-202/cv-203): 关(缺省, 置灰) / 开(高亮)——
           开关状态走悬停 tooltip(直显文字占工具栏空间, 用户裁决) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="isolatedOn ? 'btn-blue' : 'btn-ghost opacity-50 hover:opacity-100'"
        :disabled="quickLocked"
        :title="isolatedTitle"
        @click="toggleIsolated"
      >
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M16 3h5v5" /><path d="M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" /><path d="M21 3l-9 9" /></svg>
      </button>
      <!-- 语境摘要(仅转达语境): 选史 → 生成摘要 → 随转达下发执行器 -->
      <button
        v-if="canDigest"
        class="btn btn-xs !px-1.5"
        :class="digestMode ? 'btn-teal' : 'btn-ghost'"
        title="语境摘要(/选摘) — 选取会话历史生成摘要, 随转达发给执行器"
        @click="toggleDigestMode"
      >
        <ClipboardDocumentIcon class="w-3.5 h-3.5" />
      </button>
      <!-- 工具条: 纯 icon(悬停 title 提示); 动作均可用 /命令 触达(见命令浮层) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="props.diagramSkill ? 'btn-blue' : 'btn-ghost'"
        :disabled="busy"
        :title="`${t('requirement.chat.diagramSkill')} — /绘图`"
        @click="emit('toggle-diagram-skill', !props.diagramSkill)"
      >
        <svg
          class="w-3.5 h-3.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        ><path d="M3 3h18v18H3z" /><path d="M3 9h18" /><path d="M3 15h18" /><path d="M9 3v18" /></svg>
      </button>
      <slot name="toolbar-extra" />
      <!-- v2 语境路由(发起者感知自动变 + 菜单单次翻转): 靠右加宽, 同钮显示当前执行器完整名称 -->
      <div class="relative shrink-0 ml-auto">
        <button
          class="btn btn-xs gap-1 !px-2 max-w-[200px]"
          :class="routeBtnClass"
          :title="routeDetail(effectiveRoute) + '（点击切换）；执行器选择见菜单底部'"
          @click="routeMenuOpen = !routeMenuOpen"
        >
          <AtSymbolIcon class="w-3.5 h-3.5 shrink-0" />
          <span
            class="truncate text-[10px] font-mono"
            :class="props.boundExecutorId ? 'text-ctp-teal' : 'opacity-70'"
          >{{ executorLabel }}</span>
        </button>
        <div
          v-if="routeMenuOpen"
          class="absolute bottom-full right-0 z-50 mb-1 w-72 flex-col gap-1 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1.5 shadow-lg flex"
          @mouseleave="routeMenuOpen = false"
        >
          <div class="px-1.5 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">回复对象（单次, 发送后复位）</div>
          <button
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
            :class="effectiveRoute.kind === 'architect' && !routeOverride ? 'bg-ctp-blue/10' : ''"
            @click="pickRoute({ kind: 'architect' })"
          >
            <span class="font-mono text-ctp-sky">@architect</span>
            <span class="ml-1.5 text-ctp-subtext0">外循环(分析/设计/编排)</span>
          </button>
          <button
            v-if="activeTask"
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
            :class="effectiveRoute.kind === 'task' && effectiveRoute.taskId === activeTask.id && !routeOverride ? 'bg-ctp-blue/10' : ''"
            @click="pickRoute({ kind: 'task', taskId: activeTask.id })"
          >
            <span class="font-mono text-ctp-sky truncate">→ {{ taskTitleOf(activeTask.id) || '活跃任务' }}</span>
            <span class="ml-1.5 text-ctp-subtext0">转达（{{ activeTask.status === 'waiting_input' ? '等待回复' : '排队' }}）</span>
          </button>
          <!-- 会话执行器: 绑定后新任务卡默认使用(与 /执行 直通、模型建卡同链) -->
          <div class="mx-1 my-0.5 border-t border-ctp-surface0" />
          <div class="px-1.5 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">会话执行器（新任务卡默认）</div>
          <button
            v-for="e in (props.executors || [])"
            :key="e.id"
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0 flex items-center gap-1.5"
            :class="e.id === props.boundExecutorId ? 'bg-ctp-teal/10' : ''"
            @click="pickExecutor(e.id)"
          >
            <CpuChipIcon class="w-3 h-3 shrink-0 text-ctp-teal" />
            <span class="font-mono truncate">{{ executorFull(e) }}</span>
            <span class="flex-1" />
            <span
              v-if="e.id === props.boundExecutorId"
              class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal shrink-0"
            >已绑定</span>
            <span
              v-else-if="e.default"
              class="chip !text-[9px] bg-ctp-surface0/60 text-ctp-overlay0 shrink-0"
            >默认</span>
          </button>
          <div
            v-if="!(props.executors || []).length"
            class="px-2 py-1.5 text-[10px] text-ctp-overlay0"
          >注册表无启用执行器</div>
          <div class="px-1.5 pt-0.5 text-[10px] text-ctp-overlay0">
            ℹ 临时单次换引擎：输入框以 <span class="font-mono">@cline</span> 开头发送
          </div>
        </div>
      </div>
    </div>

    <!-- 知识资产面板(K2): 任务回执/里程碑沉淀清单, 检索+删除(会话中心场景移至左栏, showAssetsPanel=false 隐藏) -->
    <AssetsPanel
      v-if="props.showAssetsPanel !== false && props.convId"
      :conv-id="props.convId"
      :read-only="props.readOnly"
    />

    <div class="relative flex items-end gap-2 border-t border-ctp-surface0 p-2.5 shrink-0">
      <!-- `/` 命令提示浮层(会话指令发后端 + 会话操作本地执行) -->
      <div
        v-if="cmdMenuOpen"
        class="absolute bottom-full left-2 z-50 mb-1 w-72 flex-col gap-0.5 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1 shadow-lg flex"
      >
        <span class="px-2 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">会话操作(本地)</span>
        <button
          v-for="c in cmdFilter.filter((x) => LOCAL_CMD_LIST.includes(x))"
          :key="c.name"
          class="rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
          @click="pickCmd(c.name)"
        >
          <span class="font-mono text-ctp-mauve">/{{ c.name }}</span>
          <span class="ml-1.5 text-ctp-subtext0">{{ c.desc }}</span>
        </button>
      </div>
      <textarea
        ref="inputRef"
        v-model="input"
        rows="2"
        class="input !py-2.5 text-xs resize-y min-h-0"
        :disabled="props.readOnly"
        :placeholder="inputPlaceholder"
        @input="autoResize"
        @keydown="onInputKeydown"
      />
      <div class="flex flex-col items-end gap-1 shrink-0">
        <!-- 空态也显示(裁决): 发送按钮正上方, 新会话 used=0 即可见 -->
        <CtxUsageChip v-if="ctxUsage" :usage="ctxUsage" />
        <button
          v-if="busy"
          class="btn btn-red !py-2.5 whitespace-nowrap"
          :title="t('requirement.chat.stop')"
          @click="emit('stop')"
        >
          <StopIcon class="w-4 h-4" />{{ t('requirement.chat.stop') }}
        </button>
        <button
          v-else
          class="btn btn-primary !py-2.5 whitespace-nowrap"
          :disabled="!input.trim() || props.readOnly"
          :title="t('coding.sendHint')"
          @click="send"
        >
          <PaperAirplaneIcon class="w-4 h-4" />{{ t('coding.send') }}
        </button>
      </div>
    </div>

    <!-- 删除消息确认弹窗(DOM) -->
    <div
      v-if="deletePending !== null"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
      @click.self="cancelDeleteTurn"
    >
      <div class="panel w-full max-w-xs">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <TrashIcon class="w-4 h-4 text-ctp-red" />{{ t('requirement.chat.deleteTurn') }}
          </span>
        </div>
        <div class="p-4 text-xs text-ctp-subtext1">
          {{ t('requirement.chat.deleteTurnConfirm') }}
        </div>
        <div class="flex items-center justify-end gap-2 px-4 pb-4">
          <button
            class="btn btn-sm btn-ghost"
            @click="cancelDeleteTurn"
          >
            {{ t('requirement.chat.deleteTurnCancel') }}
          </button>
          <button
            class="btn btn-sm btn-red"
            @click="confirmDeleteTurn"
          >
            {{ t('requirement.chat.deleteTurnOk') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 工具轨迹浮层：防信息过载，默认收起；Teleport+fixed 避免被对话区 overflow 裁剪 -->
    <Teleport to="body">
      <div
        v-if="trailOpen"
        class="fixed inset-0 z-50 bg-black/40"
        @click="trailOpen = false"
      >
        <div
          class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(520px,92vw)] max-h-[70vh] flex flex-col rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden"
          @click.stop
        >
          <div class="flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0 shrink-0">
            <WrenchScrewdriverIcon class="w-4 h-4 text-ctp-blue" />
            <span class="text-sm font-semibold text-ctp-text">{{ t('requirement.chat.trail') }}</span>
            <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[10px]">{{ toolTrail?.length ?? 0 }}</span>
            <span class="flex-1" />
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
              @click="trailOpen = false"
            >
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div class="p-3 space-y-1 overflow-y-auto">
            <div
              v-for="(it, i) in toolTrail"
              :key="`${it.tool}-${i}`"
              class="flex items-start gap-2 px-2 py-1.5 rounded-lg bg-ctp-mantle"
            >
              <span class="shrink-0 mt-0.5">
                <CheckIcon
                  v-if="it.ok === true"
                  class="w-3.5 h-3.5 text-ctp-green"
                />
                <XMarkIcon
                  v-else-if="it.ok === false"
                  class="w-3.5 h-3.5 text-ctp-red"
                />
                <ArrowPathIcon
                  v-else
                  class="w-3.5 h-3.5 text-ctp-yellow animate-spin"
                />
              </span>
              <span class="min-w-0">
                <span class="font-mono text-[11px] text-ctp-text">{{ it.tool }}</span>
                <span
                  v-if="it.summary"
                  class="block text-[10px] text-ctp-subtext0 truncate"
                  :title="it.summary"
                >{{ it.summary }}</span>
              </span>
            </div>
            <div
              v-if="!toolTrail || !toolTrail.length"
              class="text-[11px] text-ctp-overlay0 px-2 py-3"
            >
              {{ t('requirement.chat.trailEmpty') }}
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
