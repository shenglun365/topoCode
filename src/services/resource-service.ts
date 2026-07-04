import type { Resource } from '@/types'
import { getDeviceId } from '@/utils/device-id'
import { mockResources } from '@/utils/mock'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const USE_MOCK = import.meta.env.DEV || !window.navigator.onLine

function addPricingDefaults(r: any): Resource {
  return {
    ...r,
    pricing_model: r.pricing_model || 'free',
    points_cost: r.points_cost ?? 0,
    price_cny: r.price_cny ?? 0,
    subscription_tier: r.subscription_tier || '',
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
    throw new Error(body.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

function delay(ms = 300): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}

export const resourceService = {
  async list(params?: { page?: number; category?: string }): Promise<{ total: number; items: Resource[] }> {
    if (USE_MOCK) {
      await delay()
      let items = [...mockResources].map(addPricingDefaults) as Resource[]
      if (params?.category) {
        items = items.filter(r => r.category === params.category)
      }
      const page = params?.page || 1
      const pageSize = 12
      const start = (page - 1) * pageSize
      return { total: items.length, items: items.slice(start, start + pageSize) }
    }
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.category) q.set('category', params.category)
    const result = await request<{ total: number; items: any[] }>(`/api/resources?${q}`)
    return { total: result.total, items: result.items.map(addPricingDefaults) }
  },

  async detail(id: number): Promise<Resource> {
    if (USE_MOCK) {
      await delay()
      const item = (mockResources as Resource[]).find(r => r.id === id)
      if (!item) throw new Error('资源不存在')
      return addPricingDefaults(item)
    }
    const result = await request<any>(`/api/resources/${id}`)
    return addPricingDefaults(result)
  },

  async getDownloadUrl(id: number, token: string): Promise<string> {
    if (USE_MOCK) {
      await delay()
      return 'https://example.com/mock-download.zip'
    }
    const res = await request<{ url: string }>(`/api/resources/${id}/download`, {
      headers: { 'Authorization': `Bearer ${token}`, 'X-Device-Id': getDeviceId() },
    })
    return res.url
  },
}