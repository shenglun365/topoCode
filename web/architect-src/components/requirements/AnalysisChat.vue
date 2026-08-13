<script setup lang="ts">
import { nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, PaperAirplaneIcon, ChatBubbleLeftRightIcon, BookOpenIcon, CheckIcon, QuestionMarkCircleIcon, ClipboardDocumentCheckIcon, ClipboardDocumentIcon, TrashIcon, CubeTransparentIcon, BoltIcon, AdjustmentsHorizontalIcon, ChevronDownIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'
import type { KbAnalysisTurn } from '@/services/kb-analysis-agent'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import type { ArchLlmModel, SemanticAsset, SemanticAssetKind } from '@/types'

const props = defineProps<{
  turns: KbAnalysisTurn[]
  busy: boolean
  models?: ArchLlmModel[]
  modelId?: string
  /** 对话标题(缺省「需求分析对话」；资产管理等复用场景可覆盖)。 */
  title?: string
  /** 是否显示「提取语义资产」按钮(需求分析对话隐藏；资产管理保留)。 */
  showExtract?: boolean
  /** 绘图增强(IR→代码)：开启后 agent 经 diagram.build 工具生成语法正确的图。 */
  diagramSkill?: boolean
}>()

const emit = defineEmits<{
  send: [text: string]
  answers: [answers: Record<string, string>]
  'confirm-draft': []
  'model-change': [id: string]
  'delete-turn': [index: number]
  'extract-assets': [kinds?: SemanticAssetKind[]]
  'refresh-asset': [assetId: string]
  'toggle-diagram-skill': [enabled: boolean]
}>()

const { t } = useI18n()
const input = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const scrollRef = ref<HTMLElement | null>(null)
const answers = reactive<Record<string, string>>({})

function onModelChange(e: Event) {
  const id = (e.target as HTMLSelectElement).value
  emit('model-change', id)
}

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

/** 单条消息删除：DOM 弹窗确认后移除本地 turn(持久化删除由 workspace 处理)。 */
const deletePending = ref<number | null>(null)

function removeTurn(i: number) {
  if (props.busy) return
  const m = props.turns[i]
  if (!m) return
  deletePending.value = i
}

function confirmDeleteTurn() {
  const i = deletePending.value
  deletePending.value = null
  if (i === null) return
  emit('delete-turn', i)
}

function cancelDeleteTurn() {
  deletePending.value = null
}

// ---- 复制：整条消息按钮 + 选中即复制(监听 copy 事件) + 轻提示 ----
const copiedTurn = ref<number | null>(null)
const copiedTimer = ref<ReturnType<typeof setTimeout> | null>(null)
const toastVisible = ref(false)
const toastText = ref('')
let toastTimer: ReturnType<typeof setTimeout> | null = null

/** 一键复制整条消息(纯文本内容)。 */
async function copyTurn(i: number) {
  const m = props.turns[i]
  if (!m) return
  const ok = await copyToClipboard(m.content)
  if (ok) {
    copiedTurn.value = i
    if (copiedTimer.value) clearTimeout(copiedTimer.value)
    copiedTimer.value = setTimeout(() => { copiedTurn.value = null }, 1600)
    showToast(t('requirement.chat.copySuccess'))
  } else {
    showToast(t('requirement.chat.copyFailed'))
  }
}

/** 选中即复制：消息区内发生 copy 事件(快捷键/右键)时，提示已复制。 */
function onMsgCopy() {
  const sel = window.getSelection()
  const text = sel?.toString().trim() ?? ''
  if (text) showToast(t('requirement.chat.copySuccess'))
}

/** 复制到剪贴板；不可用时降级 execCommand。 */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fallthrough
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

function showToast(text: string) {
  toastText.value = text
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, 2000)
}

// ---- 推理内容(thinking)折叠展示 ----
const reasoningOpen = reactive<Record<number, boolean>>({})

function toggleReasoning(i: number) {
  reasoningOpen[i] = !reasoningOpen[i]
}

// ---- 语义数据资产卡片 ----
const expandedAssets = reactive<Record<string, boolean>>({})

function assetKey(turnIdx: number, assetIdx: number) {
  return `${turnIdx}-${assetIdx}`
}

function toggleAsset(i: number, ai: number) {
  const k = assetKey(i, ai)
  expandedAssets[k] = !expandedAssets[k]
}

function assetKindIcon(kind?: SemanticAsset['kind']) {
  if (kind === 'process') return BoltIcon
  if (kind === 'decision' || kind === 'state') return AdjustmentsHorizontalIcon
  if (kind === 'contract') return CubeTransparentIcon
  return CubeTransparentIcon
}

function assetKindLabel(kind?: SemanticAsset['kind']): string {
  return t(`requirement.chat.assetKind.${kind ?? 'asset'}`)
}

function assetSummary(a: SemanticAsset): string {
  const d = a.detail
  if (!d) return ''
  const parts: string[] = []
  if (d.fields?.length) parts.push(`${t('requirement.chat.assetFields')} ${d.fields.length}`)
  if (d.steps?.length) parts.push(`${t('requirement.chat.assetSteps')} ${d.steps.length}`)
  if (d.branches?.length) parts.push(`${t('requirement.chat.assetBranches')} ${d.branches.length}`)
  if (a.astRefs?.length) parts.push(`${a.astRefs.length} AST`)
  return parts.join(' · ')
}

function copyAsset(a: SemanticAsset) {
  const lines = [`${a.name} (${assetKindLabel(a.kind)})`, `ID: ${a.id}`, a.desc]
  if (a.astRefs?.length) {
    lines.push('')
    lines.push(...a.astRefs.slice(0, 10).map((r) => `${r.file}:L${r.startLine}-L${r.endLine} ${r.symbol}`))
  }
  void copyToClipboard(lines.join('\n')).then((ok) => showToast(ok ? t('requirement.chat.copySuccess') : t('requirement.chat.copyFailed')))
}

function onExtractAssets() {
  if (props.busy) return
  emit('extract-assets')
}

/** 资产是否可引用(active 且未标记需更新)。 */
function assetUsable(a: SemanticAsset): boolean {
  return a.status !== 'stale' && a.status !== 'deleted' && !a.needsUpdate
}

function onRefreshAsset(a: SemanticAsset) {
  if (props.busy) return
  emit('refresh-asset', a.id)
}

onUnmounted(() => {
  if (copiedTimer.value) clearTimeout(copiedTimer.value)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<template>
  <div class="relative flex flex-col h-full min-h-0 border border-ctp-surface0 rounded-lg overflow-hidden bg-ctp-crust/30">
    <div class="panel-header shrink-0">
      <span class="flex items-center gap-2">
        <ChatBubbleLeftRightIcon class="w-4 h-4 text-ctp-blue" />{{ title ?? t('requirement.chat.title') }}
      </span>
      <select
        v-if="props.models?.length"
        class="input !py-0.5 !px-2 !text-[11px] w-auto font-mono"
        :value="props.modelId ?? ''"
        @change="onModelChange"
      >
        <option value="" disabled>{{ t('requirement.chat.selectModel') }}</option>
        <option
          v-for="m in props.models"
          :key="m.id"
          :value="m.id"
        >{{ m.name }} · {{ m.model }}</option>
      </select>
      <span
        v-else
        class="chip bg-ctp-teal/10 text-ctp-teal"
      >topocode KB</span>
    </div>

    <div
      ref="scrollRef"
      class="flex-1 min-h-[320px] overflow-auto p-3 space-y-2.5"
    >
        <div
          v-for="(m, i) in turns"
          :key="i"
          class="animate-fade-up flex items-start gap-2"
          @copy="onMsgCopy"
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
              class="text-ctp-overlay0 hover:text-ctp-red transition-colors p-0.5"
              :title="t('requirement.chat.deleteTurn')"
              :disabled="busy"
              @click="removeTurn(i)"
            >
              <TrashIcon class="w-3 h-3" />
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
          <ChatMessageBlocks :content="m.content" />

          <div
            v-if="m.assets?.length"
            class="mt-2 space-y-1.5"
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
                <span class="text-[11px] font-medium text-ctp-text truncate">{{ a.name }}</span>
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
                  <div class="font-medium text-ctp-mauve mb-0.5">AST 锚点</div>
                  <div
                    v-for="(r, ri) in a.astRefs.slice(0, 8)"
                    :key="ri"
                    class="pl-2 font-mono"
                  >{{ r.file }}:L{{ r.startLine }}-L{{ r.endLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span></div>
                </div>
              </div>
            </div>
          </div>

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

    <div class="flex items-center gap-2 border-t border-ctp-surface0 px-2.5 py-1.5 shrink-0">
      <button
        class="btn btn-xs"
        :class="props.diagramSkill ? 'btn-blue' : 'btn-ghost'"
        :disabled="busy"
        :title="t('requirement.chat.diagramSkillHint')"
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
        {{ t('requirement.chat.diagramSkill') }}
      </button>
      <span class="text-[10px] text-ctp-overlay0">{{ t('requirement.chat.diagramSkillHint') }}</span>
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
        v-if="props.showExtract !== false"
        class="btn !py-2.5 shrink-0 whitespace-nowrap btn-ghost"
        :disabled="busy"
        :title="t('requirement.chat.extractAssets')"
        @click="onExtractAssets"
      >
        <CubeTransparentIcon class="w-4 h-4" />{{ t('requirement.chat.extractAssets') }}
      </button>
      <button
        class="btn btn-primary !py-2.5 shrink-0 whitespace-nowrap"
        :disabled="!input.trim() || busy"
        @click="send"
      >
        <PaperAirplaneIcon class="w-4 h-4" />{{ t('coding.send') }}
      </button>
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
  </div>
</template>
