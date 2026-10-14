/**
 * 内核自持 token 读取（F3/A5 抽取时随行）：
 * graph-kernel 设计为可独立消费（web-core 与 architect 共同依赖），
 * 不反向 import web-core —— 故此处保留与 web-core services/token.ts 同语义的
 * 最小实现（`#token=` 首粘 → localStorage `topocode:token`），仅用于
 * plantuml /api/topo 的 Bearer 头注入。两端键名/协议保持一致。
 */

export const TOKEN_KEY = 'topocode:token'

export function readKernelToken(): string {
  if (typeof window === 'undefined') return ''
  try {
    const m = window.location.hash.match(/token=([A-Za-z0-9]+)/)
    if (m && m[1]) {
      localStorage.setItem(TOKEN_KEY, m[1])
      window.history.replaceState(null, '', window.location.pathname + window.location.search)
      return m[1]
    }
  } catch {}
  return localStorage.getItem(TOKEN_KEY) || ''
}

/** diagram 引擎请求头（plantuml POST 鉴权） */
export function kernelAuthHeaders(): Record<string, string> {
  const tok = readKernelToken()
  return tok ? { Authorization: `Bearer ${tok}` } : {}
}
