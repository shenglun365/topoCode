import { ref, nextTick, type Ref, type ComputedRef } from 'vue'
import { chat } from '@/services/llmClient'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'error' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
}

export interface UseChatSessionOptions {
  modelId: Ref<string | null | undefined> | ComputedRef<string | null | undefined>
  scrollContainer?: Ref<HTMLElement | null>
  preserveSystemMessages?: boolean
}

export function useChatSession(options: UseChatSessionOptions) {
  const messages = ref<ChatMessage[]>([])
  const streaming = ref(false)
  const userInput = ref('')
  const chatAbort = ref<AbortController | null>(null)

  function scrollToBottom() {
    nextTick(() => {
      const el = options.scrollContainer?.value || document.querySelector('.chat-messages') as HTMLElement
      if (el) el.scrollTop = el.scrollHeight
    })
  }

  function addMessage(role: ChatMessage['role'], content: string, isStreaming?: boolean): ChatMessage {
    const msg: ChatMessage = {
      id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      role,
      content,
      timestamp: Date.now(),
      isStreaming: isStreaming ?? role === 'assistant',
    }
    messages.value.push(msg)
    scrollToBottom()
    return msg
  }

  function getChatHistory(): Array<{ role: string; content: string }> {
    return messages.value
      .filter(m => {
        if (m.isStreaming) return false
        if (!options.preserveSystemMessages && m.role === 'system') return false
        return m.role === 'user' || m.role === 'assistant' || m.role === 'system'
      })
      .map(m => ({ role: m.role, content: m.content }))
  }

  async function sendMessage(input?: string): Promise<string | null> {
    const text = (input ?? userInput.value).trim()
    if (!text || streaming.value) return null
    const mid = options.modelId.value
    if (!mid) return null

    userInput.value = ''
    streaming.value = true

    const abort = new AbortController()
    chatAbort.value = abort

    addMessage('user', text)
    const assistantMsg = addMessage('assistant', '', true)

    try {
      const fullContent = await chat({
        modelId: mid,
        messages: getChatHistory(),
        onChunk(chunk: string) {
          assistantMsg.content += chunk
        },
        signal: abort.signal,
      } as any)
      assistantMsg.content = fullContent
      assistantMsg.isStreaming = false
      scrollToBottom()
      return fullContent
    } catch (err: unknown) {
      if ((err as Error).name === 'AbortError') {
        assistantMsg.content = assistantMsg.content || '(已取消)'
      } else {
        assistantMsg.content = (err as Error).message || '请求失败'
        assistantMsg.role = 'error'
      }
      assistantMsg.isStreaming = false
      return null
    } finally {
      streaming.value = false
      chatAbort.value = null
      scrollToBottom()
    }
  }

  function cancelStream() {
    chatAbort.value?.abort()
    chatAbort.value = null
  }

  function clearMessages() {
    messages.value = []
    userInput.value = ''
  }

  function setMessages(msgs: ChatMessage[]) {
    messages.value = msgs
  }

  return {
    messages,
    streaming,
    userInput,
    addMessage,
    scrollToBottom,
    sendMessage,
    cancelStream,
    clearMessages,
    setMessages,
    getChatHistory,
    chatAbort,
  }
}
