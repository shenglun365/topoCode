/**
 * 会话中心 service(P1) —— 会话是唯一主体。
 * 裁决对齐: 无流程实体；分类=元数据(标题/时间/模块/自定义分组)；备案文档随时提取。
 */
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './api-client'

export interface SessionTags {
  modules: string[]
  groups: string[]
}

export interface ConversationMeta {
  id: string
  kind: string
  reqId: string
  title: string
  /** 生命周期: active | running | archived(不可逆) */
  status: string
  /** 查看状态: read | unread | awaiting_reply | error */
  reviewState?: string
  /** 流程相位(governance/flow.py 派生缓存): free|clarifying|armed|executing|reviewing|interrupted */
  flowState?: string
  /** 执行角色(默认 architect) */
  /** 工作相位: architect(常态) | running(外调作业执行中) */
  workState?: 'architect' | 'running'
  /** 分析挡位: strict(需求分析→规约→任务) | quick(轻整理直出任务卡)。缺省 strict。 */
  analysisMode?: 'strict' | 'quick'
  /** 角色集(能力声明; architect 恒在) */
  roles?: string[]
  tags: SessionTags
  summary: string
  msgCount: number
  preview: string
  firstUserTime?: number
  createdAt?: number
  updatedAt?: number
  /** 归属项目(scope=all 跨库列表用于能力提案等项目级操作)。 */
  projectId?: string
}

export interface ConversationDetail {
  id: string
  kind?: string
  reqId?: string
  title?: string
  messages: { id?: string; role: 'user' | 'assistant'; content: string }[]
}

export interface SessionGroupsInfo {
  groups: string[]
  modules: string[]
}

export interface ContextUnit {
  id: string
  type: string
  title: string
  content: string
  importance: number
  createdAt?: number
}

/** 会话知识单元(K2 沉淀): /units 投影行(跨会话列示时带 conversationId)。 */
export interface SessionUnit {
  id: string
  conversationId?: string
  projectId?: string
  type: string
  title: string
  content: string
  refs?: Record<string, unknown>
  importance?: number
  createdAt?: number
}

export interface SessionDoc {
  id: string
  conversationId: string
  type: string
  title: string
  contentMd: string
  refs?: Record<string, unknown>
  createdAt?: number
  updatedAt?: number
}

function qs(params?: Record<string, string | number | undefined>): string {
  if (!params) return ''
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  if (!entries.length) return ''
  return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
}

export const sessionService = {
  async list(params?: { kind?: string; q?: string; limit?: number; scope?: string; project?: string }): Promise<ConversationMeta[]> {
    return apiGet<ConversationMeta[]>(`/sessions${qs(params)}`)
  },
  async groups(scope?: string, project?: string): Promise<SessionGroupsInfo> {
    const p = new URLSearchParams()
    if (scope) p.set('scope', scope)
    if (project) p.set('project', project)
    const q = p.toString()
    return apiGet<SessionGroupsInfo>(`/sessions/groups${q ? `?${q}` : ''}`)
  },
  async saveGroups(groups: string[]): Promise<{ groups: string[] }> {
    return apiPut<{ groups: string[] }>('/sessions/groups', { groups })
  },
  async create(body: { kind: string; title?: string; tags?: SessionTags }): Promise<ConversationMeta> {
    return apiPost<ConversationMeta>('/sessions', body)
  },
  async update(id: string, patch: Partial<Pick<ConversationMeta, 'title' | 'status' | 'summary' | 'reviewState' | 'roles'> & { tags: SessionTags }>): Promise<ConversationMeta> {
    return apiPatch<ConversationMeta>(`/sessions/${id}`, patch)
  },
  async remove(id: string): Promise<void> {
    await apiDelete(`/sessions/${id}`)
  },
  async messages(id: string): Promise<ConversationDetail> {
    return apiGet<ConversationDetail>(`/sessions/${id}/messages`)
  },
  /** 指令引导(按需 agent 建议)：基于会话状态生成; fallback=true 时前端用静态文案。 */
  async guide(id: string): Promise<{ text: string; fallback?: boolean }> {
    return apiPost<{ text: string; fallback?: boolean }>(`/sessions/${id}/guide`)
  },
  /** force=1: 用户显式触发自动摘要(总是重生成标题); 缺省(系统自动)尊重手改标题。 */
  async summarize(id: string, force = false): Promise<ConversationMeta> {
    return apiPost<ConversationMeta>(`/sessions/${id}/summarize${force ? '?force=1' : ''}`)
  },
  async context(id: string): Promise<ContextUnit[]> {
    return apiGet<ContextUnit[]>(`/sessions/${id}/context`)
  },
  // ── 知识单元(知识资产) ──
  /** convId 缺省 + scope=all → 跨全库汇总(会话中心左栏统一视图, 条目带 conversationId)。 */
  async units(params?: { convId?: string; type?: string; q?: string; scope?: string; limit?: number }): Promise<{ units: SessionUnit[] }> {
    const p = new URLSearchParams()
    if (params?.convId) p.set('convId', params.convId)
    if (params?.type) p.set('type', params.type)
    if (params?.q?.trim()) p.set('q', params.q.trim())
    if (params?.scope) p.set('scope', params.scope)
    p.set('limit', String(params?.limit ?? 200))
    return apiGet<{ units: SessionUnit[] }>(`/units?${p.toString()}`)
  },
  async removeUnit(unitId: string): Promise<void> {
    await apiDelete(`/units/${unitId}`)
  },
  /** 会话大纲条目标题语义缩略(批量按需补算; 结果由前端 outline-cache 缓存)。 */
  async abbreviateOutline(items: { id: string; text: string }[]): Promise<{ items: { id: string; short: string; degraded?: boolean }[]; degraded?: boolean }> {
    return apiPost<{ items: { id: string; short: string; degraded?: boolean }[]; degraded?: boolean }>(
      '/sessions/outline/abbreviate', { items: items.slice(0, 20) })
  },
  // ── 备案文档 ──
  async docs(conversationId?: string): Promise<SessionDoc[]> {
    return apiGet<SessionDoc[]>(`/session-docs${qs({ conversation_id: conversationId })}`)
  },
  async docFromConversation(conversationId: string, title?: string): Promise<SessionDoc> {
    return apiPost<SessionDoc>(`/session-docs/from-conversation/${conversationId}`, { title: title || '' })
  },
  async updateDoc(id: string, patch: Partial<Pick<SessionDoc, 'title' | 'contentMd'>>): Promise<SessionDoc> {
    return apiPatch<SessionDoc>(`/session-docs/${id}`, patch)
  },
  async removeDoc(id: string): Promise<void> {
    await apiDelete(`/session-docs/${id}`)
  },
  // ── 开发简报(P4) ──
  async generateDigest(sinceDays = 7): Promise<SessionDoc> {
    return apiPost<SessionDoc>('/digest', { sinceDays })
  },
  async digests(limit = 10): Promise<DigestInfo[]> {
    return apiGet<DigestInfo[]>(`/digest?limit=${limit}`)
  },
}

export interface DigestEntry {
  type: 'exec' | 'session' | 'doc'
  execId?: string
  conversationId?: string
  docId?: string
  title: string
  summary?: string
  branch?: string
  commit?: string
  landedAt?: number
}

export interface DigestInfo {
  id: string
  title: string
  contentMd: string
  refs?: { entries?: DigestEntry[]; sinceDays?: number; generatedAt?: number }
  createdAt?: number
  updatedAt?: number
}
