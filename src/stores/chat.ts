/** Chat Store - AI 助手会话管理 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatSession, ChatMessage } from '@/utils/mock'
import { mockSessions, mockModelConfig, delay } from '@/utils/mock'

export const useChatStore = defineStore('chat', () => {
  // State
  const sessions = ref<ChatSession[]>([])
  const activeSessionId = ref<string | null>(null)
  const inputMode = ref<'chat' | 'design'>('chat')
  const inputText = ref('')
  const isTyping = ref(false)
  const modelConfig = ref(mockModelConfig)
  const loading = ref(false)

  // Getters
  const activeSession = computed(() =>
    sessions.value.find(s => s.id === activeSessionId.value)
  )

  const sessionCount = computed(() => sessions.value.length)

  const runningSessions = computed(() =>
    sessions.value.filter(s => s.status === 'running')
  )

  // Actions
  async function loadSessions() {
    loading.value = true
    await delay(300)
    sessions.value = [...mockSessions]
    activeSessionId.value = sessions.value[0]?.id || null
    loading.value = false
  }

  function createSession(title: string = '新对话') {
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
  }

  function closeSession(sessionId: string) {
    const idx = sessions.value.findIndex(s => s.id === sessionId)
    if (idx === -1) return

    sessions.value.splice(idx, 1)

    if (activeSessionId.value === sessionId) {
      activeSessionId.value = sessions.value[0]?.id || null
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

    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: inputText.value.trim(),
      timestamp: new Date().toISOString(),
    }

    session.messages.push(userMessage)
    session.updatedAt = new Date().toISOString()
    inputText.value = ''
    isTyping.value = true

    // 模拟 AI 回复
    await delay(1000)
    const aiMessage: ChatMessage = {
      id: `msg-${Date.now() + 1}`,
      role: 'assistant',
      content: '这是一个模拟的 AI 回复。实际功能将连接到后端 LLM 服务。',
      timestamp: new Date().toISOString(),
    }

    session.messages.push(aiMessage)
    isTyping.value = false
  }

  function handleAction(action: string) {
    // 模拟用户点击操作按钮
    const actionMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: action,
      timestamp: new Date().toISOString(),
    }

    const session = activeSession.value
    if (session) {
      session.messages.push(actionMessage)
    }
  }

  return {
    sessions,
    activeSessionId,
    inputMode,
    inputText,
    isTyping,
    modelConfig,
    loading,
    activeSession,
    sessionCount,
    runningSessions,
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
