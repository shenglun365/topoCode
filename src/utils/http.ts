import { getDeviceId } from './device-id'

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
}

function getToken(): string | null {
  return localStorage.getItem('topocode_token')
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Device-Id': getDeviceId(),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
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

export function getTokenHeader(): Record<string, string> {
  const token = getToken()
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}
