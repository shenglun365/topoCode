/**
 * 聊天会话持久化 store
 *
 * Session key 规则：
 * - 架构分析 (analysis): `arch:{projectId}:{taskId}` — 按分析任务隔离
 * - 架构分析无活跃任务: `arch:{projectId}:free` — 按项目隔离
 * - 代码解析 (code): `code:{projectId}` — 按项目隔离
 * - 其他: `free:YYYY-MM-DD` — 全局自由会话
 */

export type SessionPage = 'analysis' | 'code' | 'home'

interface PersistedMessage {
  id: string
  role: 'user' | 'assistant' | 'error' | 'system'
  content: string
  timestamp: number
}

const STORAGE_PREFIX = 'chat-session:'

function todayKey(): string {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `free:${d.getFullYear()}-${mm}-${dd}`
}

function load(key: string): PersistedMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function save(key: string, messages: PersistedMessage[]) {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(messages))
  } catch { /* quota exceeded — silent */ }
}

export function useChatSession() {
  function buildKey(page: SessionPage, projectId?: string, taskId?: string): string {
    if (page === 'analysis' && projectId && taskId) return `arch:${projectId}:${taskId}`
    if (page === 'analysis' && projectId) return `arch:${projectId}:free`
    if (page === 'code' && projectId) return `code:${projectId}`
    return todayKey()
  }

  function loadSession(key: string): PersistedMessage[] {
    return load(key)
  }

  function saveSession(key: string, messages: PersistedMessage[]) {
    save(key, messages)
  }

  function clearSession(key: string) {
    try { localStorage.removeItem(STORAGE_PREFIX + key) } catch {}
  }

  return { buildKey, loadSession, saveSession, clearSession }
}
