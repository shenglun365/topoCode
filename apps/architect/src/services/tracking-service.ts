/**
 * 需求跟踪台账 service —— 会话中心左栏「需求跟踪」。
 * 条目 = 工作记录六维度: 谁创建/内容/待谁操作/操作类型/结果/当前状态。
 * 自动挂账在后端事件点完成; 此处承担 手动挂账/流转修正/字典管理/清单读取。
 */
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './api-client'

export interface TrackingItem {
  id: string
  category: string
  title: string
  content: string
  actionType: string
  creatorRole: string            // user | architect | coding
  creatorId?: string
  assigneeRole?: string          // 空 = 无待办
  assigneeId?: string
  state: string                  // running | waiting | done | failed | cancelled
  waitingFor?: string            // state=waiting 时的目标角色
  result?: string
  resultState?: string           // ok | failed | cancelled
  valid: number | boolean        // 0/1(人工作废=0)
  mainConversationId?: string    // 主会话(需求主线)
  conversationId?: string        // 直接(子)会话
  refType?: string
  refId?: string
  projectId?: string
  createdAt?: number
  updatedAt?: number
}

export interface TrackingVocab {
  categories: string[]
  actionTypes: string[]
  roles: string[]
  states: string[]
}

export interface TrackingListParams {
  scope?: string                 // 'all' = 跨全库
  category?: string
  state?: string
  assignee?: string
  q?: string
  limit?: number
}

function qs(params?: Record<string, string | number | undefined>): string {
  if (!params) return ''
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  if (!entries.length) return ''
  return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
}

export const trackingService = {
  async list(params?: TrackingListParams): Promise<{ items: TrackingItem[] }> {
    return apiGet<{ items: TrackingItem[] }>(`/tracking/items${qs({
      scope: params?.scope, category: params?.category, state: params?.state,
      assignee: params?.assignee, q: params?.q, limit: params?.limit,
    })}`)
  },
  async create(body: {
    category?: string; title: string; content?: string; actionType?: string
    assigneeRole?: string; assigneeId?: string; state?: string; waitingFor?: string
    conversationId?: string
  }): Promise<TrackingItem> {
    return apiPost<TrackingItem>('/tracking/items', body)
  },
  async update(id: string, patch: Partial<Pick<TrackingItem,
    'category' | 'title' | 'content' | 'actionType' | 'assigneeRole' | 'assigneeId'
    | 'state' | 'waitingFor' | 'result' | 'resultState' | 'valid'>>): Promise<TrackingItem> {
    return apiPatch<TrackingItem>(`/tracking/items/${id}`, patch)
  },
  async delete(id: string): Promise<{ deleted: boolean; id: string }> {
    return apiDelete<{ deleted: boolean; id: string }>(`/tracking/items/${id}`)
  },
  async vocab(): Promise<TrackingVocab> {
    return apiGet<TrackingVocab>('/tracking/vocab')
  },
  async saveVocab(body: { categories?: string[]; actionTypes?: string[] }): Promise<{ categories: string[]; actionTypes: string[] }> {
    return apiPut('/tracking/vocab', body)
  },
}
