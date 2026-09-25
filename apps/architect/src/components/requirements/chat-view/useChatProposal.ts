/**
 * useChat · proposal 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { reactive, ref, watch } from 'vue'
import type { KbAnalysisTurn } from '@/services/kb-analysis-agent'
import { apiPost, apiGet } from '@/services/api-client'
import { useI18n } from 'vue-i18n'

import type { ChatDeps } from './chatTypes'

export function useChatProposal(D: ChatDeps) {
  const { t } = useI18n()
  const props = D.props
  const emit = D.emit

const confirmingProposalId = ref('')
// 提案卡状态核验(防重复存入): p.confirmed 是本地态, 刷新即失——以后端为准
const proposalState = reactive<Record<string, string>>({})   // reqId -> draft/ready/done
const proposalChecked = reactive<Record<string, boolean>>({})
async function ensureProposalState(m: KbAnalysisTurn) {
  const p = m.proposal
  if (!p || p.confirmed || proposalChecked[p.id]) return
  proposalChecked[p.id] = true
  try {
    const r = await apiGet<Record<string, any>>(`/requirements/${p.id}`)
    const st = String(r?.status || '')
    if (st) proposalState[p.id] = st
    if (st === 'ready' || st === 'done') p.confirmed = true   // 已存入: 抑制存入按钮
  } catch { /* 状态获取失败不阻塞卡片展示 */ }
}
// cv-188: 追踪 proposal 挂载本身——attachProposal 在回合已存在时写入,
// turns.length 不变, 旧 watcher(只看长度)永不触发 → 实时卡漏判「已存入」
watch(() => props.turns.map((t) => t.proposal?.id || '').join(','), () => {
  for (const m of props.turns) if (m.proposal) void ensureProposalState(m)
}, { immediate: true })
/** 已存入(ready): 本地确认态或后端状态任一即可; done=已完成(不可再跑)。 */
function proposalStored(m: KbAnalysisTurn): boolean {
  const p = m.proposal
  if (!p) return false
  return p.confirmed || proposalState[p.id] === 'ready'
}
function proposalDone(m: KbAnalysisTurn): boolean {
  const p = m.proposal
  return !!p && proposalState[p.id] === 'done'
}
async function confirmProposal(m: KbAnalysisTurn) {
  const p = m.proposal
  if (!p || proposalStored(m) || confirmingProposalId.value) return   // 防重复存入
  confirmingProposalId.value = p.id
  try {
    const analysis = {
      ...(p.analysis ?? {}),
      implementationPath: p.analysis?.implementationPath || p.analysis?.designMd || '',
    }
    const row = await apiPost<Record<string, unknown>>(`/requirements/${p.id}/finalize`, { analysis })
    if (row && (row as any).id) {
      p.confirmed = true
      proposalState[p.id] = String((row as any).status || 'ready')
      D.actions.showToast(t('assetChat.extractPlan.confirmed'))
    } else {
      D.actions.showToast(t('assetChat.extractPlan.confirmFailed'))
    }
  } catch (e: any) {
    // 透出门禁原因(如"方案为空, 请 /调整 补全")而非笼统失败
    const msg = e?.response?.data?.message || e?.message || ''
    D.actions.showToast(msg ? `${t('assetChat.extractPlan.confirmFailed')}：${String(msg).slice(0, 120)}` : t('assetChat.extractPlan.confirmFailed'))
  } finally {
    confirmingProposalId.value = ''
  }
}
/** 提案卡运行: /执行 直通——按会话绑定执行器建任务卡(确认卡后 subagent 启动)。 */
function runProposal() {
  // cv-197: 按钮触发的 /执行 为合成消息——不回显气泡(后端落库带 synthetic 标记)
  emit('send', { text: '/执行', synthetic: true })
}

// ---- 推理内容(thinking)折叠展示 ----

  return {
    confirmProposal,
    confirmingProposalId,
    ensureProposalState,
    proposalChecked,
    proposalDone,
    proposalState,
    proposalStored,
    runProposal,
  }
}
