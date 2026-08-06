import { defineStore } from 'pinia'
import type { DesignPlan, Requirement, RequirementAnalysis } from '@/types'
import { CODE_MAPPINGS, PLANS, REQUIREMENTS } from '@/services/mock/order-system'
import { apiGet, apiPost } from '@/services/api-client'
import { backendReady, backendUp } from '@/services/backend'
import { requirementService } from '@/services/requirement-service'

/** 归属推导：未显式记录时按旧 tier 兼容。 */
function locationOf(r: Requirement): 'proposal' | 'pool' {
  return r.location ?? (r.tier === 'raw' ? 'proposal' : 'pool')
}

/** 代码映射对齐：补 file；核心资产补伪代码示意。 */
function enrichAnalysis(rep?: RequirementAnalysis): RequirementAnalysis | undefined {
  if (!rep) return undefined
  rep.assetScope.forEach((a) => {
    if (!a.file) a.file = CODE_MAPPINGS.find((m) => m.targetId === a.assetId)?.file
    if (!a.keyNode && a.role === 'core') {
      const cm = CODE_MAPPINGS.find((m) => m.targetId === a.assetId)
      a.keyNode = `${cm?.file ? `${cm.file} ` : ''}${cm?.line ? `${cm.line} ` : ''}· 核心逻辑示意：锁定现状实现后按需求扩展(状态流转/唯一约束/边界校验)`
    }
  })
  if (!rep.assessment) {
    const core = rep.assetScope.filter((a) => a.role === 'core').length
    rep.assessment = {
      necessity: { grade: core ? 'high' : 'medium', reason: rep.feasibility.ok ? '与既有核心链路直接相关，具备明确业务价值' : '需先确认业务背景与范围' },
      atomicity: { independent: core <= 3, reason: core <= 3 ? '核心资产收敛，可独立交付、与其他需求解耦' : '跨资产较多，建议拆分为多个可独立验收的需求' },
      acceptability: { ok: true, reason: '可转化为功能用例 + 边界用例进行验收' },
    }
  }
  return rep
}

/** 提交需求种子(整体写入 / 提案保存共用)。 */
interface ReqSeed {
  id?: string
  title: string
  desc: string
  priority: 'P0' | 'P1' | 'P2'
  preferredAssetIds?: string[]
  /** 基本信息正文 MD，写入 Requirement.remarks；desc 字段留空。 */
  basicMd?: string
  /** 批量分析保存(多条勾选)新建提案时，指向本次勾选的关联源提案 id 列表。 */
  relatedTo?: string[]
}

export const useArchRequirementStore = defineStore('arch-requirement', {
  state: () => ({
    items: [] as Requirement[],
    plans: [] as DesignPlan[],
    loading: false,
    loaded: false,
  }),
  getters: {
    rawItems: (s) => s.items.filter((r) => locationOf(r) === 'proposal' && !r.analysis && r.status !== 'cancelled'),
    analyzedItems: (s) => s.items.filter((r) => locationOf(r) === 'pool' && r.status !== 'cancelled'),
    /** 需求提案：未入池(可已分析、继续讨论)。 */
    proposals: (s) => s.items.filter((r) => locationOf(r) === 'proposal' && r.status !== 'cancelled'),
    /** 需求池(已分析待执行，唯一执行入口)。 */
    poolItems: (s) => s.items.filter((r) => locationOf(r) === 'pool' && r.status !== 'cancelled'),
    cancelled: (s) => s.items.filter((r) => r.status === 'cancelled'),
    confirmedPlans: (s) => s.plans.filter((p) => p.status === 'confirmed'),
    draftPlans: (s) => s.plans.filter((p) => p.status === 'draft'),
    planConfirmed: (s) => s.plans.some((p) => p.status === 'confirmed'),
  },
  actions: {
    async load() {
      if (this.loaded) return
      this.loading = true
      // 后端优先：需求 + 方案列表；不可达回退 mock。
      if (await backendUp()) {
        try {
          const [items, plans] = await Promise.all([
            requirementService.list(),
            apiGet<DesignPlan[]>('/plans'),
          ])
          this.items = items ?? []
          this.plans = plans ?? []
          this.items.forEach((r) => { if (r.analysis) enrichAnalysis(r.analysis) })
          this.loaded = true
          this.loading = false
          return
        } catch {
          // fall through to mock
        }
      }
      this.items = structuredClone(REQUIREMENTS)
      this.plans = structuredClone(PLANS)
      this.items.forEach((r) => { if (r.analysis) enrichAnalysis(r.analysis) })
      this.loaded = true
      this.loading = false
    },
    async addRaw(input: Partial<Requirement>): Promise<Requirement> {
      const r: Requirement = {
        id: `RQ-${Date.now().toString().slice(-4)}`,
        kind: 'user-story',
        tier: 'raw',
        location: 'proposal',
        title: input.title ?? '未命名需求',
        priority: input.priority ?? 'P1',
        status: 'raw',
        desc: input.desc ?? '',
        acceptance: input.acceptance ?? [],
        traceTo: input.traceTo ?? [],
        preferredAssetIds: input.preferredAssetIds ?? [],
        updatedAt: Date.now(),
      }
      this.items.unshift(r)
      return r
    },
    updateRaw(id: string, patch: Partial<Requirement>) {
      const r = this.items.find((x) => x.id === id)
      if (r) Object.assign(r, patch, { updatedAt: Date.now() })
    },
    cancel(id: string) {
      const r = this.items.find((x) => x.id === id)
      if (r && r.status === 'raw') r.status = 'cancelled'
    },
    uncancel(id: string) {
      const r = this.items.find((x) => x.id === id)
      if (r && r.status === 'cancelled') r.status = 'raw'
    },
    /** 完成分析并入池(门槛由调用方校验)：单条提案 → 需求池(已分析)。 */
    finalizeAnalysis(
      seed: ReqSeed,
      report: RequirementAnalysis,
    ): Requirement {
      const existing = seed.id ? this.items.find((x) => x.id === seed.id) : undefined
      enrichAnalysis(report)
      const assetIds = report.assetScope.map((a) => a.assetId)
      if (existing) {
        existing.tier = 'analyzed'
        existing.location = 'pool'
        existing.status = 'analyzed'
        existing.title = seed.title
        existing.desc = ''
        existing.priority = seed.priority
        existing.preferredAssetIds = seed.preferredAssetIds ?? existing.preferredAssetIds
        existing.remarks = seed.basicMd ?? existing.remarks
        existing.routedBy = 'analysis'
        existing.analysis = report
        existing.traceTo = [...new Set([...existing.traceTo, ...assetIds])]
        existing.updatedAt = Date.now()
        return existing
      }
      const r: Requirement = {
        id: `RQ-${Date.now().toString().slice(-4)}`,
        kind: 'user-story',
        tier: 'analyzed',
        location: 'pool',
        title: seed.title,
        priority: seed.priority,
        status: 'analyzed',
        desc: '',
        acceptance: [],
        remarks: seed.basicMd,
        traceTo: assetIds,
        preferredAssetIds: seed.preferredAssetIds,
        routedBy: 'analysis',
        analysis: report,
        updatedAt: Date.now(),
      }
      this.items.unshift(r)
      return r
    },
    /**
     * 直通进池：跳过概要设计，提案一步落入需求池(带「直通」标记 + 精简概要)。
     * 供「直通执行 / 暂存池」路径使用；选择权完全在用户，系统仅给出评估建议。
     */
    addDirect(seed: ReqSeed, suggestion?: Requirement['suggestion']): Requirement {
      const existing = seed.id ? this.items.find((x) => x.id === seed.id) : undefined
      if (existing) {
        existing.tier = 'analyzed'
        existing.location = 'pool'
        existing.status = 'analyzed'
        existing.title = seed.title
        existing.desc = ''
        existing.priority = seed.priority
        existing.preferredAssetIds = seed.preferredAssetIds ?? existing.preferredAssetIds
        existing.remarks = seed.basicMd ?? existing.remarks
        existing.routedBy = 'direct'
        existing.suggestion = suggestion
        existing.traceTo = [...new Set([...existing.traceTo, ...(seed.preferredAssetIds ?? [])])]
        existing.updatedAt = Date.now()
        return existing
      }
      const r: Requirement = {
        id: `RQ-${Date.now().toString().slice(-4)}`,
        kind: 'user-story',
        tier: 'analyzed',
        location: 'pool',
        title: seed.title,
        priority: seed.priority,
        status: 'analyzed',
        desc: '',
        acceptance: [],
        remarks: seed.basicMd,
        traceTo: seed.preferredAssetIds ?? [],
        preferredAssetIds: seed.preferredAssetIds,
        routedBy: 'direct',
        suggestion,
        analysis: {
          functionalScope: [seed.title, '边界与异常'],
          entityBoundary: [],
          feasibility: { ok: true, reason: '直通需求：单循环就地解决，不改动核心数据资产边界', estMin: 60 },
          assetScope: (seed.preferredAssetIds ?? []).map((assetId) => ({ assetId, assetType: 'component', role: 'core', source: 'manual' })),
          implementationPath: `直通执行：在既有实现内扩展以覆盖「${seed.title}」，单循环一步到位，随后回归验证。`,
          changes: [],
          steps: [{ id: 'dstep-1', title: '直通实现', desc: `在既有服务内完成「${seed.title}」改动`, estMin: 60 }],
        },
        updatedAt: Date.now(),
      }
      this.items.unshift(r)
      return r
    },
    addPlan(plan: DesignPlan) {
      this.plans.unshift(plan)
    },
    updatePlan(id: string, patch: Partial<DesignPlan>) {
      const p = this.plans.find((x) => x.id === id)
      if (p) Object.assign(p, patch, { updatedAt: Date.now() })
    },
    confirmPlan(id: string) {
      const p = this.plans.find((x) => x.id === id)
      if (!p) return
      p.status = 'confirmed'
      if (!p.taskPlanId) p.taskPlanId = `tp-${Date.now().toString().slice(-4)}`
      this.items.forEach((r) => {
        if (p.reqIds.includes(r.id)) { r.planId = id; r.status = 'planned' }
      })
      if (backendReady()) apiPost<unknown>(`/plans/${id}/confirm`).catch(() => {})
    },
    /** 方案被重新规划/取消时，需求回到 analyzed，可被别的方案再选。 */
    releasePlan(id: string) {
      const p = this.plans.find((x) => x.id === id)
      if (!p) return
      p.status = 'draft'
      this.items.forEach((r) => {
        if (p.reqIds.includes(r.id) && r.planId === id) { r.planId = undefined; r.status = 'analyzed' }
      })
      if (backendReady()) apiPost<unknown>(`/plans/${id}/release`).catch(() => {})
    },
    /**
     * 代码级回退(回流特殊情况)：执行中需求/设计出现重大问题，该批次覆盖的
     * 所有需求回到需求池(analyzed)，释放方案，待补充设计/调整需求后再进入执行。
     */
    reflowPlan(planId: string) {
      const p = this.plans.find((x) => x.id === planId)
      if (!p) return
      p.status = 'draft'
      this.items.forEach((r) => {
        if (p.reqIds.includes(r.id)) {
          r.planId = undefined
          r.execId = undefined
          if (r.status !== 'done') r.status = 'analyzed'
        }
      })
    },
    /** 方案确认后进入执行：方案覆盖的需求状态 → executing。 */
    markPlanReqsExecuting(planId: string) {
      const p = this.plans.find((x) => x.id === planId)
      if (!p) return
      this.items.forEach((r) => {
        if (p.reqIds.includes(r.id) && (r.status === 'planned' || r.status === 'designed')) r.status = 'executing'
      })
    },
    /** 方案验收通过：方案覆盖的需求状态 → done。 */
    markPlanReqsDone(planId: string) {
      const p = this.plans.find((x) => x.id === planId)
      if (!p) return
      this.items.forEach((r) => {
        if (p.reqIds.includes(r.id) && (r.status === 'planned' || r.status === 'executing' || r.status === 'designed')) r.status = 'done'
      })
    },
    byId(id: string): Requirement | undefined {
      return this.items.find((r) => r.id === id)
    },
    /**
     * 入池门槛：数据资产必须明确(不要求 100%) + 质量评估四维齐全。
     * 明确资产 ≠ 必须入池；用户可继续保留在提案中讨论。
     */
    gateCheck(r: Requirement): { pass: boolean; missing: string[] } {
      const analysis = r.analysis
      const missing: string[] = []
      const assets = analysis?.assetScope ?? []
      if (!assets.length) missing.push('assetScope')
      else if (!assets.some((a) => a.role === 'core')) missing.push('assetCore')
      const bad = assets.filter((a) => !a.assetId)
      if (bad.length) missing.push('assetUnresolved')
      if (!analysis?.assessment) missing.push('assessment')
      return { pass: missing.length === 0, missing }
    },
    /**
     * 保存/更新为提案(可带分析，继续讨论)，不经过入池门槛。
     * 细化规则(批量分析保存)：
     *   - 勾选 1 条：seed.id = 该提案 → 就地更新(含已分析内容)。
     *   - 勾选多条：seed.id = undefined + relatedTo = 勾选源集合 → 新建一条提案，
     *     并对源提案标记 mergedInto(避免重复处理)；关联关系供前端展示。
     */
    saveProposal(seed: ReqSeed, analysis?: RequirementAnalysis): Requirement {
      const existing = seed.id ? this.items.find((x) => x.id === seed.id) : undefined
      if (analysis) enrichAnalysis(analysis)
      const assetIds = analysis?.assetScope.map((a) => a.assetId) ?? []
      if (existing) {
        existing.title = seed.title
        existing.desc = ''
        existing.priority = seed.priority
        existing.preferredAssetIds = seed.preferredAssetIds ?? existing.preferredAssetIds
        existing.remarks = seed.basicMd ?? existing.remarks
        existing.relatedTo = seed.relatedTo ?? existing.relatedTo
        existing.location = 'proposal'
        existing.tier = analysis ? 'analyzed' : 'raw'
        existing.status = analysis ? 'analyzed' : 'raw'
        existing.analysis = analysis ?? existing.analysis
        existing.traceTo = [...new Set([...existing.traceTo, ...assetIds])]
        existing.updatedAt = Date.now()
        return existing
      }
      const r: Requirement = {
        id: `RQ-${Date.now().toString().slice(-4)}`,
        kind: 'user-story',
        tier: analysis ? 'analyzed' : 'raw',
        location: 'proposal',
        title: seed.title,
        priority: seed.priority,
        status: analysis ? 'analyzed' : 'raw',
        desc: '',
        acceptance: [],
        remarks: seed.basicMd,
        relatedTo: seed.relatedTo,
        traceTo: assetIds,
        preferredAssetIds: seed.preferredAssetIds,
        analysis,
        updatedAt: Date.now(),
      }
      this.items.unshift(r)
      return r
    },
    /** 标记源提案已并入某条新提案(避免重复处理；分析选择列表中排除)。 */
    markMerged(sourceId: string, mergedId: string) {
      const src = this.byId(sourceId)
      if (src) {
        src.mergedInto = mergedId
        src.updatedAt = Date.now()
      }
    },
    /** 提案 → 需求池(需已通过门槛)。 */
    moveToPool(id: string): Requirement | undefined {
      const r = this.byId(id)
      if (!r) return undefined
      r.location = 'pool'
      r.tier = 'analyzed'
      r.status = 'analyzed'
      r.updatedAt = Date.now()
      return r
    },
    /** 需求池 → 提案：保留分析数据继续讨论/调整。 */
    moveToProposal(id: string): Requirement | undefined {
      const r = this.byId(id)
      if (!r) return undefined
      r.location = 'proposal'
      r.planId = undefined
      r.execId = undefined
      r.status = r.analysis ? 'analyzed' : 'raw'
      r.tier = r.analysis ? 'analyzed' : 'raw'
      r.updatedAt = Date.now()
      return r
    },
    planById(id: string): DesignPlan | undefined {
      return this.plans.find((p) => p.id === id)
    },
    async reset() {
      this.plans.forEach((p) => { p.status = 'draft' })
    },
  },
})
