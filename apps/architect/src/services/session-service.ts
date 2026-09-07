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
  status: string
  tags: SessionTags
  summary: string
  msgCount: number
  preview: string
  firstUserTime?: number
  createdAt?: number
  updatedAt?: number
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
  async list(params?: { kind?: string; q?: string; limit?: number }): Promise<ConversationMeta[]> {
    return apiGet<ConversationMeta[]>(`/sessions${qs(params)}`)
  },
  async groups(): Promise<SessionGroupsInfo> {
    return apiGet<SessionGroupsInfo>('/sessions/groups')
  },
  async saveGroups(groups: string[]): Promise<{ groups: string[] }> {
    return apiPut<{ groups: string[] }>('/sessions/groups', { groups })
  },
  async create(body: { kind: string; title?: string; tags?: SessionTags }): Promise<ConversationMeta> {
    return apiPost<ConversationMeta>('/sessions', body)
  },
  async update(id: string, patch: Partial<Pick<ConversationMeta, 'title' | 'status' | 'summary'> & { tags: SessionTags }>): Promise<ConversationMeta> {
    return apiPatch<ConversationMeta>(`/sessions/${id}`, patch)
  },
  async remove(id: string): Promise<void> {
    await apiDelete(`/sessions/${id}`)
  },
  async messages(id: string): Promise<ConversationDetail> {
    return apiGet<ConversationDetail>(`/sessions/${id}/messages`)
  },
  async summarize(id: string): Promise<ConversationMeta> {
    return apiPost<ConversationMeta>(`/sessions/${id}/summarize`)
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
}
