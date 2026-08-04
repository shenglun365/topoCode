/** API client for architect backend. */

const API_BASE = '/api/architect'

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
