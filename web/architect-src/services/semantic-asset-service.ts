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

export const semanticAssetService = {
  /** 检索已提取的语义资产。 */
  async search(query: string, kind?: SemanticAssetKind): Promise<SemanticAsset[]> {
    const parts = [`q=${encodeURIComponent(query || '')}`]
    if (kind) parts.push(`kind=${encodeURIComponent(kind)}`)
    return apiGet<SemanticAsset[]>(`/kb/semantic/search${qsWith(parts.join('&'))}`)
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
}
