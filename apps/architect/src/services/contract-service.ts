import { apiDelete, apiGet, apiPost, apiPut } from './api-client'
import { currentProjectParams } from './project-service'
import type { DiagramSchema } from '@topo/web-core/topoOne/core/types.ts'

/**
 * 契约条目 / 契约包 / 验收 适配接口 —— architect 自持（plan-C-M0 §2/§6.7/§7）。
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

// ── 类型（与 M0 冻结 schema 对齐，API 形状 camelCase） ─────────

export type ContractItemStatus =
  | 'draft' | 'confirmed' | 'injected' | 'verifying' | 'accepted' | 'rejected'

export interface ContractOrigin {
  convId?: string
  messageId?: string
  /** 设计者原话引用（V2 证据链锚点）。 */
  quote?: string
}

export interface ContractTarget {
  file?: string
  symbol?: string
  componentId?: string
}

export interface ContractBehavior {
  fields?: { name: string; type?: string; semantic?: string }[]
  steps?: { order: number; semantic: string; condition?: string }[]
  branches?: { condition: string; semantic?: string }[]
  states?: string[]
  transitions?: { from: string; to: string; condition?: string }[]
  relations?: { target: string; type?: string; semantic?: string }[]
}

export interface ContractZAxisItem {
  category: 'observability' | 'resilience' | 'config' | 'security'
  text: string
  anchor?: string
}

export interface ContractAcceptance {
  mode?: 'auto' | 'assisted' | 'manual'
  criteria?: string
  linkedTests?: string[]
}

export interface ContractItem {
  id: string
  projectId: string
  seq: number
  reqId?: string
  convId?: string
  origin?: ContractOrigin
  kind: string
  level: string
  target?: ContractTarget
  intentOnly?: number
  behavior?: ContractBehavior
  zAxis?: ContractZAxisItem[]
  acceptance?: ContractAcceptance
  status: ContractItemStatus
  staleByFramework?: number
  version: number
  createdBy?: string
  createdAt: number
  confirmedAt?: number
  injectedAt?: number
  verifiedAt?: number
}

export interface ContractItemInput {
  kind: string
  level?: string
  reqId?: string
  origin?: ContractOrigin
  target?: ContractTarget
  behavior?: ContractBehavior
  zAxis?: ContractZAxisItem[]
  acceptance?: ContractAcceptance
}

export interface ContractPackageSnapshot {
  version: number
  activeTier: string
  directivesDepth: string
  acceptanceDefault?: { mode?: string; layers?: string[]; l3?: string }
}

export interface ContractPackage {
  id: string
  projectId: string
  seq: number
  frameworkSnapshot: ContractPackageSnapshot
  itemIds: string[]
  assetRefs?: string[]
  componentRefs?: string[]
  agentsMd: string
  status: 'created' | 'injected' | 'superseded'
  injectedTo?: string
  createdAt: number
  injectedAt?: number
}

export type AcceptanceVerdict = 'pass' | 'fail' | 'partial'

export interface AcceptanceReport {
  id: string
  projectId: string
  seq: number
  packageId: string
  triggerInfo?: { type?: string; ref?: string; files?: string[] }
  extractionProfile: string
  summary?: {
    total?: number
    pass?: number
    fail?: number
    awaitingHuman?: number
    degraded?: boolean
    l3AwaitingHuman?: boolean
  }
  createdAt: number
}

export interface AcceptanceFact {
  id: string
  reportId: string
  itemId: string
  checkLayer: 'L1' | 'L2'
  verdict: AcceptanceVerdict
  evidence?: { assetId?: string; anchors?: { file: string; symbol: string; startLine?: number; endLine?: number }[]; detail?: string; notes?: string[] }
  createdAt: number
}

/** B2 双图对照：契约条目期望子图 vs 匹配资产实际子图（复用共享 IR）。 */
export interface DualDiagramResult {
  itemId: string
  assetId: string
  assetName: string
  expected: DiagramSchema
  actual: DiagramSchema
  diffs: { type: 'missing' | 'extra'; semantic: string }[]
}

/** C1 可授权清单：当前 mode 下哪些校验可自动授权、哪些必须人工。 */
export interface AuthorizationCheck {
  id: string
  label: string
  cls: 'mechanical' | 'intent' | 'opinion'
  authorizable: boolean
  status: 'pending' | 'not-run'
  note: string
}

export interface AuthorizationResult {
  itemId: string
  mode: 'auto' | 'assisted' | 'manual'
  autoPassable: boolean
  intentZCount: number
  humanRequired: string[]
  checks: AuthorizationCheck[]
}

export interface AcceptanceOpinion {
  id: string
  reportId: string
  itemId: string
  text: string
  confidence: number
  model?: string
  evidence?: { facts?: string[] }
  triggerBy?: string
  createdAt: number
}

export interface AcceptanceReportDetail {
  report: AcceptanceReport
  facts: AcceptanceFact[]
  opinions: AcceptanceOpinion[]
}

// ── 契约条目 ───────────────────────────────────────────────────

export const contractService = {
  /** 契约条目列表（status/reqId 过滤）。 */
  async items(status = '', reqId = '', limit = 500): Promise<ContractItem[]> {
    const extra = [`status=${encodeURIComponent(status)}`, `reqId=${encodeURIComponent(reqId)}`, `limit=${limit}`]
    return apiGet<ContractItem[]>(`/contracts/items${qsWith(extra.join('&'))}`)
  },

  /** 创建 draft 条目（固化卡「确认」前的落库通道）。 */
  async createItem(item: ContractItemInput): Promise<ContractItem> {
    return apiPost<ContractItem>('/contracts/items', { ...body(), item })
  },

  /** 固化卡「确认」：draft→confirmed（V2：需 origin）。 */
  async confirmItem(id: string): Promise<ContractItem> {
    return apiPost<ContractItem>(`/contracts/items/${id}/confirm`, body())
  },

  /** 固化卡「修改」：仅 draft 态编辑期望字段。 */
  async updateItem(id: string, patch: Partial<ContractItemInput>): Promise<ContractItem> {
    return apiPut<ContractItem>(`/contracts/items/${id}`, { ...body(), patch })
  },

  /** 固化卡「删」：仅 draft 态。 */
  async deleteItem(id: string): Promise<{ deleted: boolean }> {
    return apiDelete<{ deleted: boolean }>(`/contracts/items/${id}`)
  },

  /** 设计者判定：accepted / rejected（唯一判定入口）。 */
  async verdict(id: string, verdict: 'accepted' | 'rejected'): Promise<ContractItem> {
    return apiPost<ContractItem>(`/contracts/items/${id}/verdict`, { ...body(), verdict })
  },

  /** rejected → 修改期望 → version+1 回 confirmed（V6）。 */
  async revise(id: string, patch: Partial<ContractItemInput>): Promise<ContractItem> {
    return apiPost<ContractItem>(`/contracts/items/${id}/revise`, { ...body(), patch })
  },

  /** 契约包列表。 */
  async packages(limit = 100): Promise<ContractPackage[]> {
    return apiGet<ContractPackage[]>(`/contracts/packages${qsWith(`limit=${limit}`)}`)
  },

  /** 由 confirmed 条目建包（缺省=全部 confirmed；框架快照随行冻结）。 */
  async createPackage(itemIds?: string[]): Promise<ContractPackage> {
    return apiPost<ContractPackage>('/contracts/packages', { ...body(), itemIds })
  },

  /** 注入 runner（agentsMd 生成；条目→injected）。 */
  async injectPackage(id: string, injectedTo = 'runner'): Promise<ContractPackage> {
    return apiPost<ContractPackage>(`/contracts/packages/${id}/inject`, { ...body(), injectedTo })
  },

  // ── 验收 ────────────────────────────────────────────────────

  /** 触发验收（严 profile 提取 → L1/L2 机械比对 → 报告落库）。 */
  async runAcceptance(packageId: string, triggerType: string = 'manual', ref = ''): Promise<AcceptanceReportDetail> {
    return apiPost<AcceptanceReportDetail>('/acceptance/run', {
      ...body(), packageId, triggerType, ref,
    })
  },

  /** 验收报告列表。 */
  async reports(packageId = '', limit = 100): Promise<AcceptanceReport[]> {
    const extra = packageId ? `packageId=${encodeURIComponent(packageId)}` : ''
    return apiGet<AcceptanceReport[]>(`/acceptance/reports${qsWith([extra, `limit=${limit}`].filter(Boolean).join('&'))}`)
  },

  /** 报告详情（facts/opinions 分区返回）。 */
  async reportDetail(id: string): Promise<AcceptanceReportDetail> {
    return apiGet<AcceptanceReportDetail>(`/acceptance/reports/${id}${qsWith('')}`)
  },

  /** 手动激活 L3：模型辅助参考意见（设计者主判，意见不改变判定）。 */
  async activateL3(reportId: string, itemId: string, instruction = ''): Promise<AcceptanceOpinion> {
    return apiPost<AcceptanceOpinion>(
      `/acceptance/reports/${reportId}/items/${itemId}/opinion`,
      { ...body(), instruction },
    )
  },

  /** 起草修复指令（只起草不发送）。 */
  async fixInstruction(itemId: string): Promise<{ instruction: string; source: string; itemId: string; basedOnFacts: number }> {
    return apiPost<{ instruction: string; source: string; itemId: string; basedOnFacts: number }>(
      `/acceptance/items/${itemId}/fix-instruction`, body())
  },

  /** A7：验收条目关联单测用例（引用关系；任意状态可改，不升 version）。 */
  async setLinkedTests(itemId: string, linkedTests: string[]): Promise<ContractItem> {
    return apiPost<ContractItem>(`/contracts/items/${itemId}/linked-tests`, { ...body(), linkedTests })
  },

  /** B2 双图对照：契约条目期望子图 vs 匹配资产实际子图（复用共享 IR）。 */
  async dualDiagram(itemId: string): Promise<DualDiagramResult> {
    return apiPost<DualDiagramResult>(`/acceptance/items/${itemId}/dual-diagram`, body())
  },

  /** C1 可授权清单：当前 mode 下哪些校验可自动授权、哪些必须人工。 */
  async authorization(itemId: string): Promise<AuthorizationResult> {
    return apiPost<AuthorizationResult>(`/contracts/items/${itemId}/authorization`, body())
  },
}
