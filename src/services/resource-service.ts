import type { Resource, ResourceListMeta } from '@/types'
import { getDeviceId } from '@/utils/device-id'
import { mockResources } from '@/utils/mock'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const USE_MOCK = (import.meta.env.DEV || !window.navigator.onLine) && !import.meta.env.VITE_DISABLE_MOCK

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
}

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

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Device-Id': getDeviceId(),
  }
  const existingHeaders = (options.headers as Record<string, string>) || {}
  Object.assign(headers, existingHeaders)
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.message || `HTTP ${res.status}`)
  }
  const json: ApiResponse<T> = await res.json()
  if (!json.success) {
    throw new Error(json.message || '请求失败')
  }
  return json.data
}

function delay(ms = 300): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}

const MOCK_META: ResourceListMeta = {
  _version: '1',
  categories: [
    { key: '', label: '全部' },
    { key: '微服务', label: '微服务', color: '#6366f1' },
    { key: '前端', label: '前端', color: '#3b82f6' },
    { key: '云原生', label: '云原生', color: '#06b6d4' },
    { key: 'AI', label: 'AI', color: '#8b5cf6' },
    { key: '游戏', label: '游戏', color: '#ec4899' },
    { key: '已购', label: '已购资源', color: '#22c55e', scope: 'owned', auth_required: true },
  ],
  styles: {
    '--rc-card-radius': '8px',
    '--rc-card-shadow': '0 2px 8px rgba(0,0,0,0.1)',
    '--rc-card-thumb-h': '100px',
    '--rc-card-gap': '12px',
    '--rc-card-max-w': '220px',
    '--rc-detail-max-w': '500px',
  },
  feature_flags: {
    show_download_count: true,
    show_category_filter: true,
  },
  labels: {
    download: '下载',
    re_download: '重新下载',
    points_exchange: '{cost} 积分兑换',
    points_insufficient: '积分不足（需 {cost}）',
    free: '免费',
    download_count: '下载量',
    publish_date: '发布时间',
    close: '关闭',
    login_hint: '登录后可下载资源',
  },
}

export const resourceService = {
  async list(params?: { page?: number; category?: string; owned?: boolean; token?: string }): Promise<ResourceListResult> {
    if (USE_MOCK) {
      await delay()
      let items = [...mockResources].map(addPricingDefaults) as Resource[]
      if (params?.category) {
        items = items.filter(r => r.category === params.category)
      }
      const page = params?.page || 1
      const pageSize = 12
      const start = (page - 1) * pageSize
      return {
        total: items.length,
        page,
        page_size: pageSize,
        meta: MOCK_META,
        items: items.slice(start, start + pageSize).map(r => ({
          ...r,
          theme: { color: undefined, badge_text: null, badge_style: null, featured: false, icon_url: null, owned: false },
        })),
      }
    }
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.category) q.set('category', params.category)
    if (params?.owned) q.set('owned', 'true')

    const headers: Record<string, string> = {}
    if (params?.token) {
      headers['Authorization'] = `Bearer ${params.token}`
    }

    const result = await request<{
      total: number; page: number; page_size: number; meta: ResourceListMeta; items: any[]
    }>(`/topoapi/resources?${q}`, { headers })
    return {
      total: result.total,
      page: result.page,
      page_size: result.page_size,
      meta: result.meta || defaultMeta(),
      items: (result.items || []).map(addPricingDefaults),
    }
  },

  async detail(id: number, token?: string): Promise<Resource> {
    if (USE_MOCK) {
      await delay()
      const item = (mockResources as Resource[]).find(r => r.id === id)
      if (!item) throw new Error('资源不存在')
      return {
        ...addPricingDefaults(item),
        theme: { color: undefined, badge_text: null, badge_style: null, featured: false, icon_url: null, owned: false },
      }
    }
    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    const result = await request<any>(`/topoapi/resources/${id}`, { headers })
    return addPricingDefaults(result)
  },

  async getDownloadUrl(id: number, token: string): Promise<string> {
    if (USE_MOCK) {
      await delay()
      return 'https://example.com/mock-download.zip'
    }
    const res = await request<{ url: string }>(`/topoapi/resources/${id}/download`, {
      headers: { 'Authorization': `Bearer ${token}`, 'X-Device-Id': getDeviceId() },
    })
    return res.url
  },
}
