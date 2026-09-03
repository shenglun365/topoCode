import type { AssetDiagramResult, SemanticAsset, SemanticAssetDetail, SemanticAssetKind, SemanticAssetLevel } from '@/types'
import { apiGet, apiPost } from './api-client'
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

export interface SemanticGraphResult {
  nodes: SemanticGraphNode[]
  edges: SemanticGraphEdge[]
  anchors: SemanticGraphAnchor[]
  count: number
}

/** 锚点前后源码窗口（SourceSnippet：行号+代码+命中高亮行段）。 */
export interface SourceSnippet {
  file: string
  symbol?: string
  anchorLine: number
  highlight: number[]
  lines: { line: number; code: string }[]
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
  native?: { nodes?: number }
}

export const semanticAssetService = {
  /** codegraph 符号源开关：状态查询 / 三档切换(on|off|auto，KV 持久化)。 */
  async codegraphStatus(): Promise<CodegraphStatus | undefined> {
    return await apiGet<CodegraphStatus>('/kb/semantic/codegraph')
  },

  async setCodegraphMode(mode: 'on' | 'off' | 'auto'): Promise<boolean> {
    await apiPost<unknown>('/kb/semantic/codegraph', { mode })
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

  /** 锚点前后源码窗口（symbol 已知时后端优先展开整个符号体；limit 可放宽以取全文）。 */
  async sourceSnippet(file: string, line: number, symbol?: string, before = 10, after = 10, limit?: number): Promise<SourceSnippet | undefined> {
    const parts = [`file=${encodeURIComponent(file)}`, `line=${line}`]
    if (symbol) parts.push(`symbol=${encodeURIComponent(symbol)}`)
    parts.push(`before=${before}`)
    parts.push(`after=${after}`)
    if (limit) parts.push(`limit=${limit}`)
    return apiGet<SourceSnippet>(`/kb/semantic/source-snippet${qsWith(parts.join('&'))}`)
  },

  /** 查询时生成/获取资产关联代码的伪码级说明(有效生命周期内缓存；stale 时重生成)。 */
  async pseudo(assetId: string, modelId?: string): Promise<{ pseudo: string; cached: boolean; degraded: boolean }> {
    const extra = modelId ? `model_id=${encodeURIComponent(modelId)}` : ''
    return apiGet<{ pseudo: string; cached: boolean; degraded: boolean }>(
      `/kb/semantic/${assetId}/pseudo${qsWith(extra)}`)
  },

  /** 资产卡源码窗口关键行逐行用途说明(手动触发；落库缓存随资产生命周期；force 跳过缓存重生成)。 */
  async lineNotes(assetId: string, file: string, start: number, end: number, opts?: { modelId?: string; force?: boolean }): Promise<LineNotesResult> {
    const parts = [`file=${encodeURIComponent(file)}`, `start=${start}`, `end=${end}`]
    if (opts?.modelId) parts.push(`model_id=${encodeURIComponent(opts.modelId)}`)
    if (opts?.force) parts.push('force=true')
    return apiGet<LineNotesResult>(`/kb/semantic/${assetId}/line-notes${qsWith(parts.join('&'))}`)
  },

  /** 资产节点简介(≤80 字代码级描述；fresh 命中缓存 / stale·force 重生成；失败降级原 desc)。 */
  async nodeBrief(assetId: string, force = false): Promise<{ brief: string; cached: boolean; degraded: boolean }> {
    return apiGet(`/kb/semantic/${assetId}/node-brief${qsWith(force ? 'force=true' : '')}`)
  },

  /** 资产出边关系描述(证据式；edge_notes 缓存，force 重生成)。 */
  async edgeNotes(assetId: string, force = false): Promise<{ notes: Record<string, string>; cached: boolean; degraded: boolean }> {
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
  async batchManage(action: 'clear', components: string[], opts?: { includeOther?: boolean; scope?: string[]; dryRun?: boolean }): Promise<SemanticBatchResult> {
    return apiPost<SemanticBatchResult>('/kb/semantic/batch', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      action,
      components,
      includeOther: opts?.includeOther,
      scope: opts?.scope,
      dryRun: opts?.dryRun,
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
  async graph(kind?: SemanticAssetKind, scope?: string[], level?: SemanticAssetLevel, opts?: { focus?: string; hops?: number; includeIndirect?: boolean }): Promise<SemanticGraphResult> {
    const parts: string[] = []
    if (kind) parts.push(`kind=${encodeURIComponent(kind)}`)
    if (level) parts.push(`level=${encodeURIComponent(level)}`)
    if (scope?.length) parts.push(`scope=${encodeURIComponent(scope.join(','))}`)
    if (opts?.focus) parts.push(`focus=${encodeURIComponent(opts.focus)}`)
    if (opts?.hops) parts.push(`hops=${opts.hops}`)
    if (opts?.includeIndirect) parts.push('include_indirect=true')
    parts.push('limit=2000')
    return apiGet<SemanticGraphResult>(`/kb/semantic/graph${qsWith(parts.join('&'))}`)
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
  async switchFramework(tier: 'low' | 'mid' | 'high', note?: string): Promise<FrameworkVersionRow> {
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
  activeTier: 'low' | 'mid' | 'high' | 'custom'
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
