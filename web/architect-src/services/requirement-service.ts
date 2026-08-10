import type { ConversationDetail, ConversationSummary, Requirement } from '@/types'
import { apiDelete, apiGet, apiPatch, apiPost } from './api-client'
import { currentProjectParams } from './project-service'

export const requirementService = {
  async list(): Promise<Requirement[]> {
    return apiGet<Requirement[]>('/requirements')
  },
  async create(data: Partial<Requirement>): Promise<Requirement> {
    return apiPost<Requirement>('/requirements', data)
  },
  async update(id: string, data: Partial<Requirement>): Promise<Requirement> {
    return apiPatch<Requirement>(`/requirements/${id}`, data)
  },
  /** 历史会话摘要(仅临时/未绑定提案)。 */
  async conversations(): Promise<ConversationSummary[]> {
    const { project } = currentProjectParams()
    const qs = project ? `?project=${encodeURIComponent(project)}` : ''
    return apiGet<ConversationSummary[]>(`/requirements/conversations${qs}`)
  },
  /** 按会话 id 拉取详情+消息(导入)。 */
  async conversation(id: string): Promise<ConversationDetail> {
    return apiGet<ConversationDetail>(`/requirements/conversations/${id}`)
  },
  /** 按正式提案 id 拉取其历史会话(自动导入)。 */
  async conversationByReq(reqId: string): Promise<ConversationDetail | null> {
    const { project } = currentProjectParams()
    const qs = project ? `?project=${encodeURIComponent(project)}` : ''
    return apiGet<ConversationDetail | null>(`/requirements/conversations/by-req/${encodeURIComponent(reqId)}${qs}`)
  },
  /** 删除临时会话。 */
  async deleteConversation(id: string): Promise<{ deleted: boolean; id: string }> {
    return apiDelete<{ deleted: boolean; id: string }>(`/requirements/conversations/${id}`)
  },
  /** 删除会话内单条消息(对话流单条删除)。 */
  async deleteMessage(convId: string, messageId: string): Promise<{ deleted: boolean; id: string }> {
    return apiDelete<{ deleted: boolean; id: string }>(`/requirements/conversations/${convId}/messages/${messageId}`)
  },
  /** 绑定临时会话到正式提案(保存/入池后 rebind req_id)。 */
  async bindConversation(id: string, reqId: string, title?: string): Promise<ConversationDetail | null> {
    const data: { reqId: string; title?: string } = { reqId }
    if (title) data.title = title
    return apiPatch<ConversationDetail>(`/requirements/conversations/${id}`, data)
  },
}
