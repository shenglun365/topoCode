import type {
  AssetScopeItem, ChangeItem, FormDraft, QuestionItem, ReqKind, RequirementAnalysis, RequirementAssessment, RequirementStep,
} from '@/types'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { useArchMcpStore } from '@/stores/mcp-store'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { currentProjectParams } from './project-service'
import { CODE_MAPPINGS } from './mock/order-system'
import { mockResult } from './mock/delay'

/**
 * topocode 知识库 agent 适配接口 —— 需求管理工作区(左栏对话)专用。
 *
 * 显式收集回合协议：
 *   1. clarify   — 依据需求意图返回「待回答问题清单」questions
 *   2. collect   — 用户作答(answers / 自由补充 note)后，收敛为「结果表单草案」formDraft
 *                  (若仍缺关键信息，可再返回一轮 questions)
 *   3. 用户确认 formDraft → 「整份替换」右栏表单；可多轮迭代
 *
 * 原型阶段全部为 mock 实现，以架构资产(组件/数据结构/流程/数据流 + 代码映射)充当知识库检索源。
 */
export interface KbAnalysisTurn {
  role: 'user' | 'assistant'
  content: string
  questions?: QuestionItem[]
  formDraft?: FormDraft
}

export interface KbAnalysisRequest {
  title: string
  desc: string
  priority: 'P0' | 'P1' | 'P2'
  kind?: ReqKind
  preferredAssetIds?: string[]
  /** greenfield 模式：空 KB 不走 matchAssets，走领域建模分支。 */
  mode?: 'greenfield' | 'existing'
}

export interface ClarifyResult {
  turns: KbAnalysisTurn[]
  questions: QuestionItem[]
}

export interface CollectResult {
  turns: KbAnalysisTurn[]
  questions?: QuestionItem[]
  formDraft?: FormDraft
}

export interface RequirementAnalysisAgent {
  clarify(req: KbAnalysisRequest): Promise<ClarifyResult>
  collect(ctx: { turns: KbAnalysisTurn[]; base: KbAnalysisRequest; answers: Record<string, string>; note?: string }): Promise<CollectResult>
}

interface KbAsset {
  id: string
  type: AssetScopeItem['assetType']
  name: string
  desc: string
}

function collectKbAssets(): KbAsset[] {
  const arch = useArchArchitectureStore()
  const assets: KbAsset[] = []
  arch.components.forEach((c) => assets.push({ id: c.id, type: 'component', name: c.name, desc: c.desc }))
  arch.erTables.forEach((d) => assets.push({ id: d.id, type: 'er', name: d.name, desc: d.desc }))
  arch.ormMappings.forEach((d) => assets.push({ id: d.id, type: 'orm', name: d.name, desc: d.desc }))
  arch.entityClasses.forEach((d) => assets.push({ id: d.id, type: 'entity', name: d.name, desc: d.desc }))
  arch.executionFlows.forEach((f) => assets.push({ id: f.id, type: 'flow', name: f.name, desc: `${f.trigger} ${f.desc}` }))
  arch.dataFlows.forEach((f) => assets.push({ id: f.id, type: 'dataflow', name: f.name, desc: f.desc }))
  return assets
}

/** 抽取检索 token：ASCII 单词 + 中文 2-gram。 */
function extractTokens(text: string): string[] {
  const tokens = new Set<string>()
  text
    .toLowerCase()
    .split(/[\s,，。、:：/;；()（）！!？?]+/)
    .filter((t) => t.length >= 2)
    .forEach((t) => {
      if (/[a-z0-9-]/.test(t)) tokens.add(t)
      for (let i = 0; i < t.length - 1; i++) {
        if (/[\u4e00-\u9fff]/.test(t[i]) && /[\u4e00-\u9fff]/.test(t[i + 1])) tokens.add(t.slice(i, i + 2))
      }
    })
  return [...tokens]
}

/** 关键词打分匹配知识库资产。 */
function matchAssets(text: string, preferred?: string[]): { hits: KbAsset[]; manual: AssetScopeItem[] } {
  const kb = collectKbAssets()
  const manual: AssetScopeItem[] = (preferred ?? [])
    .map((id): AssetScopeItem | null => {
      const a = kb.find((x) => x.id === id)
      if (!a) return null
      return enrichAsset({ assetId: a.id, assetType: a.type, role: 'core', source: 'manual' })
    })
    .filter((x): x is AssetScopeItem => x !== null)

  const tokens = extractTokens(text)

  const scored = kb.map((a) => {
    const hay = `${a.id} ${a.name} ${a.desc}`.toLowerCase()
    let score = 0
    if (preferred?.includes(a.id)) score += 10
    for (const tk of tokens) {
      if (hay.includes(tk)) score += 2
    }
    return { a, score }
  })

  const hits = scored
    .filter((x) => x.score > 0)
    .sort((x, y) => y.score - x.score)
    .slice(0, 6)
    .map((x) => x.a)
  return { hits, manual }
}

/** 代码映射对齐：补 file；核心资产补伪代码示意。 */
function enrichAsset(a: AssetScopeItem): AssetScopeItem {
  const cm = CODE_MAPPINGS.find((m) => m.targetId === a.assetId)
  return {
    ...a,
    file: a.file ?? cm?.file,
    keyNode: a.role === 'core'
      ? (a.keyNode ?? `${cm?.file ?? a.assetId} ${cm?.line ?? ''} · 核心逻辑：锁定现状实现后按需求扩展(状态流转/唯一约束/边界校验)`)
      : a.keyNode,
  }
}

type CompleteAnalysis = RequirementAnalysis & { implementationPath: string; changes: ChangeItem[]; steps: RequirementStep[] }

function buildReport(req: KbAnalysisRequest, hits: KbAsset[], manual: AssetScopeItem[]): CompleteAnalysis {
  const core = hits.slice(0, 3)
  const related = hits.slice(3)
  const assetScope: AssetScopeItem[] = [
    ...manual,
    ...core.map((a) => enrichAsset({ assetId: a.id, assetType: a.type, role: 'core' as const, source: 'auto' as const })),
    ...related.map((a) => enrichAsset({ assetId: a.id, assetType: a.type, role: 'related' as const, source: 'auto' as const })),
  ].filter((v, i, arr) => arr.findIndex((x) => x.assetId === v.assetId) === i)

  const primaryNames = core.map((a) => a.name).join('、')
  const affectedNames = assetScope.map((a) => a.assetId).join(', ')

  const changes: ChangeItem[] = core.map((a) => ({
    resource: a.name,
    kind: 'modified',
    before: `当前 ${a.name} 基线实现`,
    after: `扩展以覆盖「${req.title}」`,
  }))

  const steps: RequirementStep[] = [
    {
      id: 'step-1', title: '梳理现状与边界', desc: `检索知识库中 ${primaryNames || '相关资产'} 的现状，确认逻辑边界与不变量`, estMin: 30,
      context: hits.slice(0, 3).map((a) => a.name), files: CODE_MAPPINGS.filter((m) => hits.some((h) => h.id === m.targetId)).slice(0, 2).map((m) => m.file),
    },
    {
      id: 'step-2', title: '核心链路改动', desc: `在 ${primaryNames || '核心资产'} 内实现「${req.title}」主体逻辑，补齐唯一约束与异常路径`, estMin: 120,
      context: core.map((a) => a.name), files: CODE_MAPPINGS.filter((m) => core.some((c) => c.id === m.targetId)).slice(0, 2).map((m) => m.file),
    },
    {
      id: 'step-3', title: '关联资产适配', desc: `联动调整 ${related.map((a) => a.name).join('、') || '关联资产'}，保证跨资产契约一致`, estMin: 90,
      context: related.map((a) => a.name),
    },
    {
      id: 'step-4', title: '测试与验收', desc: '补充单测与集成用例，覆盖幂等/回滚/回调去重等边界，跑通验收清单', estMin: 60,
      context: ['验收标准'],
    },
  ].filter((s) => s.title)

  const feasibilityOk = hits.length > 0 || manual.length > 0
  const coreCount = core.length
  return {
    functionalScope: [req.title, ...hits.map((a) => a.name)],
    entityBoundary: hits.filter((a) => a.type === 'entity' || a.type === 'er' || a.type === 'orm').map((a) => a.name).slice(0, 4),
    feasibility: {
      ok: feasibilityOk,
      reason: feasibilityOk
        ? `知识库命中 ${hits.length} 项资产，实现路径清晰，改动集中在 ${affectedNames || '核心模块'}`
        : '知识库未命中明显资产，需先补充需求上下文',
      estMin: steps.reduce((s, x) => s + x.estMin, 0),
    },
    assessment: buildAssessment(hits.length, coreCount),
    assetScope,
    specsMd: [
      '跨组件调用仅经公开接口(RPC/事件)，禁止直连数据库',
      '涉及的数据资产契约变更需与关联方对齐，保持向后兼容',
      ...(core.some((a) => a.type === 'er' || a.type === 'entity') ? ['新增唯一约束需走统一迁移流程'] : []),
    ].join('\n'),
    implementationPath: `经知识库检索，建议以「${primaryNames || req.title}」为主干：先锁定当前基线实现，随后按「${req.title}」扩展核心资产(${affectedNames || '—'})，再联动关联资产补齐契约，最后以测试验收闭环。`,
    changes,
    steps,
    assessmentSummary: buildSummary(req.title, feasibilityOk, coreCount, hits.length),
  }
}

/** 四维评估的综合结论(TopoCode Agent 的评估 skills 产出，表单仅记录此结论)。 */
function buildSummary(title: string, feasibilityOk: boolean, coreCount: number, hitCount: number): string {
  const parts: string[] = [
    `需求「${title}」评估结论：${feasibilityOk ? '可行，实现路径清晰' : '可行但需补充上下文'}`,
    `知识库命中 ${hitCount} 项资产，涉及 ${coreCount} 项核心修改`,
    coreCount <= 3 ? '可独立交付，与其他需求解耦' : '跨资产较多，建议按需求拆分独立验收',
  ]
  return parts.join('；') + '。'
}

function buildAssessment(hitCount: number, coreCount: number): RequirementAssessment {
  return {
    necessity: { grade: hitCount ? 'high' : 'medium', reason: hitCount ? `命中 ${hitCount} 项数据资产，与核心链路直接相关` : '知识库命中不足，建议先澄清业务背景与价值' },
    atomicity: { independent: coreCount <= 3, reason: coreCount <= 3 ? '核心资产收敛，可独立交付、与其他需求解耦' : '跨核心资产较多，建议拆分为多个可独立验收的需求' },
    acceptability: { ok: true, reason: '可转化为功能用例 + 边界用例进行验收' },
  }
}

/** 多行/逗号分隔 → 数组。 */
function splitList(s?: string): string[] {
  return (s ?? '')
    .split(/[\n,，;；]/)
    .map((x) => x.trim())
    .filter(Boolean)
}

/** 备注分段：标题 + 行。 */
function section(title: string, lines: string[]): string {
  return lines.length ? `【${title}】\n${lines.join('\n')}` : ''
}

/**
 * 基本信息正文(MD)：描述 + 可验收标准 + 功能范围 + 业务实体/边界，
 * 用户作答优先，缺省由报告派生。所有散文并入一个 basicMd 字段。
 */
function buildBasicMd(req: KbAnalysisRequest, report: CompleteAnalysis, answers: Record<string, string>): string {
  const acc = splitList(answers.acceptance)
  const scope = splitList(answers.scope)
  const boundary = splitList(answers.boundary)
  const parts: string[] = [
    section('描述', req.desc.trim() ? req.desc.trim().split('\n') : []),
    section('可验收标准', acc.length ? acc : report.functionalScope.slice(0, 2).map((f) => `${f} 可被验证`)),
    section('功能范围', scope.length ? scope : report.functionalScope),
    section('业务实体/边界', boundary.length ? boundary : report.entityBoundary),
  ]
  return parts.filter(Boolean).join('\n\n')
}

function toFormDraft(req: KbAnalysisRequest, report: CompleteAnalysis, answers: Record<string, string>): FormDraft {
  return {
    title: req.title,
    kind: req.kind ?? 'user-story',
    priority: req.priority,
    tags: [],
    basicMd: buildBasicMd(req, report, answers),
    assetScope: report.assetScope,
    assessmentSummary: report.assessmentSummary ?? '',
    estMin: report.feasibility.estMin ?? 0,
    specsMd: report.specsMd ?? '',
    implementationPath: report.implementationPath,
    report,
  }
}

/** 合并旧报告与新增字段，保证历史数据(缺新字段)也能完整渲染。 */
export function normalizeReport(rep?: RequirementAnalysis): RequirementAnalysis {
  const base = rep ?? {
    functionalScope: [], entityBoundary: [],
    feasibility: { ok: true, reason: '', estMin: 0 }, assetScope: [],
    implementationPath: '', changes: [], steps: [],
  }
  return {
    ...base,
    functionalScope: base.functionalScope ?? [],
    entityBoundary: base.entityBoundary ?? [],
    feasibility: base.feasibility ?? { ok: true, reason: '', estMin: 0 },
    assetScope: base.assetScope ?? [],
    assessment: base.assessment,
    specsMd: base.specsMd ?? '',
    implementationPath: base.implementationPath ?? '',
    changes: base.changes ?? [],
    steps: base.steps ?? [],
    assessmentSummary: base.assessmentSummary ?? '',
  }
}

class MockKnowledgeBaseAgent implements RequirementAnalysisAgent {
  async clarify(req: KbAnalysisRequest): Promise<ClarifyResult> {
    await mockResult(null, 450)
    // greenfield 模式：走领域建模分支
    if (req.mode === 'greenfield') {
      const questions: QuestionItem[] = [
        { key: 'scope', label: '需求的功能范围包含哪些？建议的模块/服务划分？', type: 'text', hint: '如：订单管理、支付、库存…一行一条。' },
        { key: 'boundary', label: '核心业务实体有哪些？', type: 'text', hint: '如 Order、Payment、Product 等业务抽象。' },
        { key: 'flows', label: '核心业务流？', type: 'text', hint: '如：下单流程、支付回调流程、超时关单…' },
        { key: 'acceptance', label: '可验收标准？(至少一条可测试的行为)', type: 'text', hint: '描述可验证的输入/输出与边界行为。' },
      ]
      const turns: KbAnalysisTurn[] = [
        { role: 'user', content: `请基于领域建模思路澄清需求「${req.title}」。\n${req.desc || '(未提供详细描述)'}\n\n当前项目从零开始，暂无既有知识库。` },
        { role: 'assistant', content: '项目从零开始，没有既有知识库可以检索。请描述需求的功能范围和核心业务实体，我会据此给出领域建模建议。', questions },
      ]
      this.record('topocode.kb.domain-model', `领域建模：需求「${req.title}」`)
      return { turns, questions }
    }
    const { hits } = matchAssets(`${req.title} ${req.desc}`, req.preferredAssetIds)
    const options = hits.slice(0, 6).map((h) => h.name)
    const questions: QuestionItem[] = [
      {
        key: 'scope',
        label: '需求的功能范围包含哪些？',
        type: 'text',
        hint: `命中候选：${options.join('、') || '无'}。一行一条或逗号分隔。`,
      },
      {
        key: 'boundary',
        label: '涉及的核心业务实体与逻辑边界？',
        type: 'text',
        hint: '如 Order、OutboxEvent 等业务抽象(非详细代码)。',
      },
      {
        key: 'acceptance',
        label: '可验收标准？(至少一条可测试的行为)',
        type: 'text',
        hint: '描述可验证的输入/输出与边界行为。',
      },
    ]
    const turns: KbAnalysisTurn[] = [
      { role: 'user', content: `请基于知识库澄清需求「${req.title}」。\n${req.desc || '(未提供详细描述)'}` },
      {
        role: 'assistant',
        content: `已检索知识库(命中 ${hits.length} 项资产：${options.join('、') || '—'})。先回答下面几个问题，我会据此生成结果表单草案。`,
        questions,
      },
    ]
    this.record('topocode.kb.clarify', `需求「${req.title}」澄清问题清单 · 命中 ${hits.length} 项资产`)
    return { turns, questions }
  }

  async collect(ctx: { turns: KbAnalysisTurn[]; base: KbAnalysisRequest; answers: Record<string, string>; note?: string }): Promise<CollectResult> {
    await mockResult(null, 500)
    const turns = [...ctx.turns]
    const answered = Object.entries(ctx.answers).filter(([, v]) => v && v.trim())
    if (answered.length) {
      turns.push({ role: 'user', content: answered.map(([k, v]) => `• ${k}: ${v}`).join('\n') })
    }
    if (ctx.note?.trim()) turns.push({ role: 'user', content: ctx.note.trim() })

    // greenfield 模式：不走资产命中，改由 answers 合成建议资产
    if (ctx.base.mode === 'greenfield') {
      const scope = splitList(ctx.answers.scope)
      const boundary = splitList(ctx.answers.boundary)
      const acceptance = splitList(ctx.answers.acceptance)
      const suggestedServices = scope.length ? scope : ['core-service']
      const suggestedEntities = boundary.length ? boundary : ['CoreEntity']
      const assetScope: AssetScopeItem[] = [
        ...suggestedServices.map((s) => ({
          assetId: `p-c-${s.replace(/\s+/g, '-').toLowerCase()}`,
          assetType: 'component' as AssetScopeItem['assetType'],
          role: 'core' as const, source: 'auto' as const,
        })),
        ...suggestedEntities.map((e, idx) => ({
          assetId: `p-entity-${e.replace(/\s+/g, '-').toLowerCase()}`,
          assetType: 'entity' as AssetScopeItem['assetType'],
          role: idx === 0 ? 'core' as const : 'related' as const, source: 'auto' as const,
        })),
      ]
      const primary = suggestedServices[0] ?? '核心服务'
      const basicParts = [
        ctx.base.desc.trim() ? `【描述】\n${ctx.base.desc}` : '',
        acceptance.length ? `【可验收标准】\n${acceptance.join('\n')}` : '',
        scope.length ? `【功能范围】\n${scope.join('\n')}` : '',
        boundary.length ? `【业务实体/边界】\n${boundary.join('\n')}` : '',
      ]
      const report: RequirementAnalysis = {
        functionalScope: scope,
        entityBoundary: boundary,
        feasibility: { ok: true, reason: `建议以「${primary}」为核心模块，覆盖 ${scope.length} 个功能域`, estMin: scope.length * 120 },
        assetScope,
        assessment: { necessity: { grade: 'high', reason: `与核心链路直接相关` }, atomicity: { independent: true, reason: '核心模块收敛' }, acceptability: { ok: true, reason: '可转换为功能用例验收' } },
        assessmentSummary: `需求「${ctx.base.title}」评估结论：可行。建议模块：${suggestedServices.join('、')}。涉及 ${assetScope.length} 项建议资产。`,
        implementationPath: `建议以「${primary}」为主干，实现「${ctx.base.title}」核心逻辑，覆盖建议模块与实体边界。`,
        steps: [{ id: 'gstep-1', title: '领域设计', desc: '细化建议模块的边界与职责', estMin: 60, context: suggestedServices }, { id: 'gstep-2', title: '核心实现', desc: `按蓝图实现「${ctx.base.title}」主体`, estMin: 120, context: suggestedServices }],
      }
      const draft: FormDraft = {
        title: ctx.base.title, kind: ctx.base.kind ?? 'user-story', priority: ctx.base.priority,
        tags: [], basicMd: basicParts.filter(Boolean).join('\n\n'), assetScope,
        assessmentSummary: report.assessmentSummary ?? '', estMin: report.feasibility.estMin,
        specsMd: '跨模块调用仅经公开接口\n建议资产为从零规划，待架构蓝图细化确认',
        implementationPath: report.implementationPath ?? '', report,
      }
      const missingInfo = !answered.length && !ctx.note?.trim()
      if (missingInfo) {
        const questions: QuestionItem[] = [{ key: 'acceptance', label: '请至少补充一条备注信息，将并入备注。', type: 'text', hint: '描述可验证的行为或期望的功能范围。' }]
        turns.push({ role: 'assistant', content: '请补充需求描述后再继续。', questions })
        this.record('topocode.kb.domain-model', `需求「${ctx.base.title}」待补充`)
        return { turns, questions }
      }
      turns.push({ role: 'assistant', content: `已基于需求描述生成领域建模建议草案(覆盖 ${assetScope.length} 项建议资产)。可审阅右栏预览，确认后整份替换当前表单。`, formDraft: draft })
      this.record('topocode.kb.domain-model', `需求「${ctx.base.title}」领域建模草案 · ${assetScope.length} 项建议资产`)
      return { turns, formDraft: draft }
    }

    const { hits, manual } = matchAssets(
      `${ctx.base.title} ${ctx.base.desc} ${ctx.note ?? ''} ${Object.values(ctx.answers).join(' ')}`,
      ctx.base.preferredAssetIds,
    )
    const report = buildReport(ctx.base, hits, manual)
    const draft = toFormDraft(ctx.base, report, ctx.answers)

    const missingInfo = !splitList(ctx.answers.acceptance).length
      && !splitList(ctx.answers.scope).length
      && !splitList(ctx.answers.boundary).length
      && !ctx.note?.trim()
    if (missingInfo) {
      const questions: QuestionItem[] = [{ key: 'acceptance', label: '请至少补充一条备注信息(可验收标准 / 功能范围等)，将并入备注。', type: 'text', hint: '描述可验证的行为或期望的功能范围。' }]
      turns.push({ role: 'assistant', content: '结果表单尚缺备注信息(可验收标准/功能范围)，请补充后再确认。', questions })
      this.record('topocode.kb.collect', `需求「${ctx.base.title}」待补充备注信息`)
      return { turns, questions }
    }

    turns.push({
      role: 'assistant',
      content: `已生成结果表单草案(覆盖 ${draft.assetScope.length} 项数据资产，含四维评估)。请审阅右栏预览，确认后整份替换当前表单；也可以继续补充信息迭代。`,
      formDraft: draft,
    })
    this.record('topocode.kb.collect', `需求「${ctx.base.title}」结果表单草案 · 命中 ${hits.length} 项资产`)
    return { turns, formDraft: draft }
  }

  private record(tool: string, detail: string, method: 'read' | 'invoke' = 'read') {
    const mcp = useArchMcpStore()
    mcp.record({
      id: `kb-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      source: 'topocode-kb',
      tool,
      method,
      time: Date.now(),
      status: 'ok',
      detail,
    })
  }
}

/**
 * 后端优先的 kb 分析 agent：后端不可达时回退本地 mock(MockKnowledgeBaseAgent)。
 * 后端契约见 docs/architect/api-knowledge-greenfield.md §1：
 *   POST /requirements/analyze/clarify  → { turns, questions }
 *   POST /requirements/analyze/collect  → { formDraft? | questions? | report }
 */
class BackendFirstKnowledgeBaseAgent implements RequirementAnalysisAgent {
  private mock = new MockKnowledgeBaseAgent()

  async clarify(req: KbAnalysisRequest): Promise<ClarifyResult> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{ turns: KbAnalysisTurn[]; questions: QuestionItem[] }>('/requirements/analyze/clarify', { req, ...currentProjectParams() })
        if (res.turns?.length && res.questions?.length) return { turns: res.turns, questions: res.questions }
      } catch {
        // fall through to mock
      }
    }
    return this.mock.clarify(req)
  }

  async collect(ctx: { turns: KbAnalysisTurn[]; base: KbAnalysisRequest; answers: Record<string, string>; note?: string }): Promise<CollectResult> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{ formDraft?: FormDraft; questions?: QuestionItem[]; report?: RequirementAnalysis }>(
          '/requirements/analyze/collect',
          { base: ctx.base, answers: ctx.answers, note: ctx.note, ...currentProjectParams() },
        )
        if (res.formDraft) {
          return this.assemble(ctx, res.formDraft)
        }
        if (res.questions?.length) {
          return {
            turns: [...ctx.turns, { role: 'assistant', content: '请补充需求描述后再继续。', questions: res.questions }],
            questions: res.questions,
          }
        }
        if (res.report) {
          const draft = toFormDraft(ctx.base, normalizeReport(res.report) as CompleteAnalysis, ctx.answers)
          return this.assemble(ctx, draft)
        }
      } catch {
        // fall through to mock
      }
    }
    return this.mock.collect(ctx)
  }

  private assemble(ctx: { turns: KbAnalysisTurn[]; base: KbAnalysisRequest; answers: Record<string, string>; note?: string }, draft: FormDraft): CollectResult {
    const turns = [...ctx.turns]
    const answered = Object.entries(ctx.answers).filter(([, v]) => v && v.trim())
    if (answered.length) turns.push({ role: 'user', content: answered.map(([k, v]) => `• ${k}: ${v}`).join('\n') })
    if (ctx.note?.trim()) turns.push({ role: 'user', content: ctx.note.trim() })
    turns.push({
      role: 'assistant',
      content: `已生成结果表单草案(覆盖 ${draft.assetScope.length} 项数据资产，含四维评估)。请审阅右栏预览，确认后整份替换当前表单。`,
      formDraft: draft,
    })
    return { turns, formDraft: draft }
  }
}

export const analysisAgent: RequirementAnalysisAgent = new BackendFirstKnowledgeBaseAgent()
