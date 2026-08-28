/** API client for architect backend. */

// 独立服务后：可用 VITE_ARCH_API_BASE 指向 3470；缺省同源 /api/architect(vite 代理)。
const API_BASE: string = (import.meta.env.VITE_ARCH_API_BASE as string | undefined) || '/api/architect'

export function apiBaseUrl(): string {
  return API_BASE
}

// ── 鉴权（token）：与 web-core 一致，网关要求 `Authorization: Bearer <token>` 或 `?token=` ──
// 浏览器获取 token（一次粘贴，持久化）：首次用 `http://<host>:3456/#token=<token>` 打开
// （token 见 `topo serve` 输出或 ~/.topocode/token），自动存入 localStorage `topocode:token`
// 并清理 URL；之后同源各子项目（含 architect）请求自动携带 Bearer，WS 自动携带 ?token=。
function readToken(): string {
  if (typeof window === 'undefined') return ''
  try {
    const m = window.location.hash.match(/token=([A-Za-z0-9]+)/)
    if (m && m[1]) {
      localStorage.setItem('topocode:token', m[1])
      window.history.replaceState(null, '', window.location.pathname + window.location.search)
      return m[1]
    }
  } catch { /* ignore */ }
  return localStorage.getItem('topocode:token') || ''
}

function authHeaders(): Record<string, string> {
  const tok = readToken()
  return tok ? { Authorization: `Bearer ${tok}` } : {}
}

/** 供 WS 客户端复用：返回当前 token（空串表示未设置）。 */
export function getToken(): string {
  return readToken()
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, { headers: authHeaders() })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}

export async function apiPost<T>(path: string, data?: unknown, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: data ? JSON.stringify(data) : undefined,
    signal,
  })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}

export async function apiPatch<T>(path: string, data: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(data),
  })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}

export async function apiPut<T>(path: string, data: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(data),
  })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, { method: 'DELETE', headers: authHeaders() })
  const body = await resp.json()
  if (body.code !== 0) throw new Error(body.message || `API error: ${path}`)
  return body.data as T
}
