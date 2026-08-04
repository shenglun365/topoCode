<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, PaperAirplaneIcon, ChatBubbleLeftRightIcon, BookOpenIcon, CheckIcon, QuestionMarkCircleIcon, ClipboardDocumentCheckIcon } from '@heroicons/vue/24/outline'
import type { KbAnalysisTurn } from '@/services/kb-analysis-agent'

const props = defineProps<{
  turns: KbAnalysisTurn[]
  busy: boolean
}>()

const emit = defineEmits<{
  send: [text: string]
  answers: [answers: Record<string, string>]
  'confirm-draft': []
}>()

const { t } = useI18n()
const input = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const scrollRef = ref<HTMLElement | null>(null)
const answers = reactive<Record<string, string>>({})

watch(
  () => props.turns.length,
  async () => {
    await nextTick()
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  },
)
watch(
  () => props.turns,
  (turns) => {
    const q = turns[turns.length - 1]?.questions
    if (q) q.forEach((item) => { if (!(item.key in answers)) answers[item.key] = item.answer ?? '' })
  },
  { deep: true },
)

function send() {
  if (!input.value.trim() || props.busy) return
  emit('send', input.value.trim())
  input.value = ''
  resetInputHeight()
  nextTick(() => scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' }))
}

const MAX_ROWS = 8
/** 自适应高度：随内容加高，上限 8 行，超过显示滚动条。 */
function autoResize() {
  const el = inputRef.value
  if (!el) return
  const lineH = parseFloat(getComputedStyle(el).lineHeight) || 16
  const pad = (parseFloat(getComputedStyle(el).paddingTop) || 0) + (parseFloat(getComputedStyle(el).paddingBottom) || 0)
  const max = lineH * MAX_ROWS + pad
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, max)}px`
  el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
}
/** 发送后回到默认一行高度。 */
function resetInputHeight() {
  const el = inputRef.value
  if (!el) return
  const lineH = parseFloat(getComputedStyle(el).lineHeight) || 16
  const pad = (parseFloat(getComputedStyle(el).paddingTop) || 0) + (parseFloat(getComputedStyle(el).paddingBottom) || 0)
  el.style.height = `${lineH + pad}px`
  el.style.overflowY = 'hidden'
}
/** Enter 发送；Ctrl/Cmd+Enter 手动插入换行(保证各浏览器一致)。 */
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

function submitAnswers() {
  emit('answers', { ...answers })
  Object.keys(answers).forEach((k) => delete answers[k])
}
</script>

<template>
  <div class="flex flex-col h-full min-h-0 border border-ctp-surface0 rounded-lg overflow-hidden bg-ctp-crust/30">
    <div class="panel-header shrink-0">
      <span class="flex items-center gap-2">
        <ChatBubbleLeftRightIcon class="w-4 h-4 text-ctp-blue" />{{ t('requirement.chat.title') }}
      </span>
      <span class="chip bg-ctp-teal/10 text-ctp-teal">topocode KB</span>
    </div>

    <div
      ref="scrollRef"
      class="flex-1 min-h-[320px] overflow-auto p-3 space-y-2.5"
    >
      <div
        v-for="(m, i) in turns"
        :key="i"
        class="animate-fade-up flex items-start gap-2"
      >
        <div
          class="flex-1 min-w-0 rounded-lg rounded-tl-none px-3 py-2 text-xs bg-ctp-surface0/80"
          :class="m.role === 'user' ? 'ring-1 ring-ctp-sky/20' : ''"
        >
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
              v-else
              class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve"
            >
              <BookOpenIcon class="w-2.5 h-2.5 inline" />{{ t('requirement.chat.kb') }}
            </span>
          </div>
          <p class="whitespace-pre-wrap text-ctp-subtext1">
            {{ m.content }}
          </p>

          <div
            v-if="m.questions"
            class="mt-2 border border-ctp-blue/25 bg-ctp-blue/5 rounded-lg p-2 space-y-2"
          >
            <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-ctp-blue">
              <QuestionMarkCircleIcon class="w-3 h-3" />{{ t('requirement.chat.questions') }}
            </div>
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
            </div>
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

      <div
        v-if="busy"
        class="flex items-center gap-2 text-xs text-ctp-blue animate-pulse"
      >
        <ArrowPathIcon class="w-3.5 h-3.5 animate-spin" />{{ t('requirement.chat.thinking') }}
      </div>
    </div>

    <div class="flex items-end gap-2 border-t border-ctp-surface0 p-2.5 shrink-0">
      <textarea
        ref="inputRef"
        v-model="input"
        rows="1"
        class="input !py-2.5 text-xs resize-none"
        :placeholder="t('requirement.chat.placeholder')"
        @input="autoResize"
        @keydown="onInputKeydown"
      />
      <button
        class="btn btn-primary !py-2.5 shrink-0 whitespace-nowrap"
        :disabled="!input.trim() || busy"
        @click="send"
      >
        <PaperAirplaneIcon class="w-4 h-4" />{{ t('coding.send') }}
      </button>
    </div>
  </div>
</template>
