/**
 * chat SSE 流消费助手（R2 修正：原 ChatSession.vue 内联 ~40 行 ReadableStream 循环）。
 *
 * 协议：POST /api/chat/sessions/{id}/messages 返回 `data: {...}` 行流，
 * type ∈ chunk / reasoning / tool_call / tool_result / done / error。
 * token 鉴权与请求体由调用方构造（headers 见 services/token authHeaders）。
 */

export interface ChatStreamCallbacks {
  /** 正文增量 */
  onChunk?: (text: string) => void
  /** 思考过程增量 */
  onReasoning?: (text: string) => void
  /** 工具调用发起 */
  onToolCall?: (call: { id: string; name: string; arguments: Record<string, any> }) => void
  /** 工具调用结果（id 对应 onToolCall） */
  onToolResult?: (id: string, result: string) => void
  /** 完成（含 quality/content/reasoning 终值） */
  onDone?: (data: any) => void
  /** 服务端返回错误（message 已存在时优先） */
  onError?: (message: string) => void
}

/** 消费一条 chat SSE Response；resolve 于流结束/done/error。 */
export async function consumeChatSse(resp: Response, cb: ChatStreamCallbacks): Promise<void> {
  const reader = resp.body?.getReader()
  if (!reader) return
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    let finished = false
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6))
        switch (data.type) {
          case 'chunk':
            if (data.text) cb.onChunk?.(data.text)
            break
          case 'reasoning':
            if (data.text) cb.onReasoning?.(data.text)
            break
          case 'tool_call':
            cb.onToolCall?.({ id: data.id, name: data.name, arguments: data.arguments || {} })
            break
          case 'tool_result':
            cb.onToolResult?.(data.id, typeof data.result === 'string' ? data.result.slice(0, 500) : JSON.stringify(data.result).slice(0, 500))
            break
          case 'done':
            cb.onDone?.(data)
            finished = true
            break
          case 'error':
            cb.onError?.(data.message || '')
            finished = true
            break
        }
      } catch { /* 忽略残缺行 */ }
      if (finished) return
    }
  }
}
