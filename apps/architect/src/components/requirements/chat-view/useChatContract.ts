/**
 * useChat · contract 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { reactive } from 'vue'
import type { AcceptanceFact, AcceptanceReportDetail, ContractItem } from '@/services/contract-service'
import type { NamingConvention } from '@/services/naming-service'
import { useI18n } from 'vue-i18n'

import type { ChatDeps } from './chatTypes'

export function useChatContract(D: ChatDeps) {
  const { t } = useI18n()
  const props = D.props
  const emit = D.emit

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
    D.actions.showToast(t('requirement.chat.contractEditInvalid'))
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

  return {
    contractBehaviorText,
    contractEditOpen,
    contractEditText,
    contractStatusCls,
    contractStatusLabel,
    contractTargetText,
    diffSummary,
    onContractConfirm,
    onContractDelete,
    onConventionConfirm,
    onConventionIgnore,
    onGotoAcceptance,
    openContractEdit,
    saveContractEdit,
  }
}
