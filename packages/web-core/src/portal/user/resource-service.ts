/** 用户中心（基础服务）资源服务 —— 自 workbench 迁入，走统一网关 /topoapi */
import type { Resource, ResourceListMeta } from './types'
import { request, API_BASE } from '../../utils/http'

export interface ResourceListResult {
  total: number
  page: number
  page_size: number
  meta: ResourceListMeta
  items: Resource[]
}

function addPricingDefaults(r: any): Resource {
  return {
    ...r,
    pricing_model: r.pricing_model || 'free',
    points_cost: r.points_cost ?? 0,
    price_cny: r.price_cny ?? 0,
    subscription_tier: r.subscription_tier || '',
  }
}

function defaultMeta(): ResourceListMeta {
  return {
    _version: '0',
    categories: [],
    styles: {},
    feature_flags: {},
    labels: {},
  }
}

export const resourceService = {
  async list(params?: { page?: number; category?: string; owned?: boolean; token?: string; q?: string; sort_by?: string; sort_order?: string }): Promise<ResourceListResult> {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.category) q.set('category', params.category)
    if (params?.owned) q.set('owned', 'true')
    if (params?.q) q.set('q', params.q)
    if (params?.sort_by) q.set('sort_by', params.sort_by)
    if (params?.sort_order) q.set('sort_order', params.sort_order)

    const result = await request<{
      total: number; page: number; page_size: number; meta: ResourceListMeta; items: any[]
    }>(`/topoapi/resources?${q}`)
    return {
      total: result.total,
      page: result.page,
      page_size: result.page_size,
      meta: result.meta || defaultMeta(),
      items: (result.items || []).map(addPricingDefaults),
    }
  },

  async detail(id: number, token?: string): Promise<Resource> {
    const result = await request<any>(`/topoapi/resources/${id}`)
    return addPricingDefaults(result)
  },

  async getDownloadUrl(id: number, token: string): Promise<string> {
    const res = await request<{ redirect_url: string; oss_url?: string }>(
      `/topoapi/resources/${id}/download`,
      { method: 'POST' },
    )
    return res.oss_url || `${API_BASE}${res.redirect_url}`
  },

  async getDownloadInfo(id: number): Promise<{ redirect_url: string; oss_url?: string; expires_at?: string }> {
    return request<{ redirect_url: string; oss_url?: string; expires_at?: string }>(
      `/topoapi/resources/${id}/download`,
      { method: 'POST' },
    )
  },

  async getImportStatus(importId: string): Promise<{ status: string; progress: number; message: string; result?: { projectId: string; projectName: string } }> {
    const result = await (window.api as any)?.system?.importStatus?.(importId)
    return result || { status: '', progress: 0, message: '' }
  },

  async vote(resourceId: number, vote: number): Promise<{ like_count: number; dislike_count: number }> {
    return request<any>(
      `/topoapi/resources/${resourceId}/vote`,
      { method: 'POST', body: JSON.stringify({ vote }) },
    )
  },

  async createComment(resourceId: number, content: string): Promise<{ id: number; content: string }> {
    return request<any>(
      `/topoapi/resources/${resourceId}/comments`,
      { method: 'POST', body: JSON.stringify({ content }) },
    )
  },
}
