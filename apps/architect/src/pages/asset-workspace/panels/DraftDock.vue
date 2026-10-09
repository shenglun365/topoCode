<script setup lang="ts">
/**
 * 需求草稿停靠面板（重构版）：
 * - Tab 模型：草稿文档（编辑）/ MD 预览——都可关；启动为空态，点列表项/新建只开编辑 tab；
 *   预览经工具栏按钮按需打开（打开期间跟随内容刷新），关闭即清空。
 * - 自动保存（无按钮）：2s 节流写 LS；10s 轮询发现修改才 PUT 回写；关键动作与 tab 关闭即时 flush。
 * - 悬浮工具栏：AI 预设/执行指令块(topo-cmd)+预览+发布——可拖动、可折叠单 icon。
 * - 草稿列表在右侧：点击打开（仅编辑 tab）、✎ 行内改名、删除、归档只读+续写。
 * - 自定义指令：正文 ```topo-cmd 标记块（预览过滤不解析）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextIcon, PlusIcon, TrashIcon, EyeIcon, XMarkIcon,
  PencilSquareIcon, ArchiveBoxIcon, SparklesIcon, ChevronRightIcon, CheckIcon,
  PaperAirplaneIcon, PlayCircleIcon, LinkIcon, CheckBadgeIcon, WrenchScrewdriverIcon, Bars3Icon,
  TagIcon, ChatBubbleLeftRightIcon,
} from '@heroicons/vue/24/outline'
import { useAppDialog } from '@/composables/useAppDialog'
import { apiGet } from '@/services/api-client'
import MarkdownView from '@/components/MarkdownView.vue'
import DiagramCard from '@/components/diagram/DiagramCard.vue'
import { parseMessageBlocks } from '@/services/parse-message-blocks'
import { renderDiagram } from '@/services/topo-render'
import { semanticAssetService } from '@/services/semantic-asset-service'
import { sessionService } from '@/services/session-service'
import { reqDraftService, type ReqDraft } from '@/services/req-draft-service'
import { onDraftRef, type DraftRefPayload } from '../draft-ref-bus'
import { currentProjectParams } from '@/services/project-service'
import { diffLines, diffStat } from '@/utils/diff-lines'

const { t } = useI18n()
const dialog = useAppDialog()
/** 行内改名输入自动聚焦。 */
const vFocus = { mounted: (el: HTMLElement) => el.focus() }

// ══════════ 列表与当前草稿（单实例） ══════════
const drafts = ref<ReqDraft[]>([])
const current = ref<ReqDraft | null>(null)
const loading = ref(false)
/** 编辑缓冲（title/contentMd 本地）。 */
const titleDraft = ref('')
const contentDraft = ref('')
const editTa = ref<HTMLTextAreaElement | null>(null)

// ---- 列表视图（状态过滤 + 搜索；更新时间倒序为服务端既有排序） ----
type ListFilter = 'all' | 'editing' | 'archived'
const listFilter = ref<ListFilter>('all')
const listQuery = ref('')
const filteredDrafts = computed(() => {
  const q = listQuery.value.trim().toLowerCase()
  return drafts.value.filter((d) => {
    if (listFilter.value !== 'all' && (d.status || 'editing') !== listFilter.value) return false
    if (!q) return true
    return (d.title || '').toLowerCase().includes(q)
      || (d.excerpt || '').toLowerCase().includes(q)
  })
})
const filterCounts = computed(() => ({
  all: drafts.value.length,
  editing: drafts.value.filter((d) => (d.status || 'editing') === 'editing').length,
  archived: drafts.value.filter((d) => d.status === 'archived').length,
}))
const archived = computed(() => current.value?.status === 'archived')

/** 待回写状态点（列表项）：本地与基线有差异且未落库。 */
function pendingOf(id: string): boolean {
  return id === current.value?.id && pending.value
}

// ══════════ 自动保存引擎（LS 2s 节流 + DB 10s 轮询按需回写） ══════════
/** 基线：与服务器一致的内容（打开/回写成功后同步）。 */
let baseTitle = ''
let baseContent = ''
/** 有未回写修改。 */
const pending = ref(false)
const saving = ref(false)
let lsTimer: ReturnType<typeof setInterval> | null = null
let dbTimer: ReturnType<typeof setInterval> | null = null

function lsKey(id: string): string {
  const { project } = currentProjectParams()
  return `draft-dock:${project || ''}:${id}`
}

function isDirty(): boolean {
  return !!current.value && (titleDraft.value !== baseTitle || contentDraft.value !== baseContent)
}

function lsWrite(): void {
  if (!current.value || archived.value) return
  try {
    localStorage.setItem(lsKey(current.value.id), JSON.stringify({
      title: titleDraft.value, contentMd: contentDraft.value, ts: Date.now(),
    }))
  } catch { /* LS 满等静默 */ }
}

function lsClear(id: string): void {
  try { localStorage.removeItem(lsKey(id)) } catch { /* 忽略 */ }
}

/** flush：有修改立即 PUT 回写（关键动作/tab 关闭调用）。 */
async function flush(): Promise<void> {
  if (!current.value || archived.value || !isDirty() || saving.value) return
  saving.value = true
  try {
    current.value = await reqDraftService.update(current.value.id, {
      title: titleDraft.value, contentMd: contentDraft.value,
    })
    baseTitle = titleDraft.value
    baseContent = contentDraft.value
    pending.value = false
    lsClear(current.value.id)
    syncListRow()
  } catch { /* 回写失败保留 LS，下轮重试 */ } finally {
    saving.value = false
  }
}

/** 10s 轮询：有修改才回写（无修改不发请求）。 */
function dbTick(): void {
  if (pending.value || isDirty()) void flush()
}

/** 2s 节流：dirty 时写 LS。 */
function lsTick(): void {
  if (isDirty()) lsWrite()
}

function startAutosave(): void {
  if (!lsTimer) lsTimer = setInterval(lsTick, 2000)
  if (!dbTimer) dbTimer = setInterval(dbTick, 10000)
}
function stopAutosave(): void {
  if (lsTimer) { clearInterval(lsTimer); lsTimer = null }
  if (dbTimer) { clearInterval(dbTimer); dbTimer = null }
}

function syncListRow(): void {
  if (!current.value) return
  const idx = drafts.value.findIndex((x) => x.id === current.value!.id)
  if (idx >= 0) drafts.value[idx] = { ...drafts.value[idx], ...current.value }
}

// ---- LS 恢复（刷新接续）：LS.ts 比服务端新 → 恢复继续编辑 ----
function lsRestore(d: ReqDraft): boolean {
  try {
    const raw = localStorage.getItem(lsKey(d.id))
    if (!raw) return false
    const saved = JSON.parse(raw) as { title: string; contentMd: string; ts: number }
    if ((saved.ts ?? 0) <= (d.updatedAt ?? 0)) {
      lsClear(d.id)
      return false
    }
    titleDraft.value = saved.title ?? ''
    contentDraft.value = saved.contentMd ?? ''
    baseTitle = d.title ?? ''
    baseContent = d.contentMd ?? ''
    pending.value = true
    return true
  } catch {
    return false
  }
}

// ══════════ Tab 模型（都可关；启动空态） ══════════
type Tab = 'edit' | 'preview'
const tabs = ref<Tab[]>([])
const activeTab = ref<Tab>('edit')
/** 当前编辑 tab 是否有效（有打开的草稿）。空态=无 tab。 */

function closeTab(tab: Tab): void {
  if (tab === 'edit') {
    // 关编辑 tab = 关闭当前草稿：先 flush 再回空态
    void flush().finally(() => {
      current.value = null
      titleDraft.value = ''
      contentDraft.value = ''
      baseTitle = ''
      baseContent = ''
      pending.value = false
      tabs.value = []
      activeTab.value = 'edit'
    })
    return
  }
  // 关预览 tab = 清空
  tabs.value = tabs.value.filter((x) => x !== 'preview')
  if (activeTab.value === 'preview') activeTab.value = 'edit'
}

/** 打开草稿（列表点击 / LS 恢复）：只开编辑 tab；旧草稿先 flush。 */
async function openDraft(d: ReqDraft): Promise<void> {
  if (current.value?.id === d.id) {
    activeTab.value = 'edit'
    if (!tabs.value.includes('edit')) tabs.value.push('edit')
    return
  }
  await flush()   // 旧草稿落库（自动保存取代人工确认）
  loading.value = true
  cancelTagEdit()
  try {
    const full = await reqDraftService.get(d.id)
    if (!full) return
    current.value = full
    baseTitle = full.title ?? ''
    baseContent = full.contentMd ?? ''
    pending.value = false
    if (lsRestore(full)) { /* LS 较新：恢复离线编辑接续 */ }
    else {
      titleDraft.value = full.title ?? ''
      contentDraft.value = full.contentMd ?? ''
    }
    tabs.value = ['edit']   // 预览不自动开；需经工具栏按钮
    activeTab.value = 'edit'
    void loadGaps()
  } finally {
    loading.value = false
  }
}

async function createDraft(): Promise<void> {
  await flush()
  loading.value = true
  try {
    const d = await reqDraftService.create({ title: t('draft.untitled') })
    await loadList()
    await openDraft(d)
    // 新草稿正文开头自动带 topo-cmd 模板(注释引导, 用户填写指令)
    if (!contentDraft.value.trim()) {
      contentDraft.value = `${cmdTemplate()}\n\n`
      pending.value = true
      await flush()
    }
  } finally {
    loading.value = false
  }
}

async function loadList(selectId?: string): Promise<void> {
  loading.value = true
  try {
    drafts.value = await reqDraftService.list()
    if (selectId) {
      const target = drafts.value.find((d) => d.id === selectId)
      if (target) await openDraft(target)
    }
  } finally {
    loading.value = false
  }
}

// ---- 列表项：行内改名（✎ → input，Enter/失焦提交，Esc 取消） ----
const renamingId = ref('')
const renameDraft = ref('')
function startRename(d: ReqDraft): void {
  if (d.status === 'archived') return
  renamingId.value = d.id
  renameDraft.value = d.title || ''
}
async function commitRename(): Promise<void> {
  const id = renamingId.value
  if (!id) return
  renamingId.value = ''
  const title = renameDraft.value.trim()
  const row = drafts.value.find((x) => x.id === id)
  if (!row || !title || title === row.title) return
  const updated = await reqDraftService.update(id, { title })
  if (current.value?.id === id) {
    current.value = updated
    titleDraft.value = updated.title
    baseTitle = updated.title
  }
  syncListRow()
}
function cancelRename(): void {
  renamingId.value = ''
}

// ---- 标签（概念泛化后的自由分类）：文档头部浮层(展示/编辑) + 联想 ----
const tagsEditing = ref(false)
const tagInput = ref('')
const tagSuggestOpen = ref(false)
const tagSuggestIdx = ref(-1)
const allTags = ref<{ name: string; count: number }[]>([])
const tagsOf = computed<string[]>(() => (Array.isArray(current.value?.tags) ? current.value!.tags! : []))
/** 联想候选：备选全集 contains 匹配、排除已选；输入为空给 top 备选。 */
const tagCandidates = computed(() => {
  const q = tagInput.value.trim().toLowerCase()
  return allTags.value
    .filter((c) => !tagsOf.value.includes(c.name) && (!q || c.name.toLowerCase().includes(q)))
    .slice(0, 8)
})
const tagHasNew = computed(() => {
  const s = tagInput.value.trim()
  return !!s && !tagsOf.value.includes(s) && !tagCandidates.value.some((c) => c.name === s)
})

async function refreshAllTags(): Promise<void> {
  try {
    allTags.value = await reqDraftService.allTags()
  } catch { /* 备选加载失败静默——可继续手输新建 */ }
}

function startTagEdit(): void {
  if (archived.value || !current.value) return
  tagsEditing.value = true
  tagInput.value = ''
  tagSuggestIdx.value = -1
  void refreshAllTags()
}
function cancelTagEdit(): void {
  tagsEditing.value = false
  tagInput.value = ''
  tagSuggestOpen.value = false
  tagSuggestIdx.value = -1
}

/** 增/删后立即落库(低频离散操作不走自动保存引擎)；服务端归一结果回填。 */
async function commitTags(tags: string[]): Promise<void> {
  if (!current.value) return
  try {
    const updated = await reqDraftService.update(current.value.id, { tags })
    current.value = updated
    syncListRow()
    void refreshAllTags()
  } catch { /* 失败保留本地，下次操作重试 */ }
}
function addTag(name: string): void {
  const s = name.trim()
  tagInput.value = ''
  tagSuggestOpen.value = false
  tagSuggestIdx.value = -1
  if (!s || !current.value || tagsOf.value.includes(s) || tagsOf.value.length >= 20) return
  void commitTags([...tagsOf.value, s])
}
function removeTag(name: string): void {
  void commitTags(tagsOf.value.filter((x) => x !== name))
}
function onTagInput(): void {
  tagSuggestOpen.value = true
  tagSuggestIdx.value = -1
}
function onTagKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.preventDefault()
    if (tagSuggestOpen.value) { tagSuggestOpen.value = false; tagSuggestIdx.value = -1 }
    else cancelTagEdit()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const pick = tagSuggestIdx.value >= 0 ? tagCandidates.value[tagSuggestIdx.value]?.name : undefined
    addTag(pick || tagInput.value)
  } else if (e.key === 'ArrowDown' && tagSuggestOpen.value) {
    e.preventDefault()
    tagSuggestIdx.value = Math.min(tagSuggestIdx.value + 1, tagCandidates.value.length - 1)
  } else if (e.key === 'ArrowUp' && tagSuggestOpen.value) {
    e.preventDefault()
    tagSuggestIdx.value = Math.max(tagSuggestIdx.value - 1, 0)
  } else if (e.key === 'Backspace' && !tagInput.value && tagsOf.value.length) {
    removeTag(tagsOf.value[tagsOf.value.length - 1])
  }
}
/** 列表 tag chip 点击 → 填入搜索框(按 tag 查找)。 */
function filterByTag(name: string): void {
  listQuery.value = name
}

// ---- 卡片内容引用接收(代码资产卡/符号卡/逻辑资产卡 → 草稿) ----
function _esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/`/g, '\u0060')
}
function refSourceLine(src: DraftRefPayload['source']): string {
  const parts: string[] = []
  if (src.projectId) parts.push(`项目 \`${_esc(src.projectId)}\``)
  if (src.compId) parts.push(`组件 \`${_esc(src.compId)}\``)
  if (src.viewId) parts.push(`视图 \`${_esc(src.viewId)}\`「${_esc(src.viewName ?? '')}」`)
  if (src.fileId) parts.push(`文件 \`${_esc(src.fileId)}\`${src.fileLabel ? `(${_esc(src.fileLabel)})` : ''}`)
  if (src.assetId) parts.push(`资产 \`${_esc(src.assetId)}\`「${_esc(src.assetName ?? '')}」`)
  if (src.coreAssetId) parts.push(`核心资产 \`${_esc(src.coreAssetId)}\``)
  if (src.symbolName) {
    const span = src.lineStart ? ` L${src.lineStart}${src.lineEnd && src.lineEnd !== src.lineStart ? `-L${src.lineEnd}` : ''}` : ''
    parts.push(`符号 \`${_esc(src.symbolName)}\`${span}`)
  }
  return parts.join(' · ')
}
function refBlock(p: DraftRefPayload): string {
  const time = new Date().toLocaleTimeString('zh-CN', { hour12: false }).slice(0, 5)
  const fence = '```'
  const body = p.text.split('\n').map((l) => `> ${l}`.trimEnd()).join('\n')
  const lang = p.lang ? _esc(p.lang) : ''
  return [
    `> **引用** · ${time}`,
    `> 来源：${refSourceLine(p.source) || '—'}`,
    '>',
    `> ${fence}${lang}`,
    body,
    `> ${fence}`,
  ].join('\n')
}
async function receiveDraftRef(p: DraftRefPayload): Promise<void> {
  await flush()
  const usable = current.value && (current.value.status || 'editing') === 'editing' ? current.value : null
  if (!usable) {
    await createDraft()   // 无打开中的草稿 → 新建(openDraft 已切编辑态)
  }
  contentDraft.value = `${contentDraft.value.replace(/\s+$/, '')}\n\n${refBlock(p)}\n`
  pending.value = true
  await flush()          // 关键动作即时落库
  syncListRow()
  // 引用块定位: 编辑区滚到尾部(预览 tab 同样滚底); 广播完成(浮条「已引用」反馈)
  void nextTick(() => {
    const ta = editTa.value as HTMLTextAreaElement | null
    if (activeTab.value === 'edit' && ta) ta.scrollTop = ta.scrollHeight
    const pv = document.querySelector('[data-draft-preview]')
    if (pv) pv.scrollTop = pv.scrollHeight
  })
  window.dispatchEvent(new CustomEvent('draft-ref-done', { detail: { created: !usable } }))
}
onMounted(() => {
  startAutosave()
  window.addEventListener('beforeunload', onBeforeUnload)
  offDraftRef = onDraftRef((p) => { void receiveDraftRef(p) })
})

async function removeDraft(): Promise<void> {
  if (!current.value) return
  if (!(await dialog.confirm(t('draft.deleteConfirm', { title: current.value.title || t('draft.untitled') }), { danger: true }))) return
  const id = current.value.id
  lsClear(id)
  await reqDraftService.remove(id)
  current.value = null
  tabs.value = []
  await loadList()
}

/** 续写：归档草稿复制副本继续编写。 */
async function copyDraft(): Promise<void> {
  if (!current.value) return
  const cp = await reqDraftService.copy(current.value.id)
  await loadList(cp.id)
}

// ══════════ 悬浮工具栏（可拖动/可折叠） ══════════
const { project: projKey } = currentProjectParams()
const tbPos = ref({ x: 12, y: 8 })
const tbCollapsed = ref(false)
try {
  const saved = JSON.parse(localStorage.getItem(`draft-dock-toolbar:${projKey || ''}`) || '{}')
  if (typeof saved.x === 'number') tbPos.value = { x: saved.x, y: saved.y }
  if (typeof saved.collapsed === 'boolean') tbCollapsed.value = saved.collapsed
} catch { /* 忽略 */ }

function persistToolbar(): void {
  try {
    localStorage.setItem(`draft-dock-toolbar:${projKey || ''}`,
      JSON.stringify({ x: tbPos.value.x, y: tbPos.value.y, collapsed: tbCollapsed.value }))
  } catch { /* 忽略 */ }
}

/** 主区容器（拖动边界 clamp）。 */
const editorHost = ref<HTMLElement | null>(null)
let dragStart: { px: number; py: number; x: number; y: number } | null = null
/** 折叠态：icon 兼把手——移动超阈值视为拖动，抑制随后的 click（避免拖完误切折叠）。 */
let collapsedDragging = false

function onToolbarDown(e: PointerEvent): void {
  const target = e.target as HTMLElement
  const fromHandle = !!target.closest('.tb-handle')
  const fromCollapsed = tbCollapsed.value && !!target.closest('button')
  if (!fromHandle && !fromCollapsed) return
  dragStart = { px: e.clientX, py: e.clientY, x: tbPos.value.x, y: tbPos.value.y }
  collapsedDragging = false
  const move = (ev: PointerEvent): void => {
    if (!dragStart) return
    const dx = ev.clientX - dragStart.px
    const dy = ev.clientY - dragStart.py
    if (fromCollapsed && Math.hypot(dx, dy) > 4) collapsedDragging = true
    const host = editorHost.value
    const maxX = (host?.clientWidth ?? 800) - 60
    const maxY = (host?.clientHeight ?? 400) - 30
    tbPos.value = {
      x: Math.max(4, Math.min(maxX, dragStart.x + dx)),
      y: Math.max(4, Math.min(maxY, dragStart.y + dy)),
    }
  }
  const up = (): void => {
    dragStart = null
    persistToolbar()
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}

function onCollapsedClick(): void {
  if (collapsedDragging) {   // 拖动结束的这次 click 不切换折叠
    collapsedDragging = false
    return
  }
  tbCollapsed.value = !tbCollapsed.value
  persistToolbar()
}

// ══════════ AI 处理（指令=正文 topo-cmd 块；无专用输入框） ══════════
const aiBusy = ref(false)
const aiStatus = ref('')
// C3 缺口建议(上下文感知): 打开草稿时拉取, 提示不拦截; chips 一键调技能
const gaps = ref<{ skill: string; reason: string }[]>([])
const gapsDismissedFor = ref('')
async function loadGaps(): Promise<void> {
  if (!current.value || current.value.status === 'archived') { gaps.value = []; return }
  try {
    const r = await apiGet<{ gaps: { skill: string; reason: string }[] }>(
      `/req-drafts/${encodeURIComponent(current.value.id)}/gaps`)
    gaps.value = r?.gaps ?? []
  } catch { gaps.value = [] }
}
let aiJobTimer: ReturnType<typeof setInterval> | null = null

function hasCmdBlock(): boolean {
  return /```topo-cmd[ \t]*\r?\n[\s\S]*?```/.test(contentDraft.value)
}

/** topo-cmd 指令模板(带注释引导; BE 剥离注释行, 注释不会发给 AI)。 */
function cmdTemplate(): string {
  return t('draft.ai.topoTemplate')
}
/** 围栏内指令文本(剥注释后)——空=全注释未填写。 */
function cmdText(): string {
  const m = contentDraft.value.match(/```topo-cmd[ \t]*\r?\n([\s\S]*?)```/)
  if (!m) return ''
  return (m[1] ?? '').split('\n')
    .filter((l) => !l.trim().startsWith('#') && !l.trim().startsWith('//'))
    .join('\n').trim()
}
/** 在正文开头插入指令块模板(已存在则不重复)。 */
async function insertCmdTemplate(): Promise<void> {
  if (hasCmdBlock()) return
  await flush()
  contentDraft.value = `${cmdTemplate()}\n\n${contentDraft.value.replace(/^\s+/, '')}`
  pending.value = true
  await flush()
  syncListRow()
}

async function runAi(preset: 'generate' | 'review' | 'relate' | 'custom'): Promise<void> {
  if (!current.value || aiBusy.value || archived.value) return
  if (preset === 'custom') {
    if (!hasCmdBlock()) {
      // 无指令块 → 自动插入模板(不再仅报错), 用户填写后再次执行
      await insertCmdTemplate()
      aiStatus.value = t('draft.ai.cmdInserted')
      return
    }
    if (!cmdText()) {
      aiStatus.value = t('draft.ai.cmdEmpty')
      return
    }
  }
  await flush()   // AI 上下文=已保存正文
  aiBusy.value = true
  aiStatus.value = t('draft.ai.submitting')
  try {
    const r = await reqDraftService.runAi(current.value.id, { preset })
    const jobId = r?.job?.id
    if (!jobId || (!r?.started && r?.reason !== 'already_running')) {
      aiStatus.value = r?.reason === 'already_running'
        ? t('assetMgmt.compExtractAlreadyRunning') : t('draft.ai.submitFailed')
      return
    }
    await new Promise<void>((resolve) => {
      aiJobTimer = setInterval(async () => {
        try {
          const j = await semanticAssetService.getJob(jobId)
          if (!j || j.state === 'done') resolve()
          else if (j.state === 'failed' || j.state === 'cancelled' || j.state === 'lost') {
            aiStatus.value = t('draft.ai.failed')
            resolve()
          } else aiStatus.value = t('draft.ai.running', { current: j.result?.summary || j.state })
        } catch { /* 轮询失败静默 */ }
      }, 2000)
    })
    if (aiJobTimer) { clearInterval(aiJobTimer); aiJobTimer = null }
    current.value = await reqDraftService.get(current.value.id) ?? current.value
    aiStatus.value = current.value.lastProposedMd ? t('draft.ai.done') : t('draft.ai.failed')
    // 产物就绪 → 自动展开比对区(默认收起曾致「无结果」感知——用户需显式发现折叠条)
    if (current.value.lastProposedMd) proposedOpen.value = true
  } catch (e) {
    aiStatus.value = e instanceof Error && e.message ? e.message : t('draft.ai.submitFailed')
  } finally {
    if (aiJobTimer) { clearInterval(aiJobTimer); aiJobTimer = null }
    aiBusy.value = false
  }
}

// ══════════ AI 产物比对（git diff；采纳/放弃保留参考） ══════════
const proposedOpen = ref(false)
const adopting = ref(false)
const proposedDiff = computed(() =>
  current.value?.lastProposedMd
    ? diffLines(current.value.contentMd || '', current.value.lastProposedMd)
    : [])
const proposedStat = computed(() => diffStat(proposedDiff.value))

async function adoptProposal(): Promise<void> {
  if (!current.value || adopting.value) return
  adopting.value = true
  try {
    current.value = await reqDraftService.adopt(current.value.id)
    contentDraft.value = current.value.contentMd
    titleDraft.value = current.value.title
    baseTitle = current.value.title
    baseContent = current.value.contentMd
    pending.value = false
    lsClear(current.value.id)
    syncListRow()
  } finally {
    adopting.value = false
  }
}

// ══════════ 发布（草稿 → 需求卡 → 会话） ══════════
interface ConvOption { id: string; title: string; reqId?: string }
const publishOpen = ref(false)
const publishBusy = ref(false)
const publishTarget = ref<'new' | string>('new')
const convOptions = ref<ConvOption[]>([])
const publishMsg = ref('')
const pickerPage = ref(0)
const pickerTotal = ref(0)
const pickerOrFallback = ref(false)
const pickerLoading = ref(false)
const pickerQuery = ref('')
let pickerSearchTimer: ReturnType<typeof setTimeout> | null = null
const PICKER_PAGE_SIZE = 10
const pickerPageCount = computed(() => Math.max(1, Math.ceil(pickerTotal.value / PICKER_PAGE_SIZE)))

async function loadPicker(page = 0, kw = pickerQuery.value.trim()): Promise<void> {
  pickerLoading.value = true
  try {
    const r = await sessionService.picker({
      kw: kw || undefined, limit: PICKER_PAGE_SIZE, offset: page * PICKER_PAGE_SIZE,
    })
    convOptions.value = r?.items ?? []
    pickerTotal.value = r?.total ?? 0
    pickerOrFallback.value = !!r?.orFallback
    pickerPage.value = page
    if (publishTarget.value !== 'new' && !convOptions.value.some((c) => c.id === publishTarget.value)) {
      publishTarget.value = convOptions.value[0]?.id ?? 'new'
    }
  } catch {
    convOptions.value = []
    pickerTotal.value = 0
  } finally {
    pickerLoading.value = false
  }
}

function onPickerSearch(): void {
  if (pickerSearchTimer) clearTimeout(pickerSearchTimer)
  pickerSearchTimer = setTimeout(() => { void loadPicker(0) }, 300)
}

async function openPublish(): Promise<void> {
  if (!current.value || archived.value || !(contentDraft.value || '').trim()) return
  await flush()
  publishMsg.value = ''
  publishTarget.value = 'new'
  pickerQuery.value = ''
  publishOpen.value = true
  await loadPicker(0, '')
}

async function doPublish(overwrite = false): Promise<void> {
  if (!current.value || publishBusy.value) return
  publishBusy.value = true
  publishMsg.value = ''
  try {
    const r = await reqDraftService.publish(current.value.id, {
      targetConvId: publishTarget.value === 'new' ? undefined : publishTarget.value,
      overwrite,
    })
    current.value = r.draft
    publishOpen.value = false
    pending.value = false
    lsClear(current.value.id)
    syncListRow()
  } catch (e: unknown) {
    const msg = e instanceof Error && e.message ? e.message : String(e)
    if (msg.includes('未完结需求卡') && await dialog.confirm(msg + '\n\n' + t('draft.publish.overwriteConfirm'))) {
      publishBusy.value = false
      await doPublish(true)
      return
    }
    publishMsg.value = msg
  } finally {
    publishBusy.value = false
  }
}

// ══════════ 预览（MD tab；topo-cmd 块过滤不解析） ══════════
interface PreviewBlock {
  kind: 'text' | 'mermaid' | 'plantuml' | 'diagram' | 'dot'
  text?: string
  code?: string
}
const CMD_FENCE_RE = /```topo-cmd[ \t]*\r?\n[\s\S]*?```/g
/** 预览源：正文剥离 topo-cmd 指令块（MD 预览过滤不解析）。 */
const previewSource = computed(() => (contentDraft.value || '').replace(CMD_FENCE_RE, ''))
const previewBlocks = computed<PreviewBlock[]>(() => {
  const src = previewSource.value
  const out: PreviewBlock[] = []
  const DOT_RE = /```dot[ \t]*\r?\n([\s\S]*?)```/g
  const dotSpans: [number, number, string][] = []
  let m: RegExpExecArray | null
  while ((m = DOT_RE.exec(src))) dotSpans.push([m.index, m.index + m[0].length, m[1]])
  let cursor = 0
  for (const blocks of parseMessageBlocks(src)) {
    if (blocks.type === 'diagram') continue
    if (blocks.type === 'text') {
      const text = blocks.text
      const absStart = src.indexOf(text, cursor)
      let localCursor = 0
      for (const [sPos, ePos, code] of dotSpans.filter(([sp]) => sp >= absStart && sp < absStart + text.length)) {
        const rel = sPos - absStart
        const before = text.slice(localCursor, rel)
        if (before.trim()) out.push({ kind: 'text', text: before })
        out.push({ kind: 'dot', code })
        localCursor = ePos - absStart
      }
      const rest = text.slice(localCursor)
      if (rest.trim()) out.push({ kind: 'text', text: rest })
      cursor = absStart + text.length
    } else {
      out.push({ kind: blocks.type, code: blocks.code })
    }
  }
  return out
})

/** dot 块渲染（PlantUML 服务端原生支持 GraphViz DOT；失败降级源码+短路）。 */
const dotSvgs = ref<Record<number, string>>({})
const plantumlDown = ref(false)
watch(previewBlocks, async (blocks, prev) => {
  if (blocks !== prev) plantumlDown.value = false
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i]
    if (b.kind !== 'dot' || !b.code) continue
    if (plantumlDown.value) { dotSvgs.value[i] = '' }
    try {
      dotSvgs.value[i] = await renderDiagram('plantuml', b.code.trim())
      plantumlDown.value = false
    } catch {
      dotSvgs.value[i] = ''
      plantumlDown.value = true
    }
  }
}, { immediate: true })

/** 打开 MD 预览 tab（工具栏按钮；切换草稿后预览关闭需再次打开）。 */
function openPreviewTab(): void {
  if (!current.value) return
  if (!tabs.value.includes('preview')) tabs.value.push('preview')
  activeTab.value = 'preview'
}

function fmtTime(ts: number): string {
  return ts ? new Date(ts).toLocaleString() : ''
}

// ══════════ 生命周期 ══════════
function onBeforeUnload(): void {
  if (current.value && isDirty()) lsWrite()
}

onMounted(() => {
  startAutosave()
  window.addEventListener('beforeunload', onBeforeUnload)
  void loadList()
})
let offDraftRef: (() => void) | null = null
onBeforeUnmount(() => {
  void flush()
  stopAutosave()
  if (aiJobTimer) clearInterval(aiJobTimer)
  if (pickerSearchTimer) clearTimeout(pickerSearchTimer)
  window.removeEventListener('beforeunload', onBeforeUnload)
  offDraftRef?.()
  offDraftRef = null
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- Tab 栏：草稿文档 / MD预览（都可关；空态无 tab） -->
    <div class="flex h-8 shrink-0 items-center gap-1 border-b border-ctp-surface0 px-2">
      <template v-if="tabs.length">
        <div
          v-for="tab in tabs" :key="tab"
          class="flex items-center gap-1 rounded-t-md px-2 py-1 text-[11px] cursor-pointer"
          :class="activeTab === tab ? 'bg-ctp-surface0 text-ctp-text' : 'text-ctp-overlay1 hover:text-ctp-subtext1'"
          @click="activeTab = tab"
        >
          <DocumentTextIcon class="h-3 w-3" />
          {{ tab === 'edit' ? t('draft.tab.edit') : t('draft.tab.preview') }}
          <button class="text-ctp-overlay0 hover:text-ctp-red" @click.stop="closeTab(tab)">
            <XMarkIcon class="h-3 w-3" />
          </button>
        </div>
        <span class="ml-2 min-w-0 truncate text-[10px] text-ctp-overlay0" :title="current?.title">
          {{ current?.title || t('draft.untitled') }}<span v-if="pending" class="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-ctp-peach" />
        </span>
      </template>
      <template v-else>
        <span class="text-[11px] text-ctp-overlay0">{{ t('draft.emptyTabs') }}</span>
      </template>
    </div>

    <!-- AI 状态行 -->
    <div v-if="aiBusy || aiStatus" class="shrink-0 px-2 py-0.5 text-[10px]" :class="aiBusy ? 'text-ctp-sky' : 'text-ctp-overlay1'">
      {{ aiBusy ? t('draft.ai.running', { current: aiStatus }) : aiStatus }}
    </div>

    <!-- 文档头部标签浮层(展示/编辑态; UI 层, 不在 MD 文本范围内) -->
    <div
      v-if="tabs.length && current"
      class="relative z-10 flex shrink-0 flex-wrap items-center gap-1 border-b border-ctp-surface0 px-2 py-1"
    >
      <TagIcon class="h-3 w-3 shrink-0 text-ctp-overlay0" />
      <template v-if="!tagsEditing">
        <span
          v-for="tg in tagsOf" :key="tg"
          class="max-w-40 cursor-pointer truncate rounded bg-ctp-surface0 px-1.5 py-0.5 text-[10px] text-ctp-overlay1 hover:text-ctp-text"
          :title="tg" @click="filterByTag(tg)"
        >{{ tg }}</span>
        <span v-if="!tagsOf.length" class="text-[10px] text-ctp-overlay0">{{ t('draft.tags.addPlaceholder') }}</span>
        <button
          v-if="!archived"
          class="ml-0.5 rounded px-1 py-0.5 text-[10px] text-ctp-overlay1 hover:bg-ctp-surface0 hover:text-ctp-text"
          :title="t('draft.tags.edit')" @click="startTagEdit"
        >✎</button>
      </template>
      <template v-else>
        <span
          v-for="tg in tagsOf" :key="tg"
          class="flex max-w-40 items-center gap-0.5 truncate rounded bg-ctp-surface0 px-1.5 py-0.5 text-[10px] text-ctp-subtext1"
          :title="tg"
        >
          {{ tg }}
          <button class="text-ctp-overlay0 hover:text-ctp-red" @click="removeTag(tg)">×</button>
        </span>
        <span class="relative inline-flex">
          <input
            v-model="tagInput" v-focus
            class="input !w-36 !px-1.5 !py-0.5 !text-[10px]"
            maxlength="32"
            :placeholder="t('draft.tags.addPlaceholder')"
            :title="t('draft.tags.tooLong')"
            @input="onTagInput"
            @keydown="onTagKeydown"
            @blur="tagSuggestOpen = false"
          >
          <!-- 联想浮层：已有标签备选(含计数) + 新建项; Esc/失焦/选中关闭 -->
          <div
            v-if="tagSuggestOpen && (tagCandidates.length || tagHasNew)"
            class="absolute left-0 top-full z-30 mt-0.5 max-h-44 w-48 overflow-y-auto rounded-md border border-ctp-surface1 bg-ctp-mantle py-0.5 shadow-lg"
          >
            <div v-if="tagCandidates.length" class="px-2 py-0.5 text-[9px] text-ctp-overlay0">{{ t('draft.tags.suggestTitle') }}</div>
            <button
              v-for="(c, i) in tagCandidates" :key="c.name"
              class="flex w-full items-center gap-1 px-2 py-0.5 text-left text-[10px]"
              :class="i === tagSuggestIdx ? 'bg-ctp-surface0 text-ctp-text' : 'text-ctp-subtext1 hover:bg-ctp-surface0/60'"
              @mousedown.prevent="addTag(c.name)"
            >
              <span class="min-w-0 flex-1 truncate">{{ c.name }}</span>
              <span class="font-mono text-[9px] text-ctp-overlay0">{{ c.count }}</span>
            </button>
            <button
              v-if="tagHasNew"
              class="w-full px-2 py-0.5 text-left text-[10px] text-ctp-blue"
              :class="tagSuggestIdx === tagCandidates.length ? 'bg-ctp-surface0' : 'hover:bg-ctp-surface0/60'"
              @mousedown.prevent="addTag(tagInput)"
            >+ {{ t('draft.tags.tagNew', { name: tagInput.trim() }) }}</button>
          </div>
        </span>
        <button class="btn btn-xs btn-blue ml-0.5" @click="cancelTagEdit">{{ t('draft.tags.done') }}</button>
      </template>
    </div>

    <div class="flex min-h-0 flex-1">
      <!-- 左：主区（编辑/预览 + 悬浮工具栏） -->
      <div ref="editorHost" class="relative flex min-h-0 min-w-0 flex-1">
        <!-- 悬浮工具栏（拖动/折叠）：AI + 预览 + 发布 -->
        <div
          v-if="tabs.length && !archived"
          class="absolute z-20 flex items-center gap-0.5 rounded-lg border border-ctp-surface1 bg-ctp-mantle/95 px-1 py-0.5 shadow-lg"
          :style="{ top: tbPos.y + 'px', left: tbPos.x + 'px' }"
          @pointerdown="onToolbarDown"
        >
          <template v-if="!tbCollapsed">
            <span
              class="tb-handle mr-0.5 cursor-grab self-stretch flex items-center text-ctp-overlay0 hover:text-ctp-text active:cursor-grabbing"
              :title="t('draft.toolbar.drag')"
              @pointerdown.stop="onToolbarDown"
            ><Bars3Icon class="h-3.5 w-3.5" /></span>
            <!-- C3 缺口建议条: 上下文感知(过短/缺验收/未关联), chips 一键调技能; 可关闭 -->
            <div
              v-if="gaps.length && gapsDismissedFor !== current?.id"
              class="flex min-w-0 items-center gap-1 rounded border border-ctp-yellow/25 bg-ctp-yellow/8 px-1.5 py-0.5"
            >
              <span class="shrink-0 text-[9px] text-ctp-yellow">{{ t('draft.gapHint') }}</span>
              <button
                v-for="g in gaps" :key="g.skill"
                class="max-w-[130px] shrink-0 truncate rounded bg-ctp-surface0/80 px-1 text-[9px] text-ctp-subtext1 hover:text-ctp-text"
                :title="g.reason"
                :disabled="aiBusy"
                @click="runAi(g.skill as any)"
              >{{ g.skill === 'generate' ? t('draft.ai.generate') : g.skill === 'review' ? t('draft.ai.review') : t('draft.ai.relate') }}</button>
              <button
                class="shrink-0 text-ctp-overlay0 hover:text-ctp-text"
                :title="t('common.close')" @click="gapsDismissedFor = current?.id || ''"
              ><XMarkIcon class="h-2.5 w-2.5" /></button>
            </div>
            <button class="tb-btn" :disabled="aiBusy" :title="t('draft.ai.generate')" @click="runAi('generate')"><SparklesIcon class="h-3.5 w-3.5" /></button>
            <button class="tb-btn" :disabled="aiBusy" :title="t('draft.ai.review')" @click="runAi('review')"><CheckBadgeIcon class="h-3.5 w-3.5" /></button>
            <button class="tb-btn" :disabled="aiBusy" :title="t('draft.ai.relate')" @click="runAi('relate')"><LinkIcon class="h-3.5 w-3.5" /></button>
            <button class="tb-btn" :disabled="aiBusy" :title="t('draft.ai.runCmd')" @click="runAi('custom')"><PlayCircleIcon class="h-3.5 w-3.5" /></button>
            <span class="mx-0.5 h-4 w-px bg-ctp-surface1" />
            <button class="tb-btn" :title="t('draft.toolbar.preview')" @click="openPreviewTab"><EyeIcon class="h-3.5 w-3.5" /></button>
            <span class="mx-0.5 h-4 w-px bg-ctp-surface1" />
            <button class="tb-btn" :disabled="!(contentDraft || '').trim()" :title="t('draft.publish.hint')" @click="openPublish"><PaperAirplaneIcon class="h-3.5 w-3.5" /></button>
          </template>
          <button class="tb-btn cursor-grab active:cursor-grabbing" :title="tbCollapsed ? t('draft.toolbar.expand') : t('draft.toolbar.collapse')" @click="onCollapsedClick">
            <WrenchScrewdriverIcon v-if="tbCollapsed" class="h-3.5 w-3.5 text-ctp-mauve" />
            <ChevronRightIcon v-else class="h-3.5 w-3.5 rotate-180" />
          </button>
        </div>

        <!-- 空态 -->
        <div v-if="!tabs.length" class="flex flex-1 flex-col items-center justify-center gap-2 text-ctp-overlay0">
          <DocumentTextIcon class="h-8 w-8" />
          <span class="text-xs">{{ t('draft.emptyTabsBody') }}</span>
          <button class="btn btn-xs btn-blue" @click="createDraft">
            <PlusIcon class="h-3 w-3" />{{ t('draft.newDraft') }}
          </button>
        </div>

        <!-- 编辑 tab -->
        <textarea
          v-else-if="activeTab === 'edit'"
          ref="editTa"
          v-model="contentDraft"
          class="h-full min-w-0 flex-1 resize-none bg-transparent p-3 pt-10 font-mono text-[12px] leading-relaxed text-ctp-text outline-none"
          :disabled="archived"
          :placeholder="t('draft.editorPlaceholder')"
          @input="pending = true"
        />

        <!-- 预览 tab -->
        <div v-else data-draft-preview class="h-full min-w-0 flex-1 overflow-y-auto p-3">
          <template v-for="(b, i) in previewBlocks" :key="i">
            <MarkdownView v-if="b.kind === 'text'" :content="b.text ?? ''" />
            <DiagramCard
              v-else-if="b.kind === 'mermaid'" :title="t('draft.diagram')" headerless
              :diagrams="{ mermaid: b.code ?? '' }" :allowed-langs="['mermaid']"
            />
            <DiagramCard
              v-else-if="b.kind === 'plantuml'" :title="t('draft.diagram')" headerless
              :diagrams="{ plantuml: b.code ?? '' }" :allowed-langs="['plantuml']"
            />
            <div v-else-if="b.kind === 'dot'" class="my-2 overflow-x-auto rounded-md border border-ctp-surface0 bg-ctp-crust/60 p-2">
              <span v-if="dotSvgs[i]" class="block text-center" v-html="dotSvgs[i]" />
              <template v-else>
                <p class="mb-1 text-[9px] text-ctp-overlay0">{{ t('draft.dotUnavailable') }}</p>
                <pre class="overflow-x-auto text-[10px] text-ctp-subtext0">{{ b.code }}</pre>
              </template>
            </div>
          </template>
          <p v-if="!previewBlocks.length" class="py-8 text-center text-[11px] text-ctp-overlay0">{{ t('draft.previewEmpty') }}</p>
        </div>
      </div>

      <!-- 右：草稿列表 -->
      <div class="flex w-44 shrink-0 flex-col border-l border-ctp-surface0">
        <button
          class="m-1.5 flex items-center gap-1 rounded-md border border-dashed border-ctp-surface1 px-2 py-1 text-[11px] text-ctp-overlay1 hover:border-ctp-blue/50 hover:text-ctp-text"
          @click="createDraft"
        ><PlusIcon class="h-3 w-3" />{{ t('draft.newDraft') }}</button>
        <div class="mx-1.5 flex items-center gap-0.5 overflow-hidden rounded-md border border-ctp-surface1 text-[10px]">
          <button
            v-for="f in (['all', 'editing', 'archived'] as const)" :key="f"
            class="flex-1 px-1 py-0.5"
            :class="listFilter === f ? 'bg-ctp-surface0 text-ctp-text' : 'text-ctp-overlay1 hover:text-ctp-subtext1'"
            @click="listFilter = f"
          >{{ t(`draft.filter.${f}`) }}<span class="ml-0.5 font-mono text-ctp-overlay0">{{ filterCounts[f] }}</span></button>
        </div>
        <input
          v-model="listQuery"
          class="input mx-1.5 mt-1 w-auto !px-1.5 !py-0.5 !text-[10px]"
          :placeholder="t('draft.searchPlaceholder')"
        >
        <div class="min-h-0 flex-1 overflow-y-auto px-1.5 py-1 pb-1.5">
          <div
            v-for="d in filteredDrafts" :key="d.id"
            class="group mb-0.5 cursor-pointer rounded px-1.5 py-1"
            :class="current?.id === d.id ? 'bg-ctp-surface0/80' : 'hover:bg-ctp-surface0/40'"
            @click="openDraft(d)"
          >
            <template v-if="renamingId === d.id">
              <input
                v-model="renameDraft" v-focus
                class="input !py-0 !px-1 !text-[11px] w-full"
                @keydown.enter.prevent="commitRename"
                @keydown.esc="cancelRename"
                @blur="commitRename"
              >
            </template>
            <template v-else>
              <div class="flex items-center gap-1">
                <DocumentTextIcon class="h-3 w-3 shrink-0" :class="d.status === 'archived' ? 'text-ctp-overlay0' : 'text-ctp-blue'" />
                <span class="min-w-0 flex-1 truncate text-[11px]" :class="d.status === 'archived' ? 'text-ctp-overlay1' : 'text-ctp-text'">{{ d.title || t('draft.untitled') }}</span>
                <span v-if="pendingOf(d.id)" class="h-1.5 w-1.5 shrink-0 rounded-full bg-ctp-peach" :title="t('draft.pendingBadge')" />
                <button
                  class="hidden shrink-0 text-ctp-overlay0 group-hover:block hover:text-ctp-blue"
                  :title="t('draft.rename')" @click.stop="startRename(d)"
                ><PencilSquareIcon class="h-3 w-3" /></button>
                <button
                  class="hidden shrink-0 text-ctp-overlay0 group-hover:block hover:text-ctp-red"
                  :title="t('common.delete')" @click.stop="current = d; removeDraft()"
                ><TrashIcon class="h-3 w-3" /></button>
              </div>
              <div class="truncate text-[9px] text-ctp-overlay0" :title="d.excerpt">{{ d.excerpt || '—' }}</div>
              <!-- A2 来源标记: 会话回流草稿(回合/规约/执行回执), 悬停见会话 id -->
              <div v-if="d.sourceConvId" class="flex items-center gap-0.5">
                <span
                  class="inline-flex items-center gap-0.5 rounded bg-ctp-mauve/15 px-1 text-[8px] leading-3 text-ctp-mauve"
                  :title="`${t('draft.fromSession')} · ${d.sourceConvId}`"
                >
                  <ChatBubbleLeftRightIcon class="h-2 w-2" />{{ t(`draft.srcKind.${d.sourceKind || 'turn'}`) }}
                </span>
              </div>
              <!-- 标签: 前 3 个直显(超宽 CSS 截断+title 全名), 更多收进 +N 徽标悬停看全部; 点击按 tag 查找 -->
              <div
                v-if="d.tags?.length"
                class="flex items-center gap-0.5 overflow-hidden"
                :title="d.tags.join('、')"
              >
                <span
                  v-for="tg in d.tags.slice(0, 3)" :key="tg"
                  class="max-w-[56px] cursor-pointer truncate rounded bg-ctp-surface0/70 px-1 text-[9px] leading-3.5 text-ctp-overlay1 hover:text-ctp-text"
                  :title="tg" @click.stop="filterByTag(tg)"
                >{{ tg }}</span>
                <span v-if="d.tags.length > 3" class="shrink-0 text-[9px] text-ctp-overlay0">+{{ d.tags.length - 3 }}</span>
              </div>
            </template>
          </div>
          <p v-if="!filteredDrafts.length && !loading" class="py-4 text-center text-[10px] text-ctp-overlay0">
            {{ drafts.length ? t('draft.noMatch') : t('draft.empty') }}
          </p>
        </div>
      </div>
    </div>

    <!-- AI 产物比对（git diff）：采纳覆盖 / 放弃保留参考 -->
    <div v-if="current?.lastProposedMd" class="shrink-0 border-t border-ctp-surface0">
      <button
        class="flex w-full items-center gap-1 px-2 py-1 text-[10px] text-ctp-overlay1 hover:text-ctp-text"
        @click="proposedOpen = !proposedOpen"
      >
        <ChevronRightIcon class="h-3 w-3" :class="proposedOpen ? 'rotate-90' : ''" />
        {{ t('draft.proposed.title') }}
        <span v-if="proposedStat.added || proposedStat.removed" class="font-mono">
          <span class="text-ctp-green">+{{ proposedStat.added }}</span>
          <span class="text-ctp-red">-{{ proposedStat.removed }}</span>
        </span>
        <span class="text-ctp-overlay0">{{ fmtTime(current.lastProposedAt ?? 0) }}</span>
        <span class="flex-1" />
        <span class="text-ctp-overlay0">{{ t('draft.proposed.hint') }}</span>
      </button>
      <div v-if="proposedOpen" class="border-t border-ctp-surface0">
        <div class="flex items-center gap-1.5 px-2 py-1">
          <button class="btn btn-xs btn-blue" :disabled="adopting || archived" @click="adoptProposal">
            <CheckIcon class="h-3 w-3" />{{ t('draft.proposed.adopt') }}
          </button>
          <button class="btn btn-xs btn-ghost" @click="proposedOpen = false">{{ t('draft.proposed.discard') }}</button>
        </div>
        <div class="max-h-64 overflow-auto border-t border-ctp-surface0 bg-ctp-crust/60 font-mono text-[10px] leading-5">
          <div
            v-for="(l, i) in proposedDiff" :key="i"
            class="flex gap-1 whitespace-pre px-1"
            :class="l.type === 'add' ? 'bg-ctp-green/10 text-ctp-green'
              : l.type === 'del' ? 'bg-ctp-red/10 text-ctp-red' : 'text-ctp-subtext0'"
          >
            <span class="w-8 shrink-0 select-none text-right text-ctp-overlay0">{{ l.oldNo ?? '' }}</span>
            <span class="w-8 shrink-0 select-none text-right text-ctp-overlay0">{{ l.newNo ?? '' }}</span>
            <span class="w-3 shrink-0 select-none">{{ l.type === 'add' ? '+' : l.type === 'del' ? '-' : ' ' }}</span>
            <span class="min-w-0 flex-1">{{ l.text }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 底栏：归档草稿续写入口 -->
    <div v-if="archived" class="flex shrink-0 items-center gap-2 border-t border-ctp-surface0 px-2 py-1">
      <span class="min-w-0 flex-1 truncate text-[10px] text-ctp-overlay1" :title="current?.publishedReqId">
        {{ t('draft.publishedInfo', { req: current?.publishedReqId || '—' }) }} · {{ fmtTime(current?.updatedAt ?? 0) }}
      </span>
      <button class="btn btn-xs btn-ghost" @click="copyDraft">
        <ArchiveBoxIcon class="h-3 w-3" />{{ t('draft.continue') }}
      </button>
    </div>

    <!-- 发布弹窗 -->
    <Teleport to="body">
      <div v-if="publishOpen" class="fixed inset-0 z-[240] flex items-center justify-center bg-black/45 p-4" @click.self="publishOpen = false">
        <div class="w-[26rem] max-w-full rounded-xl border border-ctp-surface0 bg-ctp-mantle p-4 shadow-2xl">
          <p class="text-sm font-semibold text-ctp-text">{{ t('draft.publish.title') }}</p>
          <p class="mt-1 text-[11px] leading-relaxed text-ctp-overlay1">{{ t('draft.publish.desc') }}</p>
          <div class="mt-3 space-y-2">
            <label class="flex cursor-pointer items-center gap-2 text-xs text-ctp-text">
              <input v-model="publishTarget" type="radio" value="new" class="accent-ctp-blue">
              {{ t('draft.publish.newConv') }}
            </label>
            <label class="flex items-center gap-2 text-xs text-ctp-text">
              <input v-model="publishTarget" type="radio" :value="convOptions[0]?.id ?? ''" class="accent-ctp-blue" :disabled="!convOptions.length">
              {{ t('draft.publish.existingConv') }}
            </label>
            <div class="flex items-center gap-1">
              <input
                v-model="pickerQuery"
                class="input !py-0.5 !px-1.5 !text-[11px] min-w-0 flex-1"
                :placeholder="t('draft.publish.searchPlaceholder')"
                :disabled="pickerLoading"
                @input="onPickerSearch"
              >
              <span v-if="pickerLoading" class="text-[10px] text-ctp-overlay0">…</span>
            </div>
            <p v-if="pickerOrFallback" class="text-[9px] text-ctp-peach">{{ t('draft.publish.orFallback') }}</p>
            <div class="max-h-44 overflow-y-auto rounded-md border border-ctp-surface0">
              <label
                v-for="c in convOptions" :key="c.id"
                class="flex cursor-pointer items-center gap-2 border-b border-ctp-surface0/60 px-2 py-1 text-[11px] last:border-0 hover:bg-ctp-surface0/40"
                :class="publishTarget === c.id ? 'bg-ctp-surface0/60' : ''"
              >
                <input v-model="publishTarget" type="radio" :value="c.id" class="accent-ctp-blue">
                <span class="min-w-0 flex-1 truncate text-ctp-text" :title="c.title">{{ c.title || c.id }}</span>
                <span v-if="c.reqId" class="chip bg-ctp-yellow/15 text-ctp-yellow !text-[8px] shrink-0" :title="t('draft.publish.boundReq')">{{ t('draft.publish.boundReq') }}</span>
              </label>
              <p v-if="!convOptions.length && !pickerLoading" class="py-3 text-center text-[10px] text-ctp-overlay0">
                {{ pickerQuery ? t('draft.publish.noMatch') : t('draft.publish.noConv') }}
              </p>
            </div>
            <div class="flex items-center gap-2 text-[10px] text-ctp-overlay1">
              <button class="btn btn-xs btn-ghost !px-1.5" :disabled="pickerPage <= 0 || pickerLoading" @click="loadPicker(pickerPage - 1)">‹</button>
              <span class="tabular-nums">{{ pickerPageCount > 1 ? `${pickerPage + 1}/${pickerPageCount}` : `${pickerTotal}` }}</span>
              <button class="btn btn-xs btn-ghost !px-1.5" :disabled="pickerPage >= pickerPageCount - 1 || pickerLoading" @click="loadPicker(pickerPage + 1)">›</button>
              <span class="flex-1" />
              <span>{{ t('draft.publish.activeOnly') }}</span>
            </div>
          </div>
          <p v-if="publishMsg" class="mt-2 text-[11px] text-ctp-red">{{ publishMsg }}</p>
          <div class="mt-3 flex justify-end gap-2">
            <button class="btn btn-ghost text-xs" :disabled="publishBusy" @click="publishOpen = false">{{ t('common.cancel') }}</button>
            <button
              class="btn btn-blue text-xs"
              :disabled="publishBusy || (publishTarget !== 'new' && !convOptions.some((c) => c.id === publishTarget))"
              @click="doPublish(false)"
            >{{ publishBusy ? t('draft.publish.publishing') : t('draft.publish.confirm') }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.tb-btn {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 2px; border-radius: 4px; color: rgb(var(--ctp-subtext1));
  cursor: pointer;
}
.tb-btn:hover:not(:disabled) { background: rgb(var(--ctp-surface0)); color: rgb(var(--ctp-text)); }
.tb-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.tb-handle { touch-action: none; }
</style>
