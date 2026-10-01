/**
 * 需求草稿 service（批C）：非会话模式的 AI 辅助需求文本编辑载体。
 * CRUD + 续写副本；AI 处理(批D)/发布(批F)后续批次接入。
 */
import { apiDelete, apiGet, apiPost, apiPut } from '@/services/api-client'
import { currentProjectParams } from '@/services/project-service'

export interface ReqDraft {
  id: string
  projectId: string
  title: string
  contentMd: string
  /** 最近一轮 AI 产物（未采纳保留，仅 UI 参考，不进下轮上下文）。 */
  lastProposedMd: string
  lastProposedAt: number
  status: 'editing' | 'archived'
  parentId: string
  publishedConvId: string
  publishedReqId: string
  createdAt: number
  updatedAt: number
  /** 列表项摘要（不带正文）。 */
  excerpt?: string
}

function ctx(): string {
  const { root, project } = currentProjectParams()
  const qs = new URLSearchParams()
  if (project) qs.set('project', project)
  if (root) qs.set('root', root)
  return qs.toString()
}

export const reqDraftService = {
  async list(): Promise<ReqDraft[]> {
    const c = ctx()
    const r = await apiGet<{ drafts: ReqDraft[] }>(`/req-drafts${c ? `?${c}` : ''}`)
    return r?.drafts ?? []
  },

  async create(payload?: { title?: string; contentMd?: string }): Promise<ReqDraft> {
    const { root, project } = currentProjectParams()
    return apiPost<ReqDraft>('/req-drafts', { root, project, ...payload })
  },

  async get(id: string): Promise<ReqDraft | undefined> {
    return apiGet<ReqDraft>(`/req-drafts/${encodeURIComponent(id)}`)
  },

  async update(id: string, patch: { title?: string; contentMd?: string }): Promise<ReqDraft> {
    return apiPut<ReqDraft>(`/req-drafts/${encodeURIComponent(id)}`, patch)
  },

  async remove(id: string): Promise<void> {
    await apiDelete(`/req-drafts/${encodeURIComponent(id)}`)
  },

  /** 续写：复制为新的 editing 副本（归档草稿继续编写的主路径）。 */
  async copy(id: string): Promise<ReqDraft> {
    const { root, project } = currentProjectParams()
    return apiPost<ReqDraft>(`/req-drafts/${encodeURIComponent(id)}/copy`, { root, project })
  },

  /** 采纳 AI 产物：contentMd ← lastProposedMd 并清空。 */
  async adopt(id: string): Promise<ReqDraft> {
    return apiPost<ReqDraft>(`/req-drafts/${encodeURIComponent(id)}/adopt`, {})
  },

  /** 提交 AI 处理作业（单轮对话+多轮工具；产物写 lastProposedMd，完成后拉取草稿比对）。 */
  async runAi(id: string, payload: { preset: 'generate' | 'review' | 'relate' | 'custom'; instruction?: string }): Promise<{ started: boolean; reason?: string; job?: { id: string; state: string } }> {
    const { root, project } = currentProjectParams()
    return apiPost(`/req-drafts/${encodeURIComponent(id)}/ai`, { root, project, ...payload })
  },
}
