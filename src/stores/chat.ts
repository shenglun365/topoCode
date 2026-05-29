/**
 * Chat Store — Coder / AI Assistant 会话管理 (v2)
 *
 * 会话持久化走 session.* IPC (SQLite llm_sessions/llm_messages)。
 * LLM 推理走 llm.chat IPC (ZMQ → Python 统一网关)，流式通过 ZMQ PUB 回传。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'

export interface ChatSession {
  id: string
  title: string
  mode: string
  status: string
  messages: ChatMessage[]
  createdAt: string
  updatedAt: string
}

export interface ChatMessage {
  id: string
  role: string
  content: string
  timestamp: string
}

export const useChatStore = defineStore('chat', () => {
  // Helper: get window.api with check
  function api() {
    if (!window.api) throw new Error('IPC bridge not available')
    return window.api
  }

  // State
  const sessions = ref<ChatSession[]>([])
  const activeSessionId = ref<string | null>(null)
  const inputMode = ref<'chat' | 'design'>('chat')
  const inputText = ref('')
  const isTyping = ref(false)
  const loading = ref(false)

  // Getters
  const activeSession = computed(() =>
    sessions.value.find(s => s.id === activeSessionId.value)
  )

  const sessionCount = computed(() => sessions.value.length)

  const runningSessions = computed(() =>
    sessions.value.filter(s => s.status === 'running')
  )

  async function clearAllSessions() {
    try {
      await api().session.clearAll()
      sessions.value = []
      activeSessionId.value = null
    } catch (e) {
      console.warn('[ChatStore] Failed to clear sessions:', e)
    }
  }

  // 获取当前默认模型 ID
  const modelId = computed(() => {
    const settingsStore = useSettingsStore()
    const defaultModel = settingsStore.models.find(m => m.isDefault)
    return defaultModel?.id || settingsStore.models[0]?.id || null
  })

  // 获取当前默认模型完整配置（用于 UI 展示）
  const modelConfig = computed(() => {
    const settingsStore = useSettingsStore()
    return settingsStore.models.find(m => m.isDefault) || settingsStore.models[0] || null
  })

  // Actions
  async function loadSessions() {
    loading.value = true
    try {
      const result = await api().session.list({ moduleType: 'ai_assistant' })
      if (result && result.sessions) {
        // 只保留最近 10 个会话，避免历史积压
        const recent = result.sessions.slice(0, 10)
        sessions.value = recent.map((s: any) => ({
          id: s.id,
          title: s.title,
          mode: 'chat',
          status: s.status,
          messages: [],
          createdAt: s.created_at,
          updatedAt: s.updated_at,
        }))

        if (!activeSessionId.value && sessions.value.length > 0) {
          activeSessionId.value = sessions.value[0].id
          await loadMessages(activeSessionId.value)
        }
      }
    } catch (e) {
      console.warn('[ChatStore] Failed to load sessions:', e)
    } finally {
      loading.value = false
    }
  }

  /** 加载指定会话的消息 */
  async function loadMessages(sessionId: string) {
    try {
      const result = await api().session.getMessages({ sessionId })
      if (result && result.messages) {
        const session = sessions.value.find(s => s.id === sessionId)
        if (session) {
          session.messages = result.messages.map((m: any) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            timestamp: m.created_at,
          }))
        }
      }
    } catch (e) {
      console.warn('[ChatStore] Failed to load messages:', e)
    }
  }

  async function createSession(title: string = '新对话') {
    try {
      const result = await api().session.create({
        moduleType: 'ai_assistant',
        title,
      })

      const newSession: ChatSession = {
        id: result.id,
        title,
        mode: inputMode.value,
        status: 'idle',
        messages: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }

      sessions.value.unshift(newSession)
      activeSessionId.value = newSession.id
    } catch (e) {
      console.warn('[ChatStore] Failed to create session:', e)
      // 降级：本地创建
      const fallbackId = `local-${Date.now()}`
      const newSession: ChatSession = {
        id: fallbackId,
        title,
        mode: inputMode.value,
        status: 'idle',
        messages: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      }
      sessions.value.unshift(newSession)
      activeSessionId.value = newSession.id
    }
  }

  async function closeSession(sessionId: string) {
    const idx = sessions.value.findIndex(s => s.id === sessionId)
    if (idx === -1) return

    sessions.value.splice(idx, 1)

    if (activeSessionId.value === sessionId) {
      activeSessionId.value = sessions.value[0]?.id || null
    }

    try {
      await api().session.delete({ sessionId })
    } catch (e) {
      console.warn('[ChatStore] Failed to delete session:', e)
    }
  }

  function switchSession(sessionId: string) {
    activeSessionId.value = sessionId
    const session = sessions.value.find(s => s.id === sessionId)
    if (session && session.messages.length === 0) {
      loadMessages(sessionId)
    }
  }

  function setMode(mode: 'chat' | 'design') {
    inputMode.value = mode
  }

  function setInputText(text: string) {
    inputText.value = text
  }

  /** 保存消息到后端 SQLite */
  async function _saveMessage(sessionId: string, msg: ChatMessage) {
    try {
      await api().session.addMessage({
        sessionId,
        role: msg.role,
        content: msg.content,
      })
    } catch (e) {
      console.warn('[ChatStore] Failed to save message:', e)
    }
  }

  async function sendMessage() {
    if (!inputText.value.trim() || !activeSessionId.value) return

    const session = sessions.value.find(s => s.id === activeSessionId.value)
    if (!session) return

    const userContent = inputText.value.trim()
    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: userContent,
      timestamp: new Date().toISOString(),
    }

    session.messages.push(userMessage)
    session.updatedAt = new Date().toISOString()
    session.status = 'running'
    inputText.value = ''
    isTyping.value = true

    // 持久化 user 消息
    _saveMessage(session.id, userMessage)

    // 创建 AI 消息占位
    const aiMessage: ChatMessage = {
      id: `msg-${Date.now() + 1}`,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    }
    session.messages.push(aiMessage)

    try {
      if (!modelId.value) {
        aiMessage.content = '请先配置大模型 API（设置 → 模型配置）'
        isTyping.value = false
        session.status = 'idle'
        return
      }

      // v2: 通过 IPC 调用后端 LLM 网关
      // 流式 chunk → ZMQ PUB 'llm' → main process → webContents.send → subscribe handler
      const result = await api().llm.chat({
        sessionId: session.id,
        modelId: modelId.value,
        messages: session.messages
          .filter(m => m.role === 'user' || m.role === 'assistant')
          .slice(0, -1)  // 去掉刚追加的空 AI 消息占位
          .map(m => ({ role: m.role, content: m.content })),
        mode: 'chat',
      })

      let fullContent = ''

      const unsubscribe = api().llm.subscribe(result.requestId, {
        onChunk(data: { index: number; text: string }) {
          fullContent += data.text
          aiMessage.content = fullContent
        },
        onDone(data: { content: string }) {
          aiMessage.content = data.content
          isTyping.value = false
          session.status = 'idle'
          session.updatedAt = new Date().toISOString()
          _saveMessage(session.id, aiMessage)
          unsubscribe()
        },
        onError(errData: { message: string }) {
          aiMessage.content = `LLM 调用失败: ${errData.message}`
          isTyping.value = false
          session.status = 'idle'
          unsubscribe()
        },
      })
    } catch (e: any) {
      aiMessage.content = `LLM 调用失败: ${e.message || String(e)}`
      console.error('[ChatStore] LLM call failed:', e)
      isTyping.value = false
      session.status = 'idle'
    }
  }

  function handleAction(action: string) {
    const actionMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: action,
      timestamp: new Date().toISOString(),
    }

    const session = activeSession.value
    if (session) {
      session.messages.push(actionMessage)
      session.updatedAt = new Date().toISOString()
    }
  }

  return {
    sessions,
    activeSessionId,
    inputMode,
    inputText,
    isTyping,
    loading,
    activeSession,
    sessionCount,
    runningSessions,
    modelId,
    modelConfig,
    loadSessions,
    clearAllSessions,
    createSession,
    closeSession,
    switchSession,
    setMode,
    setInputText,
    sendMessage,
    handleAction,
  }
})
