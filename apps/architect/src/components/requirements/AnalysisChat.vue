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
import ChatFeedPanel from './chat-view/panels/ChatFeedPanel.vue'
import ChatBottomPanel from './chat-view/panels/ChatBottomPanel.vue'

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
  /** worktree 隔离模式(cv-202): false=融合(缺省) | true=显式要求隔离执行。 */
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

    <ChatFeedPanel
      v-bind="props"
      @task-confirm="(id: string) => emit('task-confirm', id)"
      @task-cancel="(id: string) => emit('task-cancel', id)"
      @task-ignore="(id: string) => emit('task-ignore', id)"
      @task-dismiss="(id: string) => emit('task-dismiss', id)"
      @task-executor="(p: any) => emit('task-executor', p)"
      @feed-turn="(p: any) => emit('feed-turn', p)"
      @rollback-to="(i: number) => emit('rollback-to', i)"
      @send="(p: any) => emit('send', p)"
      @confirm-draft="emit('confirm-draft')"
    />

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

    <ChatBottomPanel
      v-bind="props"
      @toggle-diagram-skill="(v: boolean) => emit('toggle-diagram-skill', v)"
      @stop="emit('stop')"
    >
      <!-- cv-277 恢复插槽转发(两面板化时断裂): 宿主工具条(大纲/引导/摘要/提炼/归档) -->
      <template #toolbar-extra>
        <slot name="toolbar-extra" />
      </template>
    </ChatBottomPanel>
  </div>
</template>
