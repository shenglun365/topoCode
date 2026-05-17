/**
 * LLM Worker — 流式请求隔离到独立线程
 *
 * 职责:
 * - 请求队列 (并发 ≤3, FIFO)
 * - fetch streaming + SSE 解析
 * - 定时批处理 (16ms 窗口 + 大小兜底)
 * - 支持 Ollama / OpenAI / LM-Studio 三种 provider
 */

// ==================== 类型定义 ====================

export interface ModelConfig {
  url: string
  apiKey?: string
  provider: 'ollama' | 'openai' | 'lm-studio' | 'custom'
  model: string
  temperature?: number
  maxTokens?: number
}

export interface ChatMessage {
  role: string
  content: string
}

// 主线程 → Worker
interface WorkerRequest {
  type: 'chat' | 'embed' | 'test' | 'setConfig'
  requestId: string
  payload: any
}

// Worker → 主线程
interface WorkerResponse {
  type: 'chunk' | 'done' | 'error'
  requestId: string
  data?: any
}

// ==================== 状态 ====================

let config: ModelConfig | null = null

// 活跃请求: requestId → { resolve, reject, onChunk, cancelled }
interface ActiveRequest {
  resolve: (v: string | number[] | Record<string, any>) => void
  reject: (e: Error) => void
  onChunk: (text: string) => void
  cancelled: boolean
}

const activeRequests = new Map<string, ActiveRequest>()

// 请求队列
const queue: Array<{ req: WorkerRequest; resolve: () => void }> = []
let activeCount = 0
const MAX_CONCURRENT = 3

// ==================== 消息路由 ====================

self.onmessage = (e: MessageEvent<WorkerRequest>) => {
  const { type, requestId, payload } = e.data

  switch (type) {
    case 'setConfig':
      config = payload
      postMessage({ type: 'done', requestId, data: { ok: true } })
      break

    case 'chat':
      enqueueRequest(e.data)
      break

    case 'embed':
      enqueueRequest(e.data)
      break

    case 'test':
      enqueueRequest(e.data)
      break

    default:
      postMessage({ type: 'error', requestId, data: { message: `Unknown type: ${type}` } })
  }
}

// ==================== 请求队列 ====================

function enqueueRequest(req: WorkerRequest) {
  return new Promise<void>((resolve) => {
    if (activeCount < MAX_CONCURRENT) {
      activeCount++
      processRequest(req).finally(() => {
        activeCount--
        resolve()
      })
      drainQueue()
    } else {
      queue.push({ req, resolve })
    }
  })
}

function drainQueue() {
  while (queue.length > 0 && activeCount < MAX_CONCURRENT) {
    const item = queue.shift()!
    activeCount++
    processRequest(item.req).finally(() => {
      activeCount--
      item.resolve()
    })
  }
}

async function processRequest(req: WorkerRequest) {
  const { type, requestId, payload } = req

  try {
    switch (type) {
      case 'chat':
        await handleChat(requestId, payload)
        break
      case 'embed':
        await handleEmbed(requestId, payload)
        break
      case 'test':
        await handleTest(requestId)
        break
    }
  } catch (e: any) {
    const reqObj = activeRequests.get(requestId)
    if (reqObj && !reqObj.cancelled) {
      reqObj.reject(e)
    } else {
      postMessage({ type: 'error', requestId, data: { message: e?.message || String(e) } })
    }
  }
}

// ==================== Chat 处理 ====================

async function handleChat(requestId: string, payload: { messages: ChatMessage[] }) {
  if (!config) throw new Error('No LLM config set')

  return new Promise<void>((resolve, reject) => {
    const reqObj: ActiveRequest = {
      resolve: () => {},
      reject,
      onChunk: (text: string) => postMessage({ type: 'chunk', requestId, data: text }),
      cancelled: false,
    }
    activeRequests.set(requestId, reqObj)

    // 根据 provider 选择请求路径
    let responsePromise: Promise<Response>
    switch (config.provider) {
      case 'ollama':
        responsePromise = ollamaChatRequest(payload.messages)
        break
      case 'lm-studio':
      case 'openai':
      case 'custom':
        responsePromise = openAIChatRequest(payload.messages)
        break
      default:
        reject(new Error(`Unsupported provider: ${config.provider}`))
        return
    }

    responsePromise
      .then((response) => {
        if (!response.ok) {
          throw new Error(`${config.provider} API error: ${response.status}`)
        }
        if (!response.body) throw new Error('No response body')

        if (config.provider === 'ollama') {
          streamOllama(response.body, requestId, reqObj, resolve)
        } else {
          streamOpenAI(response.body, requestId, reqObj, resolve)
        }
      })
      .catch((e) => {
        if (!reqObj.cancelled) reject(e)
      })
  })
}

// ==================== Ollama Streaming ====================

function ollamaChatRequest(messages: ChatMessage[]): Promise<Response> {
  return fetch(`${config!.url.replace(/\/+$/, '')}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: config!.model,
      messages,
      stream: true,
      options: {
        temperature: config?.temperature,
        num_predict: config?.maxTokens,
      },
    }),
  })
}

function streamOllama(
  body: ReadableStream<Uint8Array>,
  requestId: string,
  reqObj: ActiveRequest,
  outerResolve: () => void
) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let fullContent = ''
  let buffer = ''
  let timerId: ReturnType<typeof setTimeout> | null = null
  const BATCH_INTERVAL = 16 // ms — 对齐一帧
  const BATCH_MAX_SIZE = 500 // 字符数兜底

  function flushBatch() {
    if (buffer && !reqObj.cancelled) {
      postMessage({ type: 'chunk', requestId, data: buffer })
    }
    buffer = ''
    timerId = null
  }

  function scheduleFlush() {
    if (!timerId) {
      timerId = setTimeout(flushBatch, BATCH_INTERVAL)
    }
  }

  function readLoop() {
    reader.read().then(({ done, value }): Promise<void> => {
      // ReadableStream 规范: done=true 时 value 可能仍有最后一个数据块
      if (value && value.length > 0) {
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n').filter(Boolean)

        for (const line of lines) {
          try {
            const data = JSON.parse(line)
            const content = data.message?.content || ''
            if (content) {
              fullContent += content
              buffer += content
              scheduleFlush()
              if (buffer.length >= BATCH_MAX_SIZE) flushBatch()
            }
          } catch {
            // Ignore malformed JSON lines
          }
        }
      }

      if (done) {
        if (buffer) flushBatch()
        cleanup()
        return Promise.resolve()
      }

      return readLoop()
    }).catch((e) => {
      cleanup()
      throw e
    })
  }

  function cleanup() {
    reader.releaseLock()
    if (timerId) {
      clearTimeout(timerId)
      timerId = null
    }
    activeRequests.delete(requestId)
    postMessage({ type: 'done', requestId, data: fullContent })
    outerResolve()
  }

  readLoop()
}

// ==================== OpenAI Streaming ====================

function openAIChatRequest(messages: ChatMessage[]): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (config?.apiKey) {
    headers['Authorization'] = `Bearer ${config.apiKey}`
  }

  return fetch(`${config!.url.replace(/\/+$/, '')}/v1/chat/completions`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      model: config!.model,
      messages,
      stream: true,
      temperature: config?.temperature,
      max_tokens: config?.maxTokens,
    }),
  })
}

function streamOpenAI(
  body: ReadableStream<Uint8Array>,
  requestId: string,
  reqObj: ActiveRequest,
  outerResolve: () => void
) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let fullContent = ''
  let buffer = ''
  let timerId: ReturnType<typeof setTimeout> | null = null
  const BATCH_INTERVAL = 16 // ms — 对齐一帧
  const BATCH_MAX_SIZE = 500 // 字符数兜底

  function flushBatch() {
    if (buffer && !reqObj.cancelled) {
      postMessage({ type: 'chunk', requestId, data: buffer })
    }
    buffer = ''
    timerId = null
  }

  function scheduleFlush() {
    if (!timerId) {
      timerId = setTimeout(flushBatch, BATCH_INTERVAL)
    }
  }

  function readLoop() {
    reader.read().then(({ done, value }): Promise<void> => {
      // ReadableStream 规范: done=true 时 value 可能仍有最后一个数据块
      if (value && value.length > 0) {
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n').filter(Boolean)

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') continue

            try {
              const parsed = JSON.parse(data)
              const content = parsed.choices?.[0]?.delta?.content || ''
              if (content) {
                fullContent += content
                buffer += content
                scheduleFlush()
                if (buffer.length >= BATCH_MAX_SIZE) flushBatch()
              }
            } catch {
              // Ignore malformed JSON
            }
          }
        }
      }

      if (done) {
        if (buffer) flushBatch()
        cleanup()
        return Promise.resolve()
      }

      return readLoop()
    }).catch((e) => {
      cleanup()
      throw e
    })
  }

  function cleanup() {
    reader.releaseLock()
    if (timerId) {
      clearTimeout(timerId)
      timerId = null
    }
    activeRequests.delete(requestId)
    postMessage({ type: 'done', requestId, data: fullContent })
    outerResolve()
  }

  readLoop()
}

// ==================== Embedding ====================

async function handleEmbed(requestId: string, payload: { text: string }) {
  if (!config) throw new Error('No LLM config set')

  let response: Response
  switch (config.provider) {
    case 'ollama':
      response = await fetch(`${config.url.replace(/\/+$/, '')}/api/embeddings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'nomic-embed-text',
          prompt: payload.text,
        }),
      })
      break
    case 'openai':
    case 'custom':
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (config.apiKey) headers['Authorization'] = `Bearer ${config.apiKey}`
      response = await fetch(`${config.url.replace(/\/+$/, '')}/v1/embeddings`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          model: 'text-embedding-3-small',
          input: payload.text,
        }),
      })
      break
    default:
      throw new Error(`Embedding not supported for: ${config.provider}`)
  }

  if (!response.ok) throw new Error(`${config.provider} embeddings error: ${response.status}`)
  const data = await response.json()
  const embedding = config.provider === 'ollama' ? data.embedding : (data.data?.[0]?.embedding || [])

  postMessage({ type: 'done', requestId, data: embedding })
}

// ==================== Test Connection ====================

async function handleTest(requestId: string) {
  if (!config) throw new Error('No LLM config set')
  const start = Date.now()

  try {
    let response: Response
    if (config.provider === 'ollama') {
      response = await fetch(`${config.url.replace(/\/+$/, '')}/api/tags`)
    } else {
      const headers: Record<string, string> = {}
      if (config.apiKey) headers['Authorization'] = `Bearer ${config.apiKey}`
      response = await fetch(`${config.url.replace(/\/+$/, '')}/v1/models`, { headers })
    }

    if (!response.ok) throw new Error('Connection failed')
    await response.json()
    const latency = Date.now() - start
    postMessage({ type: 'done', requestId, data: { status: 'connected', latency } })
  } catch {
    postMessage({ type: 'done', requestId, data: { status: 'error', latency: 0 } })
  }
}
