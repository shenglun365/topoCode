/**
 * useChat · digest 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, reactive, ref, watch } from 'vue'
import { apiPost } from '@/services/api-client'
import { useI18n } from 'vue-i18n'

import type { ChatDeps } from './chatTypes'

export function useChatDigest(D: ChatDeps) {
  const { t } = useI18n()
  const props = D.props
  const emit = D.emit

const DIGEST_AUTO_KEY = 'arch.digestAutoSend'
const digestMode = ref(false)
const selIds = ref<Set<string>>(new Set())
const digestBusy = ref(false)
const digestDraft = ref<string | null>(null)   // 非空=草稿卡(可编辑)

/** 任务状态卡样式映射(cv-203): running/waiting/done/failed → 图标+配色。 */
function statusStrip(it: any): { icon: string; cls: string } {
  const s = String(it?.payload?.status || it?.status || 'running')
  if (s === 'done') return { icon: '✅', cls: 'border-ctp-green/30 bg-ctp-green/5 text-ctp-subtext1' }
  if (s === 'failed') return { icon: '❌', cls: 'border-ctp-red/30 bg-ctp-red/5 text-ctp-subtext1' }
  if (s === 'waiting') return { icon: '⏸', cls: 'border-ctp-yellow/30 bg-ctp-yellow/5 text-ctp-subtext1' }
  return { icon: '🔄', cls: 'border-ctp-sky/30 bg-ctp-sky/5 text-ctp-subtext1' }
}

// ── 工具审批操作条(task_approval 消息) ──
const approvalDone = reactive<Record<string, 'approved' | 'rejected'>>({})
async function respondApproval(m: any, approved: boolean) {
  const jobId = m?.meta?.approvalJobId
  const requestId = m?.meta?.approvalRequestId
  if (!jobId || !requestId || approvalDone[m.id]) return
  try {
    await apiPost(`/exec/${jobId}/approval`, {
      requestId, approved,
      reason: approved ? 'approved' : 'rejected by user',
    })
    approvalDone[m.id] = approved ? 'approved' : 'rejected'
  } catch { /* 失败保持可重试 */ }
}
const digestAutoSend = ref(localStorage.getItem(DIGEST_AUTO_KEY) === '1')
/** 摘要入口仅转达语境(路由=任务)显示; architect 路由本就全史可见无需摘要。 */
const canDigest = computed(() => D.route.effectiveRoute.value.kind === 'task')
function toggleDigestMode() {
  if (!canDigest.value) return
  digestMode.value = !digestMode.value
  if (!digestMode.value) exitDigest()
}
function exitDigest() {
  digestMode.value = false
  selIds.value = new Set()
  digestDraft.value = null
}
function toggleSel(m: any) {
  if (!digestMode.value || !m?.id) return   // 本地乐观回合无 id, 不可选
  const s = new Set(selIds.value)
  if (s.has(m.id)) s.delete(m.id)
  else s.add(m.id)
  selIds.value = s
}
/** 生成摘要: REST → 自动通过(跳卡直发) 或 草稿卡人工审核。 */
async function generateDigest() {
  if (!selIds.value.size || digestBusy.value || !props.convId) return
  digestBusy.value = true
  try {
    const r = await apiPost<{ digest: string; chars: number; summarized: boolean }>(
      `/sessions/${props.convId}/msg-digest`, { msgIds: [...selIds.value] })
    const digest = (r as any)?.digest || (r as any)?.data?.digest || ''
    if (!digest) return
    if (digestAutoSend.value) {
      await sendDigest(digest)          // 自动通过: 不落审核卡
      exitDigest()
    } else {
      digestDraft.value = digest
    }
  } catch { /* 生成失败: 保留选择可重试 */ } finally {
    digestBusy.value = false
  }
}
async function sendDigest(digest: string) {
  const r = D.route.effectiveRoute.value
  if (r.kind !== 'task' || props.busy) return
  emit('send', { text: '', attachTo: r.taskId, digest })
}
function confirmDigest() {
  if (digestDraft.value?.trim()) void sendDigest(digestDraft.value)
  exitDigest()
}
function onAutoSendToggle(e: Event) {
  digestAutoSend.value = (e.target as HTMLInputElement).checked
  localStorage.setItem(DIGEST_AUTO_KEY, digestAutoSend.value ? '1' : '0')
}
watch(canDigest, (ok) => { if (!ok && digestMode.value) exitDigest() })
/** 草稿卡标题: 当前转达目标任务。 */
const digestTargetTitle = computed(() => {
  const r = D.route.effectiveRoute.value
  return r.kind === 'task' ? (D.route.taskTitleOf(r.taskId).slice(0, 20) || '当前任务') : '当前任务'
})
/** 占位文案随语境联动(转达任务/指派执行器时给出方向提示)。 */
const inputPlaceholder = computed(() => {
  if (props.readOnly) return t('session.readOnlyHint')
  const r = D.route.effectiveRoute.value
  if (r.kind === 'task') return `回复当前任务「${D.route.taskTitleOf(r.taskId).slice(0, 16) || '…'}」…`
  if (r.kind === 'assign') return `@${r.agent} `
  return t('requirement.chat.placeholder')
})

/** 任务卡定位: meta.taskId → 最新任务行(状态实时)。 */
function taskById(id?: string) {
  if (!id) return null
  return (props.tasks || []).find((t) => t.id === id) || null
}

/** 需求卡的执行按钮状态检测(cv-205): 需求已有进行中任务(running/
 * waiting_input/pending_confirm) → 禁用一键建卡执行(后端同守卫兜底,
 * cv-203 防重复执行); saved 不算进行中(建卡走修订分支); 终态可重试。 */

  return {
    DIGEST_AUTO_KEY,
    approvalDone,
    canDigest,
    confirmDigest,
    digestAutoSend,
    digestBusy,
    digestDraft,
    digestMode,
    digestTargetTitle,
    exitDigest,
    generateDigest,
    inputPlaceholder,
    onAutoSendToggle,
    respondApproval,
    selIds,
    sendDigest,
    statusStrip,
    taskById,
    toggleDigestMode,
    toggleSel,
  }
}
