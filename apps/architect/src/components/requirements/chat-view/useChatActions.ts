/**
 * useChat · actions 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { reactive, ref } from 'vue'
import { CubeTransparentIcon, BoltIcon, AdjustmentsHorizontalIcon } from '@heroicons/vue/24/outline'
import type { SemanticAsset } from '@/types'
import { copyText } from '@/utils/clipboard'
import { useI18n } from 'vue-i18n'

import type { ChatDeps } from './chatTypes'

export function useChatActions(D: ChatDeps) {
  const { t } = useI18n()
  const props = D.props
  const emit = D.emit

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
  const ok = await copyText(m.content)
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


function showToast(text: string) {
  toastText.value = text
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, 2000)
}

// ── 提案卡确认存入：finalize 入池(待执行)；按钮自带 reqId, 多提案各自独立确认 ──
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
  void copyText(lines.join('\n')).then((ok) => showToast(ok ? t('requirement.chat.copySuccess') : t('requirement.chat.copyFailed')))
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

  return {
    assetKey,
    assetKindIcon,
    assetKindLabel,
    assetSummary,
    assetUsable,
    cancelDeleteTurn,
    confirmDeleteTurn,
    copiedTimer,
    copiedTurn,
    copyAsset,
    copyTurn,
    deletePending,
    expandedAssets,
    onMsgCopy,
    onRefreshAsset,
    reasoningOpen,
    removeTurn,
    showToast,
    toastText,
    toastTimer,
    toastVisible,
    toggleAsset,
    toggleReasoning,
  }
}
