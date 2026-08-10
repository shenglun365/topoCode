<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon, PaperAirplaneIcon, StopIcon,
} from '@heroicons/vue/24/solid'
import { CheckCircleIcon, XCircleIcon, ChatBubbleLeftRightIcon } from '@heroicons/vue/24/outline'
import type { AgentMessage, AgentSession } from '@/types'
import { useArchAgentStore } from '@/stores/agent-store'
import { useArchTaskStore } from '@/stores/task-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchCollabStore } from '@/stores/collaboration-store'
import SessionStatsPanel from './SessionStatsPanel.vue'

const props = defineProps<{ session: AgentSession }>()

const { t } = useI18n()
const agent = useArchAgentStore()
const task = useArchTaskStore()
const requirement = useArchRequirementStore()
const collab = useArchCollabStore()
collab.load()
agent.load()
const input = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const scrollRef = ref<HTMLElement | null>(null)

const execTask = computed(() => task.findExecution(props.session.taskId))
const title = computed(() => {
  if (!execTask.value) return props.session.taskId
  const plan = requirement.planById(execTask.value.planId)
  return plan?.title ?? execTask.value.planId
})
const pendingInteractions = computed(() => collab.pending.filter((i) => i.taskId === props.session.taskId))
const answerText = ref('')

const statusColor: Record<string, string> = {
  idle: 'bg-ctp-surface0 text-ctp-subtext0',
  planning: 'bg-ctp-mauve/15 text-ctp-mauve',
  working: 'bg-ctp-blue/15 text-ctp-blue',
  testing: 'bg-ctp-yellow/15 text-ctp-yellow',
  done: 'bg-ctp-green/15 text-ctp-green',
  failed: 'bg-ctp-red/15 text-ctp-red',
  stopped: 'bg-ctp-red/15 text-ctp-red',
}
const interactionColor: Record<string, string> = {
  issue: 'bg-ctp-red/10 text-ctp-red',
  info: 'bg-ctp-sky/10 text-ctp-sky',
  choice: 'bg-ctp-peach/10 text-ctp-peach',
}

const toolColor: Record<string, string> = {
  'write-file': 'bg-ctp-blue/10 text-ctp-blue border-ctp-blue/30',
  'run-command': 'bg-ctp-mauve/10 text-ctp-mauve border-ctp-mauve/30',
  'run-test': 'bg-ctp-green/10 text-ctp-green border-ctp-green/30',
}

function roleChip(role: AgentMessage['role']) {
  return role === 'user' ? 'bg-ctp-sky/15 text-ctp-sky' : role === 'tool' ? 'bg-ctp-surface0 text-ctp-overlay1' : 'bg-ctp-mauve/15 text-ctp-mauve'
}
function roleColor(role: AgentMessage['role']) {
  if (role === 'user') return 'text-ctp-sky'
  if (role === 'tool') return 'text-ctp-overlay1'
  return 'text-ctp-text'
}

watch(
  () => props.session.messages.length,
  async () => {
    await nextTick()
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  },
)

// ---- 多行输入框(参照需求分析)：Enter 发送 / Ctrl+Enter 换行 / 上限 8 行自动滚动 ----
const MAX_ROWS = 8
function autoResize() {
  const el = inputRef.value
  if (!el) return
  const cs = getComputedStyle(el)
  const lineH = parseFloat(cs.lineHeight) || 16
  const pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0)
  const max = lineH * MAX_ROWS + pad
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, max)}px`
  el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
}
function resetInputHeight() {
  const el = inputRef.value
  if (!el) return
  const cs = getComputedStyle(el)
  const lineH = parseFloat(cs.lineHeight) || 16
  const pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0)
  el.style.height = `${lineH + pad}px`
  el.style.overflowY = 'hidden'
}
function onInputKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault()
    const el = e.target as HTMLTextAreaElement
    const start = el.selectionStart
    const end = el.selectionEnd
    input.value = input.value.slice(0, start) + '\n' + input.value.slice(end)
    nextTick(() => {
      el.selectionStart = el.selectionEnd = start + 1
      autoResize()
    })
    return
  }
  e.preventDefault()
  send()
}

async function send() {
  if (!input.value.trim()) return
  const text = input.value.trim()
  await agent.send(props.session.id, text)
  if (/^(?:追加|append)\s*[：:]/.test(text)) {
    const appended = task.addConversationalAmendment(props.session.taskId, text)
    if (appended) agent.noteAppended(props.session.id, appended.title)
  }
  input.value = ''
  resetInputHeight()
  await nextTick()
  scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
}

function stop() {
  agent.stop(props.session.id)
}
function answer(interactionId: string) {
  collab.resolve(interactionId, answerText.value.trim() || t('execute.interactionDefaultAnswer'))
  answerText.value = ''
}
</script>

<template>
  <div class="panel overflow-hidden flex flex-col h-full min-h-0">
    <div class="panel-header shrink-0">
      <div class="flex items-center gap-2 min-w-0">
        <ChatBubbleLeftRightIcon class="w-4 h-4 text-ctp-blue" />
        <span class="truncate">{{ title }}</span>
        <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ session.adapter }}</span>
        <span
          class="chip"
          :class="statusColor[session.status]"
        >{{ t(`coding.status.${session.status}`) }}</span>
      </div>
    </div>

    <div
      ref="scrollRef"
      class="flex-1 min-h-[280px] overflow-auto p-3 space-y-2.5 bg-ctp-crust/30"
    >
      <div
        v-for="m in session.messages"
        :key="m.id"
        class="animate-fade-up"
      >
        <div
          v-if="m.tool"
          class="flex items-start gap-2"
        >
          <div
            class="flex-1 min-w-0 rounded-md border px-3 py-2 text-xs"
            :class="toolColor[m.tool.type]"
          >
            <div class="flex items-center gap-2">
              <span class="font-mono">{{ m.tool.label }}</span>
              <div class="flex-1" />
              <CheckCircleIcon
                v-if="m.tool.ok"
                class="w-3.5 h-3.5 text-ctp-green"
              />
              <XCircleIcon
                v-else
                class="w-3.5 h-3.5 text-ctp-red"
              />
            </div>
            <p
              v-if="m.tool.detail"
              class="text-ctp-subtext0 mt-1"
            >
              {{ m.tool.detail }}
            </p>
          </div>
        </div>

        <div
          v-else
          class="flex items-start gap-2"
        >
          <div
            class="flex-1 min-w-0 rounded-lg rounded-tl-none px-3 py-2 text-xs bg-ctp-surface0/80"
            :class="m.role === 'user' ? 'ring-1 ring-ctp-sky/20' : ''"
          >
            <div class="flex items-center gap-1.5 mb-1">
              <span
                class="chip !text-[9px]"
                :class="roleChip(m.role)"
              >{{ m.role }}</span>
              <span class="text-[9px] text-ctp-overlay1">{{ new Date(m.time).toLocaleTimeString() }}</span>
            </div>
            <p
              class="whitespace-pre-wrap text-ctp-subtext1"
              :class="roleColor(m.role)"
            >
              {{ m.content }}
            </p>
          </div>
        </div>
      </div>

      <div
        v-if="agent.running && agent.activeSessionId === session.id"
        class="flex items-center gap-2 text-xs text-ctp-blue animate-pulse"
      >
        <ArrowPathIcon class="w-3.5 h-3.5 animate-spin" />{{ t('architecture.rendering') }}
      </div>
    </div>

    <!-- 会话统计 -->
    <div class="shrink-0 border-t border-ctp-surface0 px-3 py-2">
      <SessionStatsPanel :stats="session.stats" />
    </div>

    <!-- 需用户解答的交互 -->
    <div
      v-if="pendingInteractions.length"
      class="shrink-0 border-t border-ctp-surface0 px-3 py-2 space-y-2"
    >
      <div
        v-for="it in pendingInteractions"
        :key="it.id"
        class="rounded-lg border border-ctp-surface0 p-2.5"
      >
        <div class="flex items-center gap-2 mb-1">
          <span
            class="chip text-[10px]"
            :class="interactionColor[it.kind]"
          >{{ t(`execute.interactionKind.${it.kind}`) }}</span>
          <span class="text-xs text-ctp-subtext0">{{ it.prompt }}</span>
        </div>
        <div
          v-if="it.options?.length"
          class="flex flex-wrap gap-1.5 mb-1.5"
        >
          <button
            v-for="opt in it.options"
            :key="opt"
            class="chip border border-ctp-surface1 text-ctp-subtext1 hover:text-ctp-text hover:border-ctp-blue/40 cursor-pointer transition-colors"
            @click="collab.resolve(it.id, opt)"
          >
            {{ opt }}
          </button>
        </div>
        <div class="flex items-center gap-1.5">
          <input
            v-model="answerText"
            class="input !py-1 text-xs"
            :placeholder="t('execute.interactionAnswerPlaceholder')"
            @keydown.enter.prevent="answer(it.id)"
          >
          <button
            class="btn btn-xs btn-blue shrink-0"
            @click="answer(it.id)"
          >
            {{ t('execute.interactionAnswer') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 输入区 + 停止 -->
    <div class="shrink-0 flex items-end gap-2 border-t border-ctp-surface0 p-2.5">
      <textarea
        ref="inputRef"
        v-model="input"
        rows="1"
        class="input !py-2 text-xs resize-none"
        :placeholder="t('coding.inputPlaceholder')"
        @input="autoResize"
        @keydown="onInputKeydown"
      />
      <button
        v-if="agent.running && agent.activeSessionId === session.id"
        class="btn btn-red shrink-0 whitespace-nowrap !py-2"
        @click="stop"
      >
        <StopIcon class="w-4 h-4" />{{ t('execute.stop') }}
      </button>
      <button
        v-else
        class="btn btn-primary shrink-0 whitespace-nowrap !py-2"
        :disabled="!input.trim()"
        @click="send"
      >
        <PaperAirplaneIcon class="w-4 h-4" />{{ t('coding.send') }}
      </button>
    </div>
    <div
      v-if="execTask"
      class="shrink-0 border-t border-ctp-surface0 px-3 py-1.5 text-[10px] text-ctp-overlay1"
    >
      {{ t('coding.appendHint') }}
    </div>
  </div>
</template>
