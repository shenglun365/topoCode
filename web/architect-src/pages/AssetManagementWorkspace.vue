<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, ChevronDownIcon, ChevronRightIcon, ArrowPathIcon,
  SparklesIcon, CubeTransparentIcon, AdjustmentsHorizontalIcon, ServerStackIcon,
  ClipboardDocumentListIcon, ClipboardDocumentIcon, ScaleIcon, EyeIcon, TrashIcon,
} from '@heroicons/vue/24/outline'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import RequirementHistoryModal from '@/components/requirements/RequirementHistoryModal.vue'
import { chatStream, type KbAnalysisTurn } from '@/services/kb-analysis-agent'
import { semanticAssetService } from '@/services/semantic-asset-service'
import { kbAssetService } from '@/services/kb-assets'
import { requirementService } from '@/services/requirement-service'
import { useSplitPane } from '@/composables/useSplitPane'
import { useDiagramSkill } from '@/composables/useDiagramSkill'
import { useChatModel } from '@/composables/useChatModel'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import type { AssetDetail, ConversationDetail, SemanticAsset, SemanticAssetKind } from '@/types'

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
type AssetTab = 'semantic' | 'component'
const tab = ref<AssetTab>('semantic')
const kind = ref<SemanticAssetKind | ''>('')
const q = ref('')
const items = ref<SemanticAsset[]>([])
const comps = ref<AssetDetail[]>([])
const loading = ref(false)
const extracting = ref(false)
const reconciling = ref(false)
const statusCounts = ref<Record<string, number>>({})
const expanded = reactive<Record<string, boolean>>({})

const kinds: { value: SemanticAssetKind; label: string }[] = [
  { value: 'data_structure', label: t('assetMgmt.kind.data_structure') },
  { value: 'processing_flow', label: t('assetMgmt.kind.processing_flow') },
  { value: 'control_logic', label: t('assetMgmt.kind.control_logic') },
]

const statusText = computed(() => {
  const c = statusCounts.value
  return `active ${c.active ?? 0} · stale ${c.stale ?? 0} · deleted ${c.deleted ?? 0}`
})

// ---- 组件归属映射 + 组件范围筛选 + 按组件分组 ----
const arch = useArchArchitectureStore()
const OTHER_KEY = '__other__'

/** 统一组件节点(树/归属映射用)。 */
interface CompNode { id: string; name: string; parentId?: string; owns: string[] }

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
    return compCatalog.value.map((c) => ({ id: c.assetId, name: c.name, parentId: c.parentId ?? undefined, owns: c.owns ?? [] }))
  }
  if (arch.components.length) {
    return arch.components.map((c) => ({ id: c.id, name: c.name, parentId: c.parentId ?? undefined, owns: c.owns ?? [] }))
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
 *  → 按首个锚点文件反查；仍未命中则归「其它」。 */
function componentOf(a: SemanticAsset): string {
  const sk = a.scopeKey
  if (sk && compById.value.has(sk)) return sk
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

interface SemanticGroup { key: string; name: string; depth: number; assets: SemanticAsset[] }
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
  const walk = (parentId: string | undefined, depth: number) => {
    for (const c of treeComps.value) {
      if (c.parentId !== parentId) continue
      if (all || sel.has(c.id)) {
        const assets = byComp.get(c.id)
        if (assets?.length) groups.push({ key: c.id, name: c.name, depth, assets })
      }
      walk(c.id, depth + 1)
    }
  }
  walk(undefined, 0)
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
    const r = await semanticAssetService.searchPage(q.value, kind.value || undefined, { limit: PAGE_SIZE, offset: (page.value - 1) * PAGE_SIZE, scope: scopeParams() })
    items.value = r.items
    total.value = r.total
  } finally {
    loading.value = false
  }
}

async function loadComponents() {
  loading.value = true
  try {
    comps.value = await kbAssetService.searchComponents(q.value, {
      type: compType.value === 'all' ? undefined : compType.value,
      level: compLevel.value === 'all' ? undefined : compLevel.value,
    })
  } finally {
    loading.value = false
  }
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

/** 提取单个组件的语义资产(architect agent skills，comm 范围)。 */
async function extractComp(c: AssetDetail) {
  if (compExtracting[c.assetId]) return
  compExtracting[c.assetId] = true
  try {
    await semanticAssetService.extract({ type: 'comm', key: c.assetId }, kinds.map((k) => k.value), { modelId: chatModelId.value || undefined })
    await Promise.all([loadSemantic(), refreshStatus()])
  } catch (err: any) {
    console.warn('[asset-mgmt] extract component failed:', err)
  } finally {
    compExtracting[c.assetId] = false
  }
}

// ---- 语义资产批量管理(选定组件范围) ----
const batchOpen = ref(false)
const batchRunning = ref(false)
const batchAction = ref<'extract' | 'clear' | 'update' | ''>('')
const batchLast = ref('')

/** 当前组件范围：选中组件 id(空=全部) + 是否含「其它」。 */
function targetScope() {
  const compIds = scopeSel.value.filter((id) => id !== OTHER_KEY)
  const includeOther = scopeSel.value.length === 0 || scopeSel.value.includes(OTHER_KEY)
  return { compIds, includeOther }
}

async function runBatch(action: 'extract' | 'clear' | 'update') {
  if (batchRunning.value) return
  if (action === 'clear' && batchAction.value !== 'clear') {
    batchAction.value = 'clear'
    return
  }
  const { compIds, includeOther } = targetScope()
  if (action === 'extract' && scopeSel.value.length > 0 && compIds.length === 0) {
    batchLast.value = t('assetMgmt.batchExtractOnlyComp')
    return
  }
  batchRunning.value = true
  batchAction.value = ''
  try {
    const res = await semanticAssetService.batchManage(action, compIds, {
      includeOther,
      kinds: kinds.map((k) => k.value),
      modelId: chatModelId.value || undefined,
    })
    batchLast.value = t('assetMgmt.batchDone', { action: t(`assetMgmt.batchAction.${action}`), n: res.count })
    await Promise.all([loadSemantic(), refreshStatus()])
  } catch {
    batchLast.value = t('assetMgmt.batchFailed')
  } finally {
    batchRunning.value = false
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

async function extract() {
  extracting.value = true
  try {
    await semanticAssetService.extractAll(kinds.map((k) => k.value))
    await Promise.all([loadSemantic(), refreshStatus()])
  } finally {
    extracting.value = false
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
  if (k === 'processing_flow') return BoltIcon
  if (k === 'control_logic') return AdjustmentsHorizontalIcon
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
  if (tab.value === 'semantic') {
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
  await Promise.all([loadCompCatalog(), loadSemantic(), refreshStatus()])
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
            v-for="tb in [{ id: 'semantic' as const, label: t('assetMgmt.tab.semantic') }, { id: 'component' as const, label: t('assetMgmt.tab.component') }]"
            :key="tb.id"
            class="btn btn-xs"
            :class="tab === tb.id ? 'btn-blue' : 'btn-ghost'"
            @click="tab = tb.id; onSearch()"
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
          :disabled="extracting"
          @click="extract"
        >
          <SparklesIcon class="w-3.5 h-3.5" />{{ extracting ? t('assetMgmt.extracting') : t('assetMgmt.extractAll') }}
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
            <ClipboardDocumentListIcon class="w-4 h-4 text-ctp-mauve" />{{ tab === 'semantic' ? t('assetMgmt.tab.semantic') : t('assetMgmt.tab.component') }}
          </span>
          <input
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
          <button
            class="btn btn-xs btn-ghost"
            :disabled="loading"
            @click="onSearch"
          >
            <ArrowPathIcon class="w-3 h-3" />{{ t('assetMgmt.search') }}
          </button>
          <template v-if="tab === 'semantic'">
            <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ scopeSummary }}</span>
            <button
              class="btn btn-xs"
              :class="filterOpen ? 'btn-blue' : 'btn-ghost'"
              @click="filterOpen = !filterOpen; batchOpen = false"
            >
              <AdjustmentsHorizontalIcon class="w-3 h-3" />{{ t('assetMgmt.filter') }}
            </button>
            <button
              class="btn btn-xs"
              :class="batchOpen ? 'btn-blue' : 'btn-ghost'"
              :title="t('assetMgmt.batch')"
              @click="batchOpen = !batchOpen; filterOpen = false"
            >
              <TrashIcon class="w-3 h-3" />{{ t('assetMgmt.batch') }}
            </button>

            <!-- 点击浮层：批量管理(提取/清除/更新 选定组件范围) -->
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
                  class="btn btn-xs btn-blue"
                  :disabled="batchRunning"
                  @click="runBatch('extract')"
                >
                  <SparklesIcon class="w-3 h-3" />{{ t('assetMgmt.batchExtract') }}
                </button>
                <button
                  class="btn btn-xs btn-ghost"
                  :disabled="batchRunning"
                  @click="runBatch('update')"
                >
                  <ArrowPathIcon class="w-3 h-3" />{{ t('assetMgmt.batchUpdate') }}
                </button>
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
                <div class="flex items-center gap-1">
                  <button
                    class="btn btn-xs btn-red"
                    :disabled="batchRunning"
                    @click="runBatch('clear')"
                  >{{ t('assetMgmt.batchConfirm') }}</button>
                  <button
                    class="btn btn-xs btn-ghost"
                    @click="batchAction = ''"
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

        <div class="flex-1 min-h-0 overflow-auto p-2.5 space-y-1.5">
          <!-- 语义资产：按所属组件分组 -->
          <template v-if="tab === 'semantic'">
            <template
              v-for="g in semanticGroups"
              :key="g.key"
            >
              <div class="flex items-center gap-1.5 px-1 pt-1.5 pb-0.5">
                <ServerStackIcon
                  v-if="g.key !== OTHER_KEY"
                  class="w-3 h-3 text-ctp-blue shrink-0"
                />
                <span
                  v-else
                  class="w-3 h-3 shrink-0"
                />
                <span class="text-[10px] font-semibold text-ctp-subtext1 truncate">{{ g.name }}</span>
                <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[9px]">{{ g.assets.length }}</span>
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
                <span class="text-[11px] font-medium text-ctp-text truncate">{{ a.name }}</span>
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
                <span class="text-[9px] text-ctp-overlay0 font-mono">{{ a.id }}</span>
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

          <!-- 组件资产 -->
          <template v-else>
            <div
              v-for="c in comps"
              :key="c.assetId"
              class="border border-ctp-blue/20 hover:border-ctp-blue/40 rounded-lg overflow-hidden"
            >
              <div class="flex items-center gap-2 px-2 py-1.5">
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
                  :disabled="compExtracting[c.assetId]"
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
  </div>
</template>
