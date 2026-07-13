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

  // 懒续期：服务端通过 X-Refresh-Token 下发新 token
  const refreshedToken = res.headers.get('X-Refresh-Token')
  if (refreshedToken) {
    localStorage.setItem('topocode_token', refreshedToken)
    window.dispatchEvent(new CustomEvent('auth:token-refreshed', { detail: { token: refreshedToken } }))
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const msg = body.message || `HTTP ${res.status}`
    if (res.status === 401 || /(未登录|token.*过期|登录.*过期|token.*invalid)/i.test(msg)) {
      localStorage.removeItem('topocode_token')
      localStorage.removeItem('topocode_user')
      window.dispatchEvent(new CustomEvent('auth:expired', { detail: { message: msg } }))
    }
    throw new Error(msg)
  }
  const json: ApiResponse<T> = await res.json()
  if (!json.success) {
    const msg = json.message || '请求失败'
    if (/(未登录|token.*过期|登录.*过期|token.*invalid)/i.test(msg)) {
      localStorage.removeItem('topocode_token')
      localStorage.removeItem('topocode_user')
      window.dispatchEvent(new CustomEvent('auth:expired', { detail: { message: msg } }))
    }
    throw new Error(msg)
  }
  return json.data
}

export function getTokenHeader(): Record<string, string> {
  const token = getToken()
  return token ? { 'Authorization': `Bearer ${token}` } : {}
}
