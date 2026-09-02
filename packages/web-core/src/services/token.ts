/**
 * token 单一源（F2 修正）——原先在 browser-api.ts 与 api.ts 各有一份逐字拷贝。
 *
 * 语义：首次以 `http://<host>:3456/#token=<token>` 打开 → 自动存入 localStorage
 * `topocode:token` 并清理 URL；之后所有请求携带 `Authorization: Bearer`，WS 携带 `?token=`。
 * （token 见 `topo serve` 输出或 ~/.topocode/token）
 */

export const TOKEN_KEY = 'topocode:token'

/** 读取 token：URL hash `#token=xxx`（首次粘贴）优先，其次 localStorage */
export function readToken(): string {
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

/** 鉴权头（裸 fetch 场景复用） */
export function authHeaders(): Record<string, string> {
  const tok = readToken()
  return tok ? { Authorization: `Bearer ${tok}` } : {}
}
