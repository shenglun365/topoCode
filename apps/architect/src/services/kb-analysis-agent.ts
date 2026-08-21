import type {
  FormDraft, QuestionItem, ReqKind, RequirementAnalysis, SemanticAsset,
} from '@/types'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { currentProjectParams } from './project-service'
import { ArchWs } from './ws-client'

/**
 * topocode 知识库 agent 适配接口 —— 需求管理工作区(左栏对话)专用。
 *
 * 显式收集回合协议：
 *   1. clarify   — 依据需求意图返回「待回答问题清单」questions
 *   2. collect   — 用户作答(answers / 自由补充 note)后，收敛为「结果表单草案」formDraft
 *                  (若仍缺关键信息，可再返回一轮 questions)
 *   3. 用户确认 formDraft → 「整份替换」右栏表单；可多轮迭代
 *
 * 全部由后端(LLM 驱动)处理；后端调用失败向上抛出——不复用本地 mock。
 */
export interface KbAnalysisTurn {
  role: 'user' | 'assistant'
  content: string
  /** 推理内容(thinking)：独立于正文，前端可折叠展示。 */
  reasoning?: string
  questions?: QuestionItem[]
  formDraft?: FormDraft
  /** 语义数据资产卡片(提取/检索结果，供对话确认)。 */
  assets?: SemanticAsset[]
  /** 后端持久化消息 id(对话流单条删除用)。 */
  id?: string
}

export interface KbAnalysisRequest {
  title: string
  desc: string
  priority: 'P0' | 'P1' | 'P2'
  kind?: ReqKind
  preferredAssetIds?: string[]
  /** greenfield 模式：空 KB 不走 matchAssets，走领域建模分支。 */
  mode?: 'greenfield' | 'existing'
  /** 本次对话选择的模型：透传后端 llm.sync(空则回退全局偏好/主后端默认)。 */
  modelId?: string
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

/** 自由对话流式事件(阶段A)：逐字增量 + 推理内容 + 回合结束。 */
export interface ChatStreamEvent {
  type: 'chunk' | 'reasoning' | 'done' | 'error' | 'chat_fallback' | 'chat_start'
  delta?: string
  content?: string
  message?: string
  conversationId?: string
  /** 本回合用户消息 id(chat_start 携带)。 */
  userMessageId?: string
  /** 本回合助手消息 id(done 携带)。 */
  messageId?: string
}

export interface ChatStreamOptions {
  /** 沿用已有会话(续聊)时传入；缺省后端新建。 */
  conversationId?: string
  /** 会话归类(requirement/design/...)，阶段D 统一表 kind。 */
  kind?: string
  /** 关联需求 id。 */
  reqId?: string
  title?: string
  modelId?: string
  /** 绘图增强(IR→代码)：开启后后端注入 diagram.build/validate 工具文档。 */
  diagramSkill?: boolean
  /** 是否有流式通道可用(后端不可达/未启用时回退一次性回复)。 */
  signal?: AbortSignal
}

/**
 * 需求分析自由对话(流式)。经 WS `/ws/kb-analysis` 与后端 KB agent 逐字对话；
 * 事件经回调推送。返回最终完整文本(供调用方兜底渲染)。
 */
export async function chatStream(
  messages: { role: 'user' | 'assistant'; content: string }[],
  opts: ChatStreamOptions,
  onEvent: (ev: ChatStreamEvent) => void,
): Promise<string> {
  const ws = new ArchWs('ws/kb-analysis')
  await ws.ready()
  let full = ''
  let settled = false

  const finish = () => {
    if (settled) return
    settled = true
    ws.close()
  }

  try {
    const doneP = new Promise<string>((resolve, reject) => {
      ws.on('chat_start', (ev: any) => {
        onEvent({ type: 'chat_start', conversationId: ev?.conversationId, userMessageId: ev?.userMessageId })
      })
      ws.on('chunk', (ev: any) => {
        const delta = ev?.delta ?? ''
        if (delta) {
          full += delta
          onEvent({ type: 'chunk', delta, conversationId: ev?.conversationId })
        }
      })
      ws.on('reasoning', (ev: any) => {
        const delta = ev?.delta ?? ''
        if (delta) onEvent({ type: 'reasoning', delta, conversationId: ev?.conversationId })
      })
      ws.on('done', (ev: any) => {
        const content = ev?.content ?? full
        full = content
        onEvent({ type: 'done', content, conversationId: ev?.conversationId, messageId: ev?.messageId })
        finish()
        resolve(content)
      })
      ws.on('chat_fallback', (ev: any) => {
        onEvent({ type: 'chat_fallback', conversationId: ev?.conversationId })
      })
      ws.on('error', (ev: any) => {
        onEvent({ type: 'error', message: ev?.message, conversationId: ev?.conversationId })
        finish()
        reject(new Error(ev?.message || '对话失败'))
      })
    })

    ws.send('chat', {
      messages,
      ...currentProjectParams(),
      conversationId: opts.conversationId,
      kind: opts.kind ?? 'requirement',
      reqId: opts.reqId,
      title: opts.title,
      modelId: opts.modelId,
      diagramSkill: opts.diagramSkill,
    })

    return await doneP
  } finally {
    finish()
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
 * 基本信息正文(MD)：描述 + 可验收标准 + 功能范围 + 业务实体边界。
 * 用户作答优先，缺省由报告派生。所有散文并入一个 basicMd 字段。
 */
function buildBasicMd(req: KbAnalysisRequest, report: Required<Pick<RequirementAnalysis, 'functionalScope' | 'entityBoundary'>>, answers: Record<string, string>): string {
  const acc = splitList(answers.acceptance)
  const scope = splitList(answers.scope)
  const boundary = splitList(answers.boundary)
  const parts: string[] = [
    section('描述', req.desc.trim() ? req.desc.trim().split('\n') : []),
    section('可验收标准', acc.length ? acc : report.functionalScope.slice(0, 2).map((f) => `${f} 可被验证`)),
    section('功能范围', scope.length ? scope : report.functionalScope),
    section('业务实体/边界', boundary.length ? boundary : report.entityBoundary.slice(0, 4)),
  ]
  return parts.filter(Boolean).join('\n\n')
}

function toFormDraft(req: KbAnalysisRequest, report: RequirementAnalysis, answers: Record<string, string>): FormDraft {
  const r = report as RequirementAnalysis
  return {
    title: req.title,
    kind: req.kind ?? 'user-story',
    priority: req.priority,
    tags: [],
    basicMd: buildBasicMd(req, r, answers),
    assetScope: r.assetScope ?? [],
    assessmentSummary: r.assessmentSummary ?? '',
    estMin: r.feasibility?.estMin ?? 0,
    specsMd: r.specsMd ?? '',
    implementationPath: r.implementationPath ?? '',
    report: r,
  }
}

/**
 * 后端驱动的 kb 分析 agent：后端不可达或调用出错时向上抛错(不再回退本地 mock)。
 * 后端契约见 docs/architect/api-knowledge-greenfield.md §1：
 *   POST /requirements/analyze/clarify  → { turns, questions }
 *   POST /requirements/analyze/collect  → { formDraft? | questions? | report }
 */
class BackendKnowledgeBaseAgent implements RequirementAnalysisAgent {
  async clarify(req: KbAnalysisRequest): Promise<ClarifyResult> {
    if (!(await backendUp())) throw new Error('后端不可达，无法进行需求澄清')
    try {
      const res = await apiPost<{ turns: KbAnalysisTurn[]; questions: QuestionItem[] }>(
        '/requirements/analyze/clarify',
        { req, ...currentProjectParams() },
      )
      if (!res.turns?.length || !res.questions?.length) throw new Error('后端未返回澄清问题清单')
      return { turns: res.turns, questions: res.questions }
    } catch (err) {
      throw err
    }
  }

  async collect(ctx: { turns: KbAnalysisTurn[]; base: KbAnalysisRequest; answers: Record<string, string>; note?: string }): Promise<CollectResult> {
    if (!(await backendUp())) throw new Error('后端不可达，无法收敛需求结果')
    try {
      const res = await apiPost<{
        formDraft?: FormDraft; questions?: QuestionItem[]; report?: RequirementAnalysis; reply?: string
      }>(
        '/requirements/analyze/collect',
        { base: ctx.base, answers: ctx.answers, note: ctx.note, ...currentProjectParams() },
      )
      if (res.formDraft) return this.assemble(ctx, res.formDraft, res.reply)
      if (res.questions?.length) {
        return {
          turns: [...ctx.turns, { role: 'assistant', content: '请补充需求描述后再继续。', questions: res.questions }],
          questions: res.questions,
        }
      }
      if (res.report) {
        const draft = toFormDraft(ctx.base, normalizeReport(res.report), ctx.answers)
        return this.assemble(ctx, draft, res.reply)
      }
      throw new Error('后端未返回结果表单草案')
    } catch (err) {
      throw err
    }
  }

  private assemble(ctx: { turns: KbAnalysisTurn[]; base: KbAnalysisRequest; answers: Record<string, string>; note?: string }, draft: FormDraft, reply?: string): CollectResult {
    const turns = [...ctx.turns]
    const answered = Object.entries(ctx.answers).filter(([, v]) => v && v.trim())
    if (answered.length) turns.push({ role: 'user', content: answered.map(([k, v]) => `• ${k}: ${v}`).join('\n') })
    if (ctx.note?.trim()) turns.push({ role: 'user', content: ctx.note.trim() })
    turns.push({
      role: 'assistant',
      content: reply?.trim() || `已生成结果表单草案(覆盖 ${draft.assetScope.length} 项数据资产，含四维评估)。请审阅右侧预览，确认后替换当前表单。`,
      formDraft: draft,
    })
    return { turns, formDraft: draft }
  }
}

export const analysisAgent: RequirementAnalysisAgent = new BackendKnowledgeBaseAgent()