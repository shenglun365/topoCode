import type { AssetScopeItem, CompareResult, DesignDiff, ErTable, RequirementAnalysis, RequirementDesign, ScopeProposal } from '@/types'
import { apiGet, apiPost } from './api-client'
import { currentProjectParams } from './project-service'

/**
 * 设计方案 / 范围圈定 / 修改前后对比 —— 方向1/2/3 前端适配。
 *
 * 后端契约(plugins/architect/arch_routes/design.py)：
 *   POST /requirements/analyze/scope         → { proposal, coverage, missing, catalog, diff }
 *   POST /requirements/{reqId}/design        → { design, beforeTables, afterTables, diff }
 *   GET  /requirements/{reqId}/design        → { design?, beforeTables, afterTables, diff? }
 *   POST /requirements/{reqId}/compare       → { mode, summary, columnDiffs?, semanticDiff,
 *                                                beforeTables, afterTables, deviations? }
 */

function ctx(): string {
  const { root, project } = currentProjectParams()
  const qs = new URLSearchParams()
  if (root) qs.set('root', root)
  if (project) qs.set('project', project)
  return qs.toString()
}

export interface ScopeRequest {
  title: string
  desc?: string
  mode?: 'greenfield' | 'existing'
  preferredAssetIds?: string[]
}

export interface GenerateDesignResult {
  design: RequirementDesign
  beforeTables: ErTable[]
  afterTables: ErTable[]
  diff?: DesignDiff | null
}

export const designService = {
  /** 方向1：圈定数据资产范围(proposal + 与上版 diff)。 */
  async scope(req: ScopeRequest, prevScope?: AssetScopeItem[], modelId?: string): Promise<ScopeProposal> {
    const qs = ctx()
    return apiPost<ScopeProposal>(`/requirements/analyze/scope${qs ? `?${qs}` : ''}`, {
      req,
      prevScope,
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      modelId,
    })
  },

  /** 方向2：生成设计方案并持久化到需求.design。 */
  async design(reqId: string, analysis?: RequirementAnalysis, modelId?: string): Promise<GenerateDesignResult> {
    const qs = ctx()
    return apiPost<GenerateDesignResult>(`/requirements/${reqId}/design${qs ? `?${qs}` : ''}`, {
      analysis,
      root: currentProjectParams().root,
      project: currentProjectParams().project,
      modelId,
    })
  },

  /** 方向2：读取已生成的设计方案(含对比用 before/after 表)。 */
  async getDesign(reqId: string): Promise<GenerateDesignResult> {
    const qs = ctx()
    return apiGet<GenerateDesignResult>(`/requirements/${reqId}/design${qs ? `?${qs}` : ''}`)
  },

  /** 方向3：修改前后对比(planned 计划态 / actual 实施后实际)。 */
  async compare(reqId: string, mode: 'planned' | 'actual'): Promise<CompareResult> {
    const qs = ctx()
    return apiPost<CompareResult>(`/requirements/${reqId}/compare${qs ? `?${qs}` : ''}`, {
      mode,
      root: currentProjectParams().root,
      project: currentProjectParams().project,
    })
  },
}
