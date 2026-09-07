<script setup lang="ts">
import { nextTick, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, PaperAirplaneIcon, ChatBubbleLeftRightIcon, BookOpenIcon, CheckIcon, QuestionMarkCircleIcon, ClipboardDocumentCheckIcon, ClipboardDocumentIcon, TrashIcon, CubeTransparentIcon, BoltIcon, AdjustmentsHorizontalIcon, ChevronDownIcon, ChevronRightIcon, StopIcon, ArrowTopRightOnSquareIcon, WrenchScrewdriverIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import type { KbAnalysisTurn } from '@/services/kb-analysis-agent'
import type { AcceptanceFact, AcceptanceReportDetail, ContractItem } from '@/services/contract-service'
import type { NamingConvention } from '@/services/naming-service'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import type { SemanticAsset } from '@/types'
import type { ToolTrailItem } from '@/composables/useChatProgress'

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
  /** 绘图增强(IR→代码)：开启后 agent 经 diagram.build 工具生成语法正确的图。 */
  diagramSkill?: boolean
  /** 期望固化(🧾)：开启后 agent 把可验证期望固化为契约条目草稿。 */
  contractSkill?: boolean
  /** 是否显示 🧾 开关(仅需求方案对话显示；资产管理/工作台不显示)。 */
  showContractSkill?: boolean
}>()

const emit = defineEmits<{
  send: [text: string]
  answers: [answers: Record<string, string>]
  'confirm-draft': []
  'delete-turn': [index: number]
  'refresh-asset': [assetId: string]
  'toggle-diagram-skill': [enabled: boolean]
  'toggle-contract-skill': [enabled: boolean]
  'contract-confirm': [id: string]
  'contract-delete': [id: string]
  'contract-edit-save': [id: string, patch: Record<string, unknown>]
  'convention-confirm': [id: string]
  'convention-ignore': [id: string]
  'goto-acceptance': []
  'goto-requirements': [reqId: string]
  stop: []
}>()

const { t } = useI18n()
const input = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)

// ---- 工具轨迹浮层（防信息过载：默认收起，点击展开；回合结束/busy 清空自动关闭）----
const trailOpen = ref(false)
watch(() => props.busy, (b) => { if (!b) trailOpen.value = false })

// ---- 外部引用预填：nonce 变化 → 追加进输入框并聚焦(用户可补充问题后再发送) ----
watch(() => props.insertDraft?.nonce ?? 0, (n) => {
  if (!n) return
  const text = props.insertDraft?.text ?? ''
  if (!text) return
  input.value = input.value ? `${input.value} ${text}` : text
  void nextTick(() => {
    inputRef.value?.focus()
    autoResize()
    const el = inputRef.value
    if (el) el.selectionStart = el.selectionEnd = el.value.length
  })
})
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

/** 资产是否可引用(active 且未标记需更新)。 */
function assetUsable(a: SemanticAsset): boolean {
  return a.status !== 'stale' && a.status !== 'deleted' && !a.needsUpdate
}

function onRefreshAsset(a: SemanticAsset) {
  if (props.busy) return
  emit('refresh-asset', a.id)
}

// ── 契约条目固化卡（🧾 期望固化） ─────────────────────────────

const contractEditOpen = reactive<Record<string, boolean>>({})
const contractEditText = reactive<Record<string, string>>({})

function contractStatusLabel(s?: string): string {
  return t(`requirement.chat.contractStatus.${s ?? 'draft'}`)
}

function contractStatusCls(s?: string): string {
  const map: Record<string, string> = {
    draft: 'bg-ctp-yellow/15 text-ctp-yellow',
    confirmed: 'bg-ctp-blue/15 text-ctp-blue',
    injected: 'bg-ctp-sky/15 text-ctp-sky',
    verifying: 'bg-ctp-mauve/15 text-ctp-mauve',
    accepted: 'bg-ctp-green/15 text-ctp-green',
    rejected: 'bg-ctp-red/15 text-ctp-red',
  }
  return map[s ?? 'draft'] ?? map.draft
}

function contractTargetText(c: ContractItem): string {
  const tgt = c.target ?? {}
  const t2 = [tgt.file, tgt.symbol].filter(Boolean).join('::')
  return t2 || t('requirement.chat.contractIntentOnly')
}

function contractBehaviorText(c: ContractItem): string {
  const b = c.behavior ?? {}
  const parts: string[] = []
  if (b.steps?.length) parts.push(`${t('requirement.chat.assetSteps')} ${b.steps.length}`)
  if (b.branches?.length) parts.push(`${t('requirement.chat.assetBranches')} ${b.branches.length}`)
  if (b.fields?.length) parts.push(`${t('requirement.chat.assetFields')} ${b.fields.length}`)
  if (c.zAxis?.length) parts.push(`Z ${c.zAxis.length}`)
  return parts.join(' · ')
}

/** 展开「修改」：把可编辑期望字段序列化为 JSON 供设计者调整。 */
function openContractEdit(c: ContractItem) {
  if (contractEditOpen[c.id]) { contractEditOpen[c.id] = false; return }
  const editable = {
    target: c.target ?? {},
    behavior: c.behavior ?? {},
    zAxis: c.zAxis ?? [],
    acceptance: c.acceptance ?? {},
  }
  contractEditText[c.id] = JSON.stringify(editable, null, 2)
  contractEditOpen[c.id] = true
}

function saveContractEdit(c: ContractItem) {
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(contractEditText[c.id] || '{}')
  } catch {
    showToast(t('requirement.chat.contractEditInvalid'))
    return
  }
  contractEditOpen[c.id] = false
  emit('contract-edit-save', c.id, parsed)
}

function onContractConfirm(c: ContractItem) {
  if (props.busy) return
  emit('contract-confirm', c.id)
}

function onContractDelete(c: ContractItem) {
  if (props.busy) return
  emit('contract-delete', c.id)
}

function onConventionConfirm(c: NamingConvention) {
  if (props.busy) return
  emit('convention-confirm', c.id)
}

function onConventionIgnore(c: NamingConvention) {
  if (props.busy) return
  emit('convention-ignore', c.id)
}

function onGotoAcceptance() {
  if (props.busy) return
  emit('goto-acceptance')
}

/** 差异报告卡：L1/L2 通过率 + 待人工数 + 前三差异事实（事实/意见分区，判定在验收区块）。 */
function diffSummary(detail: AcceptanceReportDetail): { rate: string; awaiting: number; top: AcceptanceFact[] } {
  const facts = detail.facts ?? []
  const pass = facts.filter((f) => f.verdict === 'pass').length
  const rate = facts.length ? `${Math.round((pass / facts.length) * 100)}%` : '—'
  const awaiting = (detail.report?.summary?.awaitingHuman ?? 0)
    + facts.filter((f) => f.verdict === 'fail' || f.verdict === 'partial').length
  const top = facts
    .filter((f) => f.verdict !== 'pass')
    .slice(0, 3)
  return { rate, awaiting, top }
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

          <!-- 契约条目固化卡（🧾 期望固化：逐条确认/修改/删；判定动作在验收区块） -->
          <div
            v-if="m.contracts?.length"
            class="mt-2 space-y-1.5"
          >
            <div
              v-for="c in m.contracts"
              :key="c.id"
              class="border border-ctp-teal/25 bg-ctp-teal/5 rounded-lg overflow-hidden"
            >
              <div class="flex items-center gap-1.5 px-2 py-1.5">
                <span class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal shrink-0">
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
              </div>
              <div class="px-2 pb-1.5 space-y-1 text-[11px]">
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

          <!-- S5 需求提案卡（req.propose 产出：需求+方案+评估 → 前往需求方案） -->
          <div
            v-if="m.proposal"
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
              <button
                class="btn btn-xs btn-blue"
                @click="emit('goto-requirements', m.proposal.id)"
              >
                <ArrowTopRightOnSquareIcon class="w-3 h-3" />{{ t('assetChat.proposal.goto') }}
              </button>
            </div>
            <div
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
            </div>
            <div class="px-2 pb-2 space-y-1.5 text-[11px]">
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
                  v-for="(f, fi) in diffSummary(m.acceptance).top"
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
      <span v-if="props.showContractSkill === undefined || props.showContractSkill" class="text-[10px] text-ctp-overlay0">{{ t('requirement.chat.diagramSkillHint') }}</span>
      <button
        v-if="props.showContractSkill"
        class="btn btn-xs"
        :class="props.contractSkill ? 'btn-green' : 'btn-ghost'"
        :disabled="busy"
        :title="t('requirement.chat.contractSkillHint')"
        @click="emit('toggle-contract-skill', !props.contractSkill)"
      >
        <svg
          class="w-3.5 h-3.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        ><path d="M9 12h6" /><path d="M9 16h6" /><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
        {{ t('requirement.chat.contractSkill') }}
      </button>
      <span v-if="props.showContractSkill && props.contractSkill" class="text-[10px] text-ctp-overlay0">{{ t('requirement.chat.contractSkillHint') }}</span>
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
        v-if="busy"
        class="btn btn-red !py-2.5 shrink-0 whitespace-nowrap"
        :title="t('requirement.chat.stop')"
        @click="emit('stop')"
      >
        <StopIcon class="w-4 h-4" />{{ t('requirement.chat.stop') }}
      </button>
      <button
        v-else
        class="btn btn-primary !py-2.5 shrink-0 whitespace-nowrap"
        :disabled="!input.trim()"
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
