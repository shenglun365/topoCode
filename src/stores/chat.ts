/** Chat Store - AI 助手会话管理 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatSession, ChatMessage } from '@/utils/mock'
import { llmWorker } from '@/workers/llm.worker.instance'
import { useSettingsStore } from '@/stores/settings'

export const useChatStore = defineStore('chat', () => {
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

  // 获取当前默认模型配置（从 settings store 读取）
  const modelConfig = computed(() => {
    const settingsStore = useSettingsStore()
    return settingsStore.models.find(m => m.isDefault) || settingsStore.models[0] || null
  })

  // Actions
  async function loadSessions() {
    loading.value = true
    try {
      // 从后端加载会话列表
      const result = await window.api.chat.listSessions()
      if (result && result.sessions) {
        sessions.value = result.sessions
        activeSessionId.value = sessions.value[0]?.id || null
      }
    } catch (e) {
      console.warn('[ChatStore] Failed to load sessions from backend:', e)
      // 降级到本地空列表
      sessions.value = []
    } finally {
      loading.value = false
    }
  }

  async function createSession(title: string = '新对话') {
    const newSession: ChatSession = {
      id: `session-${Date.now()}`,
      title,
      mode: inputMode.value,
      status: 'idle',
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    sessions.value.unshift(newSession)
    activeSessionId.value = newSession.id

    // 同步到后端
    try {
      await window.api.chat.createSession({
        id: newSession.id,
        title: newSession.title,
        mode: newSession.mode,
      })
    } catch (e) {
      console.warn('[ChatStore] Failed to sync session to backend:', e)
    }
  }

  async function closeSession(sessionId: string) {
    const idx = sessions.value.findIndex(s => s.id === sessionId)
    if (idx === -1) return

    sessions.value.splice(idx, 1)

    if (activeSessionId.value === sessionId) {
      activeSessionId.value = sessions.value[0]?.id || null
    }

    // 同步到后端
    try {
      await window.api.chat.deleteSession({ id: sessionId })
    } catch (e) {
      console.warn('[ChatStore] Failed to delete session from backend:', e)
    }
  }

  function switchSession(sessionId: string) {
    activeSessionId.value = sessionId
  }

  function setMode(mode: 'chat' | 'design') {
    inputMode.value = mode
  }

  function setInputText(text: string) {
    inputText.value = text
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

    // 创建 AI 消息占位
    const aiMessage: ChatMessage = {
      id: `msg-${Date.now() + 1}`,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
    }
    session.messages.push(aiMessage)

    try {
      // 获取默认模型配置
      const settingsStore = useSettingsStore()
      const defaultModel = settingsStore.models.find(m => m.isDefault) || settingsStore.models[0]

      if (!defaultModel) {
        aiMessage.content = '请先配置大模型 API（设置 → 模型配置）'
        isTyping.value = false
        session.status = 'idle'
        return
      }

      // 构建消息历史
      const messages = session.messages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ role: m.role, content: m.content }))

      // 调用 LLM（流式 — Worker 执行）
      llmWorker.setConfig({
        url: defaultModel.url,
        apiKey: defaultModel.apiKey,
        provider: defaultModel.provider as 'ollama' | 'openai' | 'lm-studio' | 'custom',
        model: defaultModel.model,
        temperature: defaultModel.temperature,
        maxTokens: defaultModel.maxTokens,
      })
      const fullContent = await llmWorker.chat(messages, (chunk) => {
        if (aiMessage) {
          aiMessage.content += chunk
        }
      })

      aiMessage.content = fullContent
    } catch (e: any) {
      aiMessage.content = `LLM 调用失败: ${e.message || String(e)}`
      console.error('[ChatStore] LLM call failed:', e)
    } finally {
      isTyping.value = false
      session.status = 'idle'
      session.updatedAt = new Date().toISOString()
    }
  }

  function handleAction(action: string) {
    // 用户点击操作按钮
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
    modelConfig,
    loadSessions,
    createSession,
    closeSession,
    switchSession,
    setMode,
    setInputText,
    sendMessage,
    handleAction,
  }
})
