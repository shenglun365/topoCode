/**
 * L-2 资产/技能管理 service（2610-B1 deferred）——arch_assets REST 薄适配。
 * W6 落地的 /arch/assets 面（D-1 表为真相源；skill 型 route_hint 必填）。
 */
import { apiDelete, apiGet, apiPost } from './api-client'
import { currentProjectParams } from './project-service'

export interface ArchAsset {
  id: string
  projectId: string
  kind: string
  name: string
  description: string
  payload: Record<string, unknown>
  enabled: boolean
  createdAt: number
  updatedAt: number
}

export const ASSET_KINDS = ['skill', 'requirement', 'todo', 'plan', 'analysis'] as const

function qs(extra?: Record<string, string>): string {
  const { project } = currentProjectParams()
  const p = new URLSearchParams()
  if (project) p.set('project', project)
  for (const [k, v] of Object.entries(extra || {})) p.set(k, v)
  return p.toString() ? `?${p}` : ''
}

export const assetsService = {
  async list(kind = ''): Promise<ArchAsset[]> {
    return apiGet<ArchAsset[]>(`/arch/assets${qs(kind ? { kind } : undefined)}`)
  },
  async upsert(body: Partial<ArchAsset> & { name: string }): Promise<ArchAsset> {
    return apiPost<ArchAsset>('/arch/assets', { ...body })
  },
  async remove(id: string): Promise<boolean> {
    return (await apiDelete<{ deleted: boolean }>(`/arch/assets/${id}`)).deleted
  },
  /** 技能能力配置目录(分类分组): 内置(category)∪表技能, 含禁用行 */
  async skillsGroups(project = ''): Promise<SkillGroup[]> {
    return apiGet<SkillGroup[]>(
      `/arch/skills?project=${encodeURIComponent(project)}`)
  },
}

export interface SkillEntry {
  name: string
  description: string
  route_hint: string
  child_registry: string[]
  source: 'builtin' | 'asset'
  enabled: boolean
  assetId: string
}

export interface SkillGroup {
  category: string
  skills: SkillEntry[]
}
