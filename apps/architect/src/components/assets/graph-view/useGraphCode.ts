/**
 * 语义图谱 · code 域（MS6-W2 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { SemanticGraphResult, SourceSnippet, semanticAssetService } from '@/services/semantic-asset-service'
import { copyText } from '@/utils/clipboard'

import type { WsDeps } from './graphTypes'
import { useI18n } from 'vue-i18n'

interface CodeSegment {
  file: string
  symbol?: string
  startLine: number
  snippet: SourceSnippet | null
  loading: boolean
}


export function useGraphCode(D: WsDeps) {
  const { t } = useI18n()
  const props = D.props

/** 单个代码段：一个锚点对应一个源码窗口(symbol 已知时后端展开整个符号体)。 */
const MAX_SEGMENTS = 4
const segments = ref<CodeSegment[]>([])
const segEls: (HTMLElement | null)[] = []
let segSeq = 0

// ---- B2 多段代码手风琴(>1 段折叠，默认仅首段展开) ----
const collapsedSegs = ref<Set<number>>(new Set())
function toggleSeg(i: number) {
  const s = new Set(collapsedSegs.value)
  if (s.has(i)) s.delete(i); else s.add(i)
  collapsedSegs.value = s
}
// 重置折叠态：除首段外全部折叠(单段不折叠)。
function resetSegCollapse(n: number) {
  collapsedSegs.value = new Set(Array.from({ length: n }, (_, i) => i).filter((i) => i > 0))
}

// ---- 多文件 tab：访问历史(按文件沉淀，点击回跳资产) + 关系资产文件(预览) ----
const activeFileTab = ref('')
/** 当前资产锚点涉及的文件(去重；锚点上限 MAX_SEGMENTS 内)。 */
const anchorFiles = computed<{ file: string; label: string }[]>(() => {
  const files: string[] = []
  for (const a of D.detail.selAnchors.value.slice(0, MAX_SEGMENTS)) {
    if (!files.includes(a.file)) files.push(a.file)
  }
  return files.map((f) => ({ file: f, label: f.split('/').pop() || f }))
})
/** 访问过的文件(LRU 上限 6)：每项记住该文件最近看过的资产，点击回跳(全联动)。 */
const visitedTabs = ref<{ file: string; label: string; assetId: string; assetName: string }[]>([])
/** 当前 tab 文件可见的段(携带原索引：segEls/lineNotesMaps 均按原始 si 寻址)。 */
const activeTabSegs = computed(() =>
  segments.value
    .map((seg, si) => ({ seg, si }))
    .filter(({ seg }) => anchorFiles.value.length <= 1 || seg.file === activeFileTab.value))
/** 切换文件 tab：关系 tab 预览相关资产代码(全文模式下先退出全文)；自身文件 tab 聚焦首个代码段；
 *  全文模式切自身文件 tab → 连带切换全文文件。 */
function switchFileTab(file: string) {
  if (activeFileTab.value === file) return
  activeFileTab.value = file
  const rel = relTabs.value.find((t) => t.file === file)
    ?? expandedTabs.value.find((t) => t.file === file)
  if (rel) {
    if (fullCode.value) { fullCode.value = null; fullCodeNotes.value = {} }
    void ensureRelTab(rel).then(() => focusRelTab(rel.file))
    return
  }
  if (fullCode.value && fullCode.value.file !== file) {
    void loadFullCodeFor(file)
    return
  }
  const i = segments.value.findIndex((s) => s.file === file)
  if (i >= 0) jumpToSegment(i)
}

// ---- 关系延伸 tab：直接关系资产所在的其它文件也纳入 tab(预览相关代码，可跳转选中) ----
interface RelTab { file: string; label: string; line: number; symbol: string; targetId: string; targetName: string; relText: string }
/** tab 列表 = 自身锚点文件(self) + 关系资产文件(rel，去重、上限 3)。 */
const relTabs = computed<RelTab[]>(() => {
  const seenFile = new Set<string>(anchorFiles.value.map((f) => f.file))
  const out: RelTab[] = []
  for (const r of D.detail.selRelations.value) {
    const a = (D.data.graph.value?.anchors ?? []).find((x) => x.assetId === r.targetId)
    if (!a || seenFile.has(a.file)) continue
    seenFile.add(a.file)
    out.push({
      file: a.file, label: a.file.split('/').pop() || a.file,
      line: a.line, symbol: a.symbol ?? '',
      targetId: r.targetId, targetName: r.targetName, relText: r.desc || r.type,
    })
    if (out.length >= 3) break
  }
  return out
})
/** 拓展关联沉淀 tab(基于选中节点扩展出的关联节点所在文件；点击仅预览，不切换选中)。 */
const expandedTabs = ref<RelTab[]>([])
const fileTabs = computed(() => [
  ...visitedTabs.value.map((v) => ({ file: v.file, label: v.label, kind: 'visit' as const, assetId: v.assetId, assetName: v.assetName, rel: null as RelTab | null })),
  ...expandedTabs.value
    .filter((t) => !visitedTabs.value.some((v) => v.file === t.file))
    .map((t) => ({ file: t.file, label: t.label, kind: 'expand' as const, assetId: '', assetName: '', rel: t as RelTab | null })),
  ...relTabs.value
    .filter((t) => !visitedTabs.value.some((v) => v.file === t.file) && !expandedTabs.value.some((x) => x.file === t.file))
    .map((t) => ({ file: t.file, label: t.label, kind: 'rel' as const, assetId: '', assetName: '', rel: t as RelTab | null })),
])
/** tab 点击：访问历史 → 选中对应资产(图谱/卡/焦点全联动)；关系/拓展 tab → 仅预览相关代码。 */
function tabClick(t: { kind: 'visit' | 'rel' | 'expand'; file: string; assetId: string }) {
  if (t.kind === 'visit' && t.assetId && t.assetId !== D.detail.selId.value) {
    D.detail.selId.value = t.assetId
    return
  }
  switchFileTab(t.file)
}
const activeRelTab = computed(() =>
  relTabs.value.find((x) => x.file === activeFileTab.value)
  ?? expandedTabs.value.find((x) => x.file === activeFileTab.value)
  ?? null)
/** 关系 tab 代码窗口(按文件懒拉取)。 */
const relTabSegs = ref<Record<string, SourceSnippet | null>>({})
const relTabLoading = ref('')
const relTabEl = ref<HTMLElement | null>(null)
async function ensureRelTab(t: RelTab) {
  if (relTabSegs.value[t.file] || relTabLoading.value === t.file) return
  relTabLoading.value = t.file
  try {
    const sn = (await semanticAssetService.sourceSnippet(t.file, t.line, t.symbol || undefined, 10, 10, SEG_SNIPPET_LIMIT)) ?? null
    relTabSegs.value = { ...relTabSegs.value, [t.file]: sn }
  } catch {
    relTabSegs.value = { ...relTabSegs.value, [t.file]: null }
  } finally {
    relTabLoading.value = ''
  }
}
/** 关系 tab 聚焦：滚动到其锚点行并闪烁。 */
function focusRelTab(file: string) {
  void nextTick(() => {
    if (activeFileTab.value !== file) return
    const first = relTabEl.value?.querySelector('[data-anchor-line]')
    if (first) first.scrollIntoView({ block: 'center' })
    D.render.triggerFlash()
  })
}

// ---- 拓展关联：基于选中节点扩展 1 跳关联节点(增量合并，可累积)；相关文件沉淀为源码 tab ----
const expanding = ref(false)
const expandFeedback = ref('')
let expandFeedbackTimer: ReturnType<typeof setTimeout> | null = null

/** 拓展预判断：预取选中节点 1 跳子图(与拓展同源，含派生边)，以「不在图内的节点数」精确判定。
 *  预取失败视为未知 → 仍可点击(由点击后的「无新增」反馈兜底)，避免误置灰。 */
const pendingExpand = ref<{ selId: string; sub: SemanticGraphResult; added: number } | null>(null)
const expandUnknown = ref(false)
const expandable = computed(() =>
  expandUnknown.value || (!!pendingExpand.value
    && pendingExpand.value.selId === D.detail.selId.value
    && pendingExpand.value.added > 0))

async function prefetchExpand() {
  const id = D.detail.selId.value
  if (!id || D.data.loading.value) { pendingExpand.value = null; return }
  expandUnknown.value = false
  try {
    const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
    const sub = await semanticAssetService.graph(
      D.data.kindFilter.value || undefined, scope, D.data.effectiveLevel.value || undefined,
      { focus: id, hops: 1 })
    if (D.detail.selId.value !== id) return   // 选中已切换 → 丢弃过期结果
    const ids = new Set((D.data.graph.value?.nodes ?? []).map((n) => n.id))
    pendingExpand.value = { selId: id, sub, added: sub.nodes.filter((n) => !ids.has(n.id)).length }
  } catch {
    if (D.detail.selId.value === id) {
      pendingExpand.value = null
      expandUnknown.value = true   // 预取失败不误伤：允许点击，点击后再按实际结果反馈
    }
  }
}
watch(D.detail.selId, () => { pendingExpand.value = null; void prefetchExpand() })
watch(D.data.graph, () => { if (D.detail.selId.value) void prefetchExpand() })   // 拓展合并/重查后重算(无新增 → 置灰)

async function expandSelected() {
  if (!D.detail.selId.value || D.data.loading.value || expanding.value) return
  expanding.value = true
  try {
    let sub = pendingExpand.value?.selId === D.detail.selId.value ? pendingExpand.value.sub : null
    if (!sub) {
      const scope = props.tab.kind === 'comp' ? [props.tab.compId!] : undefined
      sub = await semanticAssetService.graph(
        D.data.kindFilter.value || undefined, scope, D.data.effectiveLevel.value || undefined,
        { focus: D.detail.selId.value, hops: 1 })
    }
    const g = D.data.graph.value
    if (!g) return
    // 增量合并：节点按 id、边按 from|to|type、锚点按 assetId|file|line 去重
    const nodeIds = new Set(g.nodes.map((n) => n.id))
    const added = sub.nodes.filter((n) => !nodeIds.has(n.id))
    const edgeKey = (e: { from: string; to: string; type?: string }) => `${e.from}|${e.to}|${e.type ?? ''}`
    const edgeKeys = new Set(g.edges.map(edgeKey))
    const newEdges = sub.edges.filter((e) => !edgeKeys.has(edgeKey(e)))
    const anchorKey = (a: { assetId: string; file: string; line: number }) => `${a.assetId}|${a.file}|${a.line}`
    const anchorKeys = new Set((g.anchors ?? []).map(anchorKey))
    const newAnchors = (sub.anchors ?? []).filter((a) => !anchorKeys.has(anchorKey(a)))
    if (added.length) {
      D.data.graph.value = {
        ...g,
        nodes: [...g.nodes, ...added],
        edges: [...g.edges, ...newEdges],
        anchors: [...(g.anchors ?? []), ...newAnchors],
        count: g.nodes.length + added.length,
      }
      // 卡片联动：新增节点的主锚点文件沉淀为拓展源码 tab(点击仅预览，不切换选中)
      const seen = new Set<string>([
        ...expandedTabs.value.map((x) => x.file),
        ...visitedTabs.value.map((v) => v.file),
        ...anchorFiles.value.map((f) => f.file),
      ])
      for (const n of added) {
        const a = newAnchors.find((x) => x.assetId === n.id)
        if (!a || seen.has(a.file)) continue
        seen.add(a.file)
        expandedTabs.value = [...expandedTabs.value, {
          file: a.file, label: a.file.split('/').pop() || a.file,
          line: a.line, symbol: a.symbol ?? '',
          targetId: n.id, targetName: n.name, relText: t('assetMgmt.graph.expandLabel'),
        }]
      }
    }
    expandFeedback.value = added.length
      ? t('assetMgmt.graph.expandAdded', { n: added.length })
      : t('assetMgmt.graph.expandNone')
    if (expandFeedbackTimer) clearTimeout(expandFeedbackTimer)
    expandFeedbackTimer = setTimeout(() => { expandFeedback.value = '' }, 2200)
  } finally {
    expanding.value = false
  }
}

// ---- C2 复制代码位置(file:Lx-Ly symbol) ----
const copiedSeg = ref(-1)
async function copySegLoc(seg: CodeSegment, si: number) {
  const s = seg.snippet
  if (!s?.lines?.length) return
  const start = s.lines[0].line
  const end = s.lines[s.lines.length - 1].line
  const loc = `${seg.file}:L${start}${end !== start ? `-L${end}` : ''}${seg.symbol ? ' ' + seg.symbol : ''}`
  if (await copyText(loc)) {
    copiedSeg.value = si
    setTimeout(() => { if (copiedSeg.value === si) copiedSeg.value = -1 }, 1500)
  }
}

// ---- C1 按类别结构化 detail(有数据时)：entity/contract→字段 · process/decision→步骤 · state→状态 ----
const detailBlock = computed<{ title: string; rows: { text: string; title: string }[] } | null>(() => {
  const d = D.detail.selDetail.value?.detail
  if (!d) return null
  const kind = D.detail.sel.value?.kind
  if ((kind === 'entity' || kind === 'contract') && d.fields?.length) {
    return {
      title: t('assetMgmt.graph.fields'),
      rows: d.fields.map((f) => {
        const text = `${f.name}${f.type ? `: ${f.type}` : ''}`
        return { text, title: f.semantic ? `${f.name}: ${f.type ?? ''} — ${f.semantic}` : text }
      }),
    }
  }
  if ((kind === 'process' || kind === 'decision') && d.steps?.length) {
    return {
      title: t('assetMgmt.graph.steps'),
      rows: d.steps.map((s, i) => {
        const n = s.order ?? i + 1
        const syms = s.symbols?.length ? ` · ${s.symbols.join(', ')}` : ''
        return { text: `${n}. ${s.semantic}`, title: `${s.semantic}${syms}` }
      }),
    }
  }
  if (kind === 'state' && d.states?.length) {
    return {
      title: t('assetMgmt.graph.states'),
      rows: d.states.map((s) => {
        const marks = [s.initial ? '●' : '', s.final ? '◉' : ''].filter(Boolean).join('')
        const text = `${s.name}${s.desc ? ` — ${s.desc}` : ''}${marks ? `  ${marks}` : ''}`
        return { text, title: text }
      }),
    }
  }
  return null
})

// 选中资产 → 拉取完整详情（astRefs 唯一来源）。
// 完整代码视图打开时：同文件资产切换保持视图(互斥：不重建资产卡)；跨文件 → 关闭全文并正常重建。
let flashSeg = 0
/** 段内高亮行判定：highlight 非空用之，否则退回锚点行，保证至少一行高亮。 */
function segHighlighted(seg: CodeSegment, line: number): boolean {
  const s = seg.snippet
  if (!s) return false
  const hl = (s.highlight ?? []).map(Number).filter((n) => n > 0)
  if (hl.length) return hl.includes(line)
  return Number(s.anchorLine || 0) === line
}

/** 滚动到某段首个锚点行并闪烁强调(最小化时不做，脉冲提示覆盖)。 */
function flashAnchor(segIdx = flashSeg) {
  if (D.render.cardMin.value) return
  const el = segEls[segIdx]
  if (!el || !segments.value[segIdx]?.snippet) return
  const first = el.querySelector('[data-anchor-line]')
  if (first) first.scrollIntoView({ block: 'center' })
  D.render.triggerFlash()
}

const lineNotesMaps = ref<Record<number, Record<number, string>>>({})
const lineNotesLoading = ref(false)
const lineNotesDegraded = ref(false)
const lineNotesError = ref('')
/** 最近一次结果是否全部来自缓存(失效缓存后端等同无缓存，不会误标)。 */
const lineNotesFromCache = ref(false)

/** 已解读行数(按钮上展示，让激活状态可见)。 */
const lineNotesCount = computed(() =>
  Object.values(lineNotesMaps.value).reduce((n, m) => n + Object.keys(m).length, 0)
  + Object.keys(fullCodeNotes.value).length)

async function loadLineNotes(force = false) {
  if (!D.detail.sel.value || lineNotesLoading.value) return
  // 完整代码模式 → 解读全文窗口
  if (fullCode.value) {
    await loadFullCodeNotes(force)
    return
  }
  const targets = segments.value
    .map((seg, i) => ({ seg, i }))
    .filter(({ seg }) => seg.snippet?.lines?.length)
  if (!targets.length) return
  lineNotesLoading.value = true
  lineNotesError.value = ''
  let degraded = false
  let anyCached = false
  let allCached = true
  for (const { seg, i } of targets) {
    const s = seg.snippet!
    try {
      const r = await semanticAssetService.lineNotes(
        D.detail.sel.value.id, s.file, s.lines[0].line, s.lines[s.lines.length - 1].line, { force })
      // 键归一为数字(JSON 反序列化后为字符串键)，避免任何运行时键型差异
      const norm: Record<number, string> = {}
      for (const [k, v] of Object.entries(r.notes || {})) norm[Number(k)] = String(v)
      lineNotesMaps.value = { ...lineNotesMaps.value, [i]: norm }
      if (r.error) { lineNotesError.value = r.error; break }
      if (r.degraded) degraded = true
      if (r.cached) anyCached = true; else allCached = false
    } catch (err: any) {
      lineNotesError.value = err?.message || 'failed'
      break
    }
  }
  // 有明确 error 时只显示失败提示(可重试)，不再叠加「降级」横幅
  lineNotesDegraded.value = degraded && !lineNotesError.value
  lineNotesFromCache.value = anyCached && allCached
  lineNotesLoading.value = false
}

/** 清除缓存重新生成(后端 force=true：视同无缓存，重新生成并覆盖)。 */
function regenerateLineNotes() {
  void loadLineNotes(true)
}

/** 锚点导航：点击锚点 → (跨文件时切到对应 tab)展开对应代码段并滚动、闪烁锚点行。 */
function jumpToSegment(i: number) {
  const seg = segments.value[i]
  if (seg && activeFileTab.value !== seg.file) activeFileTab.value = seg.file
  if (collapsedSegs.value.has(i)) toggleSeg(i)   // 先展开目标段(折叠时锚点行未渲染)
  void nextTick(() => {
    const el = segEls[i]
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    flashSeg = i
    flashAnchor(i)
  })
}

// 最小化时信息刷新(选中资产变化) → 不自动展开浮窗；停靠图标闪动缩放 ~3s 提示。
// 同时：未手动选图类型时，点击节点切换选中 → 钉住「用户正在看的视图」，
// 防止推荐随新资产类别/粒度变化而偶发跳图(如 关系图→ER)。首次点击(D.detail.sel null→资产)同样覆盖。
const iconPulse = ref(false)
/** 对比口径下资产卡代码的取数参数：
 *  - 资产参与本次对比(changed/new/removed) → 显示目标侧内容(worktree/目标 head)，
 *    并与基准 commit 做 git diff 逐行注解：基准侧资产的原代码以 -行呈现，
 *    目标侧新代码以 +行呈现(统一 diff 视图，增/删/改精确显示)；
 *  - 稳定资产(两侧内容一致) → 维持现状(工作区内容 + 符号体展开)，无 diff 开销。 */
function snippetOptsFor(assetId: string): { ref?: string; diffBase?: string } {
  const c = props.compareData
  if (!c || c.noChanges) return {}
  let side = ''
  for (const a of c.assets.changed) if (a.id === assetId) side = a.side || 'stale'
  for (const a of c.assets.new) if (a.id === assetId) side = 'target'
  for (const a of c.assets.removed) if (a.id === assetId) side = 'base'
  if (!side) return {}
  // diff 比较对象恒为 基准 vs 目标侧；ref 仅决定显示内容取哪个 head(目标侧)
  const ref = c.targetIsWorktree ? '' : c.target
  return { ref: ref || undefined, diffBase: c.base || undefined }
}

async function rebuildSegments(anchors: { file: string; startLine: number; symbol: string }[]) {
  const cap = anchors.slice(0, MAX_SEGMENTS)
  activeFileTab.value = cap[0]?.file ?? ''   // 跟随图节点切换 → 文件 tab 焦点落在主锚点文件
  const seq = ++segSeq
  segments.value = cap.map((a) => ({ file: a.file, symbol: a.symbol, startLine: a.startLine, snippet: null, loading: true }))
  resetSegCollapse(cap.length)   // B2: 除首段外全部折叠
  lineNotesMaps.value = {}
  lineNotesDegraded.value = false
  lineNotesError.value = ''
  const opts = snippetOptsFor(D.detail.selId.value)
  await Promise.all(cap.map(async (a, i) => {
    let sn: SourceSnippet | null = null
    try {
      sn = (await semanticAssetService.sourceSnippet(a.file, a.startLine, a.symbol, 10, 10, SEG_SNIPPET_LIMIT, opts)) ?? null
    } catch {
      sn = null
    }
    if (seq !== segSeq) return
    const seg = segments.value[i]
    if (seg) { seg.snippet = sn; seg.loading = false }
  }))
}
watch(D.detail.selAnchors, (anchors) => {
  if (fullCode.value) return
  void rebuildSegments(anchors)
})
// 对比数据晚到(工具栏发起对比/切 head) → 已打开的资产卡带 diff 参数重建，
// 保证 +/- 行视图与所选对比对一致(全文视图打开时同 rebuildSegments 策略跳过)。
watch(segments, (segs) => {
  if (D.render.flashOnNext && segs.some((s) => s.snippet)) {
    D.render.flashOnNext = false
    void nextTick(() => flashAnchor(flashSeg))
  }
}, { deep: true })

// ---- 完整代码视图(单文件全文；文件内多资产锚点全部高亮，点击锚点切资产) ----
// 互斥约定：全文视图内点击同文件资产锚点 → 仅切换图谱选中，不重建资产卡；
// 跨文件(新资产锚点不在当前全文文件) → 关闭全文并按常规刷新图谱+资产卡。
/** 分段源码窗口上限(行)：整符号体优先全量展示/解读(旧默认 60 行截断是「长函数只解读头部」的成因)。 */
const SEG_SNIPPET_LIMIT = 2000
/** 完整代码窗口上限(行)：优先全量提供；逐行解读超限由后端 1/2→1/4→1/8 分批降级兜住。 */
const FULL_FILE_LIMIT = 8000
const fullCode = ref<SourceSnippet | null>(null)
const fullCodeLoading = ref(false)
const fullCodeNotes = ref<Record<number, string>>({})
const fullCodeNotesLoading = ref(false)
const fullCodeError = ref('')

async function toggleFullCode() {
  fullCodeError.value = ''
  if (fullCode.value) {
    fullCode.value = null
    fullCodeNotes.value = {}
    return
  }
  const file = activeFileTab.value || D.detail.selAnchors.value[0]?.file
  if (!file || !D.detail.sel.value) return
  await loadFullCodeFor(file)
}

/** 拉取指定文件全文(窗口上限 FULL_FILE_LIMIT)；返回是否成功，供调用方兜底回退。 */
async function loadFullCodeFor(file: string): Promise<boolean> {
  fullCodeLoading.value = true
  try {
    fullCode.value = (await semanticAssetService.sourceSnippet(file, 1, undefined, FULL_FILE_LIMIT, FULL_FILE_LIMIT, FULL_FILE_LIMIT, snippetOptsFor(D.detail.selId.value))) ?? null
    fullCodeNotes.value = {}
    return !!fullCode.value
  } catch {
    fullCode.value = null
    return false
  } finally {
    fullCodeLoading.value = false
  }
}

/** 全文内 行号 → 所属资产 id(仅图谱范围内已知锚点；严谨起见只标注确知行，不猜测区间)。 */
const fullCodeOwners = computed<Map<number, string>>(() => {
  const m = new Map<number, string>()
  if (!fullCode.value) return m
  for (const a of D.data.graph.value?.anchors ?? []) {
    if (a.file !== fullCode.value!.file || !a.assetId) continue
    if (!m.has(a.line)) m.set(a.line, a.assetId)
  }
  return m
})

/** 当前资产在全文文件内的锚点行集合(精确 astRefs 区间)。 */
const fullCodeSelfLines = computed<Set<number>>(() => {
  const s = new Set<number>()
  if (!fullCode.value) return s
  const file = fullCode.value.file
  for (const r of D.detail.selDetail.value?.astRefs ?? []) {
    if ((r.file || '') !== file) continue
    const a = Number(r.startLine || 0)
    const b = Number(r.endLine || 0) || a
    for (let ln = a; ln <= b; ln++) s.add(ln)
  }
  return s
})

// 全文视图可视焦点跟随：图节点点击/行点击切换资产(同文件不重建卡) → 滚动到
// 当前资产首个锚点行并闪烁；打开全文时同样定位到首锚点行。
const fullCodePreRef = ref<HTMLPreElement | null>(null)
watch(fullCodeSelfLines, (lines) => {
  if (!fullCode.value || D.render.cardMin.value || !lines.size) return
  void nextTick(() => {
    if (!fullCode.value) return
    const first = Math.min(...lines)
    const el = fullCodePreRef.value?.querySelector(`[data-full-line="${first}"]`)
    if (el) el.scrollIntoView({ block: 'center' })
    D.render.triggerFlash()
  })
})

/** 全文行点击：命中其它资产锚点 → 切换选中(同文件 → 资产卡保持全文视图)。 */
function onFullCodeLineClick(line: number) {
  const ownerId = fullCodeOwners.value.get(line)
  if (!ownerId || ownerId === D.detail.selId.value) return
  D.detail.selId.value = ownerId
}

/** 锚点所属资产显示名(全文 tooltip 用)。 */
function ownerName(assetId: string): string {
  return D.data.graph.value?.nodes.find((n) => n.id === assetId)?.name ?? assetId
}

/** 源码路径展示：项目相对路径(去开头 ./ /)；过长时从头省略目录段(保尾部)，完整路径用 title 悬停展示。 */
function shortPath(p: string, max = 42): string {
  const norm = (p || '').replace(/\\/g, '/').replace(/^\.\//, '').replace(/^\/+/, '')
  if (norm.length <= max) return norm
  const parts = norm.split('/')
  while (parts.length > 1 && parts.join('/').length > max) parts.shift()
  const out = parts.join('/')
  return (out.length < norm.length ? '…/' : '') + out
}

// ---- 完整代码 AI 逐行解读 ----
async function loadFullCodeNotes(force = false) {
  const fc = fullCode.value
  if (!fc?.lines?.length || !D.detail.sel.value || fullCodeNotesLoading.value) return
  fullCodeNotesLoading.value = true
  fullCodeError.value = ''
  try {
    const r = await semanticAssetService.lineNotes(
      D.detail.sel.value.id, fc.file, fc.lines[0].line, fc.lines[fc.lines.length - 1].line, { force })
    const norm: Record<number, string> = {}
    for (const [k, v] of Object.entries(r.notes || {})) norm[Number(k)] = String(v)
    fullCodeNotes.value = norm
    lineNotesFromCache.value = !!r.cached && !r.error
    if (r.error) fullCodeError.value = r.error
  } catch (err: any) {
    fullCodeError.value = err?.message || 'failed'
    lineNotesFromCache.value = false
  } finally {
    fullCodeNotesLoading.value = false
  }
}

  return {
    FULL_FILE_LIMIT,
    MAX_SEGMENTS,
    SEG_SNIPPET_LIMIT,
    activeFileTab,
    activeRelTab,
    activeTabSegs,
    anchorFiles,
    collapsedSegs,
    copiedSeg,
    copySegLoc,
    detailBlock,
    ensureRelTab,
    expandFeedback,
    expandFeedbackTimer,
    expandSelected,
    expandUnknown,
    expandable,
    expandedTabs,
    expanding,
    fileTabs,
    flashAnchor,
    flashSeg,
    focusRelTab,
    fullCode,
    fullCodeError,
    fullCodeLoading,
    fullCodeNotes,
    fullCodeNotesLoading,
    fullCodeOwners,
    fullCodePreRef,
    fullCodeSelfLines,
    iconPulse,
    jumpToSegment,
    lineNotesCount,
    lineNotesDegraded,
    lineNotesError,
    lineNotesFromCache,
    lineNotesLoading,
    lineNotesMaps,
    loadFullCodeFor,
    loadFullCodeNotes,
    loadLineNotes,
    onFullCodeLineClick,
    ownerName,
    pendingExpand,
    prefetchExpand,
    rebuildSegments,
    regenerateLineNotes,
    relTabEl,
    relTabLoading,
    relTabSegs,
    relTabs,
    resetSegCollapse,
    segEls,
    segHighlighted,
    segSeq,
    segments,
    shortPath,
    snippetOptsFor,
    switchFileTab,
    tabClick,
    toggleFullCode,
    toggleSeg,
    visitedTabs,
  }
}
