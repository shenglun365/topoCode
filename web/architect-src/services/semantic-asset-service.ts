import type { SemanticAsset, SemanticAssetKind } from '@/types'
import { apiGet, apiPost } from './api-client'
import { currentProjectParams } from './project-service'

/**
 * 语义数据资产适配接口 —— architect 自持(结合最新代码结构 + codegraph)。
 *
 * 三类资产: data_structure / processing_flow / control_logic，均锚定 AST 节点。
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

export interface AssetUpdateResult {
  status: 'refreshed' | 'regenerated' | 'deleted' | 'missing'
  refreshed?: boolean
  regenerated?: boolean
  degraded?: boolean
  asset?: SemanticAsset
}

export interface SemanticBatchResult {
  action: 'extract' | 'clear' | 'update'
  count: number
  components?: number | null
  cleared?: string[]
  updated?: string[]
}

export const semanticAssetService = {
  /** 检索已提取的语义资产。 */
  async search(query: string, kind?: SemanticAssetKind, scope?: string[]): Promise<SemanticAsset[]> {
    const r = await this.searchPage(query, kind, { limit: 100, offset: 0, scope })
    return r.items
  },

  /** 分页检索已提取的语义资产(≤limit/页，返回总数供翻页)。 */
  async searchPage(query: string, kind?: SemanticAssetKind, opts?: { limit?: number; offset?: number; scope?: string[] }): Promise<{ items: SemanticAsset[]; total: number; limit: number; offset: number }> {
    const parts = [`q=${encodeURIComponent(query || '')}`]
    if (kind) parts.push(`kind=${encodeURIComponent(kind)}`)
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
  async extract(scope: SemanticExtractScope, kinds?: SemanticAssetKind[], opts?: { modelId?: string }): Promise<SemanticExtractResult> {
    return apiPost<SemanticExtractResult>('/kb/semantic/extract', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      scope,
      kinds,
      modelId: opts?.modelId,
    })
  },

  /** 批量提取(按 KB 组件/全项目)。 */
  async extractAll(kinds?: SemanticAssetKind[], opts?: { modelId?: string; maxComponents?: number }): Promise<SemanticExtractResult> {
    return apiPost<SemanticExtractResult>('/kb/semantic/extractAll', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      kinds,
      modelId: opts?.modelId,
      maxComponents: opts?.maxComponents,
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

  /** 批量管理选定组件范围的语义资产(extract/clear/update)。 */
  async batchManage(action: 'extract' | 'clear' | 'update', components: string[], opts?: { includeOther?: boolean; kinds?: SemanticAssetKind[]; modelId?: string }): Promise<SemanticBatchResult> {
    return apiPost<SemanticBatchResult>('/kb/semantic/batch', {
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      action,
      components,
      includeOther: opts?.includeOther,
      kinds: opts?.kinds,
      modelId: opts?.modelId,
    })
  },

  /** 资产新鲜度状态(active/stale/deleted/needsUpdate + 变更文件)。 */
  async status(): Promise<SemanticStatusResult> {
    return apiGet<SemanticStatusResult>(`/kb/semantic/status${qsWith('')}`)
  },
}
