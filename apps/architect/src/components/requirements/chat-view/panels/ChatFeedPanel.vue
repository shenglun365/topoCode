<script setup lang="ts">

/** MS6-W3-S2 自 AnalysisChat 模板整块迁出(逐行未动)；状态经 WS_KEY 注入。 */

import { computed, nextTick, onMounted, onUnmounted, provide, reactive, ref, watch } from 'vue'
import { DocumentTextIcon, ArrowPathIcon, PaperAirplaneIcon, ChatBubbleLeftRightIcon, PencilSquareIcon, SparklesIcon, BookOpenIcon, CheckIcon, QuestionMarkCircleIcon, ClipboardDocumentCheckIcon, ClipboardDocumentIcon, TrashIcon, CubeTransparentIcon, BoltIcon, AdjustmentsHorizontalIcon, ChevronDownIcon, ChevronRightIcon, StopIcon, ArrowTopRightOnSquareIcon, WrenchScrewdriverIcon, XMarkIcon, ExclamationCircleIcon, AtSymbolIcon, CpuChipIcon } from '@heroicons/vue/24/outline'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import TaskCard from '@/components/chat/TaskCard.vue'
import ExecutorProcessStrip from '@/components/chat/ExecutorProcessStrip.vue'
import JobCard from '@/components/chat/JobCard.vue'
import { useConversationStore } from '@/stores/conversation-store'
import ChoicesCard from '@/components/chat/ChoicesCard.vue'
import EditSpecModal from '@/components/requirements/EditSpecModal.vue'
import ReqDetailWindow from '@/components/requirements/ReqDetailWindow.vue'
import CollapseChevron from '@/components/chat/CollapseChevron.vue'
import ChevronSvg from '@/components/chat/ChevronSvg.vue'
import { useI18n } from 'vue-i18n'
import type { KbAnalysisTurn } from '@/services/kb-analysis-agent'
import { useChatWs } from '../key'

// 父层 v-bind="props" 全量下传, 本组件仅声明消费的子集——其余(insertDraft/
// analysisMode 等状态经 useChatWs 注入流动, 不走 props); 多根 fragment(尾部
// Teleport)无法自动继承 attrs, 显式关闭以消 extraneous non-props 警告(cv-278)。
defineOptions({ inheritAttrs: false })

const props = defineProps<{
  turns?: KbAnalysisTurn[]
  busy?: boolean
  busyLabel?: string
  readOnly?: boolean
  convId?: string
  toolTrail?: any[]
}>()
const { t } = useI18n()
const {
  answeredByFlow,
  answers,
  approvalDone,
  assetKey,
  assetKindIcon,
  assetKindLabel,
  assetSummary,
  assetUsable,
  choiceDrafts,
  choicesAnswered,
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
  copiedTurn,
  copyAsset,
  copyTurn,
  diffSummary,
  digestAutoSend,
  digestBusy,
  digestDraft,
  digestMode,
  digestTargetTitle,
  exitDigest,
  expandedAssets,
  feedBusyIdx,
  generateDigest,
  hasSpecCardFor,
  input,
  kindChipClass,
  mCollapsed,
  mergeBusyIdx,
  mergedDone,
  onAutoSendToggle,
  onChoicesReply,
  onContractConfirm,
  onContractDelete,
  onConventionConfirm,
  onConventionIgnore,
  onGotoAcceptance,
  onMsgCopy,
  onRefreshAsset,
  onSpecApply,
  openAssetRef,
  openContractEdit,
  proposalDone,
  proposalStored,
  reasoningOpen,
  removeTurn,
  respondApproval,
  runMergePrecheck,
  runProposal,
  saveContractEdit,
  scheduleDraftSave,
  scrollRef,
  selIds,
  send,
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
  statusStrip,
  submitAnswers,
  taskById,
  toggleAsset,
  toggleDigestMode,
  toggleM,
  toggleReasoning,
  toggleSel,
  toggleSpecCard,
  trailOpen,
} = useChatWs()
// cv-268 直通过程条: SSE progress(conversationId 键) → 会话级过程态;
// 活跃流式=完整条, turn_done 后(busy=false)折叠一行摘要, 终态 finished 帧清除
const _convStore = useConversationStore()
const proxyProc = computed(() => _convStore.proxyProgressOf(props.convId))
// cv-276 长消息折叠阅读: >600 字符 assistant 文本 → 高度上限+内部滚动+浮层放大
const LONG_MSG_CHARS = 600
function isLongMsg(m: any): boolean {
  return m?.role === 'assistant' && String(m?.content || '').length > LONG_MSG_CHARS
}
const expandedMsg = ref<{ content: string } | null>(null)
// cv-279 需求内容编辑浮窗(最新版卡头部铅笔钮触发)
const specEditing = ref<{ requirementId: string; title: string; desc: string } | null>(null)
// cv-284 需求大窗(放大钮触发; 共享组件双入口之一)
const specDetail = ref<{ requirementId: string } | null>(null)

function openSpecEdit(m: any) {
  const s = m.item?.payload?.spec || {}
  specEditing.value = {
    requirementId: String(m.item?.payload?.requirementId || ''),
    title: String(s.title || specCard(m).title || ''),
    desc: String(s.desc || ''),
  }
}
// cv-281 立即执行: 免任务计划——需求最新版直接创建单任务并立即执行
const execNowId = ref('')
async function execNow(m: any) {
  const rid = String(m.item?.payload?.requirementId || '')
  if (!rid || execNowId.value) return
  execNowId.value = String(m.id || m.item?.id || '')
  try {
    const { apiPost } = await import('@/services/api-client')
    await apiPost(`/requirements/${encodeURIComponent(rid)}/execute-now`,
      { convId: props.convId })
  } catch { /* 失败经任务卡/状态卡与回执可见 */ } finally {
    execNowId.value = ''
  }
}
// cv-282 脏区问询卡答复: 确定性消费(gate-answer 端点), 不走普通消息通道
async function onGateReply(m: any, text: string) {
  const msgId = String(m.id || m.item?.id || '')
  choicesAnswered.add(msgId)
  try {
    const { apiPost } = await import('@/services/api-client')
    await apiPost(`/tasks/${encodeURIComponent(String(m.item?.payload?.taskId || ''))}/gate-answer`,
      { choiceText: text })
  } catch { /* 回执经主流可见 */ }
}
// cv-277 最小化/展开切换(按消息 id 记态; 缺省=展开 420px 滚动)
const msgMinimized = ref<Record<string, boolean>>({})
function msgKey(m: any, i: number): string {
  return String(m?.id || `idx-${i}`)
}
function toggleMsgMin(m: any, i: number) {
  const k = msgKey(m, i)
  msgMinimized.value[k] = !msgMinimized.value[k]
}
// cv-275 持久会话状态(REST 真相源, 刷新安全): convId 变化/回合结束即查询
const proxySession = ref<{ active: boolean; executorType: string;
                           sessionRef: string; jobId?: string } | null>(null)
const proxySessionBusy = ref(false)
async function refreshProxySession() {
  if (!props.convId) { proxySession.value = null; return }
  try {
    const { apiGet } = await import('@/services/api-client')
    proxySession.value = await apiGet(`/sessions/${props.convId}/proxy-state`)
  } catch { proxySession.value = null }
}
watch([() => props.convId, () => props.busy], () => { void refreshProxySession() },
      { immediate: true })
// cv-274 渲染层探针: 数据就位但未见条 → 断点在此(与 [arch-live] 日志同风格)
watch(proxyProc, (p) => {
  if (p) console.info('[arch-live] 控制条渲染 conv=' + props.convId,
                      'tools:', p.toolCount, p.folded ? 'FOLDED' : 'LIVE')
}, { immediate: true })
const proxyStopping = ref(false)
// cv-283 JobCard 活动态覆写: REST 真相源(jobId 匹配且活跃)优先于卡内快照
function proxyJobLiveState(jobId?: string): string {
  const s = proxySession.value
  if (!s || !jobId || s.jobId !== jobId) return ''
  return s.active ? 'running' : 'idle'
}
async function onProxyStop() {
  if (!props.convId || proxyStopping.value) return
  proxyStopping.value = true
  try {
    const { apiPost } = await import('@/services/api-client')
    const r = await apiPost<{ summary?: string }>(
      `/sessions/${props.convId}/proxy-stop`, {})
    _convStore.pushLocalHint(r?.summary || '已停止')
    void refreshProxySession()
  } catch { /* 停止失败保留过程条(泵终态兜底) */ } finally {
    proxyStopping.value = false
  }
}
const emit = defineEmits<{
  'task-confirm': [id: string]
  'task-cancel': [id: string]
  'task-ignore': [id: string]
  'task-dismiss': [id: string]
  'task-executor': [p: { taskId: string; executorType: string }]
  'feed-turn': [p: { index: number; id?: string; summarize?: boolean }]
  'rollback-to': [index: number]
  send: [p: { text: string }]
  'confirm-draft': []
}>()
</script>

<template>
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
          <!-- cv-283 直通作业卡: 统一投影 type=job 且 jobCard=1 才渲染 JobCard,
               其余 proxy 文本回执走普通消息流 -->
          <JobCard
            v-if="m.item?.type === 'job' && m.item?.payload?.jobCard"
            class="mb-2"
            :payload="(m.item!.payload || {}) as any"
            :live-state="proxyJobLiveState(m.item!.payload?.jobId)"
            :stopping="proxyStopping"
            @stop="onProxyStop"
          />
          <ChoicesCard
            v-if="m.item?.type === 'choices'"
            class="mb-2"
            :payload="(m.item!.payload || {}) as any"
            :disabled="props.readOnly || props.busy"
            :used="choicesAnswered.has(String(m.id || m.item?.id || ''))
              || answeredByFlow.has(String(m.id || m.item?.id || ''))"
            :draft="choiceDrafts[String(m.id || m.item?.id || '')]"
            @draft-change="(d: any) => scheduleDraftSave(String(m.id || m.item?.id || ''), d)"
            @reply="(text: string) => m.item?.payload?.gateAsk
              ? onGateReply(m, text)
              : onChoicesReply(String(m.id || m.item?.id || ''), text)"
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
            <!-- cv-277: 长消息 最小化(头部3行)/展开(420px 滚动) 切换 + 放大弹窗 -->
            <button
              v-if="isLongMsg(m)"
              class="text-ctp-overlay0 hover:text-ctp-blue transition-colors p-0.5"
              :title="msgMinimized[msgKey(m, i)] ? '展开(420px 内滚动)' : '最小化(仅头部 3 行)'"
              @click="toggleMsgMin(m, i)"
            >
              <svg v-if="msgMinimized[msgKey(m, i)]" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" /></svg>
              <svg v-else class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M9 9V4.5M9 9H4.5M9 9 3.75 3.75M9 15v4.5M9 15H4.5M9 15 3.75 20.25M15 9V4.5M15 9h4.5M15 9l5.25-5.25M15 15v4.5M15 15h4.5M15 15l5.25 5.25" /></svg>
            </button>
            <button
              v-if="isLongMsg(m)"
              class="text-ctp-overlay0 hover:text-ctp-blue transition-colors p-0.5"
              title="放大查看全文"
              @click="expandedMsg = { content: m.content }"
            >
              <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607ZM10.5 7.5v6m3-3h-6" /></svg>
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
          <div
            v-else-if="!(m.role === 'assistant' && !m.item && specDraftIdx.has(i))
              && m.item?.type !== 'spec' && m.item?.type !== 'task_status'
              && m.item?.type !== 'choices'"
            class="relative group/msg"
          >
            <!-- cv-276/277: 长消息高度上限+内部滚动+最小化(头部3行)/展开切换+浮层放大 -->
            <div
              :class="isLongMsg(m)
                ? (msgMinimized[msgKey(m, i)]
                    ? 'line-clamp-3 overflow-hidden'
                    : 'max-h-[420px] overflow-y-auto pr-1')
                : ''"
            >
              <ChatMessageBlocks :content="m.content" />
            </div>

          </div>

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
              <!-- cv-279 编辑需求: 仅最新版可编辑(历史快照只读) -->
              <button
                v-if="!specSuperseded(m) && m.item.payload?.requirementId"
                class="text-ctp-overlay0 hover:text-ctp-blue transition-colors p-0.5 shrink-0"
                title="编辑需求内容 — 保存后生成新版(v+1)，旧版保留"
                @click="openSpecEdit(m)"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487 18.549 2.8a1.875 1.875 0 1 1 2.652 2.652L10.582 15.95a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10" /></svg>
              </button>
              <!-- cv-284 需求大窗入口(全版本浏览/关联任务/立即执行) -->
              <button
                v-if="m.item.payload?.requirementId"
                class="text-ctp-overlay0 hover:text-ctp-blue transition-colors p-0.5 shrink-0"
                title="放大查看需求 — 全文/版本切换/关联任务"
                @click="specDetail = { requirementId: String(m.item.payload.requirementId) }"
              >
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607ZM10.5 7.5v6m3-3h-6" /></svg>
              </button>
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
                  ? `该需求已有进行中的任务（${specCard(m).activeStatus}）`
                  : '按规约生成任务计划——任务卡确认后才开始执行'"
                @click="emit('send', { text: '/执行' })"
              >{{ specCard(m).active ? '任务执行中' : '任务生成' }}</button>
              <!-- cv-281 立即执行: 需求最新版单任务直发(免计划/确认门) -->
              <button
                class="btn btn-xs btn-ghost"
                :disabled="busy || specCard(m).active || execNowId === String(m.id || m.item?.id || '')"
                :title="specCard(m).active
                  ? `该需求已有进行中的任务（${specCard(m).activeStatus}）`
                  : '免任务计划——以需求最新版直接创建单任务并立即执行（规约全文自动随注入）'"
                @click="execNow(m)"
              >{{ execNowId === String(m.id || m.item?.id || '') ? '启动中…' : '立即执行' }}</button>
              <span
                v-if="specCard(m).active"
                class="text-[10px] text-ctp-overlay0"
              >任务进行中——完成后可再次发起</span>
              <span
                v-else
                class="text-[10px] text-ctp-overlay0"
              >按规约生成任务计划（任务卡确认后执行）</span>
            </div>
            <div v-else class="mt-1.5 text-[10px] text-ctp-overlay0">
              历史版本快照——任务生成请使用最新版需求卡（上下文交接始终取台账最新规约）
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

      <!-- cv-275 持久会话状态条(REST 真相源, 刷新安全): 会话存活常驻 -->
      <div v-if="proxySession?.active" class="flex items-center gap-2 rounded border border-ctp-surface1 bg-ctp-base/70 px-2 py-1">
        <span class="font-mono text-[10px]" :class="busy ? 'text-ctp-blue animate-pulse' : 'text-ctp-overlay1'">
          ⚙ 编码执行器会话
        </span>
        <span class="font-mono text-[9px] text-ctp-overlay0">{{ busy ? '执行中' : '空闲(发消息继续)' }}</span>
        <span class="flex-1" />
        <button
          class="chip !text-[9px] hover:text-ctp-red"
          :disabled="proxySessionBusy"
          :title="busy ? '暂停——中止本轮执行(会话保留)' : '结束直通会话(下条消息开启全新会话)'"
          @click="onProxyStop"
        >{{ busy ? '⏸ 暂停' : '⏹ 结束会话' }}</button>
      </div>
      <!-- cv-268/273 直通执行器会话控制条(消息区尾部; turn_done 折叠; 停止钮) -->
      <ExecutorProcessStrip
        v-if="proxyProc"
        :folded="!busy || !!proxyProc.folded"
        :process="proxyProc.process || []"
        :last-text="proxyProc.lastText || ''"
        :last-tool="proxyProc.lastTool || ''"
        :tool-count="proxyProc.toolCount || 0"
        :turn-count="proxyProc.turnCount || 0"
        :input-tokens="proxyProc.inputTokens || 0"
        :output-tokens="proxyProc.outputTokens || 0"
        :stoppable="!!proxyProc"
        @stop="onProxyStop"
      />
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

    <!-- cv-276 长消息放大浮层 -->
    <Teleport to="body">
      <div
        v-if="expandedMsg"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6"
        @click.self="expandedMsg = null"
      >
        <div class="flex w-[82vw] max-w-5xl max-h-[85vh] flex-col rounded-lg border border-ctp-surface1 bg-ctp-base shadow-2xl">
          <div class="flex shrink-0 items-center justify-between border-b border-ctp-surface1 px-3 py-2">
            <span class="text-xs font-medium text-ctp-subtext1">执行器输出全文</span>
            <button class="btn btn-xs btn-ghost" @click="expandedMsg = null">✕ 关闭</button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            <ChatMessageBlocks :content="expandedMsg.content" />
          </div>
        </div>
      </div>
    </Teleport>
    <!-- cv-279 需求内容编辑浮窗 -->
    <EditSpecModal
      v-if="specEditing"
      :requirement-id="specEditing.requirementId"
      :title="specEditing.title"
      :desc="specEditing.desc"
      :conv-id="convId"
      @close="specEditing = null"
    />
    <!-- cv-284 需求大窗 -->
    <ReqDetailWindow
      v-if="specDetail"
      :requirement-id="specDetail.requirementId"
      :conv-id="convId"
      :show-generate="true"
      @generate-tasks="emit('send', { text: '/执行' }); specDetail = null"
      @close="specDetail = null"
    />
  </template>
