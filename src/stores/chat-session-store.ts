/**
 * 聊天会话持久化 store
 *
 * 两种模式：
 * 1. 任务会话 — key=`chat:{projectId}:{taskId}`，分析任务绑定的对话
 * 2. 自由问答 — key=`chat:free:{YYYY-MM-DD}`，跨项目共享，按日期归档
 */

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
  function sessionKey(projectId?: string, taskId?: string): string {
    if (projectId && taskId) return `${projectId}:${taskId}`
    return todayKey()
  }

  function loadSession(projectId?: string, taskId?: string): PersistedMessage[] {
    return load(sessionKey(projectId, taskId))
  }

  function saveSession(messages: PersistedMessage[], projectId?: string, taskId?: string) {
    save(sessionKey(projectId, taskId), messages)
  }

  function clearSession(projectId?: string, taskId?: string) {
    try { localStorage.removeItem(STORAGE_PREFIX + sessionKey(projectId, taskId)) } catch {}
  }

  return { loadSession, saveSession, clearSession }
}
