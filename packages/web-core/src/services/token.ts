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

/** MS3-U3 一次性迁移：旧下划线鉴权键（topocode_token/topocode_user）→ 冒号键。
 *  幂等：新键已有值则只清理旧键；旧键不存在则零操作。 */
export function migrateLegacyAuthKeys(): void {
  try {
    const legacyToken = localStorage.getItem('topocode_token')
    if (!legacyToken) return
    if (!localStorage.getItem('topocode:token')) {
      localStorage.setItem('topocode:token', legacyToken)
      const legacyUser = localStorage.getItem('topocode_user')
      if (legacyUser && !localStorage.getItem('topocode:user')) {
        localStorage.setItem('topocode:user', legacyUser)
      }
    }
    localStorage.removeItem('topocode_token')
    localStorage.removeItem('topocode_user')
  } catch {}
}
