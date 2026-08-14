<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, ChevronDownIcon, ChevronRightIcon, ArrowPathIcon,
  SparklesIcon, CubeTransparentIcon, AdjustmentsHorizontalIcon, ServerStackIcon, Squares2X2Icon,
  ClipboardDocumentListIcon, ClipboardDocumentIcon, ScaleIcon, EyeIcon, TrashIcon,
} from '@heroicons/vue/24/outline'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import RequirementHistoryModal from '@/components/requirements/RequirementHistoryModal.vue'
import SemanticGraphView, { type GraphTabDef } from '@/components/assets/SemanticGraphView.vue'
import { chatStream, type KbAnalysisTurn } from '@/services/kb-analysis-agent'
import { semanticAssetService, type ExtractTaskMessage, type ExtractTaskStatus, type SemanticBatchResult, type SemanticPurgeResult, type SemanticStatsResult } from '@/services/semantic-asset-service'
import { kbAssetService } from '@/services/kb-assets'
import { requirementService } from '@/services/requirement-service'
import { useSplitPane } from '@/composables/useSplitPane'
import { useDiagramSkill } from '@/composables/useDiagramSkill'
import { useChatModel } from '@/composables/useChatModel'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import type { AssetDetail, ConversationDetail, SemanticAsset, SemanticAssetKind, SemanticAssetLevel } from '@/types'

const { t } = useI18n()

// ---- 对话模型(选择持久化到浏览器，刷新恢复或回退默认) ----
const { chatModelId, chatModels, loadChatModels, onChatModelChange } = useChatModel()

// ---- 左右栏分割(资产内容 | agent 对话) ----
const { splitPct, dragging, boxRef: splitBoxRef, onDown: onSplitPointerDown, onMove: onSplitPointerMove, onUp: onSplitPointerUp } = useSplitPane()
const turns = ref<KbAnalysisTurn[]>([])
const busy = ref(false)
const chatConvId = ref<string>('')
const historyOpen = ref(false)
const { diagramSkill, toggleDiagramSkill } = useDiagramSkill()

/** 从历史会话消息恢复 turns；返回 true 表示有可导入内容。 */
function applyConversation(conv: ConversationDetail): boolean {
  const msgs = (conv.messages ?? []).filter((m) => m.content?.trim())
  if (!msgs.length) return false
  turns.value = msgs.map((m) => ({ role: m.role, content: m.content, id: m.id }))
  chatConvId.value = conv.id
  return true
}

/** 导入指定历史会话(资产管理)。 */
async function importHistory(conv: ConversationDetail) {
  busy.value = true
  try {
    applyConversation(conv)
    historyOpen.value = false
  } finally {
    busy.value = false
  }
}

/** 对话流单条消息删除：本地移除 + 后端持久化删除(有 id 的已落库消息)。 */
async function onDeleteTurn(index: number) {
  const turn = turns.value[index]
  if (!turn) return
  const msgId = turn.id
  turns.value.splice(index, 1)
  if (msgId && chatConvId.value) {
    requirementService.deleteMessage(chatConvId.value, msgId).catch(() => {})
  }
}

// ---- 资产内容区 ----
type AssetTab = 'overview' | 'semantic' | 'component' | 'graph'
const tab = ref<AssetTab>('overview')
const kind = ref<SemanticAssetKind | ''>('')
const level = ref<SemanticAssetLevel | ''>('')
/** 语义资产 tab：组件层级(L0/L1)筛选。空 = 全部层级(按组件树展开)；L0/L1 = 以该层组件为树根。 */
const compLevelSel = ref<'all' | 'L0' | 'L1'>('all')
/** 语义图谱多资源 tab(从语义列表/组件列表打开，可并存)。 */
const graphTabs = ref<GraphTabDef[]>([])
const activeGraphTab = ref('')
/** 打开(或激活已存在的同名资源)图谱 tab；kind 相同时复用，避免重复。 */
function openGraphTab(kind: GraphTabDef['kind'], id: string, title: string) {
  const key = `${kind}:${id}`
  const existing = graphTabs.value.find((x) => x.id === key)
  if (existing) {
    activeGraphTab.value = existing.id
  } else {
    const def: GraphTabDef = { id: key, kind, title, compId: kind === 'comp' ? id : undefined, assetId: kind === 'asset' ? id : undefined }
    graphTabs.value.push(def)
    activeGraphTab.value = def.id
  }
  tab.value = 'graph'
  onSearch()
}
function closeGraphTab(id: string) {
  const i = graphTabs.value.findIndex((x) => x.id === id)
  if (i < 0) return
  graphTabs.value.splice(i, 1)
  if (activeGraphTab.value === id) {
    activeGraphTab.value = graphTabs.value[i]?.id ?? graphTabs.value[i - 1]?.id ?? ''
  }
}
const q = ref('')
const items = ref<SemanticAsset[]>([])
const comps = ref<AssetDetail[]>([])
const loading = ref(false)
const extracting = ref(false)
const reconciling = ref(false)
const statusCounts = ref<Record<string, number>>({})
const expanded = reactive<Record<string, boolean>>({})
/** 概览统计(总量/按类别/按粒度/状态)。 */
const overviewStats = ref<SemanticStatsResult | null>(null)
const purging = ref(false)

const kinds: { value: SemanticAssetKind; label: string }[] = [
  { value: 'entity', label: t('assetMgmt.kind.entity') },
  { value: 'contract', label: t('assetMgmt.kind.contract') },
  { value: 'state', label: t('assetMgmt.kind.state') },
  { value: 'rule', label: t('assetMgmt.kind.rule') },
  { value: 'process', label: t('assetMgmt.kind.process') },
  { value: 'decision', label: t('assetMgmt.kind.decision') },
]

const levels: { value: SemanticAssetLevel; label: string }[] = [
  { value: 'business', label: t('assetMgmt.level.business') },
  { value: 'logic', label: t('assetMgmt.level.logic') },
  { value: 'implementation', label: t('assetMgmt.level.implementation') },
]

const statusText = computed(() => {
  const c = statusCounts.value
  return `active ${c.active ?? 0} · stale ${c.stale ?? 0} · deleted ${c.deleted ?? 0}`
})

// ---- 组件归属映射 + 组件范围筛选 + 按组件分组 ----
const arch = useArchArchitectureStore()
const OTHER_KEY = '__other__'

/** 统一组件节点(树/归属映射用)。 */
interface CompNode { id: string; name: string; parentId?: string; owns: string[]; hierLevel?: string }

/** 组件目录(完整来源，跨 INCLUDE/CALL × L0/L1，与组件列表一致)。 */
const compCatalog = ref<AssetDetail[]>([])

async function loadCompCatalog() {
  try {
    compCatalog.value = await kbAssetService.searchComponents('')
  } catch {
    compCatalog.value = []
  }
}

/** 树来源：优先组件目录；目录为空(加载失败/降级)时回退架构模型快照；
 *  两者均空(如 KB 冷启动)时，从当前资产 scopeKey(comm-*) 兜底构建，保证筛选菜单不空。 */
const treeComps = computed<CompNode[]>(() => {
  if (compCatalog.value.length) {
    return compCatalog.value.map((c) => ({ id: c.assetId, name: c.name, parentId: c.parentId ?? undefined, owns: c.owns ?? [], hierLevel: c.hierLevel ?? undefined }))
  }
  if (arch.components.length) {
    return arch.components.map((c) => ({ id: c.id, name: c.name, parentId: c.parentId ?? undefined, owns: c.owns ?? [], hierLevel: (c as { hierLevel?: string }).hierLevel ?? undefined }))
  }
  const byId = new Map<string, CompNode>()
  for (const a of items.value) {
    const sk = a.scopeKey
    if (sk && sk.startsWith('comm-') && !byId.has(sk)) {
      byId.set(sk, { id: sk, name: sk, owns: [] })
    }
  }
  return [...byId.values()]
})

/** 组件 id → 组件节点(归属/展示用)。 */
const compById = computed<Map<string, CompNode>>(() => {
  const m = new Map<string, CompNode>()
  for (const c of treeComps.value) m.set(c.id, c)
  return m
})

/** 文件 → 组件 id(取首个归属组件的文件)。 */
const fileToComp = computed(() => {
  const m = new Map<string, string>()
  for (const c of treeComps.value) {
    for (const f of c.owns) {
      if (!m.has(f)) m.set(f, c.id)
    }
  }
  return m
})

/** 语义资产归属组件 id：优先资产自带 scopeKey(真实提取范围)；未命中组件
 *  → meta.scopes 多组件归属(INCLUDE/CALL 共享代码 / business 聚合)；
 *  → 按首个锚点文件反查；仍未命中则归「其它」。 */
function componentOf(a: SemanticAsset): string {
  const sk = a.scopeKey
  if (sk && compById.value.has(sk)) return sk
  const mscopes = a.meta?.scopes
  if (mscopes?.length) {
    for (const cid of mscopes) {
      if (compById.value.has(cid)) return cid
    }
  }
  const file = a.astRefs?.[0]?.file
  return (file && fileToComp.value.get(file)) || OTHER_KEY
}

/** 递归收集子组件 id。 */
function descendantsOf(id: string): string[] {
  const out: string[] = []
  const stack = [id]
  while (stack.length) {
    const cur = stack.pop()!
    for (const c of treeComps.value) {
      if (c.parentId === cur) {
        out.push(c.id)
        stack.push(c.id)
      }
    }
  }
  return out
}

function hasChildren(id: string): boolean {
  return treeComps.value.some((c) => c.parentId === id)
}

/** 范围筛选(空 = 全部)：组件 id + 「其它」。 */
const scopeSel = ref<string[]>([])
/** 组件树展开态(默认全部展开)。 */
const compOpen = reactive<Record<string, boolean>>({})
const filterOpen = ref(false)

function toggleComp(id: string) {
  const ids = [id, ...descendantsOf(id)]
  const sel = new Set(scopeSel.value)
  const on = sel.has(id)
  for (const i of ids) {
    if (on) sel.delete(i)
    else sel.add(i)
  }
  scopeSel.value = [...sel]
}

function toggleOther() {
  const sel = new Set(scopeSel.value)
  if (sel.has(OTHER_KEY)) sel.delete(OTHER_KEY)
  else sel.add(OTHER_KEY)
  scopeSel.value = [...sel]
}

function clearScope() {
  scopeSel.value = []
}

/** 范围筛选变化 → 回到第 1 页并按选中组件重新查询(服务端 scope 过滤)。 */
watch(scopeSel, () => {
  page.value = 1
  if (tab.value === 'semantic') loadSemantic()
})

function toggleOpen(id: string) {
  compOpen[id] = compOpen[id] !== false ? false : true
}

/** 组件树行(DFS，父在前子在后，含缩进深度)。 */
interface CompRow { comp: CompNode; depth: number }
const compRows = computed<CompRow[]>(() => {
  const rows: CompRow[] = []
  const walk = (parentId: string | undefined, depth: number) => {
    for (const c of treeComps.value) {
      if (c.parentId !== parentId) continue
      rows.push({ comp: c, depth })
      if (compOpen[c.id] !== false) walk(c.id, depth + 1)
    }
  }
  walk(undefined, 0)
  return rows
})

/** 组件资产 tab 树行：全部层级从根展开；选 L0/L1 时以该层组件为初始列表(可展开从属组件)。
 *  行对象 = 组件(AssetDetail) + depth(缩进层级)。 */
interface CompAssetRow extends AssetDetail { depth: number }
const compAssetRows = computed<CompAssetRow[]>(() => {
  const roots = compLevel.value === 'all'
    ? comps.value.filter((c) => !c.parentId)
    : comps.value.filter((c) => (c.hierLevel ?? '') === compLevel.value)
  const rows: CompAssetRow[] = []
  const walk = (parentId: string | undefined, depth: number) => {
    for (const c of comps.value) {
      if (c.parentId !== parentId) continue
      rows.push({ ...c, depth })
      if (compOpen[c.assetId] !== false) walk(c.assetId, depth + 1)
    }
  }
  for (const r of roots) {
    rows.push({ ...r, depth: 0 })
    if (compOpen[r.assetId] !== false) walk(r.assetId, 1)
  }
  return rows
})

interface SemanticGroup { key: string; name: string; depth: number; assets: SemanticAsset[]; hierLevel?: string }
/** 组件 id 层级映射(组件树 → L0/L1，供层级筛选)。 */
const compHierLevel = computed<Map<string, string>>(() => {
  const m = new Map<string, string>()
  for (const c of treeComps.value) {
    if (c.hierLevel) m.set(c.id, c.hierLevel)
  }
  return m
})
/** 资产 tab 组件树行：全部层级从根展开；选 L0/L1 时以该层组件为初始列表(可展开更低从属组件)。 */
const semanticGroups = computed<SemanticGroup[]>(() => {
  const sel = new Set(scopeSel.value)
  const all = sel.size === 0
  const byComp = new Map<string, SemanticAsset[]>()
  const other: SemanticAsset[] = []
  for (const a of items.value) {
    const cid = componentOf(a)
    if (cid === OTHER_KEY) {
      other.push(a)
    } else {
      if (!byComp.has(cid)) byComp.set(cid, [])
      byComp.get(cid)!.push(a)
    }
  }
  const groups: SemanticGroup[] = []
  // 树根：全部 → 无父节点；选层级 → 该层级组件(即便有父，也从这层开始作为初始列表)。
  const roots = compLevelSel.value === 'all'
    ? treeComps.value.filter((c) => !c.parentId)
    : treeComps.value.filter((c) => (c.hierLevel ?? compHierLevel.value.get(c.id)) === compLevelSel.value)
  const walk = (parentId: string | undefined, depth: number) => {
    for (const c of treeComps.value) {
      if (c.parentId !== parentId) continue
      if (all || sel.has(c.id)) {
        const assets = byComp.get(c.id)
        const hasChild = treeComps.value.some((x) => x.parentId === c.id)
        // 有资产或(展开态下)有下级组件时才渲染该节点
        if (assets?.length || (hasChild && compOpen[c.id] !== false)) {
          groups.push({ key: c.id, name: c.name, depth, assets: assets ?? [], hierLevel: c.hierLevel })
        }
      }
      if (compOpen[c.id] !== false) walk(c.id, depth + 1)
    }
  }
  for (const r of roots) {
    groups.push({ key: r.id, name: r.name, depth: 0, assets: byComp.get(r.id) ?? [], hierLevel: r.hierLevel })
    if (compOpen[r.id] !== false) walk(r.id, 1)
  }
  if (other.length && (all || sel.has(OTHER_KEY))) {
    groups.push({ key: OTHER_KEY, name: t('assetMgmt.other'), depth: 0, assets: other })
  }
  return groups
})

const scopeSummary = computed(() => {
  if (!scopeSel.value.length) return t('assetMgmt.scopeAll')
  const n = semanticGroups.value.reduce((s, g) => s + g.assets.length, 0)
  return `${n}/${items.value.length}`
})

/** 当前筛选的 scope 请求参数(组件 id + 「其它」哨兵)；空=全部。 */
function scopeParams(): string[] | undefined {
  if (!scopeSel.value.length) return undefined
  const out = [...scopeSel.value]
  return out
}

async function loadSemantic() {
  loading.value = true
  try {
    const r = await semanticAssetService.searchPage(q.value, kind.value || undefined, { limit: PAGE_SIZE, offset: (page.value - 1) * PAGE_SIZE, scope: scopeParams(), level: level.value || undefined })
    items.value = r.items
    total.value = r.total
  } finally {
    loading.value = false
  }
}

async function loadComponents() {
  loading.value = true
  try {
    // compLevel(L0/L1) 仅作树起点筛选(客户端)，需拉全量组件才能展开从属层级，
    // 故不传给后端；compType(INCLUDE/CALL) 是真实口径分区，保留后端过滤。
    comps.value = await kbAssetService.searchComponents(q.value, {
      type: compType.value === 'all' ? undefined : compType.value,
    })
  } finally {
    loading.value = false
  }
}

/** 概览统计：语义资产总量/类别/粒度/状态。 */
async function loadOverview() {
  try {
    overviewStats.value = await semanticAssetService.stats()
  } catch {
    overviewStats.value = null
  }
}

/** 清理确认弹窗状态(先 dry-run 展示影响范围，确认后再真正删除)。 */
const purgeOpen = ref(false)
const purgeResult = ref<SemanticPurgeResult | null>(null)
const purgeBusy = ref(false)

/** 触发清理：先 dry-run 计算影响范围(需求池引用 + 未完成任务)并弹窗确认。 */
async function runPurge() {
  if (purging.value || purgeBusy.value) return
  purging.value = true
  try {
    const res = await semanticAssetService.purge({ staleDays: 7 })
    purgeResult.value = res
    purgeOpen.value = true
  } catch (err: any) {
    turns.value.push({ role: 'assistant', content: `✘ 影响范围计算失败：${err?.message || err}` })
  } finally {
    purging.value = false
  }
}

/** 确认清理：真正物理删除 stale/deleted 行，并把受影响需求/任务标记为需重新生成方案。 */
async function confirmPurge() {
  if (purgeBusy.value) return
  purgeBusy.value = true
  try {
    const res = await semanticAssetService.purge({ staleDays: 7, confirm: true })
    const impact = res.impact
    turns.value.push({
      role: 'assistant',
      content: [
        `🧹 已物理删除 ${res.purged} 条 stale/deleted 语义资产。`,
        impact.reqCount ? `受影响需求 ${impact.reqCount} 条（已标记需重新生成方案）。` : '',
        impact.taskCount ? `受影响未完成任务 ${impact.taskCount} 个（已标记需重新生成方案）。` : '',
      ].filter(Boolean).join(' '),
    })
    await Promise.all([loadOverview(), refreshStatus()])
    purgeOpen.value = false
  } catch (err: any) {
    turns.value.push({ role: 'assistant', content: `✘ 清理失败：${err?.message || err}` })
  } finally {
    purgeBusy.value = false
  }
}

function cancelPurge() {
  purgeOpen.value = false
  purgeResult.value = null
}

// ---- 组件 tab：类型(INCLUDE/CALL) + 层级(L0/L1) 筛选 ----
const compType = ref<'all' | 'INCLUDE' | 'CALL'>('all')
const compLevel = ref<'all' | 'L0' | 'L1'>('all')

// ---- 组件 tab：概要展开(KB) / KB viewer / 单组件提取 ----
const compExpanded = reactive<Record<string, boolean>>({})
const compDetails = reactive<Record<string, AssetDetail>>({})
const compDetailLoading = reactive<Record<string, boolean>>({})
const compDetailMiss = reactive<Record<string, boolean>>({})
const compExtracting = reactive<Record<string, boolean>>({})

// ---- 提取语义资产：组件复选模式(右上角按钮 → 切到组件 tab 勾选后提交) ----
const extractMode = ref(false)
const extractSelected = ref<string[]>([])
/** 提取任务(服务端后台执行，刷新不中断)：当前任务 id + 轮询句柄 + 已同步消息游标。 */
const extractTaskId = ref<string>('')
const extractPollTimer = ref<ReturnType<typeof setInterval> | null>(null)
const extractMsgSeen = ref<Set<string>>(new Set())
const extractRunning = ref(false)

function enterExtractMode() {
  tab.value = 'component'
  extractMode.value = true
  extractSelected.value = []
  loadComponents()
}

function exitExtractMode() {
  extractMode.value = false
  extractSelected.value = []
}

function toggleExtractSelect(id: string) {
  const i = extractSelected.value.indexOf(id)
  if (i >= 0) extractSelected.value.splice(i, 1)
  else extractSelected.value.push(id)
}

function selectAllExtract() {
  extractSelected.value = comps.value.map((c) => c.assetId)
}

function invertExtract() {
  const all = comps.value.map((c) => c.assetId)
  const sel = new Set(extractSelected.value)
  extractSelected.value = all.filter((id) => !sel.has(id))
}

/** 右上角「提取语义资产」：未进入复选 → 切到组件 tab 并进入复选；已进入 → 提交所选组件提取。 */
function handleExtract() {
  if (extractRunning.value) return
  if (!extractMode.value) {
    enterExtractMode()
    return
  }
  if (!extractSelected.value.length) return
  submitExtract()
}

/** 向资产管理对话同步一条提取进度消息(去重：按消息 id)。 */
function syncExtractMsg(m: ExtractTaskMessage) {
  if (extractMsgSeen.value.has(m.id)) return
  extractMsgSeen.value.add(m.id)
  turns.value.push({ role: (m.role as 'user' | 'assistant') || 'assistant', content: m.content, id: m.id })
}

/** 停止任务轮询(清理定时器)。 */
function stopExtractPoll() {
  if (extractPollTimer.value) {
    clearInterval(extractPollTimer.value)
    extractPollTimer.value = null
  }
  extractRunning.value = false
}

/** 复位全部组件提取按钮的进行态(任务结束后释放)。 */
function resetCompExtracting() {
  for (const k of Object.keys(compExtracting)) compExtracting[k] = false
}

/** 消费一次任务快照：同步新消息；任务结束 → 停止轮询并刷新。 */
function consumeExtractTask(st: ExtractTaskStatus) {
  if (!st.found || !st.id) {
    stopExtractPoll()
    resetCompExtracting()
    return
  }
  for (const m of st.messages ?? []) syncExtractMsg(m)
  if (!st.running) {
    stopExtractPoll()
    resetCompExtracting()
    extractTaskId.value = ''
    Promise.all([loadSemantic(), refreshStatus()]).then(() => {
      if (extractMode.value) exitExtractMode()
    })
  }
}

/** 轮询任务直到结束(服务端后台执行，浏览器刷新不中断)。 */
function pollExtractTask(taskId: string) {
  stopExtractPoll()
  extractTaskId.value = taskId
  extractRunning.value = true
  const tick = async () => {
    try {
      const st = await semanticAssetService.extractTaskStatus(taskId)
      consumeExtractTask(st)
    } catch (err: any) {
      console.warn('[asset-mgmt] extract task poll failed:', err)
    }
  }
  void tick()
  extractPollTimer.value = setInterval(() => void tick(), 1200)
}

/** 提交：创建服务端后台提取任务，轮询并把进度消息同步到对话消息栏。
 *  已有任务进行中 → 忽略重复点击，避免重复激活任务。 */
async function submitExtract() {
  if (extractRunning.value || extracting.value) return
  const ids = extractSelected.value
  if (!ids.length) return
  extracting.value = true
  try {
    const names = ids
      .map((id) => comps.value.find((c) => c.assetId === id)?.name ?? id)
      .join('、')
    turns.value.push({
      role: 'assistant',
      content: `▶ 开始提取语义资产，组件：${names}（任务在服务端执行，刷新页面不中断）。`,
    })
    const { taskId } = await semanticAssetService.startExtractTask(ids, {
      kinds: kinds.map((k) => k.value),
      modelId: chatModelId.value || undefined,
    })
    pollExtractTask(taskId)
  } catch (err: any) {
    turns.value.push({ role: 'assistant', content: `✘ 提取任务创建失败：${err?.message || err}` })
    exitExtractMode()
  } finally {
    extracting.value = false
  }
}

/** 刷新后恢复：读取最近一次提取任务，若仍在运行则恢复轮询并同步历史消息。 */
async function restoreExtractTask() {
  try {
    const st = await semanticAssetService.latestExtractTask()
    if (!st || !st.found || !st.id) return
    extractMsgSeen.value = new Set((st.messages ?? []).map((m) => m.id))
    for (const m of st.messages ?? []) syncExtractMsg(m)
    if (st.running) {
      pollExtractTask(st.id)
    }
  } catch (err: any) {
    console.warn('[asset-mgmt] restore extract task failed:', err)
  }
}

async function toggleCompDetail(c: AssetDetail) {
  const id = c.assetId
  if (compExpanded[id]) {
    compExpanded[id] = false
    return
  }
  compExpanded[id] = true
  if (compDetails[id] || compDetailLoading[id]) return
  compDetailLoading[id] = true
  compDetailMiss[id] = false
  try {
    const d = await kbAssetService.detail(id)
    if (d) compDetails[id] = d
    else compDetailMiss[id] = true
  } catch {
    compDetailMiss[id] = true
  } finally {
    compDetailLoading[id] = false
  }
}

/** 在知识库 viewer 打开组件文档(新标签页，URL 与 ComponentPickerModal 一致)。 */
function openKB(c: AssetDetail) {
  const taskId = c.taskId ?? ''
  const url = `/doc?taskId=${encodeURIComponent(taskId)}&docId=${encodeURIComponent(`overall-${taskId}`)}&communityId=${encodeURIComponent(c.assetId)}&edgeType=${encodeURIComponent(c.edgeType ?? 'INCLUDE')}`
  window.open(url, '_blank')
}

/** 提取单个组件的语义资产(comm 范围，统一走服务端后台任务)。
 *  任务进行中(existing task running 或该组件已在提取) → 忽略重复点击，避免重复激活任务。 */
async function extractComp(c: AssetDetail) {
  if (extractRunning.value || compExtracting[c.assetId]) return
  compExtracting[c.assetId] = true
  try {
    turns.value.push({ role: 'assistant', content: `▶ 开始提取组件「${c.name}」的语义资产…` })
    const { taskId } = await semanticAssetService.startExtractTask([c.assetId], {
      kinds: kinds.map((k) => k.value),
      modelId: chatModelId.value || undefined,
    })
    pollExtractTask(taskId)
  } catch (err: any) {
    compExtracting[c.assetId] = false
    turns.value.push({ role: 'assistant', content: `✘ 组件「${c.name}」提取任务创建失败：${err?.message || err}` })
    console.warn('[asset-mgmt] extract component failed:', err)
  }
}

// ---- 语义资产批量管理(选定组件范围) ----
const batchOpen = ref(false)
const batchRunning = ref(false)
const batchAction = ref<'clear' | ''>('')
const batchLast = ref('')
/** clear 前的 dry-run 影响预览(需求池/未完成任务)。 */
const batchPreview = ref<SemanticBatchResult | null>(null)

/** 当前组件范围：选中组件 id(空=全部) + 是否含「其它」。 */
function targetScope() {
  const compIds = scopeSel.value.filter((id) => id !== OTHER_KEY)
  const includeOther = scopeSel.value.length === 0 || scopeSel.value.includes(OTHER_KEY)
  return { compIds, includeOther }
}

async function runBatch(action: 'clear') {
  if (batchRunning.value) return
  if (action === 'clear' && batchAction.value !== 'clear') {
    batchAction.value = 'clear'
    return
  }
  const { compIds, includeOther } = targetScope()
  // 清除 = 物理删除：确认前先 dry-run 预览对需求池/任务的影响范围。
  if (action === 'clear' && !batchPreview.value) {
    batchRunning.value = true
    try {
      const scope = scopeParams()
      const res = await semanticAssetService.batchManage(action, compIds, {
        includeOther, scope, dryRun: true,
      })
      batchPreview.value = res
    } catch {
      batchPreview.value = null
      batchLast.value = t('assetMgmt.batchFailed')
    } finally {
      batchRunning.value = false
    }
    return
  }
  batchRunning.value = true
  batchAction.value = ''
  try {
    // 与 search 的 scope 语义一致：空=全部；['__other__']=仅其它；组件 id 列表=指定范围。
    const scope = scopeParams()
    const res = await semanticAssetService.batchManage(action, compIds, {
      includeOther,
      scope,
      kinds: kinds.map((k) => k.value),
      modelId: chatModelId.value || undefined,
    })
    batchLast.value = t('assetMgmt.batchDone', { action: t(`assetMgmt.batchAction.${action}`), n: res.count })
    await Promise.all([loadSemantic(), refreshStatus()])
  } catch {
    batchLast.value = t('assetMgmt.batchFailed')
  } finally {
    batchRunning.value = false
    batchPreview.value = null
  }
}

async function refreshStatus() {
  try {
    const s = await semanticAssetService.status()
    statusCounts.value = s.counts
  } catch {
    /* ignore */
  }
}

async function reconcile() {
  reconciling.value = true
  try {
    await semanticAssetService.reconcile(true)
    await Promise.all([loadSemantic(), refreshStatus()])
  } finally {
    reconciling.value = false
  }
}

async function refreshOne(a: SemanticAsset) {
  try {
    const res = await semanticAssetService.refreshAsset(a.id)
    if (res.asset) {
      const i = items.value.findIndex((x) => x.id === a.id)
      if (i >= 0) items.value[i] = { ...items.value[i], ...res.asset }
    } else if (res.status === 'deleted') {
      const i = items.value.findIndex((x) => x.id === a.id)
      if (i >= 0) items.value[i] = { ...items.value[i], status: 'deleted', needsUpdate: 1 }
    }
    await refreshStatus()
  } catch (err: any) {
    console.warn('[asset-mgmt] refresh failed:', err)
  }
}

function usable(a: SemanticAsset): boolean {
  return a.status !== 'stale' && a.status !== 'deleted' && !a.needsUpdate
}

function toggle(id: string) {
  expanded[id] = !expanded[id]
}

function kindIcon(k: SemanticAsset['kind']) {
  if (k === 'process') return BoltIcon
  if (k === 'decision') return AdjustmentsHorizontalIcon
  if (k === 'contract') return ServerStackIcon
  if (k === 'state') return AdjustmentsHorizontalIcon
  return CubeTransparentIcon
}

/** 复制到剪贴板；不可用时降级 execCommand。 */
async function copyText(text: string): Promise<boolean> {
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

async function copyAsset(a: SemanticAsset) {
  const lines = [`${a.name} (${a.kind})`, `ID: ${a.id}`, a.desc]
  if (a.astRefs?.length) {
    lines.push('')
    lines.push(...a.astRefs.slice(0, 10).map((r) => `${r.file}:L${r.startLine}-L${r.endLine} ${r.symbol}`))
  }
  await copyText(lines.join('\n'))
}

// ---- 对话区：引用资产 → agent 确认 ----
function askAgent(text: string) {
  if (busy.value || !text.trim()) return
  turns.value.push({ role: 'user', content: text })
  const idx = turns.value.push({ role: 'assistant', content: '' }) - 1
  busy.value = true
  chatStream([{ role: 'user', content: text }], {
    conversationId: chatConvId.value || undefined,
    kind: 'asset',
    title: t('assetMgmt.chatTitle'),
    modelId: chatModelId.value || undefined,
    diagramSkill: diagramSkill.value,
  }, (ev) => {
    if (ev.conversationId) chatConvId.value = ev.conversationId
    if (ev.type === 'chunk') {
      turns.value[idx].content += ev.delta ?? ''
    } else if (ev.type === 'reasoning') {
      turns.value[idx].reasoning = (turns.value[idx].reasoning ?? '') + (ev.delta ?? '')
    } else if (ev.type === 'done') {
      turns.value[idx].content = ev.content ?? turns.value[idx].content
    } else if (ev.type === 'error') {
      turns.value[idx].content = ev.message || t('requirement.chat.fallback')
    }
  }).finally(() => { busy.value = false })
}

async function onSend(text: string) {
  if (busy.value) return
  turns.value.push({ role: 'user', content: text })
  const idx = turns.value.push({ role: 'assistant', content: '' }) - 1
  busy.value = true
  try {
    const msgs = turns.value.slice(0, -1).map((t) => ({ role: t.role, content: t.content }))
    await chatStream(msgs, {
      conversationId: chatConvId.value || undefined,
      kind: 'asset',
      title: t('assetMgmt.chatTitle'),
      modelId: chatModelId.value || undefined,
      diagramSkill: diagramSkill.value,
    }, (ev) => {
      if (ev.conversationId) chatConvId.value = ev.conversationId
      if (ev.type === 'chat_start') {
        if (ev.userMessageId) turns.value[idx - 1].id = ev.userMessageId
      } else if (ev.type === 'chunk') {
        turns.value[idx].content += ev.delta ?? ''
      } else if (ev.type === 'reasoning') {
        turns.value[idx].reasoning = (turns.value[idx].reasoning ?? '') + (ev.delta ?? '')
      } else if (ev.type === 'done') {
        turns.value[idx].content = ev.content ?? turns.value[idx].content
        if (ev.messageId) turns.value[idx].id = ev.messageId
      } else if (ev.type === 'error') {
        turns.value[idx].content = ev.message || t('requirement.chat.fallback')
      }
    })
  } catch (err: any) {
    turns.value[idx].content = err?.message || t('requirement.chat.fallback')
  } finally {
    busy.value = false
  }
}

function onExtractAssets() {
  if (busy.value) return
  const idx = turns.value.push({ role: 'assistant', content: '' }) - 1
  busy.value = true
  semanticAssetService.extractAll(kinds.map((k) => k.value), { modelId: chatModelId.value || undefined })
    .then(async (res) => {
      const assets = res.assets ?? []
      turns.value[idx].content = assets.length
        ? `${t('requirement.chat.semanticExtracted')}${res.count ?? assets.length}${t('requirement.chat.semanticExtractedTail')}`
        : t('requirement.chat.semanticEmpty')
      turns.value[idx].assets = assets
      await Promise.all([loadSemantic(), refreshStatus()])
    })
    .catch(() => { turns.value[idx].content = t('requirement.chat.semanticFailed') })
    .finally(() => { busy.value = false })
}

function onRefreshAsset(assetId: string) {
  refreshOne(items.value.find((x) => x.id === assetId) as SemanticAsset).catch(() => {})
}

function referenceAsset(a: SemanticAsset) {
  const anchor = a.astRefs?.[0]
  const pos = anchor ? `${anchor.file}:L${anchor.startLine}-L${anchor.endLine}` : ''
  askAgent(t('assetMgmt.referencePrompt', { name: a.name, id: a.id, kind: t(`assetMgmt.kind.${a.kind}`), pos }))
}

function onSearch() {
  if (tab.value === 'graph') return
  if (tab.value === 'overview') {
    loadOverview()
  } else if (tab.value === 'semantic') {
    page.value = 1
    loadSemantic()
  } else {
    loadComponents()
  }
}

// ---- 分页(数据资产每页 ≤100，超出翻页) ----
const PAGE_SIZE = 100
const page = ref(1)
const total = ref(0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

function gotoPage(p: number) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  loadSemantic()
}

onMounted(async () => {
  await loadChatModels()
  await Promise.all([loadCompCatalog(), loadOverview(), loadSemantic(), refreshStatus()])
  turns.value.push({ role: 'assistant', content: t('assetMgmt.welcome') })
  await restoreExtractTask()
})

onUnmounted(() => stopExtractPoll())
</script>

<template>
  <div class="h-full flex flex-col min-h-0">
    <div class="shrink-0 px-5 pt-5">
      <div class="flex items-center gap-3">
        <h2 class="text-sm font-semibold text-ctp-text">
          {{ t('assetMgmt.title') }}
        </h2>
        <div class="flex items-center gap-1">
          <button
            v-for="tb in [{ id: 'overview' as const, label: t('assetMgmt.tab.overview') }, { id: 'semantic' as const, label: t('assetMgmt.tab.semantic') }, { id: 'component' as const, label: t('assetMgmt.tab.component') }, { id: 'graph' as const, label: t('assetMgmt.tab.graph') }]"
            :key="tb.id"
            class="btn btn-xs"
            :class="tab === tb.id ? 'btn-blue' : 'btn-ghost'"
            @click="tab = tb.id; if (tb.id !== 'component') exitExtractMode(); onSearch()"
          >
            {{ tb.label }}
          </button>
        </div>
        <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[10px]">{{ statusText }}</span>
        <div class="flex-1" />
        <button
          class="btn btn-sm btn-ghost"
          @click="historyOpen = true"
        >
          <ClipboardDocumentListIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.historyButton') }}
        </button>
        <button
          class="btn btn-sm btn-ghost"
          :disabled="reconciling"
          @click="reconcile"
        >
          <ArrowPathIcon
            class="w-3.5 h-3.5"
            :class="reconciling ? 'animate-spin' : ''"
          />{{ reconciling ? t('assetMgmt.reconciling') : t('assetMgmt.reconcile') }}
        </button>
        <button
          class="btn btn-sm btn-primary"
          :disabled="extracting || extractRunning"
          @click="handleExtract"
        >
          <SparklesIcon class="w-3.5 h-3.5" />{{ extracting || extractRunning ? t('assetMgmt.extracting') : t('assetMgmt.extractSemantic') }}
        </button>
      </div>
    </div>

    <div
      ref="splitBoxRef"
      class="flex-1 min-h-0 flex px-5 pb-5 pt-4"
    >
      <!-- 左：资产管理内容区 -->
      <div
        class="min-h-0 panel overflow-hidden flex flex-col"
        :style="{ width: splitPct + '%' }"
      >
        <div class="panel-header shrink-0 relative !justify-start gap-1.5">
          <span class="flex items-center gap-2">
            <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-mauve" />{{ tab === 'overview' ? t('assetMgmt.tab.overview') : tab === 'semantic' ? t('assetMgmt.tab.semantic') : tab === 'graph' ? t('assetMgmt.tab.graph') : t('assetMgmt.tab.component') }}
          </span>
          <input
            v-if="tab !== 'graph' && tab !== 'overview'"
            v-model="q"
            class="input !py-0.5 !px-2 !text-[11px] w-44 font-mono ml-3"
            :placeholder="t('assetMgmt.searchPlaceholder')"
            @keydown.enter="onSearch"
          >
          <select
            v-if="tab === 'component'"
            v-model="compType"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
            :title="t('assetMgmt.compType')"
            @change="onSearch"
          >
            <option value="all">{{ t('assetMgmt.compTypeAll') }}</option>
            <option value="INCLUDE">{{ t('assetMgmt.compTypeInclude') }}</option>
            <option value="CALL">{{ t('assetMgmt.compTypeCall') }}</option>
          </select>
          <select
            v-if="tab === 'component'"
            v-model="compLevel"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
            :title="t('assetMgmt.compLevel')"
            @change="onSearch"
          >
            <option value="all">{{ t('assetMgmt.compLevelAll') }}</option>
            <option value="L0">L0</option>
            <option value="L1">L1</option>
          </select>
          <select
            v-if="tab === 'semantic'"
            v-model="kind"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
            @change="onSearch"
          >
            <option value="">{{ t('assetMgmt.allKinds') }}</option>
            <option
              v-for="k in kinds"
              :key="k.value"
              :value="k.value"
            >{{ k.label }}</option>
          </select>
          <select
            v-if="tab === 'semantic'"
            v-model="level"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
            @change="onSearch"
          >
            <option value="">{{ t('assetMgmt.allLevels') }}</option>
            <option
              v-for="l in levels"
              :key="l.value"
              :value="l.value"
            >{{ l.label }}</option>
          </select>
          <select
            v-if="tab === 'semantic'"
            v-model="compLevelSel"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
          >
            <option value="all">{{ t('assetMgmt.allCompLevels') }}</option>
            <option value="L0">L0</option>
            <option value="L1">L1</option>
          </select>
          <button
            class="btn btn-xs btn-ghost"
            :disabled="loading"
            @click="onSearch"
          >
            <ArrowPathIcon class="w-3 h-3" />{{ t('assetMgmt.search') }}
          </button>
          <template v-if="tab === 'component'">
            <button
              v-if="!extractMode"
              class="btn btn-xs btn-blue"
              :disabled="!comps.length"
              @click="enterExtractMode"
            >
              <SparklesIcon class="w-3 h-3" />{{ t('assetMgmt.enterExtractMode') }}
            </button>
            <template v-else>
              <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ extractSelected.length }}/{{ comps.length }}</span>
              <button
                class="btn btn-xs btn-ghost"
                :disabled="extractRunning"
                @click="selectAllExtract"
              >{{ t('assetMgmt.selectAll') }}</button>
              <button
                class="btn btn-xs btn-ghost"
                :disabled="extractRunning"
                @click="invertExtract"
              >{{ t('assetMgmt.invert') }}</button>
              <button
                class="btn btn-xs btn-ghost"
                :disabled="extractRunning"
                @click="exitExtractMode"
              >{{ t('assetMgmt.exitExtractMode') }}</button>
            </template>
          </template>
          <template v-if="tab === 'semantic'">
            <div class="inline-flex items-center rounded-md border border-ctp-surface1 bg-ctp-mantle/60 overflow-hidden" :title="t('assetMgmt.scopeGroupHint')">
              <span class="chip !border-0 !rounded-none bg-transparent text-ctp-subtext0 font-mono text-[9px] px-2">{{ scopeSummary }}</span>
              <button
                class="btn btn-xs !rounded-none !border-l !border-ctp-surface1"
                :class="filterOpen ? 'btn-blue' : 'btn-ghost'"
                @click="filterOpen = !filterOpen; batchOpen = false"
              >
                <AdjustmentsHorizontalIcon class="w-3 h-3" />{{ t('assetMgmt.filter') }}
              </button>
            </div>
            <button
              class="btn btn-xs"
              :class="batchOpen ? 'btn-blue' : 'btn-ghost'"
              :title="t('assetMgmt.batch')"
              @click="batchOpen = !batchOpen; filterOpen = false"
            >
              <TrashIcon class="w-3 h-3" />{{ t('assetMgmt.batch') }}
            </button>

            <!-- 点击浮层：批量清除(物理删除 选定组件范围) -->
            <div
              v-if="batchOpen"
              class="absolute right-0 top-full mt-1 z-30 w-72 max-w-[90vw] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-2.5 space-y-2"
            >
              <div class="flex items-center justify-between">
                <span class="text-[10px] text-ctp-overlay1">{{ t('assetMgmt.batchHint') }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ scopeSummary }}</span>
              </div>
              <div class="flex items-center gap-1 pt-1">
                <button
                  class="btn btn-xs"
                  :class="batchAction === 'clear' ? 'btn-red' : 'btn-ghost'"
                  :disabled="batchRunning"
                  @click="runBatch('clear')"
                >
                  <TrashIcon class="w-3 h-3" />{{ t('assetMgmt.batchClear') }}
                </button>
              </div>
              <div
                v-if="batchAction === 'clear'"
                class="border-t border-ctp-surface0 pt-1.5 space-y-1.5"
              >
                <p class="text-[10px] text-ctp-red">{{ t('assetMgmt.batchConfirmClear') }}</p>
                <div
                  v-if="batchPreview"
                  class="space-y-1"
                >
                  <p class="text-[10px] text-ctp-subtext1">
                    {{ t('assetMgmt.batchClearImpact', {
                      candidates: batchPreview.count,
                      reqCount: batchPreview.impact?.reqCount ?? 0,
                      taskCount: batchPreview.impact?.taskCount ?? 0,
                    }) }}
                  </p>
                  <div
                    v-if="batchPreview.impact?.requirements?.length"
                    class="text-[9px] text-ctp-peach"
                  >
                    {{ t('assetMgmt.purgeConfirm.reqTitle', { n: batchPreview.impact.reqCount }) }}
                    <div class="flex flex-wrap gap-1 pt-0.5">
                      <span
                        v-for="r in batchPreview.impact.requirements"
                        :key="r.id"
                        class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1"
                      >{{ r.id }} · {{ r.title }}</span>
                    </div>
                  </div>
                  <div
                    v-if="batchPreview.impact?.tasks?.length"
                    class="text-[9px] text-ctp-blue"
                  >
                    {{ t('assetMgmt.purgeConfirm.taskTitle', { n: batchPreview.impact.taskCount }) }}
                    <div class="flex flex-wrap gap-1 pt-0.5">
                      <span
                        v-for="t in batchPreview.impact.tasks"
                        :key="t.id"
                        class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1"
                      >{{ t.id }} · {{ t.title }}</span>
                    </div>
                  </div>
                  <p
                    v-if="!batchPreview.impact?.requirements?.length && !batchPreview.impact?.tasks?.length"
                    class="text-[9px] text-ctp-green"
                  >{{ t('assetMgmt.purgeConfirm.noImpact') }}</p>
                </div>
                <div class="flex items-center gap-1">
                  <button
                    class="btn btn-xs btn-red"
                    :disabled="batchRunning"
                    @click="runBatch('clear')"
                  >{{ t('assetMgmt.batchConfirm') }}</button>
                  <button
                    class="btn btn-xs btn-ghost"
                    @click="batchAction = ''; batchPreview = null"
                  >{{ t('assetMgmt.batchCancel') }}</button>
                </div>
              </div>
              <div
                v-if="batchRunning"
                class="text-[10px] text-ctp-overlay1"
              >{{ t('assetMgmt.batchRunning') }}</div>
              <div
                v-if="batchLast"
                class="text-[10px] text-ctp-subtext1"
              >{{ batchLast }}</div>
            </div>
            <div
              v-if="batchOpen"
              class="fixed inset-0 z-20"
              @click="batchOpen = false"
            />

            <!-- 点击浮层：组件范围筛选 -->
            <div
              v-if="filterOpen"
              class="absolute right-0 top-full mt-1 z-30 w-80 max-w-[90vw] rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl p-2.5 space-y-2"
            >
              <div class="flex items-center justify-between">
                <span class="text-[10px] text-ctp-overlay1">{{ t('assetMgmt.compScope') }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ scopeSummary }}</span>
              </div>
              <div class="max-h-40 overflow-auto space-y-0.5">
                <div
                  v-for="r in compRows"
                  :key="r.comp.id"
                  class="flex items-center gap-1.5 min-w-0"
                  :style="{ paddingLeft: (r.depth * 14) + 'px' }"
                >
                  <button
                    v-if="hasChildren(r.comp.id)"
                    class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                    @click="toggleOpen(r.comp.id)"
                  >
                    <ChevronDownIcon
                      v-if="compOpen[r.comp.id] !== false"
                      class="w-3 h-3"
                    />
                    <ChevronRightIcon
                      v-else
                      class="w-3 h-3"
                    />
                  </button>
                  <span
                    v-else
                    class="w-4 shrink-0"
                  />
                  <input
                    type="checkbox"
                    class="accent-ctp-blue shrink-0"
                    :checked="scopeSel.includes(r.comp.id)"
                    @change="toggleComp(r.comp.id)"
                  >
                  <span class="text-[11px] text-ctp-subtext1 truncate">{{ r.comp.name }}</span>
                </div>
                <div class="flex items-center gap-1.5 min-w-0 pt-0.5">
                  <span class="w-4 shrink-0" />
                  <input
                    type="checkbox"
                    class="accent-ctp-mauve shrink-0"
                    :checked="scopeSel.includes(OTHER_KEY)"
                    @change="toggleOther"
                  >
                  <span class="text-[11px] text-ctp-subtext1">{{ t('assetMgmt.other') }}</span>
                  <span class="text-[9px] text-ctp-overlay0 truncate">{{ t('assetMgmt.otherDesc') }}</span>
                </div>
              </div>
              <div class="flex items-center justify-between border-t border-ctp-surface0 pt-1.5">
                <span class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.scopeHint') }}</span>
                <button
                  class="btn btn-xs btn-ghost"
                  @click="clearScope"
                >{{ t('assetMgmt.clearScope') }}</button>
              </div>
            </div>

            <!-- 点击浮层外关闭 -->
            <div
              v-if="filterOpen"
              class="fixed inset-0 z-20"
              @click="filterOpen = false"
            />
          </template>
        </div>

        <!-- 语义层图谱(多资源 tab，从语义/组件列表打开) -->
        <div
          v-if="tab === 'graph'"
          class="flex-1 min-h-0 overflow-hidden flex flex-col"
        >
          <div
            v-if="!graphTabs.length"
            class="flex-1 min-h-0 flex items-center justify-center text-xs text-ctp-overlay0"
          >
            {{ t('assetMgmt.graph.noTab') }}
          </div>
          <template v-else>
            <div class="shrink-0 flex items-stretch border-b border-ctp-surface1 px-1 pt-1 overflow-x-auto">
              <button
                v-for="gt in graphTabs"
                :key="gt.id"
                class="group relative flex items-center gap-1.5 max-w-[200px] px-3 py-1.5 text-[11px] whitespace-nowrap rounded-t-lg border border-b-0 transition-colors shrink-0"
                :class="activeGraphTab === gt.id
                  ? 'bg-ctp-mantle text-ctp-text border-ctp-surface1 font-semibold'
                  : 'bg-ctp-surface0/50 text-ctp-subtext0 border-transparent hover:bg-ctp-surface0 hover:text-ctp-subtext1'"
                :title="gt.title"
                @click="activeGraphTab = gt.id"
              >
                <span class="truncate">{{ gt.title }}</span>
                <span
                  role="button"
                  class="flex items-center justify-center w-4 h-4 rounded text-ctp-overlay1 hover:text-ctp-red hover:bg-ctp-red/15 cursor-pointer shrink-0"
                  :title="t('assetMgmt.graph.closeTab')"
                  @click.stop="closeGraphTab(gt.id)"
                >
                  <XMarkIcon class="w-3 h-3" />
                </span>
              </button>
            </div>
            <div class="flex-1 min-h-0">
              <SemanticGraphView
                v-for="gt in graphTabs"
                v-show="activeGraphTab === gt.id"
                :key="gt.id"
                :tab="gt"
                @close="closeGraphTab"
              />
            </div>
          </template>
        </div>
        <div
          v-else
          class="flex-1 min-h-0 overflow-auto p-2.5 space-y-1.5"
        >
          <!-- 资产概览：作用说明 + 分类/粒度/标签 + 现有资产数量 -->
          <template v-if="tab === 'overview'">
            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <ServerStackIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.overview.title') }}
                </span>
              </div>
              <div class="p-3 space-y-2">
                <p class="text-xs text-ctp-subtext1 leading-relaxed">
                  {{ t('assetMgmt.overview.desc') }}
                </p>
              </div>
            </div>

            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <Squares2X2Icon class="w-4 h-4 text-ctp-peach" />{{ t('assetMgmt.overview.classificationTitle') }}
                </span>
              </div>
              <div class="p-3 space-y-2">
                <p class="text-[10px] text-ctp-subtext0 leading-relaxed">
                  {{ t('assetMgmt.overview.classificationDesc') }}
                </p>
                <div class="grid grid-cols-2 gap-2">
                  <div
                    v-for="k in kinds"
                    :key="k.value"
                    class="border border-ctp-surface0 rounded-md p-2"
                  >
                    <div class="text-[10px] font-semibold text-ctp-text">{{ k.label }}</div>
                    <div class="text-[9px] text-ctp-overlay0 mt-0.5">
                      {{ t(`assetMgmt.overview.kind.${k.value}`) }}
                    </div>
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-1 pt-1">
                  <span class="text-[10px] text-ctp-subtext1 shrink-0">{{ t('assetMgmt.overview.levelLabel') }}</span>
                  <span
                    v-for="l in levels"
                    :key="l.value"
                    class="chip"
                    :class="l.value === 'business' ? 'bg-ctp-peach/15 text-ctp-peach' : l.value === 'implementation' ? 'bg-ctp-sky/15 text-ctp-sky' : 'bg-ctp-surface0 text-ctp-subtext0'"
                  >{{ l.label }}</span>
                </div>
                <p class="text-[10px] text-ctp-subtext0 leading-relaxed pt-1">
                  {{ t('assetMgmt.overview.tagHint') }}
                </p>
              </div>
            </div>

            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <CubeTransparentIcon class="w-4 h-4 text-ctp-mauve" />{{ t('assetMgmt.overview.countTitle') }}
                </span>
              </div>
              <div class="p-3 space-y-2.5">
                <div class="flex items-center gap-3">
                  <div class="border border-ctp-blue/20 rounded-lg px-3 py-2 flex-1">
                    <div class="text-lg font-semibold text-ctp-blue">{{ overviewStats ? overviewStats.total : '—' }}</div>
                    <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.overview.total') }}</div>
                  </div>
                  <div class="border border-ctp-surface0 rounded-lg px-3 py-2 flex-1">
                    <div class="text-lg font-semibold text-ctp-text">{{ comps.length || compCatalog.length }}</div>
                    <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.overview.components') }}</div>
                  </div>
                  <div class="border border-ctp-green/20 rounded-lg px-3 py-2 flex-1">
                    <div class="text-lg font-semibold text-ctp-green">{{ overviewStats?.status?.active ?? statusCounts.active ?? 0 }}</div>
                    <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.overview.active') }}</div>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">{{ t('assetMgmt.overview.byKind') }}</div>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="k in kinds"
                      :key="k.value"
                      class="chip bg-ctp-surface0 text-ctp-subtext0"
                    >{{ k.label }} · {{ overviewStats?.byKind?.[k.value] ?? 0 }}</span>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">{{ t('assetMgmt.overview.byLevel') }}</div>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="l in levels"
                      :key="l.value"
                      class="chip bg-ctp-surface0 text-ctp-subtext0"
                    >{{ l.label }} · {{ overviewStats?.byLevel?.[l.value] ?? 0 }}</span>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">{{ t('assetMgmt.overview.statusLabel') }}</div>
                  <div class="flex flex-wrap gap-1.5">
                    <span class="chip bg-ctp-green/15 text-ctp-green">active · {{ overviewStats?.status?.active ?? statusCounts.active ?? 0 }}</span>
                    <span class="chip bg-ctp-yellow/15 text-ctp-yellow">stale · {{ overviewStats?.status?.stale ?? statusCounts.stale ?? 0 }}</span>
                    <span class="chip bg-ctp-red/15 text-ctp-red">deleted · {{ overviewStats?.status?.deleted ?? statusCounts.deleted ?? 0 }}</span>
                    <span class="chip bg-ctp-overlay0/20 text-ctp-overlay1">needsUpdate · {{ overviewStats?.status?.needsUpdate ?? statusCounts.needsUpdate ?? 0 }}</span>
                  </div>
                </div>

                <div class="border-t border-ctp-surface0 pt-2 flex items-center gap-2">
                  <button
                    class="btn btn-xs btn-ghost"
                    :disabled="purging"
                    @click="runPurge"
                  >
                    <TrashIcon class="w-3 h-3" />{{ purging ? t('assetMgmt.overview.purging') : t('assetMgmt.overview.purge') }}
                  </button>
                  <span class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.overview.purgeHint') }}</span>
                </div>
              </div>
            </div>
          </template>

          <!-- 语义资产：按组件树文件树形式逐层展开(选 L0/L1 时以该层为初始列表) -->
          <template v-if="tab === 'semantic'">
            <template
              v-for="g in semanticGroups"
              :key="g.key"
            >
              <div
                class="flex items-center gap-1.5 px-1 pt-1.5 pb-0.5"
                :style="{ paddingLeft: (g.depth * 12) + 'px' }"
              >
                <button
                  v-if="hasChildren(g.key)"
                  class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                  @click="toggleOpen(g.key)"
                >
                  <ChevronDownIcon
                    v-if="compOpen[g.key] !== false"
                    class="w-3 h-3"
                  />
                  <ChevronRightIcon
                    v-else
                    class="w-3 h-3"
                  />
                </button>
                <span
                  v-else
                  class="w-3.5 shrink-0"
                />
                <ServerStackIcon
                  v-if="g.key !== OTHER_KEY"
                  class="w-3 h-3 text-ctp-blue shrink-0"
                />
                <span
                  v-else
                  class="w-3 h-3 shrink-0"
                />
                <span
                  v-if="g.hierLevel"
                  class="chip !text-[8px] bg-ctp-surface0 text-ctp-overlay1 shrink-0 font-mono"
                >{{ g.hierLevel }}</span>
                <span class="text-[10px] font-semibold text-ctp-subtext1 truncate">{{ g.name }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ g.assets.length }}</span>
                <button
                  v-if="g.key !== OTHER_KEY"
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                  :title="t('assetMgmt.graph.viewCompGraph')"
                  @click="openGraphTab('comp', g.key, g.name)"
                >
                  <Squares2X2Icon class="w-3 h-3" />
                </button>
              </div>
              <div
                v-for="a in g.assets"
                :key="a.id"
                class="border border-ctp-mauve/20 hover:border-ctp-mauve/40 rounded-lg overflow-hidden"
              >
              <div class="flex items-center gap-1.5 px-2 py-1.5">
                <component
                  :is="kindIcon(a.kind)"
                  class="w-3.5 h-3.5 text-ctp-mauve shrink-0"
                />
                <span class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve shrink-0">
                  {{ t(`assetMgmt.kind.${a.kind}`) }}
                </span>
                <span
                  v-if="a.level"
                  class="chip !text-[9px] shrink-0"
                  :class="a.level === 'business' ? 'bg-ctp-peach/15 text-ctp-peach' : a.level === 'implementation' ? 'bg-ctp-sky/15 text-ctp-sky' : 'bg-ctp-surface0 text-ctp-subtext0'"
                >{{ t(`assetMgmt.level.${a.level}`) }}</span>
                <span class="text-[11px] font-medium text-ctp-text truncate">{{ a.name }}</span>
                <span
                  v-if="a.renamedFrom"
                  class="chip !text-[9px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                  :title="t('assetMgmt.canonicalHint')"
                >{{ t('assetMgmt.renamed') }}: {{ a.renamedFrom }}</span>
                <span
                  v-if="a.needsUpdate || a.status === 'stale'"
                  class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                >{{ t('assetMgmt.needsUpdate') }}</span>
                <span
                  v-else-if="a.status === 'deleted'"
                  class="chip !text-[9px] bg-ctp-red/15 text-ctp-red shrink-0"
                >{{ t('assetMgmt.deleted') }}</span>
                <span
                  v-else-if="a.change === 'added'"
                  class="chip !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0"
                >{{ t('assetMgmt.added') }}</span>
                <span
                  v-else-if="a.change === 'modified'"
                  class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                >{{ t('assetMgmt.modified') }}</span>
                <span class="flex-1" />
                <span
                  class="text-[9px] text-ctp-overlay0 font-mono"
                  :title="[a.canonicalKey ? t('assetMgmt.canonicalHint') + ' · ' + a.canonicalKey : '', ...(a.nameAlias ?? []).map((x) => t('assetMgmt.renamed') + ': ' + x)].filter(Boolean).join('\n') || undefined"
                >{{ a.id }}</span>
                <span class="text-[9px] text-ctp-overlay0">{{ a.astRefs?.length ?? 0 }} AST</span>
                <button
                  v-if="!usable(a)"
                  class="text-ctp-yellow hover:text-ctp-peach p-0.5"
                  :title="t('assetMgmt.refresh')"
                  @click="refreshOne(a)"
                >
                  <ArrowPathIcon class="w-3 h-3" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                  :title="t('assetMgmt.reference')"
                  @click="referenceAsset(a)"
                >
                  <ScaleIcon class="w-3 h-3" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                  :title="t('assetMgmt.graph.viewAssetGraph')"
                  @click="openGraphTab('asset', a.id, a.name)"
                >
                  <Squares2X2Icon class="w-3 h-3" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                  :title="t('assetMgmt.copy')"
                  @click="copyAsset(a)"
                >
                  <ClipboardDocumentIcon class="w-3 h-3" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                  :title="t('assetMgmt.expand')"
                  @click="toggle(a.id)"
                >
                  <ChevronDownIcon
                    v-if="expanded[a.id]"
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
                v-if="expanded[a.id]"
                class="border-t border-ctp-mauve/15 px-2 py-1.5 space-y-1 text-[10px]"
              >
                <div v-if="a.detail?.fields?.length">
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('assetMgmt.fields') }}</div>
                  <div
                    v-for="f in a.detail.fields"
                    :key="f.name"
                    class="pl-2"
                  ><span class="font-mono text-ctp-text">{{ f.name }}</span><span class="text-ctp-overlay0">: {{ f.type ?? '—' }}</span> {{ f.semantic ? `— ${f.semantic}` : '' }}</div>
                </div>
                <div v-if="a.detail?.steps?.length">
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('assetMgmt.steps') }}</div>
                  <div
                    v-for="(s, si) in a.detail.steps"
                    :key="si"
                    class="pl-2"
                  >{{ s.order ?? si + 1 }}. {{ s.semantic }}</div>
                </div>
                <div v-if="a.detail?.branches?.length">
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('assetMgmt.branches') }}</div>
                  <div
                    v-for="(b, bi) in a.detail.branches"
                    :key="bi"
                    class="pl-2"
                  ><span class="font-mono text-ctp-text">if {{ b.condition ?? '?' }}</span> → {{ b.then ?? '—' }}<span v-if="b.else"> / else {{ b.else }}</span></div>
                </div>
                <div v-if="a.astRefs?.length">
                  <div class="font-medium text-ctp-mauve mb-0.5">AST</div>
                  <div
                    v-for="(r, ri) in a.astRefs.slice(0, 8)"
                    :key="ri"
                    class="pl-2 font-mono text-ctp-overlay0"
                  >{{ r.file }}:L{{ r.startLine }}-L{{ r.endLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span></div>
                </div>
              </div>
              </div>
            </template>
            <p
              v-if="!semanticGroups.length && !loading"
              class="text-xs text-ctp-overlay0 text-center py-8"
            >
              {{ t('assetMgmt.emptySemantic') }}
            </p>
          </template>

          <!-- 组件资产：按 KB 组件树文件目录树形式逐层展开(选 L0/L1 时以该层为初始列表) -->
          <template v-else>
            <div
              v-for="c in compAssetRows"
              :key="c.assetId"
              class="border border-ctp-blue/20 hover:border-ctp-blue/40 rounded-lg overflow-hidden"
            >
              <div
                class="flex items-center gap-2 px-2 py-1.5"
                :style="{ paddingLeft: (c.depth * 14 + 8) + 'px' }"
              >
                <button
                  v-if="comps.some((x) => x.parentId === c.assetId)"
                  class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                  :title="t('assetMgmt.expandCollapse')"
                  @click="toggleOpen(c.assetId)"
                >
                  <ChevronDownIcon
                    v-if="compOpen[c.assetId] !== false"
                    class="w-3 h-3"
                  />
                  <ChevronRightIcon
                    v-else
                    class="w-3 h-3"
                  />
                </button>
                <span
                  v-else
                  class="w-3.5 shrink-0"
                />
                <input
                  v-if="extractMode"
                  type="checkbox"
                  class="accent-ctp-blue shrink-0"
                  :checked="extractSelected.includes(c.assetId)"
                  @change="toggleExtractSelect(c.assetId)"
                >
                <ServerStackIcon class="w-3.5 h-3.5 text-ctp-blue shrink-0" />
                <span class="text-[11px] font-medium text-ctp-text truncate">{{ c.name }}</span>
                <span class="chip !text-[9px] bg-ctp-blue/15 text-ctp-blue shrink-0">{{ t(`assetMgmt.componentKind.${c.kind ?? 'component'}`) }}</span>
                <span
                  v-if="c.parentName"
                  class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0 shrink-0"
                >{{ t('assetMgmt.parent') }}: {{ c.parentName }}</span>
                <span
                  v-if="c.fileCount !== undefined"
                  class="text-[9px] text-ctp-overlay1 shrink-0"
                >{{ c.fileCount }} {{ t('assetMgmt.files') }}</span>
                <span class="flex-1" />
                <span class="text-[9px] text-ctp-overlay0 font-mono hidden sm:inline">{{ c.assetId }}</span>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-blue p-0.5"
                  :title="t('assetMgmt.viewKb')"
                  @click="openKB(c)"
                >
                  <EyeIcon class="w-3.5 h-3.5" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                  :title="t('assetMgmt.graph.viewCompGraph')"
                  @click="openGraphTab('comp', c.assetId, c.name)"
                >
                  <Squares2X2Icon class="w-3.5 h-3.5" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                  :disabled="compExtracting[c.assetId] || extractRunning"
                  :title="t('assetMgmt.extractComp')"
                  @click="extractComp(c)"
                >
                  <ArrowPathIcon
                    class="w-3.5 h-3.5"
                    :class="compExtracting[c.assetId] ? 'animate-spin text-ctp-mauve' : ''"
                  />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-blue p-0.5"
                  :title="t('assetMgmt.summary')"
                  @click="toggleCompDetail(c)"
                >
                  <ChevronDownIcon
                    v-if="compExpanded[c.assetId]"
                    class="w-3.5 h-3.5"
                  />
                  <ChevronRightIcon
                    v-else
                    class="w-3.5 h-3.5"
                  />
                </button>
              </div>

              <!-- 组件概要信息(从 KB 获取) -->
              <div
                v-if="compExpanded[c.assetId]"
                class="border-t border-ctp-blue/15 px-2 py-1.5 space-y-1 text-[10px]"
              >
                <p
                  v-if="compDetailLoading[c.assetId]"
                  class="text-ctp-overlay0"
                >{{ t('assetMgmt.summaryLoading') }}</p>
                <p
                  v-else-if="compDetailMiss[c.assetId]"
                  class="text-ctp-peach"
                >{{ t('assetMgmt.summaryMiss') }}</p>
                <template v-else-if="compDetails[c.assetId]">
                  <p
                    v-if="compDetails[c.assetId].desc"
                    class="text-ctp-subtext1 leading-relaxed"
                  >{{ compDetails[c.assetId].desc }}</p>
                  <div class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[9px] text-ctp-overlay0">
                    <span v-if="compDetails[c.assetId].lang">lang: {{ compDetails[c.assetId].lang }}</span>
                    <span v-if="compDetails[c.assetId].hierLevel">hier: {{ compDetails[c.assetId].hierLevel }}</span>
                    <span v-if="compDetails[c.assetId].edgeType">edge: {{ compDetails[c.assetId].edgeType }}</span>
                    <span v-if="compDetails[c.assetId].parentName">{{ t('assetMgmt.parent') }}: {{ compDetails[c.assetId].parentName }}</span>
                    <span v-if="compDetails[c.assetId].fileCount !== undefined">{{ compDetails[c.assetId].fileCount }} {{ t('assetMgmt.files') }}</span>
                    <span v-if="compDetails[c.assetId].nodeCount !== undefined">{{ compDetails[c.assetId].nodeCount }} nodes</span>
                    <span v-if="compDetails[c.assetId].edgeCount !== undefined">{{ compDetails[c.assetId].edgeCount }} edges</span>
                  </div>
                  <div v-if="compDetails[c.assetId].responsibilities?.length">
                    <span class="font-medium text-ctp-blue">{{ t('assetMgmt.resp') }}:</span>
                    <span class="text-ctp-subtext1">{{ (compDetails[c.assetId]?.responsibilities ?? []).join('；') }}</span>
                  </div>
                  <div v-if="compDetails[c.assetId].owns?.length">
                    <span class="font-medium text-ctp-blue">{{ t('assetMgmt.owns') }}:</span>
                    <span class="font-mono text-ctp-subtext1">{{ (compDetails[c.assetId]?.owns ?? []).join(', ') }}</span>
                  </div>
                  <div v-if="compDetails[c.assetId].dependsOn?.length">
                    <span class="font-medium text-ctp-blue">{{ t('assetMgmt.deps') }}:</span>
                    <span class="font-mono text-ctp-subtext1">{{ (compDetails[c.assetId]?.dependsOn ?? []).join(', ') }}</span>
                  </div>
                </template>
                <p
                  v-else
                  class="text-ctp-overlay0"
                >{{ t('assetMgmt.summaryMiss') }}</p>
              </div>
            </div>
            <p
              v-if="!comps.length && !loading"
              class="text-xs text-ctp-overlay0 text-center py-8"
            >
              {{ t('assetMgmt.emptyComponent') }}
            </p>
          </template>
        </div>

        <!-- 分页：数据资产每页 ≤100，超出翻页 -->
        <div
          v-if="tab === 'semantic' && totalPages > 1"
          class="shrink-0 border-t border-ctp-surface0 flex items-center justify-between px-2 py-1.5"
        >
          <span class="text-[10px] text-ctp-overlay1 font-mono">{{ page }} / {{ totalPages }} · {{ total }}</span>
          <div class="flex items-center gap-1">
            <button
              class="btn btn-xs"
              :disabled="page <= 1"
              @click="gotoPage(page - 1)"
            >{{ t('assetMgmt.prevPage') }}</button>
            <button
              class="btn btn-xs"
              :disabled="page >= totalPages"
              @click="gotoPage(page + 1)"
            >{{ t('assetMgmt.nextPage') }}</button>
          </div>
        </div>
      </div>

      <!-- 分割线 -->
      <div
        class="w-4 shrink-0 -mx-0.5 flex items-center justify-center cursor-col-resize select-none touch-none group"
        :class="dragging ? 'cursor-col-resize' : ''"
        @pointerdown="onSplitPointerDown"
        @pointermove="onSplitPointerMove"
        @pointerup="onSplitPointerUp"
        @pointercancel="onSplitPointerUp"
        @pointerleave="onSplitPointerUp"
      >
        <div
          class="h-12 w-0.5 rounded-full bg-ctp-overlay1/40 transition-colors group-hover:bg-ctp-blue/60"
          :class="dragging ? '!bg-ctp-blue/70' : ''"
        />
      </div>

      <!-- 右：agent 对话区 -->
      <div class="min-h-0 flex-1 flex flex-col gap-2">
        <AnalysisChat
          class="flex-1 min-h-0"
          :turns="turns"
          :busy="busy"
          :models="chatModels"
          :model-id="chatModelId"
          :title="t('assetMgmt.chatTitle')"
          :diagram-skill="diagramSkill"
          @send="onSend"
          @model-change="onChatModelChange"
          @delete-turn="onDeleteTurn"
          @extract-assets="onExtractAssets"
          @refresh-asset="onRefreshAsset"
          @toggle-diagram-skill="toggleDiagramSkill"
        />
        <p class="text-[10px] text-ctp-overlay0 leading-relaxed">
          {{ t('assetMgmt.chatHint') }}
        </p>
      </div>
    </div>

    <RequirementHistoryModal
      :open="historyOpen"
      :active-conv-id="chatConvId"
      kind="asset"
      @close="historyOpen = false"
      @import="importHistory"
    />

    <!-- 清理语义资产确认：展示对需求池/未完成任务的影响范围 -->
    <div
      v-if="purgeOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div class="flex flex-col w-full max-w-2xl max-h-[85vh] rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden">
        <div class="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0">
          <TrashIcon class="w-4 h-4 text-ctp-red" />
          <h3 class="text-sm font-semibold text-ctp-text">
            {{ t('assetMgmt.purgeConfirm.title') }}
          </h3>
          <span class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.purgeConfirm.hint') }}</span>
        </div>

        <div class="flex-1 min-h-0 overflow-auto p-4 space-y-3">
          <p class="text-xs text-ctp-subtext1">
            {{ t('assetMgmt.purgeConfirm.summary', {
              candidates: purgeResult?.candidates ?? 0,
              reqCount: purgeResult?.impact?.reqCount ?? 0,
              taskCount: purgeResult?.impact?.taskCount ?? 0,
            }) }}
          </p>

          <div
            v-if="purgeResult?.impact?.requirements?.length"
            class="border border-ctp-peach/25 rounded-md p-2.5 space-y-1"
          >
            <div class="text-[10px] font-semibold text-ctp-peach">
              {{ t('assetMgmt.purgeConfirm.reqTitle', { n: purgeResult.impact.reqCount }) }}
            </div>
            <div
              v-for="r in purgeResult.impact.requirements"
              :key="r.id"
              class="text-[10px] text-ctp-subtext1"
            >
              <span class="font-mono text-ctp-overlay1">{{ r.id }}</span>
              · {{ r.title }}
              <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1">{{ r.location }}</span>
            </div>
            <p class="text-[9px] text-ctp-peach">{{ t('assetMgmt.purgeConfirm.reqRegen') }}</p>
          </div>

          <div
            v-if="purgeResult?.impact?.tasks?.length"
            class="border border-ctp-blue/25 rounded-md p-2.5 space-y-1"
          >
            <div class="text-[10px] font-semibold text-ctp-blue">
              {{ t('assetMgmt.purgeConfirm.taskTitle', { n: purgeResult.impact.taskCount }) }}
            </div>
            <div
              v-for="t in purgeResult.impact.tasks"
              :key="t.id"
              class="text-[10px] text-ctp-subtext1"
            >
              <span class="font-mono text-ctp-overlay1">{{ t.id }}</span>
              · {{ t.title }}
              <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1">{{ t.status }}</span>
            </div>
            <p class="text-[9px] text-ctp-blue">{{ t('assetMgmt.purgeConfirm.taskRegen') }}</p>
          </div>

          <p
            v-if="!purgeResult?.impact?.requirements?.length && !purgeResult?.impact?.tasks?.length"
            class="text-[10px] text-ctp-green"
          >{{ t('assetMgmt.purgeConfirm.noImpact') }}</p>
        </div>

        <div class="shrink-0 border-t border-ctp-surface0 px-4 py-2.5 flex justify-end gap-2">
          <button
            class="btn btn-ghost"
            :disabled="purgeBusy"
            @click="cancelPurge"
          >{{ t('assetMgmt.purgeConfirm.cancel') }}</button>
          <button
            class="btn btn-red"
            :disabled="purgeBusy"
            @click="confirmPurge"
          >{{ purgeBusy ? t('assetMgmt.purgeConfirm.deleting') : t('assetMgmt.purgeConfirm.confirm') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
