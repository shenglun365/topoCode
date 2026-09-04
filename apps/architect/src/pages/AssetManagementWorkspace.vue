<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, ChevronDownIcon, ChevronRightIcon, ArrowPathIcon,
  SparklesIcon, CubeTransparentIcon, AdjustmentsHorizontalIcon, ServerStackIcon, Squares2X2Icon,
  ClipboardDocumentListIcon, ClipboardDocumentIcon, ScaleIcon, EyeIcon, TrashIcon,
  ChartBarSquareIcon, StopIcon, XMarkIcon, ArrowsRightLeftIcon, ChatBubbleLeftRightIcon,
} from '@heroicons/vue/24/outline'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import RequirementHistoryModal from '@/components/requirements/RequirementHistoryModal.vue'
import SemanticGraphView, { type GraphTabDef } from '@/components/assets/SemanticGraphView.vue'
import PseudoExplainer from '@/components/assets/PseudoExplainer.vue'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { chatStream, type KbAnalysisTurn } from '@/services/kb-analysis-agent'
import { semanticAssetService, type BaselineDiff, type CoverageInfo, type FrameworkPreview, type FrameworkResult, type SemanticBatchResult, type SemanticPurgeResult, type SemanticStatsResult } from '@/services/semantic-asset-service'
import { kbAssetService } from '@/services/kb-assets'
import { requirementService } from '@/services/requirement-service'
import { namingService, type NamingConvention } from '@/services/naming-service'
import { useSplitPane } from '@/composables/useSplitPane'
import { useDiagramSkill } from '@/composables/useDiagramSkill'
import { useChatProgress } from '@/composables/useChatProgress'
import { readModelPref } from '@topo/web-core/shell'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import type { AssetDetail, AssetDiagramItem, ConversationDetail, SemanticAsset, SemanticAssetKind, SemanticAssetLevel } from '@/types'

const { t } = useI18n()

// ---- 对话模型: 统一用顶部工具栏选择(读同一 localStorage 键 topoone-model-architect, 透传后端) ----

// ---- 左右栏分割(资产内容 | agent 对话) ----
const { splitPct, dragging, boxRef: splitBoxRef, onDown: onSplitPointerDown } = useSplitPane()
const turns = ref<KbAnalysisTurn[]>([])
const busy = ref(false)
const chatConvId = ref<string>('')
const chatAbort = ref<AbortController | null>(null)
function stopChat() { chatAbort.value?.abort() }
const historyOpen = ref(false)
const { diagramSkill, toggleDiagramSkill } = useDiagramSkill()
// 对话等待期进度反馈（动态忙碌文案 + 工具轨迹；详见 useChatProgress）
const { busyLabel, toolTrail, begin: beginProgress, onChatEvent: onProgressEvent } = useChatProgress()

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

// ---- 静态资产图弹窗(entity → 类图，state → 状态图) ----
const diagramModalOpen = ref(false)
const diagramModalLoading = ref(false)
const diagramModalItems = ref<AssetDiagramItem[]>([])
const diagramModalTitle = ref('')

async function openAssetDiagram(a: SemanticAsset) {
  diagramModalOpen.value = true
  diagramModalLoading.value = true
  diagramModalTitle.value = a.name
  diagramModalItems.value = []
  try {
    const res = await semanticAssetService.assetDiagram([a.id])
    diagramModalItems.value = res.diagrams ?? []
  } catch {
    diagramModalItems.value = []
  } finally {
    diagramModalLoading.value = false
  }
}
const kind = ref<SemanticAssetKind | ''>('')
const level = ref<SemanticAssetLevel | ''>('')
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
const loading = ref(false)
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

/** 组件 id 层级推断：comm-<task>-incl|call-<L\d+>-… KB 社区递归细分最深到 L5，
 *  目录 hierLevel 字段缺失时按 id 兜底(实测 catalog 14 组件 hierLevel 全 None)。 */
function compLevelFromId(id: string | undefined): string | undefined {
  if (!id) return undefined
  return /-(?:incl|call)-(L\d+)-/.exec(id)?.[1]
}

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
    return compCatalog.value.map((c) => ({ id: c.assetId, name: c.name, parentId: c.parentId ?? undefined, owns: c.owns ?? [], hierLevel: c.hierLevel ?? compLevelFromId(c.assetId) }))
  }
  if (arch.components.length) {
    return arch.components.map((c) => ({ id: c.id, name: c.name, parentId: c.parentId ?? undefined, owns: c.owns ?? [], hierLevel: (c as { hierLevel?: string }).hierLevel ?? compLevelFromId(c.id) }))
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

/** 文件 → 拥有它的组件 id 列表(同一文件可被多组件同时拥有，如 INCLUDE/CALL 两套口径)。 */
const fileToComps = computed(() => {
  const m = new Map<string, string[]>()
  for (const c of treeComps.value) {
    for (const f of c.owns) {
      const arr = m.get(f)
      if (arr) {
        if (!arr.includes(c.id)) arr.push(c.id)
      } else {
        m.set(f, [c.id])
      }
    }
  }
  return m
})

/** 语义资产归属组件 id 列表(多归属)：优先资产自带 scopeKey(若为组件) +
 *  meta.scopes 多组件归属(INCLUDE/CALL 共享代码 / business 聚合)；
 *  均未命中组件 → 按首个锚点文件反查全部拥有组件。
 *  返回空 = 无组件归属(归「其它」)。共享代码资产会同时归属多个组件，
 *  保证各组件视角(树分组/关系图)都能看到它。 */
function componentsOf(a: SemanticAsset): string[] {
  const out: string[] = []
  const add = (cid: string | undefined | null) => {
    if (cid && compById.value.has(cid) && !out.includes(cid)) out.push(cid)
  }
  add(a.scopeKey)
  for (const cid of a.meta?.scopes ?? []) add(cid)
  if (!out.length) {
    const file = a.astRefs?.[0]?.file
    for (const cid of fileToComps.value.get(file) ?? []) add(cid)
  }
  return out
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

/** 范围筛选变化 → 按选中组件重新查询(服务端 scope 过滤)。 */
watch(scopeSel, () => {
  batchAction.value = ''
  batchPreview.value = null
  if (tab.value === 'semantic') loadSemantic()
})

function toggleOpen(id: string) {
  compOpen[id] = compOpen[id] !== false ? false : true
}

/** 树展开级别(工具栏单按钮循环)：
 *  0 全部收起(只显示顶层组件) → 1 组件展开(所有组件组头) → 2 文件展开(组件+文件) → 3 全部展开(含资产)。 */
const treeLevel = ref(1)
const TREE_LEVEL_MAX = 3
function cycleTreeLevel() {
  treeLevel.value = treeLevel.value >= TREE_LEVEL_MAX ? 0 : treeLevel.value + 1
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
interface SemanticGroup { key: string; name: string; depth: number; assets: SemanticAsset[]; hierLevel?: string }
/** 组件 id 层级映射(组件树 → L0/L1，供层级筛选)。 */
const compHierLevel = computed<Map<string, string>>(() => {
  const m = new Map<string, string>()
  for (const c of treeComps.value) {
    if (c.hierLevel) m.set(c.id, c.hierLevel)
  }
  return m
})
/** 目录树行：组件(目录) / 文件 / 资产 三类节点的扁平 DFS 序列。
 *  结构 = 组件按父子层级作目录；文件挂「独有它的」组件节点(own = owns − 直接子组件 owns，
 *  被子组件拥有的文件下放到子组件)；资产挂首锚点文件下，无锚点资产挂组件直属；无归属资产归「其它」。 */
type TreeRow = { key: string; t: 'comp' | 'file' | 'asset'; depth: number;
                 g?: SemanticGroup; file?: string; n?: number; a?: SemanticAsset;
                 fk?: string }
const fileOpen = reactive<Record<string, boolean>>({})
const subtreeCount = ref(new Map<string, number>())
function toggleFileOpen(key: string) {
  fileOpen[key] = fileOpen[key] !== false ? false : true
}
function fileBase(p: string): string {
  const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
  return i >= 0 ? p.slice(i + 1) : p
}

const semanticTreeRows = computed<TreeRow[]>(() => {
  const sel = new Set(scopeSel.value)
  const all = sel.size === 0
  // 资产分桶：首锚点文件 → byFile；无锚点 → 组件直属 direct；无归属 → other
  const byFile = new Map<string, SemanticAsset[]>()
  const direct = new Map<string, SemanticAsset[]>()
  const otherFiles = new Map<string, SemanticAsset[]>()
  const otherDirect: SemanticAsset[] = []
  for (const a of items.value) {
    const cids = componentsOf(a)
    const file = a.astRefs?.[0]?.file || ''
    if (!cids.length) {
      if (file) {
        const l = otherFiles.get(file) ?? []
        l.push(a)
        otherFiles.set(file, l)
      } else otherDirect.push(a)
      continue
    }
    const cid = a.scopeKey && cids.includes(a.scopeKey) ? a.scopeKey : cids[0]!
    if (file) {
      const l = byFile.get(file) ?? []
      l.push(a)
      byFile.set(file, l)
    } else {
      const l = direct.get(cid) ?? []
      l.push(a)
      direct.set(cid, l)
    }
  }
  const children = new Map<string, CompNode[]>()
  const roots: CompNode[] = []
  for (const c of treeComps.value) {
    const pk = c.parentId ?? ''
    const arr = children.get(pk) ?? []
    arr.push(c)
    children.set(pk, arr)
    if (!c.parentId) roots.push(c)
  }
  const uniqueFiles = (c: CompNode): string[] => {
    const sub = new Set<string>()
    for (const ch of children.get(c.id) ?? []) for (const f of ch.owns) sub.add(f)
    return c.owns.filter((f) => !sub.has(f)).sort()
  }
  // 子树资产总数(组头计数 chip，模板引用)——每次重算填充
  const counts = new Map<string, number>()
  const countSub = (c: CompNode): number => {
    const sub = new Set<string>()
    for (const ch of children.get(c.id) ?? []) for (const f of ch.owns) sub.add(f)
    let n = direct.get(c.id)?.length ?? 0
    for (const f of c.owns) if (!sub.has(f)) n += byFile.get(f)?.length ?? 0
    for (const ch of children.get(c.id) ?? []) n += countSub(ch)
    counts.set(c.id, n)
    return n
  }
  const rows: TreeRow[] = []
  const walk = (c: CompNode, depth: number) => {
    if (!(all || sel.has(c.id))) {
      // 路径节点：自身不渲染，仍下探(选中集可能命中后代)；level0 只显示顶层组件
      if (treeLevel.value >= 1) {
        for (const ch of children.get(c.id) ?? []) walk(ch, depth + 1)
      }
      return
    }
    countSub(c)
    rows.push({ key: c.id, t: 'comp', depth,
                g: { key: c.id, name: c.name, depth, assets: [], hierLevel: c.hierLevel } })
    if (compOpen[c.id] === false) return   // 单节点折叠 → 子组件/文件/资产整支隐藏
    const lv = treeLevel.value
    if (lv >= 1) {
      for (const ch of children.get(c.id) ?? []) walk(ch, depth + 1)
    }
    if (lv >= 2) {
      for (const f of uniqueFiles(c)) {
        const fk = c.id + '::' + f
        const list = byFile.get(f) ?? []
        rows.push({ key: 'f:' + fk, t: 'file', depth: depth + 1, file: f, n: list.length, fk })
        if (lv === 3 && fileOpen[fk] !== false) {
          for (const a of list) rows.push({ key: 'a:' + a.id + ':' + fk, t: 'asset', depth: depth + 2, a })
        }
      }
    }
    if (lv === 3) {
      for (const a of direct.get(c.id) ?? []) rows.push({ key: 'a:' + a.id, t: 'asset', depth: depth + 1, a })
    }
  }
  for (const r of roots) walk(r, 0)
  if ((otherFiles.size || otherDirect.length) && (all || sel.has(OTHER_KEY))) {
    rows.push({ key: OTHER_KEY, t: 'comp', depth: 0,
                g: { key: OTHER_KEY, name: t('assetMgmt.other'), depth: 0, assets: [] } })
    if (compOpen[OTHER_KEY] !== false && treeLevel.value >= 2) {
      for (const f of [...otherFiles.keys()].sort()) {
        const fk = OTHER_KEY + '::' + f
        const list = otherFiles.get(f) ?? []
        rows.push({ key: 'f:' + fk, t: 'file', depth: 1, file: f, n: list.length, fk })
        if (treeLevel.value === 3 && fileOpen[fk] !== false) {
          for (const a of list) rows.push({ key: 'a:' + a.id + ':' + fk, t: 'asset', depth: 2, a })
        }
      }
      if (treeLevel.value === 3) {
        for (const a of otherDirect) rows.push({ key: 'a:' + a.id, t: 'asset', depth: 1, a })
      }
    }
  }
  subtreeCount.value = counts
  return rows
})

const scopeSummary = computed(() => {
  if (!scopeSel.value.length) return t('assetMgmt.scopeAll')
  // 共享资产会挂在多个组件下 → 按资产 id 去重计数
  const sel = new Set(scopeSel.value)
  const ids = new Set<string>()
  for (const a of items.value) {
    const cids = componentsOf(a)
    if (!cids.length) {
      if (sel.has(OTHER_KEY)) ids.add(a.id)
      continue
    }
    if (cids.some((cid) => sel.has(cid))) ids.add(a.id)
  }
  return `${ids.size}/${items.value.length}`
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
    // 树形分组视图(按组件逐层展开)必须全量加载——分页会把组内条目截断到单页，
    // 组头计数与低序组件组显示错误(后端 _grouped_search_items 本就全量排序后返回)。
    const r = await semanticAssetService.searchPage(q.value, kind.value || undefined, { limit: 2000, offset: 0, scope: scopeParams(), level: level.value || undefined })
    items.value = r.items
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

// ---- 基线对比模式（三视图 diff：基线 lastHead → 工作区 变更文件集）----
const diffMode = ref(false)
const diffLoading = ref(false)
const baselineDiffData = ref<BaselineDiff | null>(null)

async function loadBaselineDiff() {
  diffLoading.value = true
  try {
    baselineDiffData.value = await semanticAssetService.baselineDiff()
  } catch {
    baselineDiffData.value = null
  } finally {
    diffLoading.value = false
  }
}

function toggleDiffMode() {
  diffMode.value = !diffMode.value
  if (diffMode.value) loadBaselineDiff()
}

/** 变更文件 → 类别 快查表（语义行徽标 / 图谱节点着色用）。 */
const changedFileMap = computed<Map<string, 'added' | 'modified' | 'deleted'>>(() => {
  const m = new Map<string, 'added' | 'modified' | 'deleted'>()
  const d = baselineDiffData.value
  if (!d) return m
  for (const p of d.files.added) m.set(p, 'added')
  for (const p of d.files.modified) m.set(p, 'modified')
  for (const p of d.files.deleted) m.set(p, 'deleted')
  return m
})

/** 资产变更标记：任一 astRef 文件 ∈ 变更集 → 返回类别（工作区态优先）。
 *  ⚠️ 模板勿直接调用本函数：它遍历 astRefs，行内多次调用会重复求值；
 *  请用下方 changeMarkById（每资产仅算一次）。 */
function assetChangeMark(a: SemanticAsset): 'added' | 'modified' | 'deleted' | '' {
  if (!diffMode.value) return ''
  const files = a.astRefs?.map((r) => r.file) ?? []
  let mark: 'added' | 'modified' | 'deleted' | '' = ''
  for (const f of files) {
    const c = changedFileMap.value.get(f)
    if (c === 'added') return 'added'
    if (c === 'deleted') { mark = 'deleted'; continue }
    if (c === 'modified') { if (mark !== 'deleted') mark = 'modified' }
  }
  return mark
}

/** 资产 id → 变更类别（语义行徽标渲染入口：diffMode/变更集变化时统一重算一次）。 */
const changeMarkById = computed<Map<string, 'added' | 'modified' | 'deleted'>>(() => {
  const m = new Map<string, 'added' | 'modified' | 'deleted'>()
  if (!diffMode.value) return m
  for (const a of items.value) {
    const mark = assetChangeMark(a)
    if (mark) m.set(a.id, mark)
  }
  return m
})

/** diff 徽标文案（markAdded/markModified/markDeleted）；空 mark 返回空串。 */
function diffMarkLabel(mark?: 'added' | 'modified' | 'deleted'): string {
  if (!mark) return ''
  return t(`assetMgmt.diff.mark${mark[0].toUpperCase()}${mark.slice(1)}`)
}

/** 图谱节点变更标记（按节点锚点文件）。SemanticGraphView 节点含 anchor 文件。 */
const changedFilesForGraph = computed<Set<string>>(() => new Set(changedFileMap.value.keys()))

/** 变更文件总数（工具栏徽标）。 */
const totalChanged = computed(() => {
  const c = baselineDiffData.value?.counts
  return c ? c.added + c.modified + c.deleted : 0
})

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

/** 批量范围签名(预览与执行之间范围变化 → 作废预览)。 */
function batchScopeSig() {
  return JSON.stringify([targetScope(), scopeParams()])
}

async function runBatch(action: 'clear') {
  if (batchRunning.value) return
  const { compIds, includeOther } = targetScope()
  // 清除 = 物理删除：一击式确认——首击 dry-run 预览影响并把同一按钮转为「确认清除」，再击执行。
  if (!batchPreview.value) {
    const sig = batchScopeSig()
    batchRunning.value = true
    try {
      const scope = scopeParams()
      const res = await semanticAssetService.batchManage(action, compIds, {
        includeOther, scope, dryRun: true,
      })
      if (sig !== batchScopeSig()) return
      batchPreview.value = res
      batchAction.value = action
    } catch {
      batchPreview.value = null
      batchAction.value = ''
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

// 提取完成 → 主动刷新资产数据(agent 在对话中执行 asset.semantic.extract 落库后，
// 资产列表/状态/覆盖度不会自动更新；此处去抖合并刷新，回合结束时兜底再刷一次)。
let extractDirty = false
let extractRefreshTimer: ReturnType<typeof setTimeout> | null = null
function refreshAfterExtract() {
  extractDirty = false
  if (extractRefreshTimer) { clearTimeout(extractRefreshTimer); extractRefreshTimer = null }
  void Promise.all([loadSemantic(), refreshStatus(), loadOverview(), loadCoverage()])
}
function markExtracted() {
  extractDirty = true
  if (extractRefreshTimer) clearTimeout(extractRefreshTimer)
  extractRefreshTimer = setTimeout(refreshAfterExtract, 1500)
}

function askAgent(text: string) {
  if (busy.value || !text.trim()) return
  turns.value.push({ role: 'user', content: text })
  const idx = turns.value.push({ role: 'assistant', content: '' }) - 1
  busy.value = true
  beginProgress()
  const ac = new AbortController(); chatAbort.value = ac
  chatStream([{ role: 'user', content: text }], {
    conversationId: chatConvId.value || undefined,
    kind: 'asset',
    title: t('assetMgmt.chatTitle'),
    modelId: readModelPref('architect') || undefined,
    diagramSkill: diagramSkill.value,
    skillScenarios: ['extract'],
    signal: ac.signal,
  }, (ev) => {
    onProgressEvent(ev)
    if (ev.conversationId) chatConvId.value = ev.conversationId
    if (ev.type === 'chunk') {
      turns.value[idx].content += ev.delta ?? ''
    } else if (ev.type === 'reasoning') {
      turns.value[idx].reasoning = (turns.value[idx].reasoning ?? '') + (ev.delta ?? '')
    } else if (ev.type === 'tool_result' && ev.tool === 'asset.semantic.extract' && ev.ok) {
      markExtracted()
    } else if (ev.type === 'done') {
      turns.value[idx].content = ev.content ?? turns.value[idx].content
    } else if (ev.type === 'error') {
      turns.value[idx].content = ev.message || t('requirement.chat.fallback')
    }
  }).finally(() => {
    chatAbort.value = null
    busy.value = false
    if (extractDirty) refreshAfterExtract()
  })
}

async function onSend(text: string) {
  if (busy.value) return
  seedConventionIds()
  turns.value.push({ role: 'user', content: text })
  const idx = turns.value.push({ role: 'assistant', content: '' }) - 1
  busy.value = true
  beginProgress()
  const ac = new AbortController(); chatAbort.value = ac
  try {
    const msgs = turns.value.slice(0, -1).map((t) => ({ role: t.role, content: t.content }))
      await chatStream(msgs, {
        conversationId: chatConvId.value || undefined,
        kind: 'asset',
        title: t('assetMgmt.chatTitle'),
        modelId: readModelPref('architect') || undefined,
        diagramSkill: diagramSkill.value,
        // 手动输入也注入 extract 场景：指令化提取(组件ID 权威范围，确定执行)
        skillScenarios: ['extract'],
        signal: ac.signal,
      }, (ev) => {
      onProgressEvent(ev)
      if (ev.conversationId) chatConvId.value = ev.conversationId
      if (ev.type === 'chat_start') {
        if (ev.userMessageId) turns.value[idx - 1].id = ev.userMessageId
      } else if (ev.type === 'tool_result' && ev.tool === 'convention.propose' && ev.ok) {
        onConventionProposed(idx)
      } else if (ev.type === 'tool_result' && ev.tool === 'asset.semantic.extract' && ev.ok) {
        markExtracted()
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
    chatAbort.value = null
    busy.value = false
    if (extractDirty) refreshAfterExtract()
  }
}

function onRefreshAsset(assetId: string) {
  refreshOne(items.value.find((x) => x.id === assetId) as SemanticAsset).catch(() => {})
}

// ── A4 命名规约归纳提议卡（agent 检测命名模式 → pending 提案；确认固化/忽略） ──

/** 已展示过的规约提案 id（防历史 pending 在每次发送时重复弹卡）。 */
const seenConventionIds = ref<Set<string>>(new Set())
/** 会话首轮发送前是否已快照既有 pending 提案。 */
const conventionSeeded = ref(false)

function seedConventionIds() {
  if (conventionSeeded.value) return
  conventionSeeded.value = true
  // 会话首轮发送前快照既有 pending 提案，避免把历史提案当本次新提议
  namingService.conventions('pending').then((rows) => {
    for (const r of rows) if (r.id) seenConventionIds.value.add(r.id)
  }).catch(() => {})
}

/** tool_result(convention.propose, ok) → 拉取 pending 提案，把新增的挂到当前助手回合。 */
async function onConventionProposed(idx: number) {
  try {
    const rows = await namingService.conventions('pending')
    const fresh = rows.filter((r) => r.id && !seenConventionIds.value.has(r.id))
    if (!fresh.length) return
    fresh.forEach((r) => seenConventionIds.value.add(r.id))
    const turn = turns.value[idx]
    if (!turn) return
    turn.conventions = [...(turn.conventions ?? []), ...fresh]
  } catch (err: any) {
    console.warn('[naming] 拉取规约提案失败:', err?.message)
  }
}

async function onConventionConfirm(id: string) {
  try {
    await namingService.updateConvention(id, { status: 'active' })
  } catch (err: any) {
    console.warn('[naming] 规约确认失败:', err?.message)
  }
}

async function onConventionIgnore(id: string) {
  try {
    await namingService.deleteConvention(id)
  } catch (err: any) {
    console.warn('[naming] 规约忽略失败:', err?.message)
  }
}

// ── M1 认知框架（框架即配置；概览 tab 面板 + 标准变更确认流） ──

const frameworkInfo = ref<FrameworkResult | null>(null)
const coverageInfo = ref<CoverageInfo | null>(null)
const fwLoading = ref(false)
const fwSwitching = ref(false)
const fwPreview = ref<FrameworkPreview | null>(null)

async function loadFramework() {
  fwLoading.value = true
  try {
    frameworkInfo.value = await semanticAssetService.getFramework()
  } catch {
    frameworkInfo.value = null
  } finally {
    fwLoading.value = false
  }
}

async function loadCoverage() {
  try {
    coverageInfo.value = await semanticAssetService.coverage()
  } catch {
    coverageInfo.value = null
  }
}

/** 标准变更确认流：preview(dry-run) → 设计者确认 → switch（整体作废+命名不迁移）。 */
async function switchTier(tier: 'low' | 'mid' | 'high') {
  if (fwSwitching.value) return
  try {
    fwPreview.value = await semanticAssetService.previewFrameworkChange()
    const pv = fwPreview.value
    const dist = Object.entries(pv.byKind ?? {})
      .map(([k, n]) => `${t(`assetMgmt.kind.${k}`)}×${n}`)
      .join(', ') || '0'
    const msg = t('assetMgmt.framework.confirmMsg', { n: pv.voidedAssets, dist })
    if (!window.confirm(msg)) return
    fwSwitching.value = true
    await semanticAssetService.switchFramework(tier)
    await Promise.all([loadFramework(), loadSemantic(), loadOverview(), loadCoverage(), refreshStatus()])
  } catch (e: any) {
    window.alert(e?.message || t('assetMgmt.framework.switchFailed'))
  } finally {
    fwSwitching.value = false
  }
}

/** 对话提取：聚焦右栏对话并预填提取提示（按需提取，提议制由 agent 承接）。 */
function askExtractGeneral() {
  askAgent(t('assetMgmt.chatExtractPrompt'))
}

/** 按需提取：确定性直调 REST(不走对话模型——小模型可能不按工具协议执行而编造报告)。
 *  过程与结果以对话回合呈现；完成后刷新资产数据。 */
async function askExtractComponent(key: string, name: string) {
  if (busy.value) return
  turns.value.push({ role: 'user', content: t('assetMgmt.compExtractUser', { name, key }) })
  const idx = turns.value.push({ role: 'assistant', content: t('assetMgmt.compExtractRunning') }) - 1
  busy.value = true
  const ac = new AbortController(); chatAbort.value = ac
  try {
    const res = await semanticAssetService.extract(
      { type: 'comm', key },
      kinds.map((k) => k.value),
      { level: 'implementation' },
    )
    const n = res.count ?? res.assets?.length ?? 0
    if (res.error) {
      turns.value[idx].content = `${t('assetMgmt.compExtractFailed')}\n${res.error}`
      const cands: { id: string; name: string }[] = (res as { candidates?: { id: string; name: string }[] }).candidates ?? []
      if (cands.length) {
        turns.value[idx].content += '\n' + t('assetMgmt.compExtractCandidates')
        for (const c of cands.slice(0, 8)) turns.value[idx].content += `\n· ${c.name} (${c.id})`
      }
    } else {
      turns.value[idx].content = res.degraded
        ? (res.reason === 'index_missing' || (res.source && res.source !== 'codegraph')
            ? t('assetMgmt.compExtractDegradedIndex', { n })
            : t('assetMgmt.compExtractDegraded', { n }))
        : t('assetMgmt.compExtractDone', { n })
      turns.value[idx].assets = res.assets ?? []
    }
    // 数据变更 → 刷新列表/状态/覆盖度(与对话提取联动同口径)
    refreshAfterExtract()
  } catch (err: any) {
    turns.value[idx].content = err?.name === 'AbortError'
      ? t('requirement.chat.semanticStopped')
      : (err?.message || t('assetMgmt.batchFailed'))
  } finally {
    chatAbort.value = null
    busy.value = false
  }
}

/** 组件覆盖状态（概览覆盖度数据投影到语义 tab 组头）；无数据返回 '' 不渲染。 */
function compCoverage(compId: string): 'full' | 'partial' | 'none' | '' {
  const c = coverageInfo.value?.components?.find((x) => x.componentId === compId)
  return c?.coverage ?? ''
}

/** 组件元数据（owns/dependsOn 摘要，供组头 tooltip）。 */
function compMetaText(compId: string): string {
  const c = compById.value.get(compId)
  if (!c) return ''
  const parts: string[] = []
  if (c.owns?.length) parts.push(`owns: ${c.owns.slice(0, 6).join(', ')}${c.owns.length > 6 ? '…' : ''}`)
  if (c.parentId) parts.push(`parent: ${compById.value.get(c.parentId)?.name ?? c.parentId}`)
  return parts.join(' · ')
}

// ---- 组件「拷贝/引用 名称+ID」快捷操作（与 KB 组件目录严格同名同 ID，供对话精准对接）----
/** 统一引用格式：`名称 (comm-…)`——agent 工具按名称/ID 双向可解析。 */
function compRefText(name: string, id: string): string {
  return `${name} (${id})`
}

const copiedKey = ref('')
let copiedTimer: ReturnType<typeof setTimeout> | null = null
async function copyCompRef(key: string, name: string, id: string) {
  const text = compRefText(name, id)
  let ok = false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      ok = true
    }
  } catch { /* fallthrough */ }
  if (!ok) {
    // 非安全上下文(LAN http) clipboard API 不可用 → execCommand 降级
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      ok = document.execCommand('copy')
      document.body.removeChild(ta)
    } catch { ok = false }
  }
  if (ok) {
    copiedKey.value = key
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => { copiedKey.value = '' }, 1500)
  }
}

/** 引用组件到对话输入框（预填不发送，用户可补充问题）。 */
const chatDraft = ref<{ text: string; nonce: number } | null>(null)
let draftNonce = 0
function referenceComp(name: string, id: string) {
  chatDraft.value = { text: compRefText(name, id), nonce: ++draftNonce }
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
    loadCoverage()
  } else {
    loadSemantic()
  }
}

// 搜索词防抖自动查询(300ms)——筛选下拉均为 @change 即时提交, 搜索框对齐同体验
let qDebounce: ReturnType<typeof setTimeout> | null = null
watch(q, () => {
  if (qDebounce) clearTimeout(qDebounce)
  qDebounce = setTimeout(() => {
    qDebounce = null
    if (tab.value !== 'graph' && tab.value !== 'overview') loadSemantic()
  }, 300)
})

// 分页已移除：语义资产为树形分组视图，全量加载(loadSemantic limit=2000)。

onMounted(async () => {
  await Promise.all([loadCompCatalog(), loadOverview(), loadSemantic(), refreshStatus(), loadFramework(), loadCoverage()])
  turns.value.push({ role: 'assistant', content: t('assetMgmt.welcome') })
})
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
            v-for="tb in [{ id: 'overview' as const, label: t('assetMgmt.tab.overview') }, { id: 'semantic' as const, label: t('assetMgmt.tab.semantic') }, { id: 'graph' as const, label: t('assetMgmt.tab.graph') }]"
            :key="tb.id"
            class="btn btn-xs"
            :class="tab === tb.id ? 'btn-blue' : 'btn-ghost'"
            @click="tab = tb.id; onSearch()"
          >
            {{ tb.label }}
          </button>
        </div>
        <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[10px]">{{ statusText }}</span>
        <button
          class="btn btn-xs"
          :class="diffMode ? 'btn-blue' : 'btn-ghost'"
          :title="t('assetMgmt.diff.hint')"
          @click="toggleDiffMode"
        >
          <ArrowsRightLeftIcon class="w-3.5 h-3.5" :class="diffLoading ? 'animate-spin' : ''" />
          {{ t('assetMgmt.diff.toggle') }}
        </button>
        <span v-if="diffMode && baselineDiffData" class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[10px]">
          <template v-if="baselineDiffData.aligned">{{ t('assetMgmt.diff.aligned') }}</template>
          <template v-else-if="baselineDiffData.stale">{{ t('assetMgmt.diff.stale', { n: totalChanged }) }}</template>
          <template v-else>{{ t('assetMgmt.diff.noBaseline') }}</template>
        </span>
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
          :disabled="busy"
          :title="t('assetMgmt.chatExtractHint')"
          @click="askExtractGeneral"
        >
          <SparklesIcon class="w-3.5 h-3.5" />{{ t('assetMgmt.chatExtract') }}
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
            <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-mauve" />{{ t(`assetMgmt.tab.${tab}`) }}
          </span>
          <input
            v-if="tab !== 'graph' && tab !== 'overview'"
            v-model="q"
            class="input !py-0.5 !px-2 !text-[11px] w-44 font-mono ml-3"
            :placeholder="t('assetMgmt.searchPlaceholder')"
            @keydown.enter="onSearch"
          >
          <select
            v-if="tab === 'semantic'"
            v-model="kind"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
            @change="onSearch"
          >
            <option value="">
              {{ t('assetMgmt.allKinds') }}
            </option>
            <option
              v-for="k in kinds"
              :key="k.value"
              :value="k.value"
            >
              {{ k.label }}
            </option>
          </select>
          <select
            v-if="tab === 'semantic'"
            v-model="level"
            class="input !py-0.5 !px-2 !text-[11px] w-auto"
            @change="onSearch"
          >
            <option value="">
              {{ t('assetMgmt.allLevels') }}
            </option>
            <option
              v-for="l in levels"
              :key="l.value"
              :value="l.value"
            >
              {{ l.label }}
            </option>
          </select>
          <button
            v-if="tab === 'semantic'"
            class="btn btn-ghost !py-0.5 !px-2 !text-[11px] shrink-0"
            :title="t('assetMgmt.treeLevelHint')"
            @click="cycleTreeLevel"
          >{{ t(`assetMgmt.treeLevel.${treeLevel}`) }}</button>
          <template v-if="tab === 'semantic'">
            <div
              class="inline-flex items-center rounded-md border border-ctp-surface1 bg-ctp-mantle/60 overflow-hidden"
              :title="t('assetMgmt.scopeGroupHint')"
            >
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
                  <TrashIcon class="w-3 h-3" />{{ batchAction === 'clear' ? t('assetMgmt.batchConfirm') : t('assetMgmt.batchClear') }}
                </button>
                <button
                  v-if="batchAction === 'clear'"
                  class="btn btn-xs btn-ghost"
                  @click="batchAction = ''; batchPreview = null"
                >
                  {{ t('assetMgmt.batchCancel') }}
                </button>
              </div>
              <div
                v-if="batchAction === 'clear'"
                class="border-t border-ctp-surface0 pt-1.5 space-y-1.5"
              >
                <p class="text-[10px] text-ctp-red">
                  {{ t('assetMgmt.batchConfirmClear') }}
                </p>
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
                  >
                    {{ t('assetMgmt.purgeConfirm.noImpact') }}
                  </p>
                </div>
              </div>
              <div
                v-if="batchRunning"
                class="text-[10px] text-ctp-overlay1"
              >
                {{ t('assetMgmt.batchRunning') }}
              </div>
              <div
                v-if="batchLast"
                class="text-[10px] text-ctp-subtext1"
              >
                {{ batchLast }}
              </div>
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
                >
                  {{ t('assetMgmt.clearScope') }}
                </button>
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
                :diff-files="changedFilesForGraph"
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
                    <div class="text-[10px] font-semibold text-ctp-text">
                      {{ k.label }}
                    </div>
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
                    <div class="text-lg font-semibold text-ctp-blue">
                      {{ overviewStats ? overviewStats.total : '—' }}
                    </div>
                    <div class="text-[9px] text-ctp-overlay0">
                      {{ t('assetMgmt.overview.total') }}
                    </div>
                  </div>
                  <div class="border border-ctp-surface0 rounded-lg px-3 py-2 flex-1">
                    <div class="text-lg font-semibold text-ctp-text">
                      {{ compCatalog.length }}
                    </div>
                    <div class="text-[9px] text-ctp-overlay0">
                      {{ t('assetMgmt.overview.components') }}
                    </div>
                  </div>
                  <div class="border border-ctp-green/20 rounded-lg px-3 py-2 flex-1">
                    <div class="text-lg font-semibold text-ctp-green">
                      {{ overviewStats?.status?.active ?? statusCounts.active ?? 0 }}
                    </div>
                    <div class="text-[9px] text-ctp-overlay0">
                      {{ t('assetMgmt.overview.active') }}
                    </div>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">
                    {{ t('assetMgmt.overview.byKind') }}
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="k in kinds"
                      :key="k.value"
                      class="chip bg-ctp-surface0 text-ctp-subtext0"
                    >{{ k.label }} · {{ overviewStats?.byKind?.[k.value] ?? 0 }}</span>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">
                    {{ t('assetMgmt.overview.byLevel') }}
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="l in levels"
                      :key="l.value"
                      class="chip bg-ctp-surface0 text-ctp-subtext0"
                    >{{ l.label }} · {{ overviewStats?.byLevel?.[l.value] ?? 0 }}</span>
                  </div>
                </div>

                <div class="space-y-1">
                  <div class="text-[10px] font-medium text-ctp-subtext1">
                    {{ t('assetMgmt.overview.statusLabel') }}
                  </div>
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

            <!-- M1 认知框架：三组默认预设 + 标准变更确认流（plan-C §3；框架即配置） -->
            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <AdjustmentsHorizontalIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.framework.title') }}
                </span>
                <span
                  v-if="frameworkInfo?.config?.frameworkVersion"
                  class="chip bg-ctp-surface0 text-ctp-overlay1 font-mono !text-[9px]"
                >v{{ frameworkInfo.config.frameworkVersion }}</span>
              </div>
              <div class="p-3 space-y-2">
                <div class="grid grid-cols-3 gap-2">
                  <button
                    v-for="tier in (['low', 'mid', 'high'] as const)"
                    :key="tier"
                    class="border rounded-md p-2 text-left transition-colors"
                    :class="frameworkInfo?.config?.activeTier === tier
                      ? 'border-ctp-blue/60 bg-ctp-blue/10'
                      : 'border-ctp-surface0 hover:border-ctp-blue/40'"
                    :disabled="fwLoading || fwSwitching"
                    @click="switchTier(tier)"
                  >
                    <div class="flex items-center gap-1.5">
                      <span class="text-[11px] font-semibold text-ctp-text">{{ t(`assetMgmt.framework.tier.${tier}`) }}</span>
                      <span
                        v-if="frameworkInfo?.config?.activeTier === tier"
                        class="chip !text-[8px] bg-ctp-blue/20 text-ctp-blue"
                      >{{ t('assetMgmt.framework.active') }}</span>
                    </div>
                    <div class="text-[9px] text-ctp-overlay0 mt-1 leading-snug">
                      {{ t(`assetMgmt.framework.tierDesc.${tier}`) }}
                    </div>
                    <div class="text-[9px] text-ctp-subtext0 mt-1 font-mono">
                      {{ frameworkInfo?.presets?.[tier]?.x?.length ?? '—' }} {{ t('assetMgmt.framework.kindsUnit') }} · {{ frameworkInfo?.presets?.[tier]?.y?.length ?? '—' }} {{ t('assetMgmt.framework.levelsUnit') }}
                    </div>
                  </button>
                </div>
                <p class="text-[9px] text-ctp-overlay0 leading-relaxed">
                  {{ t('assetMgmt.framework.hint') }}
                </p>
              </div>
            </div>

            <!-- M1 覆盖度（诚实呈现部分真相：plan-C §4.3） -->
            <div class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <ChartBarSquareIcon class="w-4 h-4 text-ctp-green" />{{ t('assetMgmt.coverage.title') }}
                </span>
              </div>
              <div class="p-3 space-y-2">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="chip bg-ctp-green/15 text-ctp-green">{{ t('assetMgmt.coverage.extracted') }} · {{ coverageInfo?.extracted ?? '—' }}</span>
                  <span class="chip bg-ctp-yellow/15 text-ctp-yellow">{{ t('assetMgmt.coverage.stale') }} · {{ coverageInfo?.stale ?? '—' }}</span>
                  <span class="chip bg-ctp-surface0 text-ctp-subtext0">
                    {{ t('assetMgmt.coverage.components') }} · {{ coverageInfo?.componentsCovered ?? '—' }}/{{ coverageInfo?.componentsTotal ?? '—' }}
                  </span>
                </div>
                <div
                  v-if="coverageInfo?.components?.some((c) => c.coverage === 'none')"
                  class="space-y-0.5"
                >
                  <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.coverage.noneHint') }}</div>
                  <div class="flex flex-wrap gap-1">
                    <span
                      v-for="c in coverageInfo.components.filter((c) => c.coverage === 'none').slice(0, 8)"
                      :key="c.componentId"
                      class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1"
                    >{{ c.name }}</span>
                    <span
                      v-if="coverageInfo.components.filter((c) => c.coverage === 'none').length > 8"
                      class="text-[9px] text-ctp-overlay0"
                    >+{{ coverageInfo.components.filter((c) => c.coverage === 'none').length - 8 }}</span>
                  </div>
                </div>
                <p class="text-[9px] text-ctp-overlay0 leading-relaxed">
                  {{ t('assetMgmt.coverage.hint') }}
                </p>
              </div>
            </div>

            <!-- 基线变更（三视图 diff · 概览：变更文件清单） -->
            <div v-if="diffMode" class="panel overflow-hidden">
              <div class="panel-header">
                <span class="flex items-center gap-2">
                  <ArrowsRightLeftIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.diff.title') }}
                </span>
                <span class="flex items-center gap-1">
                  <span v-if="baselineDiffData?.aligned" class="chip bg-ctp-green/15 text-ctp-green">{{ t('assetMgmt.diff.aligned') }}</span>
                  <span v-else-if="baselineDiffData?.stale" class="chip bg-ctp-yellow/15 text-ctp-yellow">{{ t('assetMgmt.diff.stale', { n: totalChanged }) }}</span>
                  <span v-else class="chip bg-ctp-surface0 text-ctp-subtext0">{{ t('assetMgmt.diff.noBaseline') }}</span>
                </span>
              </div>
              <div v-if="diffLoading" class="p-3 text-[10px] text-ctp-overlay0">{{ t('assetMgmt.reconciling') }}</div>
              <div v-else-if="!baselineDiffData" class="p-3 text-[10px] text-ctp-overlay0">—</div>
              <div v-else-if="!totalChanged" class="p-3 text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.noChanges') }}</div>
              <div v-else class="p-3 grid grid-cols-3 gap-3">
                <div v-for="col in [
                  { key: 'added' as const, label: t('assetMgmt.diff.added'), tone: 'text-ctp-green', files: baselineDiffData.files.added },
                  { key: 'modified' as const, label: t('assetMgmt.diff.modified'), tone: 'text-ctp-yellow', files: baselineDiffData.files.modified },
                  { key: 'deleted' as const, label: t('assetMgmt.diff.deleted'), tone: 'text-ctp-red', files: baselineDiffData.files.deleted },
                ]" :key="col.key" class="min-w-0">
                  <div class="flex items-center gap-1 mb-1">
                    <span class="text-[10px] font-semibold" :class="col.tone">{{ col.label }}</span>
                    <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ col.files.length }}</span>
                  </div>
                  <div class="space-y-0.5 max-h-40 overflow-y-auto">
                    <div v-for="f in col.files.slice(0, 30)" :key="f" class="font-mono text-[9px] text-ctp-subtext0 truncate" :title="f">{{ f }}</div>
                    <div v-if="col.files.length > 30" class="text-[9px] text-ctp-overlay0">+{{ col.files.length - 30 }}</div>
                    <div v-if="!col.files.length" class="text-[9px] text-ctp-overlay0">—</div>
                  </div>
                </div>
              </div>
              <div v-if="baselineDiffData && baselineDiffData.dirty" class="px-3 pb-2 text-[9px] text-ctp-overlay0">
                {{ t('assetMgmt.diff.dirty') }}: {{ baselineDiffData.dirty }}
              </div>
            </div>
          </template>

          <!-- 语义资产：按组件树文件树形式逐层展开(选 L0/L1 时以该层为初始列表) -->
          <template v-if="tab === 'semantic'">
            <template
              v-for="row in semanticTreeRows"
              :key="row.key"
            >
              <!-- 组件(目录)节点 -->
              <template v-if="row.t === 'comp'">
                <div
                  v-for="g in row.g ? [row.g] : []"
                  :key="row.key + ':h'"
                >
              <div
                class="flex items-center gap-1.5 px-1 pt-1.5 pb-0.5"
                :style="{ paddingLeft: (row.depth * 12) + 'px' }"
              >
                <button
                  v-if="g.key !== OTHER_KEY && treeLevel > 0 && (hasChildren(g.key) || (subtreeCount.get(g.key) ?? 0) > 0)"
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
                <span class="text-[10px] font-semibold text-ctp-subtext1 truncate" :title="compMetaText(g.key) || undefined">{{ g.name }}</span>
                <!-- KB 降级提示：组件树来自本地快照/资产 scopeKey，名称可能与 KB 目录不一致 -->
                <span
                  v-if="!compCatalog.length && g.key !== OTHER_KEY"
                  class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                  :title="t('assetMgmt.localSnapshotHint')"
                >{{ t('assetMgmt.localSnapshot') }}</span>
                <!-- 拷贝/引用 名称+ID：与 KB 组件目录严格同名同 ID，供资产管理对话精准对接 -->
                <template v-if="g.key !== OTHER_KEY">
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-green p-0.5 shrink-0"
                    :title="t('assetMgmt.compCopy')"
                    @click="copyCompRef(g.key, g.name, g.key)"
                  >
                    <CheckIcon
                      v-if="copiedKey === g.key"
                      class="w-3 h-3 text-ctp-green"
                    />
                    <ClipboardDocumentIcon
                      v-else
                      class="w-3 h-3"
                    />
                  </button>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-blue p-0.5 shrink-0"
                    :title="t('assetMgmt.compRef')"
                    @click="referenceComp(g.name, g.key)"
                  >
                    <ChatBubbleLeftRightIcon class="w-3 h-3" />
                  </button>
                </template>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ subtreeCount.get(g.key) ?? 0 }}</span>
                <template v-if="g.key !== OTHER_KEY">
                  <span
                    v-if="compCoverage(g.key)"
                    class="chip !text-[8px] shrink-0"
                    :class="compCoverage(g.key) === 'full' ? 'bg-ctp-green/15 text-ctp-green' : compCoverage(g.key) === 'partial' ? 'bg-ctp-yellow/15 text-ctp-yellow' : 'bg-ctp-surface0 text-ctp-overlay1'"
                  >{{ t(`assetMgmt.coverage.state.${compCoverage(g.key)}`) }}</span>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                    :title="t('assetMgmt.chatExtractHint')"
                    @click="askExtractComponent(g.key, g.name)"
                  >
                    <SparklesIcon class="w-3 h-3" />
                  </button>
                  <button
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5"
                    :title="t('assetMgmt.graph.viewCompGraph')"
                    @click="openGraphTab('comp', g.key, g.name)"
                  >
                    <Squares2X2Icon class="w-3 h-3" />
                  </button>
                </template>
              </div>
                </div>
              </template>
              <!-- 文件节点：独有文件，折叠其下资产 -->
              <div
                v-else-if="row.t === 'file'"
                class="flex items-center gap-1.5 px-1 py-0.5"
                :style="{ paddingLeft: (row.depth * 12) + 'px' }"
              >
                <button
                  v-if="treeLevel === 3"
                  class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                  @click="toggleFileOpen(row.fk!)"
                >
                  <ChevronDownIcon
                    v-if="fileOpen[row.fk!] !== false"
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
                <DocumentTextIcon class="w-3 h-3 text-ctp-overlay1 shrink-0" />
                <span
                  class="font-mono text-[10px] text-ctp-subtext1 truncate"
                  :title="row.file"
                >{{ fileBase(row.file!) }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ row.n }}</span>
              </div>
              <!-- 资产卡片(挂文件下/组件直属) -->
              <div
                v-else
                class="mt-0.5"
                :style="{ paddingLeft: (row.depth * 12) + 'px' }"
              >
                <div
                  v-for="a in row.a ? [row.a] : []"
                  :key="row.key"
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
                  <span
                    v-if="diffMode && changeMarkById.get(a.id)"
                    class="chip !text-[9px] shrink-0"
                    :class="changeMarkById.get(a.id) === 'added' ? 'bg-ctp-green/15 text-ctp-green' : changeMarkById.get(a.id) === 'deleted' ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-yellow/15 text-ctp-yellow'"
                    :title="diffMarkLabel(changeMarkById.get(a.id))"
                  >
                    <ArrowsRightLeftIcon class="w-2.5 h-2.5 inline -mt-0.5" />
                    {{ diffMarkLabel(changeMarkById.get(a.id)) }}
                  </span>
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
                    v-if="a.kind === 'entity' || a.kind === 'state'"
                    class="text-ctp-overlay0 hover:text-ctp-teal p-0.5"
                    :title="t('assetMgmt.viewDiagram')"
                    @click="openAssetDiagram(a)"
                  >
                    <ChartBarSquareIcon class="w-3 h-3" />
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
                  <PseudoExplainer :asset-id="a.id" :initial="a.pseudo" />
                  <div v-if="a.detail?.fields?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.fields') }}
                    </div>
                    <div
                      v-for="f in a.detail.fields"
                      :key="f.name"
                      class="pl-2"
                    >
                      <span class="font-mono text-ctp-text">{{ f.name }}</span><span class="text-ctp-overlay0">: {{ f.type ?? '—' }}</span> {{ f.semantic ? `— ${f.semantic}` : '' }}
                    </div>
                  </div>
                  <div v-if="a.detail?.steps?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.steps') }}
                    </div>
                    <div
                      v-for="(s, si) in a.detail.steps"
                      :key="si"
                      class="pl-2"
                    >
                      {{ s.order ?? si + 1 }}. {{ s.semantic }}
                    </div>
                  </div>
                  <div v-if="a.detail?.branches?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.branches') }}
                    </div>
                    <div
                      v-for="(b, bi) in a.detail.branches"
                      :key="bi"
                      class="pl-2"
                    >
                      <span class="font-mono text-ctp-text">if {{ b.condition ?? '?' }}</span> → {{ b.then ?? '—' }}<span v-if="b.else"> / else {{ b.else }}</span>
                    </div>
                  </div>
                  <div v-if="a.detail?.relations?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.relations') }}
                    </div>
                    <div
                      v-for="(r, ri) in a.detail.relations"
                      :key="ri"
                      class="pl-2"
                    >
                      <span class="chip !text-[8px] bg-ctp-surface0 text-ctp-overlay1">{{ r.type ?? 'ref' }}</span><span class="font-mono text-ctp-text">{{ r.target ?? '?' }}</span><span
                        v-if="r.methods?.length"
                        class="font-mono text-ctp-overlay0"
                      >{{ r.methods.join('/') }}</span><span
                        v-if="r.semantic"
                        class="text-ctp-subtext0"
                      > — {{ r.semantic }}</span>
                    </div>
                  </div>
                  <div v-if="a.detail?.states?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.states') }}
                    </div>
                    <div class="pl-2 flex flex-wrap gap-1">
                      <span
                        v-for="(st, si) in a.detail.states"
                        :key="si"
                        class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext0"
                      >{{ st.name }}<template v-if="st.initial"> · {{ t('assetMgmt.stateInitial') }}</template><template v-if="st.final"> · {{ t('assetMgmt.stateFinal') }}</template></span>
                    </div>
                  </div>
                  <div v-if="a.detail?.transitions?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.transitions') }}
                    </div>
                    <div
                      v-for="(tr, ti) in a.detail.transitions"
                      :key="ti"
                      class="pl-2 font-mono text-ctp-overlay0"
                    >
                      {{ tr.from ?? '?' }} → {{ tr.to ?? '?' }}<template v-if="tr.event">
                        on {{ tr.event }}
                      </template><template v-if="tr.condition">
                        [{{ tr.condition }}]
                      </template>
                    </div>
                  </div>
                  <div v-if="a.detail?.configSource || a.detail?.constraints?.length || a.detail?.thresholds?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.constraints') }}
                    </div>
                    <div
                      v-if="a.detail?.configSource"
                      class="pl-2"
                    >
                      {{ t('assetMgmt.configSource') }}: <span class="font-mono text-ctp-overlay0">{{ a.detail.configSource }}</span>
                    </div>
                    <div
                      v-for="(c, ci) in (a.detail?.constraints ?? [])"
                      :key="`c${ci}`"
                      class="pl-2 font-mono text-ctp-text"
                    >
                      {{ c }}
                    </div>
                    <div
                      v-for="(th, thi) in (a.detail?.thresholds ?? [])"
                      :key="`t${thi}`"
                      class="pl-2"
                    >
                      <span class="font-mono text-ctp-text">{{ th.key ?? '?' }}</span><span class="text-ctp-overlay0"> = {{ th.value ?? '?' }}</span>
                    </div>
                  </div>
                  <div v-if="a.detail?.invariants?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.invariants') }}
                    </div>
                    <div
                      v-for="(iv, ii) in a.detail.invariants"
                      :key="ii"
                      class="pl-2 text-ctp-subtext0"
                    >
                      • {{ iv }}
                    </div>
                  </div>
                  <div v-if="(a.tags?.length || a.detail?.tags?.length)">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      {{ t('assetMgmt.tags') }}
                    </div>
                    <div class="pl-2 flex flex-wrap gap-1">
                      <span
                        v-for="(tg, tgi) in (a.tags ?? a.detail!.tags ?? [])"
                        :key="tgi"
                        class="chip !text-[8px] bg-ctp-blue/15 text-ctp-blue"
                      >{{ tg }}</span>
                    </div>
                  </div>
                  <div v-if="a.astRefs?.length">
                    <div class="font-medium text-ctp-mauve mb-0.5">
                      AST
                    </div>
                    <div
                      v-for="(r, ri) in a.astRefs.slice(0, 8)"
                      :key="ri"
                      class="pl-2 font-mono text-ctp-overlay0"
                    >
                      {{ r.file }}:L{{ r.startLine }}-L{{ r.endLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span>
                    </div>
                  </div>
                </div>
              </div>
                </div>
            </template>
            <p
              v-if="!semanticTreeRows.length && !loading"
              class="text-xs text-ctp-overlay0 text-center py-8"
            >
              {{ t('assetMgmt.emptySemantic') }}
            </p>
          </template>

          <!-- 组件资产：按 KB 组件树文件目录树形式逐层展开(选 L0/L1 时以该层为初始列表) -->
        </div>
      </div>

      <!-- 分割线 -->
      <div
        class="w-4 shrink-0 -mx-0.5 flex items-center justify-center cursor-col-resize select-none touch-none group"
        :class="dragging ? 'cursor-col-resize' : ''"
        @pointerdown="onSplitPointerDown"
      >
        <div
          class="h-12 w-0.5 rounded-full bg-ctp-overlay1/40 transition-colors group-hover:bg-ctp-blue/60"
          :class="dragging ? '!bg-ctp-blue/70' : ''"
        />
      </div>

      <!-- 右：agent 对话区 -->
      <div class="min-h-0 min-w-0 flex-1 flex flex-col gap-2">
        <AnalysisChat
          class="flex-1 min-h-0"
          :turns="turns"
          :busy="busy"
          :busy-label="busyLabel"
          :tool-trail="toolTrail"
          :insert-draft="chatDraft"
          :title="t('assetMgmt.chatTitle')"
          :diagram-skill="diagramSkill"
          @send="onSend"
          @delete-turn="onDeleteTurn"
          @refresh-asset="onRefreshAsset"
          @toggle-diagram-skill="toggleDiagramSkill"
          @convention-confirm="onConventionConfirm"
          @convention-ignore="onConventionIgnore"
          @stop="stopChat"
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
            <p class="text-[9px] text-ctp-peach">
              {{ t('assetMgmt.purgeConfirm.reqRegen') }}
            </p>
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
            <p class="text-[9px] text-ctp-blue">
              {{ t('assetMgmt.purgeConfirm.taskRegen') }}
            </p>
          </div>

          <p
            v-if="!purgeResult?.impact?.requirements?.length && !purgeResult?.impact?.tasks?.length"
            class="text-[10px] text-ctp-green"
          >
            {{ t('assetMgmt.purgeConfirm.noImpact') }}
          </p>
        </div>

        <div class="shrink-0 border-t border-ctp-surface0 px-4 py-2.5 flex justify-end gap-2">
          <button
            class="btn btn-ghost"
            :disabled="purgeBusy"
            @click="cancelPurge"
          >
            {{ t('assetMgmt.purgeConfirm.cancel') }}
          </button>
          <button
            class="btn btn-red"
            :disabled="purgeBusy"
            @click="confirmPurge"
          >
            {{ purgeBusy ? t('assetMgmt.purgeConfirm.deleting') : t('assetMgmt.purgeConfirm.confirm') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 静态资产图：entity → 类图(字段/方法)，state → 状态图(状态+迁移) -->
    <div
      v-if="diagramModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      @click.self="diagramModalOpen = false"
    >
      <div class="flex flex-col w-full max-w-3xl h-[80vh] rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden">
        <div class="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-ctp-surface0">
          <ChartBarSquareIcon class="w-4 h-4 text-ctp-teal" />
          <h3 class="text-sm font-semibold text-ctp-text truncate">
            {{ diagramModalTitle }}
          </h3>
          <span class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diagramHint') }}</span>
          <span class="flex-1" />
          <button
            class="btn btn-ghost !py-1"
            @click="diagramModalOpen = false"
          >
            {{ t('assetMgmt.purgeConfirm.cancel') }}
          </button>
        </div>
        <div class="flex-1 min-h-0 p-3">
          <p
            v-if="diagramModalLoading"
            class="text-xs text-ctp-overlay1 text-center py-10"
          >
            {{ t('assetMgmt.diagramLoading') }}
          </p>
          <p
            v-else-if="!diagramModalItems.length"
            class="text-xs text-ctp-overlay0 text-center py-10"
          >
            {{ t('assetMgmt.diagramEmpty') }}
          </p>
          <template v-else>
            <div
              v-for="d in diagramModalItems"
              :key="d.assetId"
              class="h-full min-h-0"
            >
              <DiagramCard
                :title="`${d.name} (${t(`assetMgmt.diagramType.${d.type}`)})`"
                :diagrams="{ mermaid: d.mermaid }"
                :allowed-langs="['mermaid']"
              />
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
