/**
 * useChat · cards 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, reactive, ref } from 'vue'
import { useCardCollapse } from '@/composables/useCardCollapse'
import { parseSpecPayload, assembleSpecView } from '@/services/spec-view'
import { apiPost, apiGet } from '@/services/api-client'

import type { ChatDeps } from './chatTypes'

export function useChatCards(D: ChatDeps) {
  const props = D.props
  const emit = D.emit

const editingTitle = ref(false)
const titleDraft = ref('')

/** 资产引用点击 → 联动资产地图(图谱节点/资产卡)。宿主页面监听 arch:open-asset。 */
function openAssetRef(id: string) {
  window.dispatchEvent(new CustomEvent('arch:open-asset', { detail: id }))
}

// ── S3 投喂门: 消息级「转达 coding」(dock 执行 POST /feed, 结果本地消息) ──
const feedBusyIdx = ref(-1)
const mergeBusyIdx = ref(-1)
const mergedDone = ref<Record<number, boolean>>({})

/** 合并入口检查(环节十五): git 事实 → 轻提示(可否直并/需先 rebase)。 */
async function runMergePrecheck(i: number, taskId: string) {
  mergeBusyIdx.value = i
  try {
    const r = await apiGet<{ fastForward: boolean | null; mainNewCommits: string[]; branchCommits: string[]; advice: string }>(
      `/tasks/${taskId}/merge-precheck`)
    const ff = r.fastForward === true ? '✓ 可直接合并' : r.fastForward === false ? '⚠ 主目录有推进, 需先 rebase' : '— 无基点, 请手工检视'
    D.actions.showToast(`合并检查: ${ff} — ${r.advice}`)
  } catch (e: any) {
    D.actions.showToast(`✗ 合并检查失败: ${e?.message || e}`)
  } finally {
    mergeBusyIdx.value = -1
  }
}

/** 确认合并(本地 PR 语义): 门禁通过后执行; 冲突/需 rebase → 提示原文。 */
async function confirmMerge(i: number, taskId: string) {
  mergeBusyIdx.value = i
  try {
    const r = await apiPost<{ mergedHead: string; advice: string }>(
      `/tasks/${taskId}/merge`, { mode: 'ff' })
    mergedDone.value[i] = true
    D.actions.showToast(`✓ ${r.advice}`)
  } catch (e: any) {
    D.actions.showToast(`✗ 合并未执行: ${e?.message || e}`)
  } finally {
    mergeBusyIdx.value = -1
  }
}

// ── 规约 JSON 识别(字段签名): 单源在 services/spec-view(识别/归一/分节
// 组装一体)——「写入需求」按钮与正文规约草稿视图(cv-248)共用。 ──
function specPayloadOf(index: number): Record<string, unknown> | null {
  return parseSpecPayload(props.turns[index]?.content || '')
}
// 正文规约草稿视图(cv-248): 规约 schema 载荷按 MD 分节渲染(载荷形态决定
// 渲染形态), 不再代码块原样显示。computed 集合(识别含正则, 避免逐帧重跑)。
const specDraftIdx = computed(() => {
  const set = new Set<number>()
  ;(props.turns || []).forEach((m: any, i: number) => {
    if (m.role === 'assistant' && !m.item && specPayloadOf(i)) set.add(i)
  })
  return set
})
function specDraftView(i: number) {
  return assembleSpecView(specPayloadOf(i) || {}, '')
}
const specBusyIdx = ref(-1)
// cv-248: 已写入态(本地)——写入成功后按钮禁用防重复(后端另有指纹幂等兜底)
const specAppliedIdx = reactive(new Set<number>())
function onSpecApply(index: number) {
  if (specBusyIdx.value >= 0 || specAppliedIdx.has(index)) return
  const payload = specPayloadOf(index)
  if (!payload) return
  specBusyIdx.value = index
  try {
    emit('spec-apply', { index, payload })
    specAppliedIdx.add(index)
  } finally {
    setTimeout(() => { specBusyIdx.value = -1 }, 800)
  }
}

/** 阶段标注配色(设计/实现/评估/验收——消息级工具推导, 非会话分类)。 */
function stageClass(stage: string) {
  if (stage === 'design') return 'bg-ctp-peach/15 text-ctp-peach'
  if (stage === 'implement') return 'bg-ctp-sky/15 text-ctp-sky'
  if (stage === 'evaluate') return 'bg-ctp-yellow/15 text-ctp-yellow'
  return 'bg-ctp-green/15 text-ctp-green'
}
function startTitleEdit() {
  titleDraft.value = props.title || ''
  editingTitle.value = true
}
function onTitleInput(e: Event) { titleDraft.value = (e.target as HTMLInputElement).value }
function commitTitleEdit() {
  if (!editingTitle.value) return
  editingTitle.value = false
  const t = titleDraft.value.trim()
  if (t && t !== props.title) emit('rename', t)
}

const _ACTIVE_TASK_STATUS = new Set(['running', 'waiting_input', 'pending_confirm'])
function reqActiveTask(reqId?: string) {
  if (!reqId) return null
  return (props.tasks || []).find((t: any) => (t.reqId || '') === reqId
    && _ACTIVE_TASK_STATUS.has(String(t.status || ''))) || null
}

/** 同需求是否已有 spec 消息卡(唯一宿主存在 → S5 提案卡让位, 实时/刷新同构)。 */
function hasSpecCardFor(reqId?: string) {
  if (!reqId) return false
  return props.turns.some((t: any) =>
    t.item?.type === 'spec' && t.item?.payload?.requirementId === reqId)
}

/** 规约版本更新后, 旧版卡 = 历史快照(cv-215): 同需求存在更高版本卡 → 本卡
 * 退役——不渲染执行按钮(防误点旧版启动), 默认收起仅作参考信息;
 * coding 上下文交接始终取台账最新规约(服务端 dispatch), 与消息卡无关。 */
function specSuperseded(m: any) {
  const rid = m.item?.payload?.requirementId
  const ver = Number(m.item?.payload?.ver || 0)
  if (!rid || !ver) return false
  return props.turns.some((t: any) =>
    t.item?.type === 'spec' && t.item?.payload?.requirementId === rid
    && Number(t.item?.payload?.ver || 0) > ver)
}

/** 版本徽标(未带 ver 的历史卡显示 v1 口径)。 */
function specVer(m: any) {
  return Number(m.item?.payload?.ver || 0) || 1
}

/** 需求卡渲染载荷(方案 A): spec 消息卡 = 唯一宿主, 提案数据(m.proposal,
 * attach/rehydrate 供给)降级为载荷。正文 = 五段 MD(与执行器指令同构:
 * 需求目标/方案/允许改动范围/禁止改动/验收标准——所见即所得), 不截断;
 * 兜底播报原文。active: 需求已有进行中任务(执行按钮禁用)。 */
// ── 信息卡收起/展开(统一状态源 useCardCollapse; 用户覆盖持久化 localStorage) ──
const { isCollapsed: cardIsCollapsed, toggle: cardToggle } = useCardCollapse()
/** 卡键: 消息 id 为稳定持久键(可选子键区分同消息多卡, 如 conventions 多条)。 */
function _cardKey(m: any, sub = '') {
  const base = String(m.item?.id || m.id || m.proposal?.id || m.item?.payload?.requirementId || '')
  return sub ? `${base}:${sub}` : base
}
function mCollapsed(m: any, auto = false, sub = '') {
  return cardIsCollapsed(_cardKey(m, sub), auto)
}
function toggleM(m: any, auto = false, sub = '') {
  cardToggle(_cardKey(m, sub), auto)
}
/** 需求卡: 旧版快照默认收起; 用户手动展开/收起后以手动为准(持久化)。 */
function specCardCollapsed(m: any) {
  return mCollapsed(m, specSuperseded(m))
}
function toggleSpecCard(m: any) {
  toggleM(m, specSuperseded(m))
}/** 取代本卡的新版本号(快照徽标用)。 */
function specSupersededVer(m: any) {
  const rid = m.item?.payload?.requirementId
  const ver = Number(m.item?.payload?.ver || 0)
  let max = ver
  for (const t of props.turns) {
    if (t.item?.type === 'spec' && t.item?.payload?.requirementId === rid) {
      max = Math.max(max, Number(t.item?.payload?.ver || 0))
    }
  }
  return max
}
function specCard(m: any) {
  // cv-215: 卡自包含规约载荷优先(本版全文——历史版本卡即历史快照);
  // 旧数据(无 spec 载荷)回落 m.proposal(台账当前版)。
  // 分节组装单源=services/spec-view(与正文规约草稿视图共用, cv-248)。
  const p = m.item?.payload?.spec || m.proposal || {}
  const active = reqActiveTask(m.item?.payload?.requirementId)
  return {
    ...assembleSpecView(p, String(m.content || '').slice(0, 60)),
    active: !!active,
    activeStatus: active ? String(active.status) : '',
  }
}

// ── 模型 chip: 随选随生效(下次执行; 进行中作业模型已固化) ──

  return {
    _ACTIVE_TASK_STATUS,
    _cardKey,
    commitTitleEdit,
    confirmMerge,
    editingTitle,
    feedBusyIdx,
    hasSpecCardFor,
    mCollapsed,
    mergeBusyIdx,
    mergedDone,
    onSpecApply,
    onTitleInput,
    openAssetRef,
    reqActiveTask,
    runMergePrecheck,
    specAppliedIdx,
    specBusyIdx,
    specCard,
    specCardCollapsed,
    specDraftIdx,
    specDraftView,
    specPayloadOf,
    specSuperseded,
    specSupersededVer,
    specVer,
    stageClass,
    startTitleEdit,
    titleDraft,
    toggleM,
    toggleSpecCard,
  }
}
