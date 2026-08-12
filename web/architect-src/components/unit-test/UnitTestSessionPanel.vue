<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, PaperAirplaneIcon, StopIcon } from '@heroicons/vue/24/solid'
import { CheckCircleIcon, XCircleIcon, ChatBubbleLeftRightIcon, CommandLineIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import type { UnitTestSession } from '@/types'
import { useArchUnitTestStore } from '@/stores/unit-test-store'
import { useArchTaskStore } from '@/stores/task-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import SessionStatsPanel from '@/components/coding/SessionStatsPanel.vue'

const props = defineProps<{ session: UnitTestSession }>()

const { t } = useI18n()
const store = useArchUnitTestStore()
const task = useArchTaskStore()
const requirement = useArchRequirementStore()
const input = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const scrollRef = ref<HTMLElement | null>(null)

const linkedTitle = computed(() => {
  const ls = task.executionTasks.filter((e) => e.testIds?.includes(props.session.testIds[0] ?? '') || props.session.testIds.every((id) => e.testIds?.includes(id)))
  return ls[0] ? requirement.planById(ls[0].planId)?.title ?? ls[0].id : undefined
})

const toolColor: Record<string, string> = {
  'run-test': 'bg-ctp-green/10 text-ctp-green border-ctp-green/30',
  'run-command': 'bg-ctp-mauve/10 text-ctp-mauve border-ctp-mauve/30',
}

watch(
  () => props.session.messages.length,
  async () => {
    await nextTick()
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  },
)

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
  el.style.height = 'auto'
  el.style.overflowY = 'hidden'
}
function onInputKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  if (e.ctrlKey || e.metaKey) return
  e.preventDefault()
  send()
}

async function send() {
  if (!input.value.trim()) return
  const text = input.value.trim()
  await store.send(text)
  input.value = ''
  resetInputHeight()
}

function stop() {
  store.stop()
}
</script>

<template>
  <div class="panel overflow-hidden flex flex-col h-full min-h-0">
    <div class="panel-header shrink-0">
      <div class="flex items-center gap-2 min-w-0">
        <ChatBubbleLeftRightIcon class="w-4 h-4 text-ctp-lavender" />
        <span class="truncate">{{ session.title }}</span>
        <span
          class="chip font-mono text-[10px]"
          :class="session.channel === 'cli' ? 'bg-ctp-mauve/15 text-ctp-mauve' : 'bg-ctp-sky/15 text-ctp-sky'"
        >
          <component :is="session.channel === 'cli' ? CommandLineIcon : SparklesIcon" class="inline w-3 h-3 -mt-0.5 mr-0.5" />
          {{ session.channel === 'cli' ? t('unitTest.channel.cli') : t('unitTest.channel.agent') }}
        </span>
        <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ session.adapter }}</span>
        <span
          class="chip"
          :class="session.status === 'done' ? 'bg-ctp-green/15 text-ctp-green' : session.status === 'running' ? 'bg-ctp-blue/15 text-ctp-blue' : 'bg-ctp-surface0 text-ctp-subtext0'"
        >{{ t(`unitTest.sessionStatus.${session.status}`) }}</span>
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
                :class="m.role === 'user' ? 'bg-ctp-sky/15 text-ctp-sky' : 'bg-ctp-mauve/15 text-ctp-mauve'"
              >{{ m.role }}</span>
              <span class="text-[9px] text-ctp-overlay1">{{ new Date(m.time).toLocaleTimeString() }}</span>
            </div>
            <ChatMessageBlocks :content="m.content" />
          </div>
        </div>
      </div>

      <div
        v-if="store.running && store.activeSessionId === session.id"
        class="flex items-center gap-2 text-xs text-ctp-blue animate-pulse"
      >
        <ArrowPathIcon class="w-3.5 h-3.5 animate-spin" />{{ t('unitTest.running') }}
      </div>
    </div>

    <div class="shrink-0 border-t border-ctp-surface0 px-3 py-2">
      <SessionStatsPanel :stats="session.stats" />
    </div>
    <div
      v-if="linkedTitle"
      class="shrink-0 border-t border-ctp-surface0 px-3 py-1.5 text-[10px] text-ctp-overlay1"
    >
      {{ t('unitTest.linkedHint') }}  {{ linkedTitle }}
    </div>

    <div class="shrink-0 flex items-end gap-2 border-t border-ctp-surface0 p-2.5">
      <textarea
        ref="inputRef"
        v-model="input"
        rows="1"
        class="input !py-2 text-xs resize-none"
        :placeholder="t('unitTest.inputPlaceholder')"
        @input="autoResize"
        @keydown="onInputKeydown"
      />
      <button
        v-if="store.running && store.activeSessionId === session.id"
        class="btn btn-red shrink-0 whitespace-nowrap !py-2"
        @click="stop"
      >
        <StopIcon class="w-4 h-4" />{{ t('unitTest.stop') }}
      </button>
      <button
        v-else
        class="btn btn-primary shrink-0 whitespace-nowrap !py-2"
        :disabled="!input.trim()"
        @click="send"
      >
        <PaperAirplaneIcon class="w-4 h-4" />{{ t('unitTest.send') }}
      </button>
    </div>
  </div>
</template>