/**
 * useLlmChat — LLM 流式对话 composable (v2)
 *
 * 替代旧的 Worker 直连模式，通过 IPC → ZMQ → Python 后端统一网关。
 *
 * 用法:
 *   const { send, abort, isStreaming, content, error } = useLlmChat(sessionId, modelId)
 *   await send({ messages: [...] })           // 直接传 messages
 *   await send({ templateId: '...', variables: {...} })  // 或使用模板
 *
 * 流式生命周期:
 *   1. send() → window.api.llm.chat() → { requestId, status }
 *   2. window.api.llm.subscribe(requestId, callbacks) → onChunk / onToolCall / onToolResult / onDone / onError
 *   3. done/error 后自动 unsubscribe
 */

import { ref, type Ref } from 'vue'

export type LlmChatMode = 'chat' | 'tools' | 'structured'

export interface LlmChunkData {
  index: number
  text: string
}

export interface LlmToolCallData {
  toolName: string
  args: Record<string, any>
}

export interface LlmToolResultData {
  toolName: string
  result: Record<string, any>
}

export interface LlmDoneData {
  content: string
  structured?: Record<string, any>
}

export interface LlmErrorData {
  message: string
  code: string
}

export interface LlmSendOptions {
  /** 直接传入消息列表 */
  messages?: Array<{ role: string; content: string }>
  /** 或使用模板 ID + 变量 */
  templateId?: string
  variables?: Record<string, any>
  /** 模式: chat (默认) / tools / structured */
  mode?: LlmChatMode
  /** tools 模式下的工具名称列表 */
  tools?: string[]
  /** structured 模式下的 JSON Schema */
  outputSchema?: Record<string, any>
}

export interface UseLlmChatReturn {
  isStreaming: { readonly value: boolean }
  content: { readonly value: string }
  structuredOutput: { readonly value: Record<string, any> | null }
  chunks: { readonly value: LlmChunkData[] }
  toolCalls: { readonly value: LlmToolCallData[] }
  toolResults: { readonly value: LlmToolResultData[] }
  error: { readonly value: LlmErrorData | null }
  requestId: { readonly value: string | null }
  send: (options: LlmSendOptions) => Promise<string>
  abort: () => Promise<void>
  reset: () => void
}

export function useLlmChat(
  sessionId: string | Ref<string>,
  modelId: string | Ref<string>,
): UseLlmChatReturn {
  const _sessionId = typeof sessionId === 'string' ? ref(sessionId) : sessionId
  const _modelId = typeof modelId === 'string' ? ref(modelId) : modelId

  const isStreaming = ref(false)
  const content = ref('')
  const structuredOutput = ref<Record<string, any> | null>(null)
  const chunks = ref<LlmChunkData[]>([])
  const toolCalls = ref<LlmToolCallData[]>([])
  const toolResults = ref<LlmToolResultData[]>([])
  const error = ref<LlmErrorData | null>(null)
  const requestId = ref<string | null>(null)

  let unsubscribe: (() => void) | null = null

  function reset() {
    isStreaming.value = false
    content.value = ''
    structuredOutput.value = null
    chunks.value = []
    toolCalls.value = []
    toolResults.value = []
    error.value = null
    requestId.value = null
    unsubscribe?.()
    unsubscribe = null
  }

  async function send(options: LlmSendOptions): Promise<string> {
    // 先取消之前的
    if (isStreaming.value) {
      await abort()
    }
    reset()

    isStreaming.value = true

    return new Promise<string>(async (resolve, reject) => {
      if (!window.api) {
        reject(new Error('IPC bridge not available'))
        return
      }

      try {
        const result = await window.api.llm.chat({
          sessionId: _sessionId.value,
          modelId: _modelId.value,
          mode: options.mode || 'chat',
          messages: options.messages,
          templateId: options.templateId,
          variables: options.variables,
          tools: options.tools,
          outputSchema: options.outputSchema,
        })

        requestId.value = result.requestId

        // 订阅流式事件
        unsubscribe = window.api.llm.subscribe(result.requestId, {
          onChunk(data: LlmChunkData) {
            chunks.value.push(data)
            content.value += data.text
          },

          onToolCall(data: LlmToolCallData) {
            toolCalls.value.push(data)
          },

          onToolResult(data: LlmToolResultData) {
            toolResults.value.push(data)
          },

          onDone(data: LlmDoneData) {
            content.value = data.content
            structuredOutput.value = data.structured || null
            isStreaming.value = false
            unsubscribe?.()
            unsubscribe = null
            resolve(data.content)
          },

          onError(errData: LlmErrorData) {
            error.value = errData
            isStreaming.value = false
            unsubscribe?.()
            unsubscribe = null
            reject(new Error(errData.message))
          },
        })
      } catch (e: any) {
        const errData: LlmErrorData = {
          message: e.message || String(e),
          code: 'IPC_ERROR',
        }
        error.value = errData
        isStreaming.value = false
        unsubscribe?.()
        unsubscribe = null
        reject(e)
      }
    })
  }

  async function abort(): Promise<void> {
    if (requestId.value && window.api) {
      try {
        await window.api.llm.abortChat({ requestId: requestId.value })
      } catch (e) {
        console.warn('[useLlmChat] abort failed:', e)
      }
    }
    isStreaming.value = false
    unsubscribe?.()
    unsubscribe = null
  }

  return {
    isStreaming,
    content,
    structuredOutput,
    chunks,
    toolCalls,
    toolResults,
    error,
    requestId,
    send,
    abort,
    reset,
  }
}
