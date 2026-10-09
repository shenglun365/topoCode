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
  /** 用户自定义标签(概念泛化后分类用; ≤20 个/个 ≤64B)。 */
  tags?: string[]
  /** 来源会话(会话→草稿回流); 空串=无来源。 */
  sourceConvId?: string
  /** 来源形态: turn(回合)|spec(规约)|receipt(执行回执)。 */
  sourceKind?: string
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

  async create(payload?: { title?: string; contentMd?: string;
                           sourceConvId?: string; sourceKind?: string }): Promise<ReqDraft> {
    const { root, project } = currentProjectParams()
    return apiPost<ReqDraft>('/req-drafts', { root, project, ...payload })
  },

  async get(id: string): Promise<ReqDraft | undefined> {
    return apiGet<ReqDraft>(`/req-drafts/${encodeURIComponent(id)}`)
  },

  async update(id: string, patch: { title?: string; contentMd?: string; tags?: string[] }): Promise<ReqDraft> {
    return apiPut<ReqDraft>(`/req-drafts/${encodeURIComponent(id)}`, patch)
  },

  async remove(id: string): Promise<void> {
    await apiDelete(`/req-drafts/${encodeURIComponent(id)}`)
  },

  /** 项目内 tag 全集(联想备选): 去重计数按引用数降序。 */
  async allTags(): Promise<{ name: string; count: number }[]> {
    const c = ctx()
    const r = await apiGet<{ tags: { name: string; count: number }[] }>(`/req-drafts-tags${c ? `?${c}` : ''}`)
    return r?.tags ?? []
  },

  /** 续写：复制为新的 editing 副本（归档草稿继续编写的主路径）。 */
  async copy(id: string): Promise<ReqDraft> {
    const { root, project } = currentProjectParams()
    return apiPost<ReqDraft>(`/req-drafts/${encodeURIComponent(id)}/copy`, { root, project })
  },

  /** 发布草稿为需求卡：{targetConvId?, overwrite?}——未完结需求卡覆盖冲突 409。 */
  async publish(id: string, payload: { targetConvId?: string; overwrite?: boolean }): Promise<{ draft: ReqDraft; convId: string; requirementId: string; amended: boolean }> {
    const { root, project } = currentProjectParams()
    return apiPost(`/req-drafts/${encodeURIComponent(id)}/publish`, { root, project, ...payload })
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
