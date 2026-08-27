<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PlusIcon, ChevronDownIcon, ChevronRightIcon, ChatBubbleLeftRightIcon,
  DocumentTextIcon, CheckCircleIcon, UsersIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import DesignPanel from '@/components/design/DesignPanel.vue'
import { LIFECYCLE_ORDER, lifecycleLabelKey } from '@/config/lifecycle'
import { chatStream, type KbAnalysisTurn } from '@/services/kb-analysis-agent'
import { requirementService } from '@/services/requirement-service'
import { useArchTaskStore } from '@/stores/task-store'
import { readModelPref } from '@topo/web-core/shell'
import { useDiagramSkill } from '@/composables/useDiagramSkill'
import type { ConversationDetail, ReqLifecycle, ReqSession, ReqSessionGroups } from '@/types'

/**
 * 需求工作台（统一界面）：
 *  - 左栏 = 需求会话列表，按 4 段生命周期(规划/待执行/执行中/已完成)分组；
 *  - 右栏 = 常驻 plan 模式 agent 对话(WS /ws/kb-analysis) + 内嵌「方案」步骤(DesignPanel)；
 *  - 新建会话 = 一条需求提案；定稿 = 规划 → 待执行(入池)。
 * 仿资产管理页模式（左会话 + 右对话），取代原「需求池/需求提案/方案生成」三界面。
 */

const { t } = useI18n()
const { diagramSkill, toggleDiagramSkill } = useDiagramSkill()
const task = useArchTaskStore()

const groups = ref<ReqSessionGroups | null>(null)
const selectedId = ref('')
const collapsed = ref<Record<string, boolean>>({})
const rightTab = ref<'chat' | 'design'>('chat')

const turns = ref<KbAnalysisTurn[]>([])
const busy = ref(false)
const chatConvId = ref('')
const finalizing = ref(false)

// P3.2: 指派 subagent 弹窗
const assignFor = ref<ReqSession | null>(null)
const assignTarget = ref<'runner' | 'mcp'>('runner')
const assignExecId = ref('')
const assignTool = ref('')
const assignParams = ref('')
const assignBusy = ref(false)
const assignError = ref('')

const allSessions = computed<ReqSession[]>(() => {
  const g = groups.value
  if (!g) return []
  return [...g.planning, ...g.ready, ...g.executing, ...g.done]
})
const selected = computed(() => allSessions.value.find((s) => s.id === selectedId.value) ?? null)

async function loadSessions() {
  try {
    groups.value = await requirementService.sessions()
  } catch (err) {
    console.error('[workbench] 加载会话失败', err)
  }
}

function isGroupOpen(lc: ReqLifecycle) {
  return !collapsed.value[lc]
}
function toggleGroup(lc: ReqLifecycle) {
  collapsed.value[lc] = !collapsed.value[lc]
}
function prioClass(p: 'P0' | 'P1' | 'P2') {
  if (p === 'P0') return 'bg-ctp-red/15 text-ctp-red'
  if (p === 'P1') return 'bg-ctp-yellow/15 text-ctp-yellow'
  return 'bg-ctp-blue/15 text-ctp-blue'
}
function lcClass(lc: ReqLifecycle) {
  if (lc === 'planning') return 'bg-ctp-blue/15 text-ctp-blue'
  if (lc === 'ready') return 'bg-ctp-peach/15 text-ctp-peach'
  if (lc === 'executing') return 'bg-ctp-green/15 text-ctp-green'
  return 'bg-ctp-surface0 text-ctp-subtext1'
}
function lcDot(lc: ReqLifecycle) {
  if (lc === 'planning') return 'bg-ctp-blue'
  if (lc === 'ready') return 'bg-ctp-peach'
  if (lc === 'executing') return 'bg-ctp-green'
  return 'bg-ctp-overlay1'
}
function lcLabel(lc: ReqLifecycle) {
  return t(`requirement.lifecycle.${lifecycleLabelKey(lc)}`)
}

async function newSession() {
  try {
    const req = await requirementService.create({
      title: t('workbench.sessions.newTitle'),
      priority: 'P1',
      kind: 'user-story',
    })
    await loadSessions()
    selectedId.value = req.id
    resetChat()
    rightTab.value = 'chat'
  } catch (err) {
    alert(err instanceof Error ? err.message : '创建失败')
  }
}

function resetChat() {
  turns.value = []
  busy.value = false
  chatConvId.value = ''
}

async function selectSession(s: ReqSession) {
  if (s.id === selectedId.value) return
  selectedId.value = s.id
  rightTab.value = 'chat'
  resetChat()
  try {
    const conv = await requirementService.conversationByReq(s.id)
    if (conv) applyConversation(conv)
  } catch {
    // 无历史会话 → 空对话
  }
}

function applyConversation(conv: ConversationDetail) {
  const msgs = (conv.messages ?? []).filter((m) => m.content?.trim())
  if (!msgs.length) return
  turns.value = msgs.map((m) => ({ role: m.role, content: m.content, id: m.id }))
  chatConvId.value = conv.id
}

/** plan 模式对话：经 WS 流式回复，沿用 conversationId 续聊。 */
async function sendViaChat(text: string) {
  if (!selected.value || busy.value) return
  const req = selected.value
  turns.value.push({ role: 'user', content: text })
  const idx = turns.value.push({ role: 'assistant', content: '' }) - 1
  busy.value = true
  try {
    const msgs = turns.value.slice(0, -1).map((m) => ({ role: m.role, content: m.content }))
    await chatStream(msgs, {
      conversationId: chatConvId.value || undefined,
      kind: 'requirement',
      reqId: req.id,
      title: req.title || t('workbench.sessions.defaultTitle'),
      modelId: readModelPref('architect') || undefined,
      diagramSkill: diagramSkill.value,
    }, (ev) => {
      if (ev.conversationId) {
        chatConvId.value = ev.conversationId
        req.conversationId = ev.conversationId
      }
      if (ev.type === 'chat_start') {
        if (ev.userMessageId && idx >= 1) turns.value[idx - 1].id = ev.userMessageId
      } else if (ev.type === 'chunk') {
        turns.value[idx].content += ev.delta ?? ''
      } else if (ev.type === 'reasoning') {
        turns.value[idx].reasoning = (turns.value[idx].reasoning ?? '') + (ev.delta ?? '')
      } else if (ev.type === 'done') {
        turns.value[idx].content = ev.content ?? turns.value[idx].content
        if (ev.messageId) turns.value[idx].id = ev.messageId
        void loadSessions()
      } else if (ev.type === 'chat_fallback') {
        turns.value[idx].content = t('requirement.chat.fallback')
      } else if (ev.type === 'error') {
        turns.value[idx].content = ev.message || t('requirement.chat.fallback')
      }
    })
  } catch (err) {
    turns.value[idx].content = (err instanceof Error ? err.message : '') || t('requirement.chat.fallback')
  } finally {
    busy.value = false
  }
}

function onSend(text: string) {
  void sendViaChat(text)
}
function onAnswers(answers: Record<string, string>) {
  const text = Object.entries(answers).map(([k, v]) => `${k}: ${v}`).join('\n')
  void sendViaChat(text)
}
async function onDeleteTurn(index: number) {
  const turn = turns.value[index]
  if (!turn) return
  const msgId = turn.id
  turns.value.splice(index, 1)
  if (msgId && chatConvId.value) {
    requirementService.deleteMessage(chatConvId.value, msgId).catch(() => {
      // 删除失败不阻塞本地操作
    })
  }
}

/** 定稿：plan 形成结论 → 规划 转 待执行(入池，status=analyzed)。 */
async function finalize() {
  if (!selected.value || finalizing.value) return
  const req = selected.value
  finalizing.value = true
  try {
    await requirementService.update(req.id, { status: 'analyzed', location: 'pool' })
    await loadSessions()
  } catch (err) {
    alert(err instanceof Error ? err.message : '定稿失败')
  } finally {
    finalizing.value = false
  }
}

/** P3.2: 指派 subagent(待执行 → 执行中，经 broker handoff)。 */
function openAssign(s: ReqSession) {
  assignFor.value = s
  assignTarget.value = 'runner'
  assignExecId.value = s.execId || ''
  assignTool.value = ''
  assignParams.value = ''
  assignError.value = ''
  void task.load()
}
function closeAssign() {
  assignFor.value = null
}
async function confirmAssign() {
  const s = assignFor.value
  if (!s) return
  if (assignTarget.value === 'runner' && !assignExecId.value) {
    assignError.value = t('workbench.assign.execTaskEmpty')
    return
  }
  if (assignTarget.value === 'mcp' && !assignTool.value.trim()) {
    assignError.value = t('workbench.assign.tool')
    return
  }
  let params: Record<string, unknown> | undefined
  if (assignTarget.value === 'mcp' && assignParams.value.trim()) {
    try {
      params = JSON.parse(assignParams.value)
    } catch {
      assignError.value = 'JSON'
      return
    }
  }
  assignBusy.value = true
  assignError.value = ''
  try {
    await requirementService.assign(s.id, {
      target: assignTarget.value,
      execId: assignTarget.value === 'runner' ? assignExecId.value : undefined,
      tool: assignTarget.value === 'mcp' ? assignTool.value.trim() : undefined,
      params,
    })
    closeAssign()
    await loadSessions()
    selectedId.value = s.id
  } catch (err) {
    assignError.value = err instanceof Error ? err.message : t('workbench.assign.error')
  } finally {
    assignBusy.value = false
  }
}

onMounted(() => {
  void loadSessions()
  void task.load()
})
</script>

<template>
  <div class="flex h-full min-h-0">
    <!-- 左栏：4 段生命周期会话列表 -->
    <aside class="flex w-72 shrink-0 flex-col border-r border-ctp-surface0 bg-ctp-mantle">
      <div class="flex items-center justify-between border-b border-ctp-surface0 px-3 py-2.5">
        <span class="text-xs font-semibold text-ctp-subtext1">{{ t('workbench.sessions.title') }}</span>
        <button class="btn btn-xs btn-blue" @click="newSession">
          <PlusIcon class="h-3.5 w-3.5" />{{ t('workbench.sessions.new') }}
        </button>
      </div>
      <div class="min-h-0 flex-1 overflow-auto py-1">
        <template v-for="lc in LIFECYCLE_ORDER" :key="lc">
          <button
            class="flex w-full items-center justify-between px-3 py-1.5 text-[10px] uppercase tracking-wider text-ctp-overlay1 transition-colors hover:text-ctp-text"
            @click="toggleGroup(lc)"
          >
            <span class="flex items-center gap-1.5">
              <span class="h-1.5 w-1.5 rounded-full" :class="lcDot(lc)" />
              {{ lcLabel(lc) }}
            </span>
            <span class="flex items-center gap-1">
              <span class="chip bg-ctp-surface0 !text-[9px] text-ctp-subtext0">{{ (groups?.[lc] ?? []).length }}</span>
              <component :is="isGroupOpen(lc) ? ChevronDownIcon : ChevronRightIcon" class="h-3 w-3" />
            </span>
          </button>
          <div v-if="isGroupOpen(lc)">
            <div
              v-for="s in groups?.[lc] ?? []"
              :key="s.id"
              class="flex items-stretch"
            >
              <button
                class="block min-w-0 flex-1 px-3 py-1.5 text-left transition-colors"
                :class="s.id === selectedId ? 'bg-ctp-surface0/70' : 'hover:bg-ctp-surface0/40'"
                @click="selectSession(s)"
              >
                <div class="truncate text-xs text-ctp-text">{{ s.title || s.id }}</div>
                <div class="mt-0.5 flex items-center gap-1.5">
                  <span class="chip !text-[9px]" :class="prioClass(s.priority)">{{ s.priority }}</span>
                  <span class="font-mono text-[9px] text-ctp-overlay0">{{ s.id }}</span>
                  <ChatBubbleLeftRightIcon v-if="s.conversationId" class="h-3 w-3 text-ctp-overlay1" />
                  <UsersIcon v-if="s.assignedTo" class="h-3 w-3 text-ctp-green" />
                </div>
              </button>
              <button
                v-if="lc === 'ready'"
                class="shrink-0 px-1.5 text-ctp-overlay1 transition-colors hover:text-ctp-blue"
                :title="t('workbench.assign.title')"
                @click="openAssign(s)"
              >
                <UsersIcon class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </template>
        <div v-if="allSessions.length === 0" class="px-3 py-8 text-center">
          <ChatBubbleLeftRightIcon class="mx-auto mb-2 h-6 w-6 text-ctp-overlay0" />
          <p class="text-[11px] text-ctp-overlay0">{{ t('workbench.sessions.empty') }}</p>
        </div>
      </div>
    </aside>

    <!-- 右栏：plan 对话 / 方案 -->
    <section class="flex min-w-0 flex-1 flex-col">
      <template v-if="selected">
        <div class="flex shrink-0 items-center gap-2 border-b border-ctp-surface0 px-4 py-2">
          <span class="min-w-0 flex-1 truncate text-sm font-semibold text-ctp-text">{{ selected.title || selected.id }}</span>
          <span class="chip !text-[10px]" :class="lcClass(selected.lifecycle)">{{ lcLabel(selected.lifecycle) }}</span>
          <div class="flex items-center gap-1">
            <button class="btn btn-xs" :class="rightTab === 'chat' ? 'btn-blue' : 'btn-ghost'" @click="rightTab = 'chat'">
              <ChatBubbleLeftRightIcon class="h-3 w-3" />{{ t('workbench.tabs.chat') }}
            </button>
            <button class="btn btn-xs" :class="rightTab === 'design' ? 'btn-blue' : 'btn-ghost'" @click="rightTab = 'design'">
              <DocumentTextIcon class="h-3 w-3" />{{ t('workbench.tabs.design') }}
            </button>
            <button
              v-if="selected.lifecycle === 'planning'"
              class="btn btn-xs btn-green"
              :disabled="finalizing"
              @click="finalize"
            >
              <CheckCircleIcon class="h-3 w-3" />{{ finalizing ? '…' : t('workbench.finalize') }}
            </button>
          </div>
        </div>
        <div class="min-h-0 flex-1">
          <AnalysisChat
            v-if="rightTab === 'chat'"
            :turns="turns"
            :busy="busy"
            :title="selected.title || t('workbench.sessions.defaultTitle')"
            :diagram-skill="diagramSkill"
            @send="onSend"
            @answers="onAnswers"
            @delete-turn="onDeleteTurn"
            @toggle-diagram-skill="toggleDiagramSkill"
          />
          <DesignPanel
            v-else
            :open="true"
            :inline="true"
            :req-id="selected.id"
          />
        </div>
      </template>
      <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 text-ctp-overlay0">
        <ChatBubbleLeftRightIcon class="h-8 w-8" />
        <p class="text-xs">{{ t('workbench.empty') }}</p>
      </div>
    </section>

    <!-- P3.2: 指派 subagent 弹窗 -->
    <div
      v-if="assignFor"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      @click.self="closeAssign"
    >
      <div class="w-96 rounded-lg border border-ctp-surface0 bg-ctp-mantle p-4 shadow-xl">
        <div class="mb-3 flex items-center justify-between">
          <span class="text-sm font-semibold text-ctp-text">{{ t('workbench.assign.title') }}</span>
          <button class="btn btn-xs btn-ghost" @click="closeAssign">
            <XMarkIcon class="h-3.5 w-3.5" />
          </button>
        </div>
        <p class="mb-3 truncate text-xs text-ctp-subtext0">
          {{ assignFor.title || assignFor.id }}
          <span class="font-mono text-[10px] text-ctp-overlay0">{{ assignFor.id }}</span>
        </p>
        <div class="mb-3">
          <span class="mb-1.5 block text-[11px] text-ctp-subtext1">{{ t('workbench.assign.target') }}</span>
          <div class="flex gap-3">
            <label class="flex cursor-pointer items-center gap-1.5 text-xs text-ctp-text">
              <input v-model="assignTarget" type="radio" value="runner" class="accent-ctp-blue" />
              {{ t('workbench.assign.runner') }}
            </label>
            <label class="flex cursor-pointer items-center gap-1.5 text-xs text-ctp-text">
              <input v-model="assignTarget" type="radio" value="mcp" class="accent-ctp-blue" />
              {{ t('workbench.assign.mcp') }}
            </label>
          </div>
        </div>
        <div v-if="assignTarget === 'runner'" class="mb-3">
          <span class="mb-1.5 block text-[11px] text-ctp-subtext1">{{ t('workbench.assign.execTask') }}</span>
          <select v-model="assignExecId" class="input w-full !py-1.5 text-xs">
            <option value="">{{ t('workbench.assign.execTaskEmpty') }}</option>
            <option v-for="e in task.executionTasks" :key="e.id" :value="e.id">
              {{ e.id }} · {{ e.status }}
            </option>
          </select>
        </div>
        <template v-else>
          <div class="mb-3">
            <span class="mb-1.5 block text-[11px] text-ctp-subtext1">{{ t('workbench.assign.tool') }}</span>
            <input v-model="assignTool" class="input w-full !py-1.5 text-xs" />
          </div>
          <div class="mb-3">
            <span class="mb-1.5 block text-[11px] text-ctp-subtext1">{{ t('workbench.assign.params') }}</span>
            <textarea v-model="assignParams" rows="2" class="input w-full resize-none text-xs" placeholder='{"key": "value"}' />
          </div>
        </template>
        <p v-if="assignError" class="mb-2 text-[11px] text-ctp-red">{{ assignError }}</p>
        <div class="flex justify-end gap-2">
          <button class="btn btn-xs btn-ghost" @click="closeAssign">{{ t('workbench.assign.cancel') }}</button>
          <button class="btn btn-xs btn-blue" :disabled="assignBusy" @click="confirmAssign">
            {{ assignBusy ? t('workbench.assign.busy') : t('workbench.assign.submit') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
