import type { AssetDiagramResult, SemanticAsset, SemanticAssetDetail, SemanticAssetKind, SemanticAssetLevel } from '@/types'
import { apiDelete, apiGet, apiPost, apiPut } from './api-client'
import { currentProjectParams } from './project-service'

/**
 * 语义数据资产适配接口 —— architect 自持(结合最新代码结构 + codegraph)。
 *
 * 类别: structure / behavior / rule / contract；粒度: high / medium / low，均锚定 AST 节点。
 * 后端失败直接抛出——不复用本地 mock。
 */

function ctx(): string {
  const { root, project } = currentProjectParams()
  const qs = new URLSearchParams()
  if (root) qs.set('root', root)
  if (project) qs.set('project', project)
  return qs.toString()
}

function qsWith(extra: string, rootCtx = true): string {
  const parts = [extra, rootCtx ? ctx() : ''].filter(Boolean)
  return parts.length ? `?${parts.join('&')}` : ''
}

export interface SemanticExtractScope {
  type: 'files' | 'symbols' | 'comm' | 'project'
  key?: string
  files?: string[]
  symbols?: string[]
}

export interface SemanticExtractResult {
  assets: SemanticAsset[]
  source?: 'codegraph' | 'native' | 'live' | 'kb'
  degraded?: boolean
  /** 符号源后端：codegraph(外部) | native(自身 project.db AST，质量持平)。 */
  symbolSource?: 'codegraph' | 'native'
  /** 降级归因(index_missing/codegraph_missing=CLI 缺失/heuristic_fallback=旧启发式兜底)。 */
  reason?: string
  count: number
  error?: string
  /** 符号索引相对 HEAD 的对齐诊断(产出 0 时定位: 索引重建中/落后即候选可能为空)。 */
  indexStale?: boolean
  staleCount?: number
  lastHead?: string
  head?: string
  /** 零产出逐文件诊断: 无符号(no_symbols) / 无可提取类别符号(no_extractable_kind)。
   *  纯常量表/re-export 桶/启动脚本属正确语义——文件本就无可提取资产。 */
  emptyFiles?: Array<{ file: string; why: 'no_symbols' | 'no_extractable_kind' }>
  /** 业务级(high)聚合产出数；highReason 为聚合失败原因(ok/llm/parse/empty)。 */
  high?: number
  highReason?: string
}

export interface SemanticReconcileResult {
  stale: number
  active: number
  invalidated: string[]
  changed: string[]
  newFiles: string[]
  affectedFiles: string[]
}

export interface SemanticStatusResult {
  counts: Record<string, number>
  total: number
  changed: { added: string[]; modified: string[]; deleted: string[] }
}

/** A6 影响分析：跨组件变更扩散链 + 契约↔实现全局漂移。 */
export interface ImpactAnalysisResult {
  direct: { id: string; name: string; kind: string }[]
  propagated: { id: string; name: string; kind: string; via: string; viaName: string }[]
  drift: { itemId: string; kind: string; reason: 'missing' | 'stale' | 'intent'; assetId?: string; assetName?: string; quote?: string }[]
  coverage: { verifiable: number; covered: number; pct: number }
  patterns: { kind: string; count: number }[]
}

/** 资产概览统计。 */
export interface SemanticStatsResult {
  total: number
  byKind: Record<string, number>
  byLevel: Record<string, number>
  status: Record<string, number>
}

/** 清理影响项(需求/任务引用被清除资产)。 */
export interface SemanticPurgeImpactItem {
  id: string
  title: string
  location?: string
  status?: string
  assets?: string[]
}

/** 清理结果(先 dryRun 提示影响，确认后删除并标记)。 */
export interface SemanticPurgeResult {
  purged: number
  dryRun: boolean
  confirmRequired: boolean
  candidates: number
  byStatus: Record<string, number>
  impact: {
    reqCount: number
    taskCount: number
    requirements: SemanticPurgeImpactItem[]
    tasks: SemanticPurgeImpactItem[]
    assetCount: number
  }
  marked?: { req: number; task: number }
}

export interface AssetUpdateResult {
  status: 'refreshed' | 'regenerated' | 'deleted' | 'missing'
  refreshed?: boolean
  regenerated?: boolean
  degraded?: boolean
  asset?: SemanticAsset
}

export interface SemanticBatchResult {
  action: 'clear'
  count: number
  components?: number | null
  cleared?: string[]
  updated?: string[]
  dryRun?: boolean
  /** clear 的影响范围(需求池/未完成任务)，dryRun 时返回供确认。 */
  impact?: {
    reqCount: number
    taskCount: number
    requirements: SemanticPurgeImpactItem[]
    tasks: SemanticPurgeImpactItem[]
    assetCount: number
  }
}

/** 语义层图谱(方向4：语义资产图形化 + 稳定逻辑映射)。 */
export interface SemanticGraphNode {
  id: string
  kind: SemanticAssetKind
  level?: SemanticAssetLevel
  name: string
  desc: string
  change?: string
  status?: string
  scopeType?: string
  scopeKey?: string
  needsUpdate?: number
  canonicalKey?: string
  /** 节点简介(代码级、grounded；提取时/懒生成)。 */
  nodeBrief?: string
  /** 精简 detail(供类图/ER/序列/状态/聚合图生成)。 */
  detail?: SemanticAssetDetail
}

export interface SemanticGraphEdge {
  from: string
  to: string
  resolved?: boolean
  type?: string
  semantic?: string
  /** 证据式关系描述(edge_notes 生成；优先于 type/semantic 作边标签)。 */
  desc?: string
  /** 派生边证据：发生处(文件:行) 与解析置信度。 */
  line?: number | null
  file?: string
  confidence?: string
  resolvedBy?: string
  /** 间接边(1 跳中转)：via 为中转符号名。 */
  indirect?: boolean
  via?: string
}

export interface SemanticGraphAnchor {
  assetId: string
  file: string
  line: number
  symbol: string
  kind?: string
}

export interface SemanticSymbolMeta {
  id: string
  kind: string
  name: string
  qualifiedName: string
  file: string
  startLine: number
  endLine: number
}

export interface SemanticSymbolDetail {
  symbol: string
  meta: SemanticSymbolMeta
  snippet: string
  note: string
  error?: string
}

export interface SemanticTraceNode {
  id: string
  symbol: string
  name: string
  file: string
  nodeKind: string
  depth: number
  edgeKind?: string
  line?: number | null
  confidence?: number
  assetId?: string
  assetName?: string
  cycle?: boolean
  seenElsewhere?: boolean
  truncated?: number
  branchTotal?: number
  children?: SemanticTraceNode[]
}

export interface SemanticTraceResult {
  trace: {
    root: SemanticTraceNode
    paths: SemanticTraceNode[][]
    extraRoots: SemanticTraceNode[]
    stats: { nodes: number; depthCut?: boolean; nodeCut?: boolean; degraded: boolean; error?: string }
    error?: string
  }
  assetId?: string
  symbol?: string
  direction: 'down' | 'up'
  generatedAt: number
  error?: string
}

export interface SemanticGraphResult {
  nodes: SemanticGraphNode[]
  edges: SemanticGraphEdge[]
  anchors: SemanticGraphAnchor[]
  count: number
}

/** 锚点前后源码窗口（SourceSnippet：行号+代码+命中高亮行段）。 */
export interface SourceSnippetLine {
  line: number
  code: string
  /** diff 模式(git diff 口径)：ctx=上下文 / add=目标侧新增 / del=基准侧删除 */
  kind?: 'ctx' | 'add' | 'del'
  /** diff 模式双行号：del 行=基准侧行号；ctx 行两侧都有 */
  baseLine?: number | null
  targetLine?: number | null
}

export interface SourceSnippet {
  file: string
  symbol?: string
  anchorLine: number
  highlight: number[]
  lines: SourceSnippetLine[]
  /** diff 模式：基准 commit(对比起点的代码)；无则为普通窗口 */
  diffBase?: string
  /** 内容来源 commit(工作区时为空) */
  ref?: string
}

/** AI 逐行解读结果(关键行行号 → 用途说明)。 */
export interface LineNotesResult {
  notes: Record<number, string>
  cached: boolean
  degraded: boolean
  error?: string
}

export interface CodegraphStatus {
  mode: 'on' | 'off' | 'auto'
  env: string
  cli: boolean
  cliPath: string
  kv?: string | null
  source: 'env' | 'kv' | 'default'
  corePid?: string
  /** codegraph CLI 索引统计(.codegraph/codegraph.db) —— 与自管基线图谱正交。 */
  native?: { nodes?: number; edges?: number }
  /** auto 合并语义: native∪codegraph 合并统计(仅 auto+codegraph 可用时返回)。 */
  mergeStats?: { nativeNodes?: number; cgNodes?: number; cgMapped?: number; lineDrift?: number }
  state?: {
    head: string
    lastHead: string
    dirty: number
    stale: boolean
    staleCount: number
  }
}

/** 分区提案行(D3, GET plan/POST confirm)。 */
/** 自管基线状态(GET /kb/semantic/collect-graph/status)。 */
export interface CollectGraphStatus {
  jobs?: Array<Record<string, unknown>>
  latest?: Record<string, unknown> | null
  /** 基线锚 {head, at}(collect_graph 完成自记)。 */
  anchor?: { head?: string; at?: number } | null
  rev?: string
  counts?: { nodes?: number; edges?: number }
}

/** 组件快速命名状态(analysis_tasks.result_data.naming)。 */
/** 基线刷新作业行(批E)。 */
export interface BaselineRefreshJob {
  id: string
  kind: string
  state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'lost' | string
  progress?: { total?: number; done?: number; current?: string }
  result?: { rev?: string; head?: string; steps?: Record<string, { nodes?: number; edges?: number; components?: number; named?: number; error?: string; group?: { components?: number; hierarchy?: number; levels?: number } }> }
}

/** 自管组件命名状态(批C): arch_component_naming 覆盖口径。 */
export interface ComponentNamingStatus {
  rev: string
  total: number
  named: number
  coverage: number
  jobs?: { id: string; state: string; progress?: { named?: number } }[]
  naming: Record<string, { componentId: string; name: string; summary: string; status: string }>
}

/** 工作区符号快照节点(稳定 ID 契约, 可与基线图谱对齐)。 */
export interface WorkspaceSymbolNode {
  id: string
  kind: string
  name: string
  qualifiedName: string
  file: string
  language: string
  startLine: number
  endLine: number
  isExported: boolean
}

export interface WorkspaceSnapshot {
  projectId: string
  base: string
  explicitFiles: boolean
  filesRequested: number
  truncated: boolean
  nodeCount: number
  nodes: WorkspaceSymbolNode[]
}

/** 符号源选择器状态(与 codegraph on/off/auto 正交)。 */
export interface SymbolSourceStatus {
  pref: 'auto' | 'codegraph' | 'native'
  effective: { mode?: string; source?: string }
  nativeAvailable: boolean
  corePid: string
  head?: string
  lastHead?: string
  dirty?: number
  stale?: boolean
}

/** 基线(lastHead) → 工作区 变更文件集（三视图 diff 数据源）。 */
export interface BaselineDiff {
  head: string
  lastHead: string
  stale: boolean
  aligned: boolean
  dirty: number
  files: { added: string[]; modified: string[]; deleted: string[] }
  counts: { added: number; modified: number; deleted: number }
}

/** 资产/组件变更对比(任意 head 对 vs head/工作区；缓存态)。 */
export interface AssetCompareComponent {
  id: string
  /** KB 组件展示名；「其他」桶(id=__other__)为空串，由前端 i18n */
  name: string
  added: number
  modified: number
  deleted: number
}

export interface AssetCompareAsset {
  id: string
  name: string
  kind: string
  level: string
  /** 所属组件 id；未归属=__other__ */
  component: string
  files: string[]
  /** 侧归属：资产提取时锚点哈希与哪一侧内容匹配（base=基准侧/target=目标侧/stale=中间态） */
  side?: 'base' | 'target' | 'stale'
  /** 符号级判定：true=锚点符号代码段有变更(强) / false=仅同文件其他位置变更(弱，可能受影响) */
  strong?: boolean
  /** 信号点(段内行级，近似口径)：true=锚点段含新增行(绿点) / 删除行(红点) */
  hasAdded?: boolean
  hasDeleted?: boolean
}

export interface AssetCompareCrossLink {
  fromId: string
  fromName: string
  toId: string
  toName: string
  type: string
  semantic: string
}

/** 「更新语义资产」变化量计划(校验阶段产物：reconcile 标准化 + 增量统计)。 */
export interface ExtractPlanResult {
  added: number
  modified: number
  deleted: number
  neverExtracted: number
  staleOnly: number
  toExtract: number
  invalidated: number
  batchesEstimate?: number
  truncated?: boolean
  files: string[]
}

/** 快照批量提取作业(后端 daemon 线程；进程内状态，重启即失)。 */
export interface SyncExtractJob {
  running: boolean
  total: number
  done: number
  saved: number
  batches: number
  errors: { files: string[]; error: string }[]
  stopped?: boolean
  startedAt?: number
  finishedAt?: number
  level?: string
  /** 逐文件推进: 当前正在提取的文件(供 UI 进度展示) */
  current?: string
  batch?: number
}

/** 未归属组件文件(owns 未覆盖)；assetCount = 首锚点为该文件的已提取资产数，
 *  activeCount = 其中 active 态数量(仅剩 stale → 待重提，重提可复活旧行)，
 *  extractable = false 表示无独立符号(config 聚合头等)，提取结构性无产出。 */
export interface UnownedFileEntry {
  path: string
  assetCount: number
  activeCount?: number
  extractable?: boolean
}

export interface UnownedFilesResult {
  files: UnownedFileEntry[]
  unownedCount: number
  ownedCount: number
  totalFiles: number
  symbolSource?: string
  truncated?: boolean
}

/** 未归属文件 ↔ 已归属组件的跨组件符号关联(按组件聚合 + 样本边)。 */
export interface UnownedCrossLink {
  file: string
  crossCount: number
  byComponent: { component: string; count: number; kinds: string[] }[]
  samples: { node: string; target: string; targetFile: string; component: string; kind: string; dir: 'in' | 'out' }[]
}

/** 未归属文件循环批量提取作业(后端 daemon 线程；进程内状态，重启即失)。
 *  unowned/withAssets/noSymbols = 清单三分盘点(未归属 = 待提取 + 已有资产 + 无独立符号)。 */
export interface UnownedExtractJob {
  running: boolean
  total: number
  done: number
  saved: number
  batches: number
  errors: { files: string[]; error: string }[]
  stopped?: boolean
  startedAt?: number
  finishedAt?: number
  level?: string
  /** 逐文件推进: 当前正在提取的文件(供 UI 进度展示) */
  current?: string
  batch?: number
  unowned?: number
  withAssets?: number
  noSymbols?: number
}

export interface AssetCompareResult {
  base: string
  baseIsBaseline: boolean
  target: string
  targetIsWorktree: boolean
  head: string
  noChanges: boolean
  /** 基准侧资产缺失(有变更但无可锚定基线的资产)——提取闭环需先基线提取 */
  baseAssetsMissing?: boolean
  files: { added: string[]; modified: string[]; deleted: string[] }
  counts: { added: number; modified: number; deleted: number }
  components: AssetCompareComponent[]
  newFileCount: number
  assets: {
    stable: number
    changed: AssetCompareAsset[]
    changedTotal: number
    /** 符号段行区间命中变更 hunk（强关联） */
    changedStrong: number
    /** 仅同文件其他位置变更（弱关联，可能受影响） */
    changedWeak: number
    new: AssetCompareAsset[]
    newTotal: number
    removed: AssetCompareAsset[]
    removedTotal: number
    /** 目标侧存在但无资产匹配其内容 → 待提取(extractable=目标内容==工作区内容的子集, 可经工作区提取闭环) */
    pending: { count: number; files: string[]; extractable?: string[]; extractableCount?: number }
  }
  crossLinks: AssetCompareCrossLink[]
  crossLinkCount: number
  cached?: boolean
}

// ---- 组件图谱域(comp-graph): 组件/文件两级图谱 + 节点 AI 解读 ----

export interface CompGraphNode {
  id: string
  name: string
  kind: string
  level: string
  desc: string
  fileCount: number
  dependsOn: string[]
  parentId: string
  change: { added: number; modified: number; deleted: number }
  changedFiles: Record<string, string[]>
}

export interface CompGraphData {
  nodes: CompGraphNode[]
  edges: { from: string; to: string }[]
  base: string
  target: string
  noChanges: boolean
  compareError: string
}

export interface FileGraphNode {
  id: string
  path: string
  name: string
  compId: string
  compName: string
  /** '' = 无变更 */
  change: '' | 'added' | 'modified' | 'deleted'
}

export interface FileGraphChangedAsset {
  id: string
  name: string
  kind: string
  strong: boolean
  side: string
}

export interface FileGraphData {
  nodes: FileGraphNode[]
  edges: { from: string; to: string }[]
  changedAssets: Record<string, FileGraphChangedAsset[]>
  components: { id: string; name: string; kind: string }[]
  base: string
  target: string
}

export interface NodeNotesResult {
  note: string
  cached: boolean
  degraded: boolean
  error?: string
}

export interface FileLineNotesResult {
  notes: Record<string, string>
  cached: boolean
  degraded: boolean
  error?: string
}

export const semanticAssetService = {
  /** codegraph 符号源开关：状态查询 / 三档切换(on|off|auto，KV 持久化)。 */
  async codegraphStatus(): Promise<CodegraphStatus | undefined> {
    const c = ctx()
    return await apiGet<CodegraphStatus>(`/kb/semantic/codegraph${c ? `?${c}` : ''}`)
  },

  async setCodegraphMode(mode: 'on' | 'off' | 'auto'): Promise<boolean> {
    await apiPost<unknown>('/kb/semantic/codegraph', { mode })
    return true
  },

  /** 检测并同步 codegraph CLI 索引(未初始化自动 init + sync 增量; 本地快操作)。 */
  async codegraphSync(): Promise<{ synced: boolean; nodes: number; edges: number; message?: string } | undefined> {
    const { root, project } = currentProjectParams()
    return await apiPost('/kb/semantic/codegraph-sync', { root, project })
  },

  /** 自管基线状态(采集作业 + 基线锚 + 图谱计数) —— 概览「基线设定」行数据源。 */
  async collectGraphStatus(): Promise<CollectGraphStatus | undefined> {
    const c = ctx()
    return await apiGet<CollectGraphStatus>(`/kb/semantic/collect-graph/status${c ? `?${c}` : ''}`)
  },

  /** 一键基线刷新(数据主权批E): 本地编排 采集→分组→命名, 单作业进度。 */
  async baselineRefresh(force = false, anchorHead?: string): Promise<{ started: boolean; reason?: string; job?: { id: string }; message?: string } | undefined> {
    const { root, project } = currentProjectParams()
    return await apiPost('/kb/semantic/baseline-refresh', { root, project, ...(force ? { force: true } : {}), ...(anchorHead ? { anchorHead } : {}) })
  },

  /** 基线刷新作业状态(最近 5 次 + 最新)。 */
  async baselineRefreshStatus(): Promise<{ jobs: BaselineRefreshJob[]; latest?: BaselineRefreshJob } | undefined> {
    const c = ctx()
    return await apiGet(`/kb/semantic/baseline-refresh/status${c ? `?${c}` : ''}`)
  },

  /** 基线(lastHead) → 工作区 变更文件集（三视图 diff 数据源）。 */
  async baselineDiff(): Promise<BaselineDiff | undefined> {
    const c = ctx()
    return await apiGet<BaselineDiff>(`/kb/semantic/baseline-diff${c ? `?${c}` : ''}`)
  },

  /** 资产/组件变更对比：base 缺省=baselineCommit；target='worktree'(缺省)|commit。 */
  async assetCompare(base?: string, target?: string): Promise<AssetCompareResult | undefined> {
    const parts: string[] = []
    if (base) parts.push(`base=${encodeURIComponent(base)}`)
    if (target) parts.push(`target=${encodeURIComponent(target)}`)
    const qs = [parts.join('&'), ctx()].filter(Boolean).join('&')
    return await apiGet<AssetCompareResult>(`/kb/semantic/asset-compare${qs ? `?${qs}` : ''}`)
  },

  /** 组件级图谱：组件节点+依赖边+变更徽标(asset-compare 同引擎聚合)。 */
  async compGraph(base?: string, target?: string): Promise<CompGraphData | undefined> {
    const parts: string[] = []
    if (base) parts.push(`base=${encodeURIComponent(base)}`)
    if (target && target !== 'worktree') parts.push(`target=${encodeURIComponent(target)}`)
    const qs = [parts.join('&'), ctx()].filter(Boolean).join('&')
    return apiGet<CompGraphData>(`/kb/semantic/comp-graph${qs ? `?${qs}` : ''}`)
  },

  /** 文件级图谱：多组件范围内文件节点+imports 边+文件变更态。 */
  async fileGraph(components: string[], base?: string, target?: string): Promise<FileGraphData | undefined> {
    const parts = [`components=${encodeURIComponent(components.filter(Boolean).join(','))}`]
    if (base) parts.push(`base=${encodeURIComponent(base)}`)
    if (target && target !== 'worktree') parts.push(`target=${encodeURIComponent(target)}`)
    const qs = [parts.join('&'), ctx()].filter(Boolean).join('&')
    return apiGet<FileGraphData>(`/kb/semantic/file-graph${qs ? `?${qs}` : ''}`)
  },

  /** 组件/文件级 AI 语义解读(arch_symbol_notes 缓存; force 重生成)。 */
  async nodeNotes(kind: 'component' | 'file', key: string, force = false): Promise<NodeNotesResult | undefined> {
    const qs = [`kind=${kind}`, `key=${encodeURIComponent(key)}`, `force=${force}`, ctx()].filter(Boolean).join('&')
    return apiGet<NodeNotesResult>(`/kb/semantic/node-notes?${qs}`)
  },

  /** 文件级行解读(文件卡全文件模式, 窗口 md5 缓存)。 */
  async fileLineNotes(file: string, start: number, end: number, force = false): Promise<FileLineNotesResult | undefined> {
    const qs = [`file=${encodeURIComponent(file)}`, `start=${start}`, `end=${end}`, `force=${force}`, ctx()].filter(Boolean).join('&')
    return apiGet<FileLineNotesResult>(`/kb/semantic/file-line-notes?${qs}`)
  },

  /** 未归属组件的文件清单(KB owns 未覆盖, 含每文件已提取资产数)。 */
  async unownedFiles(limit = 500): Promise<UnownedFilesResult> {
    return await apiGet<UnownedFilesResult>(`/kb/semantic/unowned-files${qsWith(`limit=${limit}`)}`)
  },

  /** 未归属文件 ↔ 已归属组件的跨组件符号关联(file 缺省=全部未归属文件)。 */
  async unownedCrossLinks(file?: string, limit = 200): Promise<{ links: UnownedCrossLink[]; totalCross: number; files: number }> {
    const parts: string[] = []
    if (file) parts.push(`file=${encodeURIComponent(file)}`)
    parts.push(`limit=${limit}`)
    return await apiGet(`/kb/semantic/unowned-cross-links${qsWith(parts.join('&'))}`)
  },

  /** 启动「未归属文件」循环批量提取后端作业(daemon 线程，页面关闭不受影响)；action='stop' 请求停止。
   *  ⚠️ body 必须带 root/project——后端按它解析项目根，缺失会 invalid_root(此前 UI 批量按钮从未成功启动的根因)。 */
  async unownedExtract(action: 'start' | 'stop' = 'start', opts?: { batch?: number; level?: string; force?: boolean }): Promise<{ started?: boolean; total?: number; reason?: string; stopped?: boolean; unowned?: number; withAssets?: number; noSymbols?: number }> {
    const { root, project } = currentProjectParams()
    return await apiPost('/kb/semantic/unowned-extract', {
      root,
      project,
      action,
      batch: opts?.batch,
      level: opts?.level,
    })
  },

  /** 批量提取作业进度轮询。 */
  async unownedExtractStatus(): Promise<UnownedExtractJob> {
    return await apiGet<UnownedExtractJob>(`/kb/semantic/unowned-extract-status${qsWith('')}`)
  },

  /** 「更新语义资产」校验阶段：变化量计划(reconcile 标准化 + 增量统计与样本)。 */
  async extractPlan(): Promise<ExtractPlanResult> {
    const { root, project } = currentProjectParams()
    return await apiPost<ExtractPlanResult>('/kb/semantic/extract-plan', { root, project })
  },

  /** 「更新语义资产」执行阶段：快照批量提取作业；action='stop' 请求停止。 */
  async syncExtract(action: 'start' | 'stop' = 'start', opts?: { batch?: number; level?: string }): Promise<{ started?: boolean; total?: number; reason?: string; message?: string; stopped?: boolean }> {
    const { root, project } = currentProjectParams()
    return await apiPost('/kb/semantic/sync-extract', {
      root,
      project,
      action,
      batch: opts?.batch,
      level: opts?.level,
    })
  },

  /** 快照批量提取作业进度轮询。 */
  async syncExtractStatus(): Promise<SyncExtractJob> {
    return await apiGet<SyncExtractJob>(`/kb/semantic/sync-extract-status${qsWith('')}`)
  },

  /** 自管组件命名状态(数据主权批C): coverage + 各组件命名。 */
  async componentNamingStatus(): Promise<ComponentNamingStatus | undefined> {
    const c = ctx()
    return await apiGet<ComponentNamingStatus | undefined>(`/kb/semantic/component-name/status${c ? `?${c}` : ''}`)
  },

  /** 组件快速命名启动(本地作业, KB llm 通道): force=全量重命名。 */
  async componentNameStart(force = false): Promise<{ started: boolean; reason?: string; jobId?: string } | undefined> {
    const { root, project } = currentProjectParams()
    return await apiPost('/kb/semantic/component-name', { root, project, ...(force ? { force: true } : {}) })
  },

  /** 工作区(非基线)AST 实时快照 — KB 通道(稳定节点 ID, 可与基线图谱对齐跟踪)。 */
  async workspaceSymbols(opts?: { base?: string; files?: string[] }): Promise<WorkspaceSnapshot | undefined> {
    const { root, project } = currentProjectParams()
    return await apiPost<WorkspaceSnapshot>('/kb/semantic/workspace-symbols', {
      root, project, base: opts?.base, files: opts?.files,
    })
  },

  /** 符号源选择器(与 codegraph on/off/auto 正交): auto|codegraph|native。 */
  async symbolSource(): Promise<SymbolSourceStatus | undefined> {
    const c = ctx()
    return await apiGet<SymbolSourceStatus>(`/kb/semantic/symbol-source${c ? `?${c}` : ''}`)
  },

  async setSymbolSource(pref: 'auto' | 'codegraph' | 'native'): Promise<boolean> {
    const { root, project } = currentProjectParams()
    await apiPut<unknown>('/kb/semantic/symbol-source', { root, project, pref })
    return true
  },

  /** 检索已提取的语义资产。 */
  async search(query: string, kind?: SemanticAssetKind, scope?: string[], level?: SemanticAssetLevel): Promise<SemanticAsset[]> {
    const r = await this.searchPage(query, kind, { limit: 100, offset: 0, scope, level })
    return r.items
  },

  /** 分页检索已提取的语义资产(≤limit/页，返回总数供翻页)。 */
  async searchPage(query: string, kind?: SemanticAssetKind, opts?: { limit?: number; offset?: number; scope?: string[]; level?: SemanticAssetLevel }): Promise<{ items: SemanticAsset[]; total: number; limit: number; offset: number }> {
    const parts = [`q=${encodeURIComponent(query || '')}`]
    if (kind) parts.push(`kind=${encodeURIComponent(kind)}`)
    if (opts?.level) parts.push(`level=${encodeURIComponent(opts.level)}`)
    if (opts?.scope?.length) parts.push(`scope=${encodeURIComponent(opts.scope.join(','))}`)
    const limit = opts?.limit ?? 100
    const offset = opts?.offset ?? 0
    parts.push(`limit=${limit}`)
    parts.push(`offset=${offset}`)
    // 兼容旧版后端返回纯数组：归一化为 { items, total }。
    const data = await apiGet<unknown>(`/kb/semantic/search${qsWith(parts.join('&'))}`) as (SemanticAsset[] | { items?: SemanticAsset[]; total?: number })
    const items = Array.isArray(data) ? data : (data?.items ?? [])
    const total = Array.isArray(data) ? items.length : (data?.total ?? items.length)
    return { items, total, limit, offset }
  },

  /** 读取单个语义资产详情。 */
  async detail(assetId: string): Promise<SemanticAsset | undefined> {
    return apiGet<SemanticAsset>(`/kb/semantic/${assetId}${qsWith('')}`)
  },

  /** 锚点前后源码窗口（symbol 已知时后端优先展开整个符号体；limit 可放宽以取全文）。
   *  ref=取该 commit 时点内容；diffBase=与基准 commit 做 git diff 逐行注解(增/删/改)。 */
  async sourceSnippet(file: string, line: number, symbol?: string, before = 10, after = 10, limit?: number,
                      opts?: { ref?: string; diffBase?: string }): Promise<SourceSnippet | undefined> {
    const parts = [`file=${encodeURIComponent(file)}`, `line=${line}`]
    if (symbol) parts.push(`symbol=${encodeURIComponent(symbol)}`)
    parts.push(`before=${before}`)
    parts.push(`after=${after}`)
    if (limit) parts.push(`limit=${limit}`)
    if (opts?.ref) parts.push(`ref=${encodeURIComponent(opts.ref)}`)
    if (opts?.diffBase) parts.push(`diff_base=${encodeURIComponent(opts.diffBase)}`)
    return apiGet<SourceSnippet>(`/kb/semantic/source-snippet${qsWith(parts.join('&'))}`)
  },

  /** 查询时生成/获取资产关联代码的伪码级说明(有效生命周期内缓存；stale 时重生成)。 */
  async pseudo(assetId: string, opts?: { force?: boolean }): Promise<{ pseudo: string; cached: boolean; degraded: boolean }> {
    const extra = opts?.force ? 'force=1' : ''
    return apiGet<{ pseudo: string; cached: boolean; degraded: boolean }>(
      `/kb/semantic/${assetId}/pseudo${qsWith(extra)}`)
  },

  /** 按需生成资产功能摘要(列表展开详情触发)；fresh 缓存直返，stale 重生成。 */
  async assetDesc(assetId: string): Promise<{ desc: string; cached: boolean; degraded: boolean }> {
    return apiGet<{ desc: string; cached: boolean; degraded: boolean }>(
      `/kb/semantic/${assetId}/desc${qsWith('')}`)
  },

  /** 资产卡源码窗口关键行逐行用途说明(手动触发；落库缓存随资产生命周期；force 跳过缓存重生成)。 */
  async lineNotes(assetId: string, file: string, start: number, end: number, opts?: { modelId?: string; force?: boolean }): Promise<LineNotesResult> {
    const parts = [`file=${encodeURIComponent(file)}`, `start=${start}`, `end=${end}`]
    if (opts?.modelId) parts.push(`model_id=${encodeURIComponent(opts.modelId)}`)
    if (opts?.force) parts.push('force=true')
    return apiGet<LineNotesResult>(`/kb/semantic/${assetId}/line-notes${qsWith(parts.join('&'))}`)
  },

  /** 资产节点简介(≤80 字代码级描述；fresh 命中缓存 / stale·force 重生成；失败降级原 desc)。 */
  async nodeBrief(assetId: string, force = false, signal?: AbortSignal): Promise<{ brief: string; cached: boolean; degraded: boolean }> {
    return apiGet(`/kb/semantic/${assetId}/node-brief${qsWith(force ? 'force=true' : '')}`, signal)
  },

  /** 资产出边关系描述(证据式；edge_notes 缓存，force 重生成)。 */
  async edgeNotes(assetId: string, force = false, signal?: AbortSignal): Promise<{ notes: Record<string, string>; cached: boolean; degraded: boolean }> {
    return apiGet(`/kb/semantic/${assetId}/edge-notes${qsWith(force ? 'force=true' : '')}`)
  },

  /** 入边(被谁引用)：反向扫描活跃资产 relations 指向本资产的边(附 from 资产证据描述如有)。 */
  async inEdges(assetId: string): Promise<{ inEdges: { fromId: string; fromName: string; type?: string; desc?: string }[] }> {
    return apiGet(`/kb/semantic/${assetId}/in-edges${qsWith('')}`)
  },

  /** 启动存量资产描述批量增强(后台线程)：节点简介(按文件批量) + 出边关系描述。 */
  async enhanceDesc(force = false): Promise<{ started: boolean; running: boolean; done: number; total: number; nodeBriefs: number; edgeNotes: number }> {
    return apiPost(`/kb/semantic/enhance-desc${qsWith(force ? 'force=true' : '')}`)
  },

  /** 批量增强进度。 */
  async enhanceDescStatus(): Promise<{ running: boolean; done: number; total: number; nodeBriefs: number; edgeNotes: number; error?: string }> {
    return apiGet(`/kb/semantic/enhance-desc/status${qsWith('')}`)
  },

  /** 范围提取作业提交(LLM, 后台任务)：{scopeType: files|comm, key?, files[], ...}。 */
  async startExtractScope(scope: { scopeType: 'files' | 'comm'; key?: string; files: string[] },
                          opts?: { kinds?: string[]; level?: string; modelId?: string }): Promise<{ started: boolean; reason?: string; job?: { id: string } }> {
    const { root, project } = currentProjectParams()
    return apiPost('/kb/semantic/extract-scope', {
      root, project, ...scope,
      kinds: opts?.kinds, level: opts?.level, modelId: opts?.modelId,
    })
  },

  /** 逻辑视图列表(逻辑分析分组数据源)。 */
  async listLogicViews(): Promise<LogicView[]> {
    const r = await apiGet<{ views: LogicView[] }>(`/kb/semantic/logic-views${qsWith('')}`)
    return r?.views ?? []
  },

  /** AI 详细语义讲解：指纹一致缓存秒回 / 成员变化自动失效重生成 / force 强制。 */
  async explainLogicView(id: string, force = false, modelId?: string): Promise<{ viewId: string; detail: string; cached: boolean } | undefined> {
    const { root, project } = currentProjectParams()
    return apiPost(`/kb/semantic/logic-views/${encodeURIComponent(id)}/explain`,
                   { root, project, force, modelId })
  },

  /** 图谱范围提纲(零 LLM)：核心(选中优先+中心度 top) × 1/2/3 跳邻域三档。 */
  async graphOutline(assetIds: string[], preferCores?: string[]): Promise<{ cores: { coreId: string; coreName: string; degree: number; hops: Record<'1' | '2' | '3', string[]> }[] } | undefined> {
    const { root, project } = currentProjectParams()
    return apiPost('/kb/semantic/logic-views/graph-outline', { root, project, assetIds, preferCores })
  },

  /** 图谱范围逻辑解析(同步等待作业完成)：每组 → source='graph' 逻辑视图。 */
  async induceScope(groups: { coreId: string; hops: number; memberIds: string[] }[], modelId?: string): Promise<{ viewIds: string[]; count: number } | undefined> {
    const { root, project } = currentProjectParams()
    return apiPost('/kb/semantic/logic-views/induce-scope', { root, project, groups, modelId })
  },

  /** 新建逻辑视图(手动)：核心实现资产为种子，分析后拓展为成员全集。 */
  async createLogicView(payload: { name: string; coreIds: string[] }): Promise<LogicView | undefined> {
    const { root, project } = currentProjectParams()
    return apiPost('/kb/semantic/logic-views', { root, project, ...payload })
  },

  /** 逻辑视图改名/成员编辑。 */
  async updateLogicView(id: string, payload: { name?: string; coreIds?: string[]; memberIds?: string[] }): Promise<LogicView | undefined> {
    return apiPut(`/kb/semantic/logic-views/${encodeURIComponent(id)}`, payload)
  },

  async deleteLogicView(id: string): Promise<void> {
    await apiDelete(`/kb/semantic/logic-views/${encodeURIComponent(id)}`)
  },

  /** 分析作业：核心沿调用依赖拓展(expand=core/1/2/all) → 成员更新 → LLM 概括。 */
  async analyzeLogicView(id: string, expand: 'core' | '1' | '2' | 'all' = 'all'): Promise<{ started: boolean; reason?: string; job?: { id: string } }> {
    const { root, project } = currentProjectParams()
    return apiPost(`/kb/semantic/logic-views/${encodeURIComponent(id)}/analyze`, { root, project, expand })
  },

  /** 逻辑级提取作业提交(LLM 链条归纳，基于实现级资产→落库为逻辑视图)：BE 级联——范围内实现骨架缺失自动先跑结构化提取。 */
  async startExtractLogic(payload: { rev?: string; files?: string[]; scopeKey?: string; modelId?: string } = {}): Promise<{ started: boolean; reason?: string; job?: { id: string } }> {
    const { root, project } = currentProjectParams()
    return apiPost('/kb/semantic/extract-logic', { root, project, ...payload })
  },

  /** 结构化提取作业提交(无 LLM)：rev='baseline:<sha>'/'head:<sha>' 时按 rev 内容解析。 */
  async startExtractImpl(payload: { rev?: string; files?: string[]; keys?: string[]; base?: string }): Promise<{ started: boolean; reason?: string; job?: { id: string } }> {
    const { root, project } = currentProjectParams()
    return apiPost('/kb/semantic/extract-impl', { root, project, ...payload })
  },

  /** 作业详情(轮询终态用)。 */
  async getJob(jobId: string): Promise<{ id: string; state: string; result?: { summary?: string; saved?: number; error?: string } } | undefined> {
    return apiGet(`/kb/semantic/jobs/${encodeURIComponent(jobId)}`)
  },

  /** 按范围即时提取并落库。 */
  async extract(scope: SemanticExtractScope, kinds?: SemanticAssetKind[], opts?: { modelId?: string; level?: SemanticAssetLevel }): Promise<SemanticExtractResult> {
    return apiPost<SemanticExtractResult>('/kb/semantic/extract', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      scope,
      kinds,
      modelId: opts?.modelId,
      level: opts?.level,
    })
  },

  /** 按需聚合业务级(high)语义资产。 */
  async aggregateHigh(opts?: { modelId?: string }): Promise<SemanticExtractResult> {
    return apiPost<SemanticExtractResult>('/kb/semantic/aggregate', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      modelId: opts?.modelId,
    })
  },

  /** 增量刷新某范围。 */
  async refresh(scopeType: string, scopeKey: string, opts?: { modelId?: string }): Promise<SemanticExtractResult> {
    return apiPost<SemanticExtractResult>('/kb/semantic/refresh', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      scopeType,
      scopeKey,
      modelId: opts?.modelId,
    })
  },

  /** 更新单个过期资产(增量重提；失败软删并重新生成)。 */
  async refreshAsset(assetId: string, opts?: { modelId?: string }): Promise<AssetUpdateResult> {
    return apiPost<AssetUpdateResult>('/kb/semantic/handle-stale', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      assetId,
      modelId: opts?.modelId,
    })
  },

  /** 校验资产新鲜度(标记因文件变更/新增文件影响而过期的资产为需更新)。 */
  async reconcile(force = false): Promise<SemanticReconcileResult> {
    return apiPost<SemanticReconcileResult>('/kb/semantic/reconcile', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      force,
    })
  },

  // ── 就地认知编辑（plan-C-M0 §7.2；main-KB 关联项目后端 409 拒绝） ──

  /** 资产改名（旧名自动入 renamedFrom/nameAlias 历史；overlay 审计）。 */
  async renameAsset(assetId: string, newName: string): Promise<{ asset: SemanticAsset; overlayId: string }> {
    return apiPost<{ asset: SemanticAsset; overlayId: string }>('/semantic/assets/rename', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      assetId,
      newName,
    })
  },

  /** 资产合并（目标锚点并入 intoId；目标行留痕 mergedInto）。 */
  async mergeAssets(intoId: string, targetIds: string[], targetName = ''): Promise<{ asset: SemanticAsset; merged: string[]; overlayId: string }> {
    return apiPost<{ asset: SemanticAsset; merged: string[]; overlayId: string }>('/semantic/assets/merge', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      intoId,
      targetIds,
      targetName,
    })
  },

  /** 资产拆分（按 anchorKeys=file:symbol 锚点组拆出新资产）。 */
  async splitAsset(assetId: string, parts: { name: string; anchorKeys: string[]; desc?: string }[]): Promise<{ deletedAssetId: string; created: { id: string; name: string; anchors: number }[]; overlayId: string }> {
    return apiPost<{ deletedAssetId: string; created: { id: string; name: string; anchors: number }[]; overlayId: string }>(
      '/semantic/assets/split', {
        root: currentProjectParams().root,
        project: currentProjectParams().project,
        assetId,
        parts,
      })
  },

  /** 批量清除选定组件范围的语义资产(clear)。
   *  支持 dryRun=true 预览影响(需求池/任务)供前端确认。 */
  async batchManage(action: 'clear', components: string[], opts?: { includeOther?: boolean; scope?: string[]; dryRun?: boolean; files?: string[] }): Promise<SemanticBatchResult> {
    return apiPost<SemanticBatchResult>('/kb/semantic/batch', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      action,
      components,
      includeOther: opts?.includeOther,
      scope: opts?.scope,
      dryRun: opts?.dryRun,
      files: opts?.files,
    })
  },

  /** 资产新鲜度状态(active/stale/deleted/needsUpdate + 变更文件)。 */
  async status(): Promise<SemanticStatusResult> {
    return apiGet<SemanticStatusResult>(`/kb/semantic/status${qsWith('')}`)
  },

  /** A6 影响分析：跨组件变更扩散链 + 契约↔实现全局漂移总览。 */
  async impact(): Promise<ImpactAnalysisResult> {
    return apiGet<ImpactAnalysisResult>(`/kb/semantic/impact${qsWith('')}`)
  },

  /** 资产概览统计：总量 / 按类别 / 按粒度 / 状态。 */
  async stats(): Promise<SemanticStatsResult> {
    return apiGet<SemanticStatsResult>(`/kb/semantic/stats${qsWith('')}`)
  },

  /** 语义层图谱：节点=语义资产，边=资产 relations，锚点=AST 引用。 */
  async graph(kind?: SemanticAssetKind, scope?: string[], level?: SemanticAssetLevel, opts?: { focus?: string; hops?: number; includeIndirect?: boolean; file?: string; files?: string[]; assets?: string; rev?: string }): Promise<SemanticGraphResult> {
    const parts: string[] = []
    if (kind) parts.push(`kind=${encodeURIComponent(kind)}`)
    if (level) parts.push(`level=${encodeURIComponent(level)}`)
    if (scope?.length) parts.push(`scope=${encodeURIComponent(scope.join(','))}`)
    if (opts?.focus) parts.push(`focus=${encodeURIComponent(opts.focus)}`)
    if (opts?.hops) parts.push(`hops=${opts.hops}`)
    if (opts?.includeIndirect) parts.push('include_indirect=true')
    if (opts?.file) parts.push(`file=${encodeURIComponent(opts.file)}`)
    if (opts?.files?.length) parts.push(`files=${encodeURIComponent(opts.files.join(','))}`)
    if (opts?.rev && opts.rev !== 'workspace') parts.push(`rev=${encodeURIComponent(opts.rev)}`)
    if (opts?.assets) parts.push(`assets=${encodeURIComponent(opts.assets)}`)
    // limit 10000：2000 上限在大项目(3.7k+ 资产)会把较早的活跃资产截掉——
    // 文件级/聚焦图谱查不到明明存在的资产(实测回归)。
    parts.push('limit=10000')
    return apiGet<SemanticGraphResult>(`/kb/semantic/graph${qsWith(parts.join('&'))}`)
  },

  /** 符号详情(代码资产卡·符号形态)：元数据+代码段+AI 解读缓存。 */
  async symbolDetail(symbol: string): Promise<SemanticSymbolDetail> {
    return apiGet<SemanticSymbolDetail>(`/kb/semantic/symbol-detail${qsWith(`symbol=${encodeURIComponent(symbol)}`)}`)
  },

  /** 符号 AI 解读(同步单次, grounded 于真实代码段, 服务端落缓存)。 */
  async symbolNote(symbol: string): Promise<{ note: string; cached?: boolean; degraded?: boolean }> {
    const { root, project } = currentProjectParams()
    return apiPost(`/kb/semantic/symbol-note`, { root, project, symbol })
  },

  /** 链路跟踪(深度探索)：asset=整链 / symbol=侧栏懒加载展开; direction down=它调谁 / up=谁调它。 */
  async trace(asset: string, direction: 'down' | 'up', opts?: { symbol?: string; maxDepth?: number; branchLimit?: number }): Promise<SemanticTraceResult> {
    const parts = [`direction=${direction}`,
      `max_depth=${opts?.maxDepth ?? 6}`, `branch_limit=${opts?.branchLimit ?? 3}`]
    if (asset) parts.push(`asset=${encodeURIComponent(asset)}`)
    if (opts?.symbol) parts.push(`symbol=${encodeURIComponent(opts.symbol)}`)
    return apiGet<SemanticTraceResult>(`/kb/semantic/trace${qsWith(parts.join('&'))}`)
  },

  /** 静态资产图：entity → 类图(字段/方法)，state → 状态图。assetIds 缺省 = 项目内 entity/state 资产。 */
  async assetDiagram(assetIds?: string[]): Promise<AssetDiagramResult> {
    return apiPost<AssetDiagramResult>('/kb/semantic/asset-diagram', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      assetIds,
    })
  },

  /** 物理清理语义资产：先 dry-run 返回影响范围，确认后带 confirm=true 真正删除。 */
  async purge(opts?: { staleDays?: number; confirm?: boolean }): Promise<SemanticPurgeResult> {
    return apiPost<SemanticPurgeResult>('/kb/semantic/purge', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      staleDays: opts?.staleDays,
      confirm: opts?.confirm,
    })
  },

  // ── M1 认知框架（plan-C-M0 §7.1；框架即配置） ──────────────────

  /** 当前生效框架配置（无定制 → 后端默认 mid 预设）。 */
  async getFramework(): Promise<FrameworkResult> {
    return apiGet<FrameworkResult>(`/framework${qsWith('')}`)
  },

  /** dry-run：标准变更影响预览（作废确认流数据源）。 */
  async previewFrameworkChange(): Promise<FrameworkPreview> {
    return apiPost<FrameworkPreview>('/framework/preview-change', { ...currentProjectParams() })
  },

  /** 执行标准变更（切换预设档位；存量资产整体作废、命名不迁移）。 */
  async switchFramework(tier: 'mid' | 'high', note?: string): Promise<FrameworkVersionRow> {
    return apiPost<FrameworkVersionRow>('/framework/switch', { tier, note, ...currentProjectParams() })
  },

  /** 自建框架载入（high 档能力；M1 仅透传，UI 编辑器后续切片）。 */
  async loadCustomFramework(config: Record<string, unknown>, note?: string): Promise<FrameworkVersionRow> {
    return apiPost<FrameworkVersionRow>('/framework/custom', { config, note, ...currentProjectParams() })
  },

  /** 框架版本历史（变更留痕）。 */
  async frameworkVersions(limit = 50): Promise<FrameworkVersionRow[]> {
    return apiGet<FrameworkVersionRow[]>(`/framework/versions${qsWith(`limit=${limit}`)}`)
  },

  /** 覆盖度统计（诚实呈现部分真相：已提取/过期/未提取组件清单）。 */
  async coverage(): Promise<CoverageInfo> {
    return apiGet<CoverageInfo>(`/semantic/coverage${qsWith('')}`)
  },
}

// ── M1 认知框架类型 ────────────────────────────────────────────

export interface FrameworkAxisValue { id: string; label: string; builtin?: boolean }

export interface FrameworkTierDef {
  x: string[]
  y: string[]
  z: string[]
  acceptanceDefault?: { mode?: string; layers?: string[]; l3?: string }
  directivesDepth?: string
}

export interface FrameworkConfig {
  version?: number
  activeTier: 'mid' | 'high' | 'custom'
  axes?: { id: string; label: string; values: FrameworkAxisValue[] }[]
  tiers?: Record<string, FrameworkTierDef>
  frameworkVersion?: number
}

export interface FrameworkView {
  kinds: string[]
  levels: string[]
  z: string[]
  acceptanceDefault?: FrameworkTierDef['acceptanceDefault']
  directivesDepth?: string
}

/** 逻辑视图：跨组件业务逻辑链条(核心种子+拓展成员+LLM 概括)。 */
export interface LogicView {
  id: string
  name: string
  coreIds: string
  memberIds: string
  summary: string
  source: 'extract' | 'manual' | 'graph'
  fingerprint?: string
  /** AI 详细语义讲解(Markdown 缓存；成员资产变化指纹失效自动重生成) */
  detail?: string
  detailFp?: string
  createdAt?: number
  updatedAt?: number
}

export interface FrameworkResult { config: FrameworkConfig; view: FrameworkView; presets: Record<string, FrameworkTierDef> }

export interface FrameworkPreview { voidedAssets: number; byKind: Record<string, number>; namingMigrated: boolean }

export interface FrameworkVersionRow {
  id: string
  projectId: string
  version: number
  config: FrameworkConfig
  changeKind: string
  affectedSummary?: { voidedAssets?: number; byKind?: Record<string, number>; note?: string }
  executedBy?: string
  note?: string
  active?: number
  createdAt?: number
  voidedAssets?: number
}

export interface CoverageInfo {
  extracted: number
  stale: number
  unowned: number
  componentsTotal: number
  componentsCovered: number
  components: { componentId: string; name: string; coverage: 'full' | 'partial' | 'none'; assets: number; stale: number }[]
}
