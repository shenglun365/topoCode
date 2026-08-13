import type { SemanticAsset, SemanticAssetDetail, SemanticAssetKind, SemanticAssetLevel } from '@/types'
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
  source?: 'codegraph' | 'live' | 'kb'
  degraded?: boolean
  count: number
  error?: string
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
  action: 'extract' | 'clear'
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
  /** 精简 detail(供类图/ER/序列/状态/聚合图生成)。 */
  detail?: SemanticAssetDetail
}

export interface SemanticGraphEdge {
  from: string
  to: string
  resolved?: boolean
  type?: string
  semantic?: string
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

/** 提取任务进度项(逐组件)。 */
export interface ExtractTaskProgressItem {
  compId: string
  status: 'running' | 'done' | 'failed'
  count: number
  error?: string
}

/** 提取任务对话消息(同步到资产管理对话消息栏)。 */
export interface ExtractTaskMessage {
  id: string
  role: string
  content: string
  time: number
}

/** 提取任务状态(服务端后台执行，刷新不中断，前端轮询恢复)。 */
export interface ExtractTaskStatus {
  found: boolean
  id?: string
  status?: 'running' | 'done' | 'partial' | 'failed'
  done?: number
  total?: number
  progress?: ExtractTaskProgressItem[]
  messages?: ExtractTaskMessage[]
  title?: string
  updatedAt?: number
  running?: boolean
}

export const semanticAssetService = {
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

  /** 批量提取(按 KB 组件/全项目)。 */
  async extractAll(kinds?: SemanticAssetKind[], opts?: { modelId?: string; maxComponents?: number; level?: SemanticAssetLevel }): Promise<SemanticExtractResult> {
    return apiPost<SemanticExtractResult>('/kb/semantic/extractAll', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      kinds,
      modelId: opts?.modelId,
      maxComponents: opts?.maxComponents,
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

  /** 批量管理选定组件范围的语义资产(extract/clear)。
   *  clear 支持 dryRun=true 预览影响(需求池/任务)供前端确认。 */
  async batchManage(action: 'extract' | 'clear', components: string[], opts?: { includeOther?: boolean; kinds?: SemanticAssetKind[]; modelId?: string; level?: SemanticAssetLevel; scope?: string[]; dryRun?: boolean }): Promise<SemanticBatchResult> {
    return apiPost<SemanticBatchResult>('/kb/semantic/batch', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      action,
      components,
      includeOther: opts?.includeOther,
      kinds: opts?.kinds,
      modelId: opts?.modelId,
      level: opts?.level,
      scope: opts?.scope,
      dryRun: opts?.dryRun,
    })
  },

  /** 资产新鲜度状态(active/stale/deleted/needsUpdate + 变更文件)。 */
  async status(): Promise<SemanticStatusResult> {
    return apiGet<SemanticStatusResult>(`/kb/semantic/status${qsWith('')}`)
  },

  /** 资产概览统计：总量 / 按类别 / 按粒度 / 状态。 */
  async stats(): Promise<SemanticStatsResult> {
    return apiGet<SemanticStatsResult>(`/kb/semantic/stats${qsWith('')}`)
  },

  /** 语义层图谱：节点=语义资产，边=资产 relations，锚点=AST 引用。 */
  async graph(kind?: SemanticAssetKind, scope?: string[], level?: SemanticAssetLevel): Promise<SemanticGraphResult> {
    const parts: string[] = []
    if (kind) parts.push(`kind=${encodeURIComponent(kind)}`)
    if (level) parts.push(`level=${encodeURIComponent(level)}`)
    if (scope?.length) parts.push(`scope=${encodeURIComponent(scope.join(','))}`)
    parts.push('limit=2000')
    return apiGet<SemanticGraphResult>(`/kb/semantic/graph${qsWith(parts.join('&'))}`)
  },

  /** 创建并后台启动组件语义资产提取任务(服务端执行，刷新不中断)。返回 {taskId}。 */
  async startExtractTask(components: string[], opts?: { kinds?: SemanticAssetKind[]; modelId?: string }): Promise<{ taskId: string }> {
    return apiPost<{ taskId: string }>('/kb/semantic/extract-task', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      components,
      kinds: opts?.kinds,
      modelId: opts?.modelId,
    })
  },

  /** 轮询提取任务状态(进度 + 对话消息，供资产管理对话同步)。 */
  async extractTaskStatus(taskId: string): Promise<ExtractTaskStatus> {
    return apiGet<ExtractTaskStatus>(`/kb/semantic/extract-task/${encodeURIComponent(taskId)}`)
  },

  /** 最近一次提取任务(刷新后恢复页面状态读取)。 */
  async latestExtractTask(): Promise<ExtractTaskStatus | null> {
    return apiGet<ExtractTaskStatus | null>(`/kb/semantic/extract-task/latest${qsWith('')}`)
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
}
