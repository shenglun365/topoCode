/** API client for architect backend. */

// 独立服务后：可用 VITE_ARCH_API_BASE 指向 3470；缺省同源 /api/architect(vite 代理)。
const API_BASE: string = (import.meta.env.VITE_ARCH_API_BASE as string | undefined) || '/api/architect'

export function apiBaseUrl(): string {
  return API_BASE
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`)
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}

export async function apiPost<T>(path: string, data?: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: data ? JSON.stringify(data) : undefined,
  })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}

export async function apiPatch<T>(path: string, data: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}

export async function apiPut<T>(path: string, data: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, { method: 'DELETE' })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}
