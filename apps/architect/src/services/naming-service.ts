import { apiDelete, apiGet, apiPost, apiPut } from './api-client'
import { currentProjectParams } from './project-service'

/**
 * 命名治理适配接口 —— 项目规约页（plan-C-M0 §7.2/§7.3）。
 * 命名规约（场景标签，agent 按场景加载 R7）/ 术语表（词典）/ 墓碑参考池。
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

function body(): Record<string, unknown> {
  const { root, project } = currentProjectParams()
  return { root, project }
}

// ── 类型 ──────────────────────────────────────────────────────

export type ConventionScenario = 'extract' | 'accept' | 'naming' | 'general'
export type ConventionStatus = 'pending' | 'active' | 'pending_review' | 'disabled'

export interface NamingConvention {
  id: string
  projectId: string
  scope: string
  componentId?: string
  appliesKinds?: string[]
  ruleText: string
  source: string
  scenarios: ConventionScenario[]
  status: ConventionStatus
  author?: string
  frameworkVersion?: number
  createdAt: number
  updatedAt: number
}

export interface GlossaryTerm {
  id: string
  projectId: string
  term: string
  alias?: string[]
  definition?: string
  source: string
  sourceRef?: string
  author?: string
  createdAt: number
  updatedAt: number
}

export interface NameTombstone {
  id: string
  projectId: string
  filePath?: string
  symbol?: string
  name: string
  source?: string
  reason?: string
  assetId?: string
  note?: string
  createdAt: number
}

// ── 服务 ──────────────────────────────────────────────────────

export const namingService = {
  async conventions(status: ConventionStatus | 'all' = 'active', scenario = ''): Promise<NamingConvention[]> {
    const extra = [`status=${status}`, `scenario=${encodeURIComponent(scenario)}`]
    return apiGet<NamingConvention[]>(`/naming/conventions${qsWith(extra.join('&'))}`)
  },

  async createConvention(data: {
    ruleText: string
    scenarios: ConventionScenario[]
    appliesKinds?: string[]
    componentId?: string
    status?: string
  }): Promise<NamingConvention> {
    return apiPost<NamingConvention>('/naming/conventions', { ...body(), ...data })
  },

  async updateConvention(id: string, patch: Record<string, unknown>): Promise<NamingConvention> {
    return apiPut<NamingConvention>(`/naming/conventions/${id}`, { ...body(), ...patch })
  },

  async deleteConvention(id: string): Promise<{ deleted: boolean }> {
    return apiDelete<{ deleted: boolean }>(`/naming/conventions/${id}`)
  },

  /** agent 归纳提议（pending 提案；设计者在界面确认后 active）。 */
  async induceConvention(data: {
    ruleText: string
    scenarios?: ConventionScenario[]
    appliesKinds?: string[]
  }): Promise<NamingConvention> {
    return apiPost<NamingConvention>('/naming/conventions/induce', { ...body(), ...data })
  },

  async glossary(q = ''): Promise<GlossaryTerm[]> {
    return apiGet<GlossaryTerm[]>(`/naming/glossary${qsWith(`q=${encodeURIComponent(q)}`)}`)
  },

  async createTerm(data: { term: string; alias?: string[]; definition?: string }): Promise<GlossaryTerm> {
    return apiPost<GlossaryTerm>('/naming/glossary', { ...body(), ...data })
  },

  async updateTerm(id: string, patch: Record<string, unknown>): Promise<GlossaryTerm> {
    return apiPut<GlossaryTerm>(`/naming/glossary/${id}`, { ...body(), ...patch })
  },

  async deleteTerm(id: string): Promise<{ deleted: boolean }> {
    return apiDelete<{ deleted: boolean }>(`/naming/glossary/${id}`)
  },

  /** 从项目文档导入术语（source_ref 记来源文件）。 */
  async importTerms(path: string): Promise<{ imported: number; sourceRef: string }> {
    return apiPost<{ imported: number; sourceRef: string; terms: GlossaryTerm[] }>(
      '/naming/glossary/import', { ...body(), path })
  },

  async tombstones(q = ''): Promise<NameTombstone[]> {
    return apiGet<NameTombstone[]>(`/naming/tombstones${qsWith(`q=${encodeURIComponent(q)}`)}`)
  },

  /** 资产命名历史（墓碑 + overlay 改名重放 + 行内溯源）。 */
  async assetNames(assetId: string): Promise<{
    assetId: string
    currentName: string
    renamedFrom?: string
    nameAlias?: string[]
    history: { type: string; at: number; name?: string; seq?: number; symbol?: string; file?: string; reason?: string; source?: string; author?: string; renamedFrom?: string; nameAlias?: string[] }[]
  }> {
    return apiGet(`/semantic/assets/${assetId}/names${qsWith('')}`)
  },
}
