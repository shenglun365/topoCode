import type {
  FormDraft, QuestionItem, ReqKind, RequirementAnalysis, SemanticAsset,
} from '@/types'
import type { AcceptanceReportDetail, ContractItem } from './contract-service'
import type { NamingConvention } from './naming-service'
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
/** 消息级阶段标注(WS2): 由工具调用隐式推导，仅作过滤/回溯视角，不约束流转。 */
export type ChatStage = 'design' | 'implement' | 'evaluate' | 'accept'

/** 工具名 → 阶段推导(前向兼容: WS3+ 的 coding.task / evaluate / acceptance 工具落地即生效)。 */
export function stageOfTool(tool: string): ChatStage | '' {
  const t = tool || ''
  if (/^probe\.run$|^coding\.task\.plan/.test(t)) return 'design'
  if (/^coding\.task\.|^execution\./.test(t)) return 'implement'
  if (/^capability\.evaluate$|^evaluate\./.test(t)) return 'evaluate'
  if (/^acceptance\.|^contract\.propose$/.test(t)) return 'accept'
  return ''
}

export interface KbAnalysisTurn {
  role: 'user' | 'assistant'
  content: string
  /** 阶段标注(设计/实现/评估/验收)：本回合内工具调用推导。 */
  stage?: ChatStage
  /** 推理内容(thinking)：独立于正文，前端可折叠展示。 */
  reasoning?: string
  questions?: QuestionItem[]
  formDraft?: FormDraft
  /** 消息级元数据(作业事件标记等: {jobId, kind, branch}) */
  meta?: Record<string, any>
  /** 语义数据资产卡片(提取/检索结果，供对话确认)。 */
  assets?: SemanticAsset[]
  /** 契约条目固化卡(方案对话 🧾 固化产出，逐条确认/修改/删)。 */
  contracts?: ContractItem[]
  /** 命名规约归纳提议卡(agent 检测命名模式 → pending 提案，确认固化/忽略)。 */
  conventions?: NamingConvention[]
  /** 差异报告通知卡(验收触发后：L1/L2 通过率 + L3 待人工 + 前三差异摘要 + 前往验收)。 */
  acceptance?: AcceptanceReportDetail
  /** 需求提案卡(资产地图对话 req.propose 产出：需求+方案+评估 → 提交需求方案)。 */
  proposal?: { id: string; title: string; desc: string; priority: string; analysis?: Record<string, any>; confirmed?: boolean }
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
  /** 消息级元数据(作业事件标记等: {jobId, kind, branch}) */
  meta?: Record<string, any>
}

export interface RequirementAnalysisAgent {
  clarify(req: KbAnalysisRequest): Promise<ClarifyResult>
  collect(ctx: { turns: KbAnalysisTurn[]; base: KbAnalysisRequest; answers: Record<string, string>; note?: string }): Promise<CollectResult>
}

/** 自由对话流式事件(阶段A)：逐字增量 + 推理内容 + 回合结束。 */
export interface ChatStreamEvent {
  type: 'chunk' | 'reasoning' | 'done' | 'error' | 'chat_fallback' | 'chat_start'
    | 'tool_call' | 'tool_result' | 'status'
  delta?: string
  content?: string
  message?: string
  conversationId?: string
  /** 本回合用户消息 id(chat_start 携带)。 */
  userMessageId?: string
  /** 本回合助手消息 id(done 携带)。 */
  messageId?: string
  /** 本回合助手消息元数据(done 携带, 如守卫标记 meta.guard)。 */
  meta?: Record<string, any>
  /** 工具进度(tool_call/tool_result)：工具名。 */
  tool?: string
  /** 工具进度(tool_result)：执行是否成功。 */
  ok?: boolean
  /** 工具进度(tool_result)：结果摘要(截断)。 */
  summary?: string
  /** 工具进度(tool_result)：资产卡引用(评估报告等, 点击联动资产地图)。 */
  assets?: Array<{ id: string; name: string; kind: string; level?: string; file?: string; status?: string }>
  /** 相位事件(status)：sync=降级同步通道 / sync_llm=降级通道 LLM 第 N 轮 /
   *  sync_tool=降级通道执行工具 / llm_round=工具回喂后再生成。 */
  phase?: string
  round?: number
  idx?: number
  total?: number
}

export interface ChatStreamOptions {
  /** 沿用已有会话(续聊)时传入；缺省后端新建。 */
  conversationId?: string
  /** 会话归类(requirement/asset/design/...)，阶段D 统一表 kind——首条消息创建会话时落库。 */
  kind?: string
  /** 关联需求 id。 */
  reqId?: string
  title?: string
  modelId?: string
  /** 绘图增强(IR→代码)：开启后后端注入 diagram.build/validate 工具文档。 */
  diagramSkill?: boolean
  /** 语义资产 skill 场景（plan-C §4.1 按场景加载）：资产管理对话传 ['extract']。 */
  skillScenarios?: string[]
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
  if (opts.signal?.aborted) { ws.close(); return '' }
  await ws.ready()
  let full = ''
  let settled = false

  const finish = () => {
    if (settled) return
    settled = true
    ws.close()
  }

  try {
    let resolveDone!: (s: string) => void
    let rejectDone!: (e: Error) => void
    const doneP = new Promise<string>((res, rej) => { resolveDone = res; rejectDone = rej })

    // 终止：signal abort → 关 WS(后端随之中断) + 以已收部分文本收口(不报错)
    if (opts.signal) {
      const onAbort = () => { if (!settled) { settled = true; ws.close(); resolveDone(full) } }
      opts.signal.addEventListener('abort', onAbort, { once: true })
    }

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
      onEvent({ type: 'done', content, conversationId: ev?.conversationId,
                messageId: ev?.messageId, meta: ev?.meta })
      finish()
      resolveDone(content)
    })
    ws.on('chat_fallback', (ev: any) => {
      onEvent({ type: 'chat_fallback', conversationId: ev?.conversationId })
    })
    ws.on('tool_call', (ev: any) => {
      onEvent({ type: 'tool_call', tool: ev?.tool, conversationId: ev?.conversationId })
    })
    ws.on('tool_result', (ev: any) => {
      onEvent({
        type: 'tool_result', tool: ev?.tool, ok: ev?.ok, summary: ev?.summary,
        conversationId: ev?.conversationId,
        assets: Array.isArray(ev?.assets) ? ev.assets : undefined,
      })
    })
    ws.on('status', (ev: any) => {
      onEvent({
        type: 'status', phase: ev?.phase, round: ev?.round,
        tool: ev?.tool, idx: ev?.idx, total: ev?.total, message: ev?.message,
        conversationId: ev?.conversationId,
      })
    })
    ws.on('error', (ev: any) => {
      onEvent({ type: 'error', message: ev?.message, conversationId: ev?.conversationId })
      finish()
      rejectDone(new Error(ev?.message || '对话失败'))
    })

    ws.send('chat', {
      messages,
      ...currentProjectParams(),
      conversationId: opts.conversationId,
      kind: opts.kind,
      reqId: opts.reqId,
      title: opts.title,
      modelId: opts.modelId,
      diagramSkill: opts.diagramSkill,
      skillScenarios: opts.skillScenarios,
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