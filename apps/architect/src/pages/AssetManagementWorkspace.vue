<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, ChevronDownIcon, ChevronRightIcon, ArrowPathIcon,
  SparklesIcon, CubeTransparentIcon, AdjustmentsHorizontalIcon, ServerStackIcon, Squares2X2Icon,
  ChatBubbleOvalLeftEllipsisIcon, ClipboardDocumentListIcon, ClipboardDocumentIcon, ScaleIcon, EyeIcon, TrashIcon,
  ChartBarSquareIcon, StopIcon, XMarkIcon, ArrowsRightLeftIcon, ChatBubbleLeftRightIcon,
  DocumentTextIcon, CheckIcon, CodeBracketIcon,
} from '@heroicons/vue/24/outline'
import { apiGet } from '@/services/api-client'
import { kindChipClass, levelChipClass } from '@/services/semantic-kind-style'
import FileSourceCard from '@/components/assets/FileSourceCard.vue'
import { useRouter } from 'vue-router'
import RequirementHistoryModal from '@/components/requirements/RequirementHistoryModal.vue'
import SemanticGraphView, { type GraphTabDef } from '@/components/assets/SemanticGraphView.vue'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { semanticAssetService, type AssetCompareResult, type BaselineDiff, type CoverageInfo, type ExtractPlanResult, type FrameworkPreview, type FrameworkResult, type SemanticBatchResult, type SemanticPurgeResult, type SemanticStatsResult, type SyncExtractJob, type UnownedCrossLink, type UnownedExtractJob, type UnownedFileEntry } from '@/services/semantic-asset-service'
import { gitService, type GitLogEntry } from '@/services/git-service'
import { kbAssetService } from '@/services/kb-assets'
import { requirementService } from '@/services/requirement-service'
import { namingService, type NamingConvention } from '@/services/naming-service'
import { useSplitPane } from '@/composables/useSplitPane'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { useConversationStore } from '@/stores/conversation-store'
import ConversationDock from '@/components/chat/ConversationDock.vue'
import type { AssetDetail, AssetDiagramItem, ConversationDetail, GraphFileEntry, SemanticAsset, SemanticAssetKind, SemanticAssetLevel } from '@/types'

const { t } = useI18n()
const router = useRouter()

// ---- 对话模型: 统一用顶部工具栏选择(读同一 localStorage 键 topoone-model-architect, 透传后端) ----

// ---- P1 全局会话栏: 聊天引擎在 conversation-store，页面经钩子响应工具事件 ----
const { splitPct, dragging, boxRef: splitBoxRef, onDown: onSplitPointerDown } = useSplitPane()
const conv = useConversationStore()
const historyOpen = ref(false)
/** 对话回合反应式视图(提取进度等页面写回合，dock 内同步渲染)。 */
const turns = computed(() => conv.turns)
/** 直连提取进度(原复用对话 busy/abort，会话引擎化后独立)。 */
const extractBusy = ref(false)
const extractAbort = ref<AbortController | null>(null)

/** 页面级工具事件反应：资产提取刷新 / 规约提案挂卡(dock 内卡片) / 提取后兜底刷新。 */
const _unregChatHook = conv.registerChatHook((ev, ctx) => {
  if (ev.type === 'tool_result' && ev.ok) {
    if (ev.tool === 'asset.semantic.extract') markExtracted()
    else if (ev.tool === 'convention.propose') void onConventionProposed(ctx.turnIndex)
  } else if (ev.type === 'done') {
    if (extractDirty) refreshAfterExtract()
  }
})
onUnmounted(() => _unregChatHook())

/** dock 内「刷新资产」卡事件(全局会话栏代发)。 */
function _onDockRefreshAsset(e: Event) {
  const id = (e as CustomEvent).detail as string
  onRefreshAsset(id)
}
onMounted(() => window.addEventListener('arch:refresh-asset', _onDockRefreshAsset))
onUnmounted(() => window.removeEventListener('arch:refresh-asset', _onDockRefreshAsset))

/** 确保 dock 当前是资产会话(非资产会话时新开)。 */
function ensureAssetConversation() {
  if (!conv.activeId || conv.activeKind !== 'asset') {
    conv.newConversation('asset', t('assetMgmt.chatTitle'))
  }
}
/** 导入指定历史会话(资产管理 → 全局会话栏)。 */
function importHistory(detail: ConversationDetail) {
  conv.applyConversation(detail)
  conv.setDockOpen(true)
  historyOpen.value = false
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
    const def: GraphTabDef = { id: key, kind, title, compId: kind === 'comp' ? id : undefined, assetId: kind === 'asset' ? id : undefined, fileId: kind === 'file' ? id : undefined }
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

// ---- 图谱文件索引(>500 资产强制手动圈定)：按 tab 范围预算 文件→资产数/组件归属 ----
/** all/comp tab：范围内每个首锚点文件的资产数与归属组件；asset/file tab 无需圈定。 */
function buildGraphFileIndex(gt: GraphTabDef): GraphFileEntry[] {
  if (gt.kind !== 'all' && gt.kind !== 'comp') return []
  const inScope = (a: SemanticAsset) =>
    gt.kind === 'all' ? true : componentsOf(a).includes(gt.compId!)
  const byFile = new Map<string, { n: number; comps: Set<string> }>()
  for (const a of items.value) {
    if (a.status === 'deleted' || !inScope(a)) continue
    const f = a.astRefs?.[0]?.file || ''
    if (!f) continue
    const e = byFile.get(f) ?? { n: 0, comps: new Set<string>() }
    e.n += 1
    for (const c of componentsOf(a)) e.comps.add(c)
    byFile.set(f, e)
  }
  return [...byFile.entries()].map(([file, e]) => ({
    file,
    dir: file.includes('/') ? file.slice(0, file.lastIndexOf('/')) : '/',
    n: e.n,
    comps: [...e.comps],
  }))
}
const graphFileIndexes = computed<Record<string, GraphFileEntry[]>>(() => {
  const out: Record<string, GraphFileEntry[]> = {}
  for (const gt of graphTabs.value) out[gt.id] = buildGraphFileIndex(gt)
  return out
})
const graphCompNames = computed<Record<string, string>>(() =>
  Object.fromEntries(compCatalog.value.map((c) => [c.assetId, c.name])))
const q = ref('')
// shallowRef：3776+ 资产整表深代理开销可观；树按整表/整行替换更新，
// 行内变更(refreshOne/懒加载 detail)后手动克隆数组触发。
const items = shallowRef<SemanticAsset[]>([])
const loading = ref(false)
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
  // 按有效态翻转(而非手动记录)：level<2 下未操作组件有效态=闭，首点即展开
  compOpen[id] = !compExpandState(id)
}

/** 树展开级别(工具栏单按钮循环)——只定义列表「默认展开态」，点击时重置手动开合，
 *  此后用户逐组件/逐文件手动开合不受层级限制(手动值 > 层级默认值)：
 *  0 全部收起(只显示顶层组件) → 1 组件展开(所有组件组头) → 2 文件展开(组件+文件) → 3 全部展开(含资产)。 */
const treeLevel = ref(1)
const TREE_LEVEL_MAX = 3
function cycleTreeLevel() {
  treeLevel.value = treeLevel.value >= TREE_LEVEL_MAX ? 0 : treeLevel.value + 1
  // 重置手动开合 → 列表回到该层级的默认展开态
  for (const k of Object.keys(compOpen)) delete compOpen[k]
  for (const k of Object.keys(fileOpen)) delete fileOpen[k]
}

/** 组件子节点展开态：手动开合优先；未手动操作时按层级默认(level>=1 展开)。 */
function compChildrenOpen(cid: string): boolean {
  if (compOpen[cid] === true) return true
  if (compOpen[cid] === false) return false
  return treeLevel.value >= 1
}

/** 组件有效展开态(箭头图标与翻转的单一事实源)：
 *  手动值优先；默认 = 有子组件且 level>=1(子头可见) 或 level>=2(文件可见)。
 *  图标态若与内容渲染不同源，就会出现"箭头开、内容闭"的错位。 */
function compExpandState(cid: string): boolean {
  if (compOpen[cid] === true) return true
  if (compOpen[cid] === false) return false
  return (treeLevel.value >= 1 && hasChildren(cid)) || treeLevel.value >= 2
}

/** 文件有效展开态(同上，默认层级 3)。 */
function fileExpandState(fk: string): boolean {
  if (fileOpen[fk] === true) return true
  if (fileOpen[fk] === false) return false
  return treeLevel.value >= 3
}
/** 组件内容(独有文件)展开态：手动展开跨层级生效；默认层级 2。 */
function compContentOpen(cid: string): boolean {
  return compOpen[cid] === true || (compOpen[cid] !== false && treeLevel.value >= 2)
}
/** 组件直属资产展开态：手动展开跨层级生效；默认层级 3。 */
function compDirectOpen(cid: string): boolean {
  return compOpen[cid] === true || (compOpen[cid] !== false && treeLevel.value >= 3)
}
/** 文件下资产展开态：手动展开跨层级生效；默认层级 3。 */
function fileAssetsOpen(fk: string): boolean {
  return fileOpen[fk] === true || (fileOpen[fk] !== false && treeLevel.value >= 3)
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
                 fk?: string; unowned?: boolean; extractable?: boolean }
const fileOpen = reactive<Record<string, boolean>>({})
const subtreeCount = ref(new Map<string, number>())
/** 组件是否有可折叠内容(组头箭头渲染依据)；随 semanticTreeRows 重算填充。 */
const compCollapsible = ref(new Map<string, boolean>())
/** 基线对比 · 组件子树变化上卷(组头彩色计数 chip)；随 semanticTreeRows 重算填充。 */
const diffRollup = ref(new Map<string, { changed: number; added: number; deleted: number }>())
function toggleFileOpen(key: string) {
  fileOpen[key] = !fileExpandState(key)
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
  // 组件是否有可折叠内容(子组件/资产/独有文件任一)：组头箭头渲染依据。
  // 零资产纯文件叶子组件(如未提取的 Stream 模块)没有它时箭头不渲染 → 文件行无法收拢。
  const collap = new Map<string, boolean>()
  // 基线对比 · 组件级变化归属：直接归属(资产→componentsOf 多归属，无归属→OTHER)
  // + 子树上卷(父组件头显示整个子树的彩色计数)。文件行计数走 diffFileCounts。
  const diffSums = new Map<string, { changed: number; added: number; deleted: number }>()
  const diffDirect = new Map<string, { changed: number; added: number; deleted: number }>()
  if (diffMode.value && cmpBucketById.value.size) {
    const byId = new Map(items.value.map((x) => [x.id, x]))
    for (const [id, bucket] of cmpBucketById.value) {
      const a = byId.get(id)
      if (!a) continue
      const cids = componentsOf(a)
      for (const cid of (cids.length ? cids : [OTHER_KEY])) {
        const e = diffDirect.get(cid) ?? { changed: 0, added: 0, deleted: 0 }
        if (bucket === 'modified') e.changed += 1
        else if (bucket === 'added') e.added += 1
        else e.deleted += 1
        diffDirect.set(cid, e)
      }
    }
  }
  const diffSub = (c: CompNode): { changed: number; added: number; deleted: number } => {
    const acc = { ...(diffDirect.get(c.id) ?? { changed: 0, added: 0, deleted: 0 }) }
    for (const ch of children.get(c.id) ?? []) {
      const s = diffSub(ch)
      acc.changed += s.changed
      acc.added += s.added
      acc.deleted += s.deleted
    }
    diffSums.set(c.id, acc)
    return acc
  }
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
      // 路径节点：自身不渲染，仍下探(选中集可能命中后代)；下探条件与普通组件一致
      if (compChildrenOpen(c.id)) {
        for (const ch of children.get(c.id) ?? []) walk(ch, depth + 1)
      }
      return
    }
    countSub(c)
    collap.set(c.id, (children.get(c.id)?.length ?? 0) > 0
      || (counts.get(c.id) ?? 0) > 0 || uniqueFiles(c).length > 0)
    rows.push({ key: c.id, t: 'comp', depth,
                g: { key: c.id, name: c.name, depth, assets: [], hierLevel: c.hierLevel } })
    const expand = compChildrenOpen(c.id)     // 子组件
    const content = compContentOpen(c.id)     // 独有文件
    if (!expand && !content) return           // 整支收起(手动关闭或层级默认收起)
    if (expand) {
      for (const ch of children.get(c.id) ?? []) walk(ch, depth + 1)
    }
    if (content) {
      for (const f of uniqueFiles(c)) {
        const fk = c.id + '::' + f
        const list = byFile.get(f) ?? []
        if (hideFileless.value && !list.length) continue
        rows.push({ key: 'f:' + fk, t: 'file', depth: depth + 1, file: f, n: list.length, fk })
        if (fileAssetsOpen(fk)) {
          for (const a of list) rows.push({ key: 'a:' + a.id + ':' + fk, t: 'asset', depth: depth + 2, a })
        }
      }
    }
    if (compDirectOpen(c.id)) {
      for (const a of direct.get(c.id) ?? []) rows.push({ key: 'a:' + a.id, t: 'asset', depth: depth + 1, a })
    }
  }
  for (const r of roots) { walk(r, 0); diffSub(r) }
  // 「未归属」组(单一分组)：KB owns 未覆盖的文件 ∪ 无组件归属的孤儿资产。
  // 文件并集去重——已提取资产挂其锚点文件下(与组件组同构)；仅存在于 owns 缺口
  // 清单的文件显示「未提取」。同受组头开合(compOpen)与树层级(treeLevel)控制。
  if ((otherFiles.size || otherDirect.length || unownedFiles.value.length)
      && (all || sel.has(OTHER_KEY))) {
    const fileAssets = new Map<string, SemanticAsset[]>(otherFiles)
    const unownedEntry = new Map(unownedFiles.value.map((x) => [x.path, x]))
    for (const f of unownedFiles.value) {
      if (!fileAssets.has(f.path)) fileAssets.set(f.path, [])
    }
    counts.set(OTHER_KEY, fileAssets.size + otherDirect.length)
    collap.set(OTHER_KEY, true)
    diffSums.set(OTHER_KEY, diffDirect.get(OTHER_KEY) ?? { changed: 0, added: 0, deleted: 0 })
    rows.push({ key: OTHER_KEY, t: 'comp', depth: 0,
                g: { key: OTHER_KEY, name: t('assetMgmt.unownedFiles'), depth: 0, assets: [] } })
    if (compContentOpen(OTHER_KEY)) {
      for (const f of [...fileAssets.keys()].sort()) {
        const fk = OTHER_KEY + '::' + f
        const list = fileAssets.get(f) ?? []
        if (hideFileless.value && !list.length) continue
        rows.push({ key: 'f:' + fk, t: 'file', depth: 1, file: f, n: list.length,
                    fk, unowned: true, extractable: unownedEntry.get(f)?.extractable })
        if (fileAssetsOpen(fk)) {
          for (const a of list) rows.push({ key: 'a:' + a.id + ':' + fk, t: 'asset', depth: 2, a })
        }
      }
    }
    if (compDirectOpen(OTHER_KEY)) {
      for (const a of otherDirect) rows.push({ key: 'a:' + a.id, t: 'asset', depth: 1, a })
    }
  }
  subtreeCount.value = counts
  compCollapsible.value = collap
  diffRollup.value = diffSums
  return rows
})

const scopeSummary = computed(() => {
  if (!scopeSel.value.length) return t('assetMgmt.scopeAll')
  // 命中/全量：分母用全库总数(stats)，而非过滤后的列表长(否则恒 x/x 无意义)
  const total = overviewStats.value?.total ?? items.value.length
  return `${items.value.length}/${total}`
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
    // ⚠️ 单页拉全(页大小 10000, cap 20000)：后端本就全量排序后切片，两页各跑一遍
    // 全量(取数+分组+count)纯属重复——实测单请求省 ~1.5s。>10000 时循环仍可续页。
    const PAGE = 10000
    const CAP = 20000
    let all: SemanticAsset[] = []
    let total = 0
    for (let offset = 0; offset < CAP; offset += PAGE) {
      const r = await semanticAssetService.searchPage(q.value, kind.value || undefined, {
        limit: PAGE, offset,
        scope: scopeParams(), level: level.value || undefined,
      })
      all = all.concat(r.items)
      total = r.total
      if (all.length >= total || !r.items.length) break
    }
    items.value = all
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
  if (diffMode.value) {
    loadBaselineDiff()
    void loadCommitOptions()
    void runCompare()
  }
}

// ---- 任意 head 对 vs head/工作区 资产/组件对比(基准缺省=KB 基线 baselineCommit；缓存态) ----
const cmpBase = ref('')            // '' = KB 基线(baselineCommit)
const cmpTarget = ref('worktree')  // 'worktree' = 工作区(含未提交/未跟踪)
const commitOptions = ref<GitLogEntry[]>([])
const baselineSha = ref('')
const compareData = ref<AssetCompareResult | null>(null)
const compareError = ref('')
const compareLoading = ref(false)

async function loadCommitOptions() {
  const res = await gitService.commitLog(50)
  commitOptions.value = res.entries
  baselineSha.value = res.baseline
}

async function runCompare() {
  compareLoading.value = true
  compareError.value = ''
  try {
    compareData.value = await semanticAssetService.assetCompare(
      cmpBase.value || undefined,
      cmpTarget.value || 'worktree',
    ) ?? null
  } catch (e) {
    compareData.value = null
    compareError.value = e instanceof Error && e.message ? e.message : t('assetMgmt.diff.cmpFailed')
  } finally {
    compareLoading.value = false
  }
}

// ---- 提取闭环：待提取文件(目标侧无资产匹配) → 按文件范围补提(分批) → 重新对比 ----
const extractingPending = ref(false)
/** 可经工作区提取锚定的待提取子集(目标侧内容==工作区内容；旧响应无此字段时回退全集)。 */
const pendingExtractable = computed(() => {
  const p = compareData.value?.assets.pending
  if (!p) return []
  return p.extractable?.length ? p.extractable : (p.extractableCount === 0 ? [] : p.files)
})

async function extractPendingAndRecompare() {
  const files = pendingExtractable.value
  if (!files.length) return
  if (!window.confirm(t('assetMgmt.diff.extractConfirm', { n: files.length }))) return
  extractingPending.value = true
  let extracted = 0
  try {
    const BATCH = 10
    for (let i = 0; i < files.length; i += BATCH) {
      const res = await semanticAssetService.extract({ type: 'files', files: files.slice(i, i + BATCH) })
      extracted += res?.count ?? 0
    }
  } catch (e) {
    // 失败即止：保留错误信息(不再自动重比冲掉)，用户可手动「重新对比」
    compareError.value = e instanceof Error && e.message ? e.message : t('assetMgmt.diff.cmpFailed')
    extractingPending.value = false
    return
  } finally {
    extractingPending.value = false
  }
  if (!extracted) {
    // 全程零产出(清单多为不可提取文件 / LLM 不可用降级)：如实提示而非静默重比
    compareError.value = t('assetMgmt.diff.extractZero')
    return
  }
  await Promise.all([loadSemantic(), runCompare()])
}

// ---- 未归属组件文件：清单 + 单文件/循环批量提取 + 跨组件关联 ----
const unownedFiles = ref<UnownedFileEntry[]>([])
const unownedMeta = ref<{ unownedCount: number; ownedCount: number; totalFiles: number; truncated: boolean } | null>(null)
const unownedLoading = ref(false)
/** 文件(norm path) → 跨组件关联(计数 + 按组件聚合 + 样本)。 */
const unownedLinks = ref<Map<string, UnownedCrossLink>>(new Map())

async function loadUnownedFiles() {
  unownedLoading.value = true
  try {
    const r = await semanticAssetService.unownedFiles()
    unownedFiles.value = r.files
    unownedMeta.value = { unownedCount: r.unownedCount, ownedCount: r.ownedCount, totalFiles: r.totalFiles, truncated: !!r.truncated }
  } catch {
    unownedFiles.value = []
    unownedMeta.value = null
  } finally {
    unownedLoading.value = false
  }
}

async function loadUnownedLinks() {
  try {
    const r = await semanticAssetService.unownedCrossLinks()
    unownedLinks.value = new Map(r.links.map((l) => [l.file, l]))
  } catch {
    unownedLinks.value = new Map()
  }
}

/** 单文件提取：完成后刷新未归属清单(该文件 assetCount 变化)与资产列表。
 *  全程写对话区(与组件提取同款 user+assistant 双 turn)——提取是后端异步管线，
 *  不写对话用户看不到任何反馈。 */
const unownedExtractingOne = ref('')
async function extractUnownedFile(path: string) {
  if (unownedExtractingOne.value) return
  if (unownedExtracting.value) return
  turns.value.push({ role: 'user', content: t('assetMgmt.unowned.chatOne', { file: path }) })
  const idx = turns.value.push({ role: 'assistant', content: t('assetMgmt.compExtractRunning') }) - 1
  unownedExtractingOne.value = path
  try {
    const res = await semanticAssetService.extract(
      { type: 'files', files: [path] },
      kinds.map((k) => k.value),
      { level: 'implementation' },
    )
    const n = res.count ?? res.assets?.length ?? 0
    if (res.error) {
      turns.value[idx].content = `${t('assetMgmt.unowned.chatOneFailed')}\n${res.error}`
    } else if (n > 0) {
      turns.value[idx].content = t('assetMgmt.unowned.chatOneDone', { n })
      turns.value[idx].assets = res.assets ?? []
    } else {
      turns.value[idx].content = t('assetMgmt.unowned.chatOneEmpty')
    }
    refreshAfterExtract()
    await loadUnownedFiles()
  } catch (err: any) {
    turns.value[idx].content = err?.message || t('assetMgmt.batchFailed')
  } finally {
    unownedExtractingOne.value = ''
  }
}

// ---- 循环批量提取 = 后端作业(daemon 线程)：页面关闭不影响，进度靠轮询。 ----
// 纯增量操作(只新增/更新资产)：无需 confirm；中断后重按自动续传(跳过已提取)。
const unownedJob = ref<UnownedExtractJob | null>(null)
let unownedJobTimer: ReturnType<typeof setInterval> | null = null
let unownedJobDoneSeen = -1
/** 批量作业的对话区 turn 下标(完成后回填摘要)。 */
const unownedJobChatIdx = ref(-1)

const unownedExtracting = computed(() => !!unownedJob.value?.running)

/** 进度 chip 标题：落库数 + 清单说明(无独立符号不参与提取)。作业缺盘点字段时回退本地清单计数。 */
const unownedJobHint = computed(() => {
  const j = unownedJob.value
  const unowned = j?.unowned ?? unownedMeta.value?.unownedCount ?? unownedFiles.value.length
  const noSymbols = j?.noSymbols ?? unownedFiles.value.filter((f) => f.extractable === false).length
  return t('assetMgmt.unowned.extractingHint', { saved: j?.saved ?? 0, unowned, noSymbols })
})

function stopUnownedJobPolling() {
  if (unownedJobTimer) { clearInterval(unownedJobTimer); unownedJobTimer = null }
}

async function pollUnownedJobOnce() {
  try {
    const st = await semanticAssetService.unownedExtractStatus()
    const wasRunning = !!unownedJob.value?.running
    unownedJob.value = st
    // 每批落库后轻量刷新清单(进度可见)；作业结束做全量刷新 + 对话区摘要
    if (st.running) {
      if (st.done !== unownedJobDoneSeen) {
        unownedJobDoneSeen = st.done
        void loadUnownedFiles()
      }
    } else if (wasRunning) {
      stopUnownedJobPolling()
      if (unownedJobChatIdx.value >= 0) {
        const errs = st.errors ?? []
        let msg = st.stopped
          ? t('assetMgmt.unowned.chatJobStopped', { done: st.done, saved: st.saved })
          : t('assetMgmt.unowned.chatJobDone', { done: st.done, saved: st.saved })
        if (errs.length) {
          msg += '\n' + t('assetMgmt.unowned.chatJobErrors')
          for (const e of errs.slice(0, 3)) msg += `\n· ${e.error}`
        }
        if (!st.saved) msg += '\n' + t('assetMgmt.unowned.chatOneEmpty')
        turns.value[unownedJobChatIdx.value].content = msg
        unownedJobChatIdx.value = -1
      }
      await Promise.all([loadUnownedFiles(), loadSemantic(), refreshStatus(), loadOverview(), loadCoverage()])
    }
  } catch { /* 轮询失败静默，下轮重试 */ }
}

function startUnownedJobPolling() {
  stopUnownedJobPolling()
  unownedJobDoneSeen = unownedJob.value?.done ?? -1
  unownedJobTimer = setInterval(pollUnownedJobOnce, 2500)
  void pollUnownedJobOnce()
}

async function extractAllUnowned() {
  turns.value.push({ role: 'user', content: t('assetMgmt.unowned.chatJobUser') })
  const idx = turns.value.push({ role: 'assistant', content: t('assetMgmt.compExtractRunning') }) - 1
  const r = await semanticAssetService.unownedExtract('start', { batch: 10 })
  if (r.started) {
    unownedJob.value = { running: true, total: r.total ?? 0, done: 0, saved: 0, batches: 0, errors: [] }
    unownedJobChatIdx.value = idx
    // 等式盘点：未归属 = 待提取 + 已有资产 + 无独立符号——解释"49 个为何只提 38 个"
    turns.value[idx].content = t('assetMgmt.unowned.chatJobStart', {
      n: r.total ?? 0, unowned: r.unowned ?? 0,
      withAssets: r.withAssets ?? 0, noSymbols: r.noSymbols ?? 0,
    })
    startUnownedJobPolling()
  } else if (r.reason === 'already_running') {
    turns.value[idx].content = t('assetMgmt.unowned.chatJobAlready')
    unownedJobChatIdx.value = idx       // 接管：完成后把摘要回填到本 turn
    startUnownedJobPolling()
  } else if (r.reason === 'nothing_to_extract') {
    turns.value[idx].content = t('assetMgmt.unowned.chatJobNoneDetail', {
      unowned: r.unowned ?? 0, withAssets: r.withAssets ?? 0, noSymbols: r.noSymbols ?? 0,
    })
  } else {
    // 请求失败(服务未启动/后端版本较旧路由缺失/项目根未解析)——不能伪装成"没有待提取"
    turns.value[idx].content = r.reason === 'invalid_root'
      ? t('assetMgmt.unowned.chatJobInvalidRoot')
      : t('assetMgmt.unowned.chatJobFailed')
    void pollUnownedJobOnce()
  }
}

async function stopUnownedExtract() {
  await semanticAssetService.unownedExtract('stop')
  void pollUnownedJobOnce()
}

// ---- 更新语义资产(原「校验并提取」)：变化量计划 → 用户确认 → 快照批量作业(后端，页面关闭不影响) ----
const syncPlan = ref<ExtractPlanResult | null>(null)
const syncPlanOpen = ref(false)
const syncPlanLoading = ref(false)
const syncJob = ref<SyncExtractJob | null>(null)
let syncJobTimer: ReturnType<typeof setInterval> | null = null
let syncJobDoneSeen = -1
/** 作业对应对话区 turn 下标(完成后回填摘要)。 */
const syncJobChatIdx = ref(-1)

const syncExtracting = computed(() => !!syncJob.value?.running)

async function planSyncExtract() {
  if (syncPlanLoading.value || syncExtracting.value) return
  syncPlanLoading.value = true
  try {
    syncPlan.value = await semanticAssetService.extractPlan()
    const p = syncPlan.value
    if (!p.toExtract && !p.deleted && !p.invalidated) {
      turns.value.push({ role: 'assistant', content: t('assetMgmt.sync.noChange') })
    } else if (!p.toExtract) {
      // 只有失效(删除文件)没有待提取：校验结果直接告知
      turns.value.push({ role: 'assistant', content: t('assetMgmt.sync.invalidatedOnly', { n: p.invalidated, d: p.deleted }) })
      await Promise.all([loadSemantic(), refreshStatus()])
    } else {
      syncPlanOpen.value = true
    }
  } catch (e: any) {
    turns.value.push({ role: 'assistant', content: e?.message || t('assetMgmt.sync.planFailed') })
  } finally {
    syncPlanLoading.value = false
  }
}

function cancelSyncExtract() {
  syncPlanOpen.value = false
}

async function confirmSyncExtract() {
  syncPlanOpen.value = false
  const p = syncPlan.value
  turns.value.push({ role: 'user', content: t('assetMgmt.sync.chatUser') })
  const idx = turns.value.push({ role: 'assistant', content: t('assetMgmt.compExtractRunning') }) - 1
  const r = await semanticAssetService.syncExtract('start', { batch: 10 })
  if (r.started) {
    syncJob.value = { running: true, total: r.total ?? 0, done: 0, saved: 0, batches: 0, errors: [] }
    syncJobChatIdx.value = idx
    turns.value[idx].content = t('assetMgmt.sync.chatStart', {
      n: r.total ?? 0, batches: p?.batchesEstimate ?? Math.ceil((r.total ?? 0) / 10),
      added: p?.added ?? 0, modified: p?.modified ?? 0,
      never: p?.neverExtracted ?? 0, stale: p?.staleOnly ?? 0,
    })
    startSyncJobPolling()
  } else if (r.reason === 'already_running') {
    turns.value[idx].content = t('assetMgmt.sync.chatBusy')
    syncJobChatIdx.value = idx
    startSyncJobPolling()
  } else if (r.reason === 'unowned_running') {
    turns.value[idx].content = t('assetMgmt.sync.chatUnownedBusy')
  } else {
    turns.value[idx].content = r.message || t('assetMgmt.sync.chatFailed')
  }
}

function stopSyncJobPolling() {
  if (syncJobTimer) { clearInterval(syncJobTimer); syncJobTimer = null }
}

async function pollSyncJobOnce() {
  try {
    const st = await semanticAssetService.syncExtractStatus()
    const wasRunning = !!syncJob.value?.running
    syncJob.value = st
    if (st.running) {
      if (st.done !== syncJobDoneSeen) {
        syncJobDoneSeen = st.done
        void loadSemantic()
      }
    } else if (wasRunning) {
      stopSyncJobPolling()
      if (syncJobChatIdx.value >= 0) {
        const errs = st.errors ?? []
        let msg = st.stopped
          ? t('assetMgmt.sync.chatStopped', { done: st.done, saved: st.saved })
          : t('assetMgmt.sync.chatDone', { done: st.done, saved: st.saved })
        if (errs.length) {
          msg += '\n' + t('assetMgmt.unowned.chatJobErrors')
          for (const e of errs.slice(0, 3)) msg += `\n· ${e.error}`
        }
        turns.value[syncJobChatIdx.value].content = msg
        syncJobChatIdx.value = -1
      }
      await Promise.all([loadSemantic(), refreshStatus(), loadOverview(), loadCoverage(), loadUnownedFiles()])
    }
  } catch { /* 轮询失败静默，下轮重试 */ }
}

function startSyncJobPolling() {
  stopSyncJobPolling()
  syncJobDoneSeen = syncJob.value?.done ?? -1
  syncJobTimer = setInterval(pollSyncJobOnce, 2500)
  void pollSyncJobOnce()
}

async function stopSyncExtract() {
  await semanticAssetService.syncExtract('stop')
  void pollSyncJobOnce()
}

/** 未归属资产行的「关联 N」chip 数据(仅「其它」域资产；锚点文件反查)。 */
function unownedLinkOf(a: SemanticAsset): UnownedCrossLink | null {
  if (componentsOf(a).length) return null
  const file = a.astRefs?.[0]?.file || ''
  return unownedLinks.value.get(file) ?? null
}

function unownedLinkTitle(l: UnownedCrossLink): string {
  return l.byComponent.slice(0, 6).map((c) => `${c.component}(${c.count})`).join(' · ')
}

/** 资产 id → 跨组件关联(「其它」域资产渲染入口：links 变化时统一重算一次)。 */
const unownedLinkByAssetId = computed<Map<string, UnownedCrossLink>>(() => {
  const m = new Map<string, UnownedCrossLink>()
  for (const a of items.value) {
    const l = unownedLinkOf(a)
    if (l) m.set(a.id, l)
  }
  return m
})

/** 变更文件 → 类别 快查表（语义行徽标 / 图谱节点着色用）。
 *  选了对比对(base/target)后跟随所选口径(默认对=基线→工作区，与 baselineDiff 一致)。 */
const changedFileMap = computed<Map<string, 'added' | 'modified' | 'deleted'>>(() => {
  const m = new Map<string, 'added' | 'modified' | 'deleted'>()
  const d = compareData.value ?? baselineDiffData.value
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

/** 资产 id → 变更类别（语义行徽标渲染入口：diffMode/变更集变化时统一重算一次）。
 *  对比口径(compare)优先：资产级 side/strong 判定精确到符号段，文件级口径仅兜底。 */
const cmpBucketById = computed<Map<string, 'modified' | 'added' | 'deleted'>>(() => {
  const m = new Map<string, 'modified' | 'added' | 'deleted'>()
  const c = compareData.value
  if (!diffMode.value || !c) return m
  for (const a of c.assets.changed) m.set(a.id, 'modified')
  for (const a of c.assets.new) m.set(a.id, 'added')
  for (const a of c.assets.removed) m.set(a.id, 'deleted')
  return m
})

const changeMarkById = computed<Map<string, 'added' | 'modified' | 'deleted'>>(() => {
  const m = new Map<string, 'added' | 'modified' | 'deleted'>()
  if (!diffMode.value) return m
  const buckets = cmpBucketById.value
  for (const a of items.value) {
    const mark = buckets.get(a.id) ?? assetChangeMark(a)
    if (mark) m.set(a.id, mark)
  }
  return m
})

/** 基线对比 · 文件级变化归属：文件(树侧路径) → {changed,new,removed}(按首锚点归属)。
 *  compare 资产经 items 反查(锚点路径与树同基准)；结果供文件行彩色计数 chip。 */
const diffFileCounts = computed<Map<string, { changed: number; added: number; deleted: number }>>(() => {
  const m = new Map<string, { changed: number; added: number; deleted: number }>()
  if (!diffMode.value) return m
  const byId = new Map(items.value.map((x) => [x.id, x]))
  const buckets = cmpBucketById.value
  for (const [id, bucket] of buckets) {
    const a = byId.get(id)
    const f = a?.astRefs?.[0]?.file || ''
    if (!f) continue
    const e = m.get(f) ?? { changed: 0, added: 0, deleted: 0 }
    if (bucket === 'modified') e.changed += 1
    else if (bucket === 'added') e.added += 1
    else e.deleted += 1
    m.set(f, e)
  }
  return m
})

/** 待提取/新增文件集合(compare 的 git 路径可能是 workDir 相对) → 双向后缀匹配树侧路径。 */
function treeFileOf(cmpFile: string): string {
  const u = diffFileUniverse.value
  if (u.has(cmpFile)) return cmpFile
  for (const f of u) {
    if (f.endsWith('/' + cmpFile) || cmpFile.endsWith('/' + f)) return f
  }
  return ''
}
const pendingFileSet = computed<Set<string>>(() => {
  const s = new Set<string>()
  if (diffMode.value && compareData.value) {
    for (const f of compareData.value.assets.pending.files) {
      const t = treeFileOf(f)
      if (t) s.add(t)
    }
  }
  return s
})
const addedFileSet = computed<Set<string>>(() => {
  const s = new Set<string>()
  if (diffMode.value && compareData.value) {
    for (const f of compareData.value.files.added) {
      const t = treeFileOf(f)
      if (t) s.add(t)
    }
  }
  return s
})
/** 文件匹配全集(树侧锚点 ∪ 组件 owns)，供后缀对齐反查。 */
const diffFileUniverse = computed<Set<string>>(() => {
  const s = new Set<string>()
  for (const a of items.value) {
    const f = a.astRefs?.[0]?.file
    if (f) s.add(f)
  }
  for (const c of treeComps.value) for (const f of c.owns) s.add(f)
  return s
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
    turns.value.push({ role: 'assistant', content: t('assetMgmt.purgeImpactFailed', { msg: String(err?.message || err) }) })
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
        t('assetMgmt.purgeDone', { n: res.purged }),
        impact.reqCount ? t('assetMgmt.purgeImpactReqs', { n: impact.reqCount }) : '',
        impact.taskCount ? t('assetMgmt.purgeImpactTasks', { n: impact.taskCount }) : '',
      ].filter(Boolean).join(' '),
    })
    await Promise.all([loadOverview(), refreshStatus()])
    purgeOpen.value = false
  } catch (err: any) {
    turns.value.push({ role: 'assistant', content: t('assetMgmt.purgeFailed', { msg: String(err?.message || err) }) })
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

/** 范围筛选 · 隐藏无资产文件：文件行(含未提取的未归属文件)无资产时不渲染。 */
const hideFileless = ref(false)

/** 文件源码资产卡：列表文件行打开(复用图谱卡同批服务/缓存，无图谱联动)。 */
const fileCard = ref<{ file: string; assets: SemanticAsset[] } | null>(null)
function openFileCard(file: string) {
  const seen = new Set<string>()
  const assets = items.value.filter((x) => !seen.has(x.id) && (x.astRefs ?? []).some((r) => r.file === file) && seen.add(x.id))
  fileCard.value = { file, assets }
}
/** 卡内「在列表定位」：按资产 id 过滤列表并关卡。 */
function locateAsset(id: string) {
  q.value = id
  onSearch()
  fileCard.value = null
}
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

async function refreshOne(a: SemanticAsset) {
  try {
    const res = await semanticAssetService.refreshAsset(a.id)
    if (res.asset) {
      const i = items.value.findIndex((x) => x.id === a.id)
      if (i >= 0) {
        items.value[i] = { ...items.value[i], ...res.asset }
        items.value = [...items.value]
      }
    } else if (res.status === 'deleted') {
      const i = items.value.findIndex((x) => x.id === a.id)
      if (i >= 0) {
        items.value[i] = { ...items.value[i], status: 'deleted', needsUpdate: 1 }
        items.value = [...items.value]
      }
    }
    await refreshStatus()
  } catch (err: any) {
    console.warn('[asset-mgmt] refresh failed:', err)
  }
}

function usable(a: SemanticAsset): boolean {
  return a.status !== 'stale' && a.status !== 'deleted' && !a.needsUpdate
}

// 展开卡懒加载 detail：列表(light 模式)不带 detail 大字段；首次展开时
// 单查 /{id} 回填。detailDone 含"已确认无 detail"的行，避免重复请求。
const detailLoading = reactive<Record<string, boolean>>({})

const descLoading = reactive<Record<string, boolean>>({})

/** 全部展开时行数可达数千，逐行 DOM 令布局/绘制过载 → 前缀窗口渲染：
 * 只挂载前 renderCap 行，滚动接近底部由哨兵增量放行；筛选/搜索使行数收缩时
 * 窗口自动收敛。与 scope/kind/搜索/树层级天然兼容(同源 semanticTreeRows)。 */
const RENDER_INIT = 400
const RENDER_STEP = 300
const renderCap = ref(RENDER_INIT)
const renderedTreeRows = computed(() => semanticTreeRows.value.slice(0, renderCap.value))
watch(() => semanticTreeRows.value.length, (n) => {
  if (n < renderCap.value) renderCap.value = Math.max(RENDER_INIT, n)
})
const semScrollEl = ref<HTMLElement | null>(null)
const loadMoreSentinel = ref<HTMLElement | null>(null)
let capObserver: IntersectionObserver | null = null
watch(loadMoreSentinel, (el) => {
  capObserver?.disconnect()
  if (!el) return
  // root 每次重建：滚动容器随 tab 切换(v-else 分支)可能重挂载
  capObserver = new IntersectionObserver((es) => {
    if (es.some((e) => e.isIntersecting)) renderCap.value += RENDER_STEP
  }, { root: semScrollEl.value ?? undefined, rootMargin: '800px 0px' })
  capObserver.observe(el)
})
onUnmounted(() => {
  capObserver?.disconnect()
  capObserver = null
})

/** 按需生成功能摘要(分层口径: 批量提取不产 desc)。
 *  fresh 缓存由后端直返；腐烂(需更新)资产后端自动重生成。 */
async function genDesc(a: SemanticAsset) {
  if (descLoading[a.id]) return
  descLoading[a.id] = true
  try {
    const r = await semanticAssetService.assetDesc(a.id)
    a.desc = r.desc || ''
  } catch { /* 失败留按钮可重试 */ } finally {
    descLoading[a.id] = false
  }
}
const detailDone = new Set<string>()
async function toggle(id: string) {
  expanded[id] = !expanded[id]
  if (!expanded[id] || detailDone.has(id)) return
  const i = items.value.findIndex((x) => x.id === id)
  if (i < 0 || items.value[i]!.detail !== undefined) {
    detailDone.add(id)
    return
  }
  detailLoading[id] = true
  try {
    const full = await semanticAssetService.detail(id)
    const j = items.value.findIndex((x) => x.id === id)
    if (j >= 0) {
      items.value[j] = { ...items.value[j], detail: full?.detail }
      items.value = [...items.value]
    }
  } catch {
    /* 详情加载失败静默：展开块仅缺 fields/steps 等小节 */
  } finally {
    detailDone.add(id)
    detailLoading[id] = false
  }
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

/** 快捷提问(引用/询问按钮): 经全局会话栏发送(asset 场景)。 */
function askAgent(text: string) {
  if (conv.busy || !text.trim()) return
  ensureAssetConversation()
  void conv.send(text, { skillScenarios: ['extract'] })
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

/** 按需提取：确定性直调 REST(不走对话模型——小模型可能不按工具协议执行而编造报告)。
 *  过程与结果以对话回合呈现；完成后刷新资产数据。 */
async function askExtractComponent(key: string, name: string) {
  if (extractBusy.value) return
  turns.value.push({ role: 'user', content: t('assetMgmt.compExtractUser', { name, key }) })
  const idx = turns.value.push({ role: 'assistant', content: t('assetMgmt.compExtractRunning') }) - 1
  extractBusy.value = true
  const ac = new AbortController(); extractAbort.value = ac
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
    extractAbort.value = null
    extractBusy.value = false
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

// 引用组件到对话输入框（预填不发送，用户可补充问题）→ 全局会话栏。
function referenceComp(name: string, id: string) {
  ensureAssetConversation()
  conv.pushDraft(compRefText(name, id))
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
  await Promise.all([loadCompCatalog(), loadOverview(), loadSemantic(), refreshStatus(), loadFramework(), loadCoverage(), loadUnownedFiles(), loadUnownedLinks()])
  turns.value.push({ role: 'assistant', content: t('assetMgmt.welcome') })
  // 批量提取是后端作业：页面重开(此前关闭)也要接管进度轮询
  void pollUnownedJobOnce().then(() => {
    if (unownedJob.value?.running) startUnownedJobPolling()
  })
  void pollSyncJobOnce().then(() => {
    if (syncJob.value?.running) startSyncJobPolling()
  })
})

onUnmounted(() => {
  stopUnownedJobPolling()
  stopSyncJobPolling()
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
         <!-- 校验并提取：先校验变化量 → 确认 → 快照批量作业(后端，页面关闭不影响) -->
         <button
           class="btn btn-sm"
           :class="syncExtracting ? 'btn-primary' : 'btn-primary'"
           :disabled="syncPlanLoading || syncExtracting"
           :title="syncExtracting
             ? (syncJob?.current
                ? t('assetMgmt.sync.extractingCurrent', { saved: syncJob?.saved ?? 0, current: syncJob.current })
                : t('assetMgmt.sync.extractingHint', { saved: syncJob?.saved ?? 0 }))
             : t('assetMgmt.sync.hint')"
           @click="planSyncExtract"
         >
            <ArrowPathIcon
              class="w-3.5 h-3.5"
              :class="syncPlanLoading || syncExtracting ? 'animate-spin' : ''"
            />{{ syncExtracting
             ? t('assetMgmt.sync.extracting', { done: syncJob?.done ?? 0, total: syncJob?.total ?? 0 })
             : (syncPlanLoading ? t('assetMgmt.sync.planning') : t('assetMgmt.sync.button')) }}
         </button>
         <button
           v-if="syncExtracting"
           class="btn btn-sm btn-ghost"
           :title="t('assetMgmt.sync.stop')"
           @click="stopSyncExtract"
         >
           <StopIcon class="w-3.5 h-3.5" />
         </button>
       </div>
      <!-- 基线对比 · 对比起止 head 选择(任意 head 对 vs head/工作区；全 tab 可见) + 紧凑结果 -->
      <div v-if="diffMode" class="mt-2.5 flex items-center gap-1.5 flex-wrap">
        <span class="text-[10px] text-ctp-overlay0 shrink-0">{{ t('assetMgmt.diff.cmpBase') }}</span>
        <select
          v-model="cmpBase"
          class="input !py-0.5 !px-1.5 !text-[10px] min-w-0 max-w-[30%]"
          :title="t('assetMgmt.diff.cmpBaseHint')"
          @change="runCompare"
        >
          <option value="">{{ t('assetMgmt.diff.kbBaseline') }}{{ baselineSha ? ` (${baselineSha.slice(0, 8)})` : '' }}</option>
          <option v-for="c in commitOptions" :key="`b-${c.oid}`" :value="c.oid">{{ c.oid.slice(0, 8) }} {{ c.subject.slice(0, 26) }}</option>
        </select>
        <span class="text-ctp-overlay0 shrink-0">→</span>
        <select
          v-model="cmpTarget"
          class="input !py-0.5 !px-1.5 !text-[10px] min-w-0 max-w-[30%]"
          :title="t('assetMgmt.diff.cmpTargetHint')"
          @change="runCompare"
        >
          <option value="worktree">{{ t('assetMgmt.diff.worktree') }}</option>
          <option v-for="c in commitOptions" :key="`t-${c.oid}`" :value="c.oid">{{ c.oid.slice(0, 8) }} {{ c.subject.slice(0, 26) }}</option>
        </select>
        <!-- 重新对比按钮已删：选择即对比(@change)/提取闭环自带重比；工作区有新改动时重选目标即可触发 -->
        <span v-if="compareLoading" class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.cmpRunning') }}</span>
        <span v-else-if="compareError" class="text-[10px] text-ctp-red truncate max-w-[40%]" :title="compareError">{{ compareError }}</span>
        <!-- 结果数字不再重复在此：统一在下方「对比结果明细」统计行(缓存态/资产变化/待提取) -->
        <template v-else-if="compareData && !compareData.noChanges">
          <!-- 提取闭环(通用)：pending 中「目标侧内容==工作区内容」的子集可经工作区提取锚定；
               内容已分叉的自动排除(提取历史内容会覆盖现役资产摘要)。完成后自动重新对比 -->
          <button
            v-if="pendingExtractable.length && !extractingPending"
            class="btn btn-xs btn-blue !py-0.5 shrink-0"
            :title="pendingExtractable.length < compareData.assets.pending.count
              ? t('assetMgmt.diff.extractRecompareHint', { n: pendingExtractable.length }) + ' ' + t('assetMgmt.diff.extractDiverged', { m: compareData.assets.pending.count - pendingExtractable.length })
              : t('assetMgmt.diff.extractRecompareHint', { n: pendingExtractable.length })"
            @click="extractPendingAndRecompare"
          >
            <SparklesIcon class="w-3 h-3" />{{ t('assetMgmt.diff.extractRecompare', { n: pendingExtractable.length }) }}
          </button>
          <span v-if="extractingPending" class="inline-flex items-center gap-1 text-[10px] text-ctp-overlay0"><ArrowPathIcon class="w-3 h-3 animate-spin" />{{ t('assetMgmt.diff.extracting') }}</span>
        </template>
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
            class="input !py-0.5 !px-2 !text-[11px] w-auto cursor-pointer"
            :title="t('assetMgmt.treeLevelHint')"
            @click="cycleTreeLevel"
          >{{ t(`assetMgmt.treeLevel.${treeLevel}`) }}</button>
          <template v-if="tab === 'semantic'">
            <div
              class="inline-flex items-center h-[calc(1.5rem+2px)] rounded-md border border-ctp-surface1 bg-ctp-crust overflow-hidden"
              :title="t('assetMgmt.scopeGroupHint')"
            >
              <span class="inline-flex items-center px-2 text-[11px] text-ctp-text">{{ scopeSummary }}</span>
              <button
                class="btn btn-xs !rounded-none !border-l !border-ctp-surface1 self-stretch"
                :class="(filterOpen || scopeSel.length) ? 'btn-blue' : 'btn-ghost !text-ctp-text'"
                :title="scopeSel.length ? t('assetMgmt.filterActive', { n: scopeSel.length }) : t('assetMgmt.scopeGroupHint')"
                @click="filterOpen = !filterOpen; batchOpen = false"
              >
                <AdjustmentsHorizontalIcon class="w-3 h-3" />
              </button>
            </div>
            <button
              class="input !py-0.5 !px-2 !text-[11px] w-auto cursor-pointer inline-flex items-center justify-center h-[calc(1.5rem+2px)]"
              :class="batchOpen ? '!border-ctp-blue' : ''"
              :title="t('assetMgmt.batchClearAll')"
              @click="batchOpen = !batchOpen; filterOpen = false"
            >
              <TrashIcon class="w-3 h-3" />
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
                    class="accent-ctp-yellow shrink-0"
                    :checked="scopeSel.includes(OTHER_KEY)"
                    @change="toggleOther"
                  >
                  <span class="text-[11px] text-ctp-subtext1">{{ t('assetMgmt.unownedFiles') }}</span>
                  <span class="text-[9px] text-ctp-overlay0 truncate">{{ t('assetMgmt.unowned.desc') }}</span>
                </div>
              </div>
              <label class="flex items-center gap-1.5 border-t border-ctp-surface0 pt-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  class="accent-ctp-blue shrink-0"
                  v-model="hideFileless"
                >
                <span class="text-[10px] text-ctp-subtext1">{{ t('assetMgmt.hideFileless') }}</span>
              </label>
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
                :compare-data="compareData"
                :file-index="graphFileIndexes[gt.id] ?? []"
                :comp-names="graphCompNames"
                @close="closeGraphTab"
              />
            </div>
          </template>
        </div>
        <div
          v-else
          ref="semScrollEl"
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
                    <span
                      class="chip !text-[10px]"
                      :class="kindChipClass(k.value)"
                    >{{ k.label }}</span>
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
                    :class="levelChipClass(l.value)"
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
                      class="chip"
                      :class="kindChipClass(k.value)"
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
                      class="chip"
                      :class="levelChipClass(l.value)"
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

              <!-- 对比结果明细：资产变化 + 组件变化(其他桶) + 跨域联系；起止 head 在顶部工具栏选择 -->
              <div class="px-3 pb-3 pt-2 mt-1 border-t border-ctp-surface0 space-y-2">
                <p v-if="compareLoading" class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.cmpRunning') }}</p>
                <p v-else-if="compareError" class="text-[10px] text-ctp-red">{{ compareError }}</p>
                <template v-else-if="compareData">
                  <p v-if="compareData.noChanges" class="text-[10px] text-ctp-overlay0">{{ t('assetMgmt.diff.noChanges') }}</p>
                  <template v-else>
                    <div class="flex items-center gap-2 text-[10px] flex-wrap">
                      <span class="text-ctp-subtext1 font-semibold">{{ t('assetMgmt.diff.assetDelta') }}</span>
                      <span v-if="compareData.cached" class="chip !text-[8px] bg-ctp-surface0 text-ctp-overlay0">{{ t('assetMgmt.diff.cached') }}</span>
                      <span class="text-ctp-overlay1">{{ t('assetMgmt.diff.stableN', { n: compareData.assets.stable }) }}</span>
                      <span class="text-ctp-yellow">{{ t('assetMgmt.diff.changedN', { n: compareData.assets.changedTotal }) }}</span>
                      <span v-if="compareData.assets.newTotal" class="text-ctp-green">{{ t('assetMgmt.diff.newN', { n: compareData.assets.newTotal }) }}</span>
                      <span v-if="compareData.assets.removedTotal" class="text-ctp-red">{{ t('assetMgmt.diff.removedN', { n: compareData.assets.removedTotal }) }}</span>
                      <span v-if="compareData.assets.pending.count" class="text-ctp-peach">{{ t('assetMgmt.diff.pendingN', { n: compareData.assets.pending.count }) }}</span>
                      <span v-if="compareData.newFileCount" class="text-ctp-green">{{ t('assetMgmt.diff.pendingNew', { n: compareData.newFileCount }) }}</span>
                    </div>
                    <div class="space-y-0.5">
                      <div v-for="c in compareData.components" :key="c.id" class="flex items-center gap-2 text-[10px] min-w-0">
                        <span
                          class="truncate min-w-0 flex-1"
                          :class="c.id === '__other__' ? 'text-ctp-overlay1 italic' : 'text-ctp-text font-medium'"
                          :title="c.id === '__other__' ? t('assetMgmt.diff.otherBucketHint') : c.id"
                        >{{ c.name || t('assetMgmt.diff.otherBucket') }}</span>
                        <span class="text-ctp-green font-mono shrink-0">+{{ c.added }}</span>
                        <span class="text-ctp-yellow font-mono shrink-0">~{{ c.modified }}</span>
                        <span class="text-ctp-red font-mono shrink-0">-{{ c.deleted }}</span>
                      </div>
                    </div>
                    <!-- 资产明细：目标侧新增 / 需更新(side 标注) / 待提取文件 -->
                    <div v-if="compareData.assets.new.length" class="space-y-0.5">
                      <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.diff.newAssets') }}</div>
                      <div v-for="a in compareData.assets.new.slice(0, 20)" :key="a.id" class="flex items-center gap-2 text-[10px] min-w-0">
                        <span class="truncate min-w-0 flex-1 text-ctp-text" :title="a.id">{{ a.name }}</span>
                        <span class="chip !text-[8px] shrink-0" :class="kindChipClass(a.kind)">{{ t(`assetMgmt.kind.${a.kind}`) }}</span>
                        <span class="font-mono text-[9px] text-ctp-overlay0 shrink-0" :title="a.component">{{ a.component === '__other__' ? t('assetMgmt.diff.otherBucket') : a.component }}</span>
                      </div>
                    </div>
                    <div v-if="compareData.assets.changed.length" class="space-y-0.5">
                      <div class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.diff.changedAssets') }}</div>
                      <div v-for="a in compareData.assets.changed.slice(0, 20)" :key="a.id" class="flex items-center gap-2 text-[10px] min-w-0">
                        <span class="truncate min-w-0 flex-1 text-ctp-text" :title="a.id">{{ a.name }}</span>
                        <span
                          class="chip !text-[8px] shrink-0"
                          :class="a.strong ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-surface0 text-ctp-overlay1'"
                          :title="t(a.strong ? 'assetMgmt.diff.strongHitHint' : 'assetMgmt.diff.weakHitHint')"
                        >{{ t(a.strong ? 'assetMgmt.diff.strongHit' : 'assetMgmt.diff.weakHit') }}</span>
                        <span
                          class="chip !text-[8px] shrink-0"
                          :class="a.side === 'target' ? 'bg-ctp-green/15 text-ctp-green' : a.side === 'base' ? 'bg-ctp-blue/15 text-ctp-blue' : 'bg-ctp-peach/15 text-ctp-peach'"
                          :title="t(`assetMgmt.diff.side.${a.side || 'stale'}`)"
                        >{{ t(`assetMgmt.diff.side.${a.side || 'stale'}`) }}</span>
                        <span class="font-mono text-[9px] text-ctp-overlay0 shrink-0" :title="a.component">{{ a.component === '__other__' ? t('assetMgmt.diff.otherBucket') : a.component }}</span>
                      </div>
                      <div v-if="compareData.assets.changedWeak" class="text-[9px] text-ctp-overlay0">
                        {{ t('assetMgmt.diff.weakSummary', { strong: compareData.assets.changedStrong, weak: compareData.assets.changedWeak }) }}
                      </div>
                    </div>
                    <div v-if="compareData.assets.pending.count" class="space-y-0.5">
                      <div class="flex items-center gap-2">
                        <span class="text-[9px] text-ctp-peach">{{ t('assetMgmt.diff.pendingFiles', { n: compareData.assets.pending.count }) }}</span>
                        <button
                          v-if="compareData.targetIsWorktree && !extractingPending"
                          class="btn btn-xs btn-blue !py-0 !px-1.5 !text-[9px]"
                          :title="t('assetMgmt.diff.extractRecompareHint', { n: compareData.assets.pending.count })"
                          @click="extractPendingAndRecompare"
                        >
                          <SparklesIcon class="w-2.5 h-2.5" />{{ t('assetMgmt.diff.extractRecompare', { n: compareData.assets.pending.count }) }}
                        </button>
                        <span v-if="extractingPending" class="inline-flex items-center gap-1 text-[9px] text-ctp-overlay0"><ArrowPathIcon class="w-2.5 h-2.5 animate-spin" />{{ t('assetMgmt.diff.extracting') }}</span>
                      </div>
                      <div v-for="f in compareData.assets.pending.files.slice(0, 30)" :key="f" class="font-mono text-[9px] text-ctp-subtext0 truncate" :title="f">{{ f }}</div>
                      <div v-if="compareData.assets.pending.files.length > 30" class="text-[9px] text-ctp-overlay0">+{{ compareData.assets.pending.files.length - 30 }}</div>
                      <p v-if="!compareData.targetIsWorktree" class="text-[9px] text-ctp-overlay0">{{ t('assetMgmt.diff.pendingCommitHint') }}</p>
                    </div>
                    <div v-if="compareData.crossLinkCount" class="text-[9px] text-ctp-overlay0 leading-relaxed">
                      {{ t('assetMgmt.diff.crossLinks', { n: compareData.crossLinkCount } ) }}
                      <span
                        v-for="(l, i) in compareData.crossLinks.slice(0, 3)"
                        :key="i"
                        class="ml-1 font-mono text-ctp-subtext0"
                      >{{ l.fromName }}→{{ l.toName }}</span>
                    </div>
                  </template>
                </template>
              </div>
            </div>
          </template>

          <!-- 语义资产：按组件树文件树形式逐层展开(选 L0/L1 时以该层为初始列表) -->
          <template v-if="tab === 'semantic'">
            <template
              v-for="row in renderedTreeRows"
              :key="row.key"
            >
              <!-- 组件(目录)节点 -->
              <template v-if="row.t === 'comp'">
                <div
                  v-for="g in row.g ? [row.g] : []"
                  :key="row.key + ':h'"
                >
              <div
                class="flex items-center gap-1.5 px-1 pt-1.5 pb-0.5 tree-row"
                :style="{ paddingLeft: (row.depth * 12) + 'px' }"
              >
                <button
                  v-if="(compCollapsible.get(g.key) ?? false) || hasChildren(g.key) || (subtreeCount.get(g.key) ?? 0) > 0"
                  class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                  @click="toggleOpen(g.key)"
                >
                  <ChevronDownIcon
                    v-if="compExpandState(g.key)"
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
                <DocumentTextIcon
                  v-else
                  class="w-3 h-3 text-ctp-yellow shrink-0"
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
                <!-- 基线对比 · 组件(子树)变化上卷：需更新/新增/移除 彩色计数 -->
                <template v-if="diffMode && diffRollup.get(g.key)">
                  <span
                    v-if="diffRollup.get(g.key)!.changed"
                    class="chip !text-[8px] bg-ctp-yellow/15 text-ctp-yellow shrink-0 font-mono"
                    :title="t('assetMgmt.diff.changedN', { n: diffRollup.get(g.key)!.changed })"
                  >{{ t('assetMgmt.diff.chipChanged', { n: diffRollup.get(g.key)!.changed }) }}</span>
                  <span
                    v-if="diffRollup.get(g.key)!.added"
                    class="chip !text-[8px] bg-ctp-green/15 text-ctp-green shrink-0 font-mono"
                    :title="t('assetMgmt.diff.newN', { n: diffRollup.get(g.key)!.added })"
                  >{{ t('assetMgmt.diff.chipAdded', { n: diffRollup.get(g.key)!.added }) }}</span>
                  <span
                    v-if="diffRollup.get(g.key)!.deleted"
                    class="chip !text-[8px] bg-ctp-red/15 text-ctp-red shrink-0 font-mono"
                    :title="t('assetMgmt.diff.removedN', { n: diffRollup.get(g.key)!.deleted })"
                  >{{ t('assetMgmt.diff.chipRemoved', { n: diffRollup.get(g.key)!.deleted }) }}</span>
                </template>
                <!-- 未归属组：截断提示 + 循环批量提取(后端作业，页面关闭不影响；每批 10) -->
                <template v-if="g.key === OTHER_KEY">
                  <span
                    v-if="unownedMeta?.truncated"
                    class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                    :title="t('assetMgmt.unowned.truncatedHint', { total: unownedMeta?.totalFiles ?? 0, owned: unownedMeta?.ownedCount ?? 0 })"
                  >{{ t('assetMgmt.unowned.truncated') }}</span>
                  <span
                    v-if="unownedExtracting"
                    class="chip !text-[9px] bg-ctp-blue/15 text-ctp-blue shrink-0 font-mono"
                    :title="unownedJobHint"
                  >{{ t('assetMgmt.unowned.extracting', { done: unownedJob?.done ?? 0, total: unownedJob?.total ?? 0 }) }}</span>
                  <button
                    v-if="unownedExtracting"
                    class="text-ctp-overlay0 hover:text-ctp-red p-0.5 shrink-0"
                    :title="t('assetMgmt.unowned.stop')"
                    @click="stopUnownedExtract"
                  >
                    <StopIcon class="w-3 h-3" />
                  </button>
                  <button
                    v-else
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5 shrink-0 disabled:opacity-40"
                    :disabled="unownedExtractingOne !== ''"
                    :title="t('assetMgmt.unowned.extractAllHint')"
                    @click="extractAllUnowned"
                  >
                    <SparklesIcon class="w-3 h-3" />
                  </button>
                </template>
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
                class="flex items-center gap-1.5 px-1 py-0.5 tree-row"
                :style="{ paddingLeft: (row.depth * 12) + 'px' }"
              >
                <button
                  v-if="row.n"
                  class="p-0.5 text-ctp-overlay0 hover:text-ctp-text shrink-0"
                  @click="toggleFileOpen(row.fk!)"
                >
                  <ChevronDownIcon
                    v-if="fileExpandState(row.fk!)"
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
                <!-- 文件级语义图谱：该文件锚定的资产子图(有资产才可看) -->
                <button
                  v-if="row.n"
                  class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5 shrink-0"
                  :title="t('assetMgmt.graph.viewFileGraph')"
                  @click="openGraphTab('file', row.file!, fileBase(row.file!))"
                >
                  <Squares2X2Icon class="w-3 h-3" />
                </button>
                <!-- 文件源码资产卡：复用图谱资产卡服务/缓存，列表内浮卡展示(无资产文件=纯源码浏览) -->
                <button
                  class="text-ctp-overlay0 hover:text-ctp-blue p-0.5 shrink-0"
                  :title="t('assetMgmt.fileCard.view')"
                  @click="openFileCard(row.file!)"
                >
                  <CodeBracketIcon class="w-3 h-3" />
                </button>
                <!-- 基线对比 · 文件级变化归属：需更新/新增/移除彩色计数 + 待提取/新增文件 -->
                <template v-if="diffMode && row.file">
                  <span
                    v-if="diffFileCounts.get(row.file)?.changed"
                    class="chip !text-[8px] bg-ctp-yellow/15 text-ctp-yellow shrink-0 font-mono"
                  >{{ t('assetMgmt.diff.chipChanged', { n: diffFileCounts.get(row.file)!.changed }) }}</span>
                  <span
                    v-if="diffFileCounts.get(row.file)?.added"
                    class="chip !text-[8px] bg-ctp-green/15 text-ctp-green shrink-0 font-mono"
                  >{{ t('assetMgmt.diff.chipAdded', { n: diffFileCounts.get(row.file)!.added }) }}</span>
                  <span
                    v-if="diffFileCounts.get(row.file)?.deleted"
                    class="chip !text-[8px] bg-ctp-red/15 text-ctp-red shrink-0 font-mono"
                  >{{ t('assetMgmt.diff.chipRemoved', { n: diffFileCounts.get(row.file)!.deleted }) }}</span>
                  <span
                    v-if="pendingFileSet.has(row.file)"
                    class="chip !text-[8px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                    :title="t('assetMgmt.diff.pendingN', { n: compareData?.assets.pending.count ?? 0 })"
                  >{{ t('assetMgmt.diff.chipPending') }}</span>
                  <span
                    v-else-if="addedFileSet.has(row.file)"
                    class="chip !text-[8px] bg-ctp-green/15 text-ctp-green shrink-0"
                    :title="t('assetMgmt.diff.pendingNew', { n: compareData?.newFileCount ?? 0 })"
                  >{{ t('assetMgmt.diff.chipNewFile') }}</span>
                </template>
                <span
                  v-if="!row.unowned"
                  class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]"
                >{{ row.n }}</span>
                <!-- 未归属文件行：未提取标记 + 跨组件关联 chip + 单文件提取 -->
                <template v-if="row.unowned">
                  <span
                    v-if="row.extractable === false"
                    class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay0 shrink-0"
                    :title="t('assetMgmt.unowned.noSymbolsHint')"
                  >{{ t('assetMgmt.unowned.noSymbols') }}</span>
                  <span
                    v-else-if="!row.n"
                    class="chip !text-[9px] bg-ctp-surface0 text-ctp-overlay1 shrink-0"
                  >{{ t('assetMgmt.unowned.noAssets') }}</span>
                  <span
                    v-if="row.n"
                    class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]"
                  >{{ row.n }}</span>
                  <span
                    v-if="unownedLinks.get(row.file || '')"
                    class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal shrink-0 cursor-help"
                    :title="unownedLinkTitle(unownedLinks.get(row.file || '')!)"
                  >{{ t('assetMgmt.unowned.related', { n: unownedLinks.get(row.file || '')!.crossCount }) }}</span>
                  <button
                    v-if="row.extractable !== false"
                    class="text-ctp-overlay0 hover:text-ctp-mauve p-0.5 shrink-0 disabled:opacity-40"
                    :disabled="unownedExtractingOne !== '' || unownedExtracting"
                    :title="t('assetMgmt.unowned.extractOne')"
                    @click="extractUnownedFile(row.file!)"
                  >
                    <SparklesIcon
                      class="w-3 h-3"
                      :class="{ 'animate-pulse text-ctp-mauve': unownedExtractingOne === row.file }"
                    />
                  </button>
                </template>
              </div>
              <!-- 资产卡片(挂文件下/组件直属) -->
              <div
                v-else
                class="mt-0.5 tree-row"
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
                  <span class="chip !text-[9px] shrink-0" :class="kindChipClass(a.kind)">
                    {{ t(`assetMgmt.kind.${a.kind}`) }}
                  </span>
                  <span
                    v-if="a.level"
                    class="chip !text-[9px] shrink-0"
                    :class="levelChipClass(a.level)"
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
                  <!-- 未归属资产与组件内资产的跨组件关联：点击跳图谱聚焦，出入边即关联 -->
                  <span
                    v-if="unownedLinkByAssetId.get(a.id)"
                    class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal shrink-0 cursor-pointer hover:bg-ctp-teal/25"
                    :title="unownedLinkTitle(unownedLinkByAssetId.get(a.id)!)"
                    @click="openGraphTab('asset', a.id, a.name)"
                  >{{ t('assetMgmt.unowned.related', { n: unownedLinkByAssetId.get(a.id)!.crossCount }) }}</span>
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
                <p
                  v-if="!expanded[a.id] && a.desc"
                  class="px-2 pb-1.5 text-[10px] truncate text-ctp-teal cursor-pointer hover:text-ctp-sky"
                  :title="t('assetMgmt.descReadyHint')"
                  @click="toggle(a.id)"
                >{{ t('assetMgmt.descReady') }}</p>
                <p
                  v-else-if="!expanded[a.id]"
                  class="px-2 pb-1.5 text-[10px] line-clamp-2 whitespace-pre-wrap text-ctp-overlay0 italic cursor-pointer hover:text-ctp-subtext0"
                  :title="t('assetMgmt.descPendingHint')"
                  @click="toggle(a.id)"
                >
                  {{ t('assetMgmt.descPending') }}
                </p>
                <div
                  v-if="expanded[a.id]"
                  class="border-t border-ctp-mauve/15 px-2 py-1.5 space-y-1 text-[10px]"
                >
                  <div
                    v-if="detailLoading[a.id] && a.detail === undefined"
                    class="text-ctp-overlay0 animate-pulse"
                  >
                    {{ t('assetMgmt.detailLoading') }}
                  </div>
                  <div class="flex items-start gap-1.5">
                    <SparklesIcon class="w-3 h-3 shrink-0 mt-0.5 text-ctp-peach" />
                    <p
                      v-if="a.desc"
                      class="flex-1 m-0 whitespace-pre-wrap text-ctp-subtext1"
                    >{{ a.desc }}</p>
                    <button
                      v-else
                      class="btn btn-xs btn-ghost"
                      :disabled="!!descLoading[a.id]"
                      @click="genDesc(a)"
                    >{{ t('assetMgmt.genDesc') }}</button>
                  </div>
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
            <div
              v-if="renderedTreeRows.length < semanticTreeRows.length"
              ref="loadMoreSentinel"
              class="text-center text-[10px] text-ctp-overlay0 py-2 font-mono"
            >{{ t('assetMgmt.renderingMore', { done: renderedTreeRows.length, total: semanticTreeRows.length }) }}</div>
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

      <!-- 右：全局会话栏·inline 停靠(P1 决策2: 唯一对话栏——本页停靠形态) -->
      <div class="flex min-h-0 min-w-0 flex-1 flex-col">
        <ConversationDock inline default-kind="asset" />
      </div>
    </div>

    <RequirementHistoryModal
      :open="historyOpen"
      :active-conv-id="conv.activeId"
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

    <!-- 校验并提取 · 变化范围确认弹窗：先校验后执行(所见即所得，按快照执行) -->
    <div
      v-if="syncPlanOpen && syncPlan"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/70 p-4"
      @click.self="cancelSyncExtract"
    >
      <div class="panel max-w-lg w-full max-h-[80vh] flex flex-col">
        <div class="panel-header">
          <span class="flex items-center gap-2 text-sm font-semibold text-ctp-text">
            <ArrowPathIcon class="w-4 h-4 text-ctp-blue" />{{ t('assetMgmt.sync.planTitle') }}
          </span>
        </div>
        <div class="p-3 space-y-2 overflow-auto text-xs">
          <p class="text-ctp-subtext1">{{ t('assetMgmt.sync.planDesc') }}</p>
          <div class="grid grid-cols-2 gap-1.5">
            <div class="rounded-md bg-ctp-surface0/60 px-2.5 py-1.5 flex items-center justify-between">
              <span class="text-ctp-subtext0">{{ t('assetMgmt.sync.rowAdded') }}</span>
              <span class="font-mono text-ctp-green">{{ syncPlan.added }}</span>
            </div>
            <div class="rounded-md bg-ctp-surface0/60 px-2.5 py-1.5 flex items-center justify-between">
              <span class="text-ctp-subtext0">{{ t('assetMgmt.sync.rowModified') }}</span>
              <span class="font-mono text-ctp-yellow">{{ syncPlan.modified }}</span>
            </div>
            <div class="rounded-md bg-ctp-surface0/60 px-2.5 py-1.5 flex items-center justify-between">
              <span class="text-ctp-subtext0">{{ t('assetMgmt.sync.rowNever') }}</span>
              <span class="font-mono text-ctp-sky">{{ syncPlan.neverExtracted }}</span>
            </div>
            <div class="rounded-md bg-ctp-surface0/60 px-2.5 py-1.5 flex items-center justify-between">
              <span class="text-ctp-subtext0">{{ t('assetMgmt.sync.rowStale') }}</span>
              <span class="font-mono text-ctp-peach">{{ syncPlan.staleOnly }}</span>
            </div>
          </div>
          <div class="rounded-md border border-ctp-blue/30 bg-ctp-blue/10 px-2.5 py-1.5 flex items-center justify-between">
            <span class="text-ctp-text font-semibold">{{ t('assetMgmt.sync.rowTotal') }}</span>
            <span class="font-mono text-ctp-blue">{{ syncPlan.toExtract }}</span>
          </div>
          <p
            v-if="syncPlan.deleted || syncPlan.invalidated"
            class="text-ctp-overlay1"
          >{{ t('assetMgmt.sync.deletedNote', { d: syncPlan.deleted, n: syncPlan.invalidated }) }}</p>
          <p class="text-ctp-overlay0">{{ t('assetMgmt.sync.batchesNote', { n: syncPlan.batchesEstimate ?? Math.ceil(syncPlan.toExtract / 10) }) }}</p>
          <div v-if="syncPlan.files.length">
            <p class="text-ctp-overlay0 mb-1">{{ t('assetMgmt.sync.filesSample') }}</p>
            <div class="rounded-md bg-ctp-mantle border border-ctp-surface1 p-2 font-mono text-[10px] text-ctp-subtext1 max-h-32 overflow-auto space-y-0.5">
              <div v-for="f in syncPlan.files" :key="f">{{ f }}</div>
            </div>
          </div>
        </div>
        <div class="flex items-center justify-end gap-2 px-3 py-2 border-t border-ctp-surface0">
          <button
            class="btn btn-sm btn-ghost"
            @click="cancelSyncExtract"
          >{{ t('assetMgmt.sync.cancel') }}</button>
          <button
            class="btn btn-sm btn-primary"
            @click="confirmSyncExtract"
          >{{ t('assetMgmt.sync.confirm') }}</button>
        </div>
      </div>
    </div>
  </div>
  <FileSourceCard
    v-if="fileCard"
    :file="fileCard.file"
    :assets="fileCard.assets"
    @close="fileCard = null"
    @goto="locateAsset"
  />
</template>

<style scoped>
/* 树行离屏跳过布局/绘制(配合前缀窗口渲染): 浏览器不维护不可见行样式与合成 */
.tree-row {
  content-visibility: auto;
  contain-intrinsic-size: auto 36px;
}
</style>
