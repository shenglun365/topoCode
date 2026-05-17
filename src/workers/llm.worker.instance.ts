/**
 * LLM Worker 实例 — 单例桥接层
 *
 * 主线程通过此模块与 Worker 通信，对外暴露 Promise 接口。
 */

import LlmWorker from '@/workers/llm.worker?worker'

export interface ChatMessage {
  role: string
  content: string
}

export interface ModelConfig {
  url: string
  apiKey?: string
  provider: 'ollama' | 'openai' | 'lm-studio' | 'custom'
  model: string
  temperature?: number
  maxTokens?: number
}

let requestIdCounter = 0
function nextRequestId(): string {
  return `llm-${++requestIdCounter}-${Date.now()}`
}

class LlmWorkerClient {
  private worker: Worker
  private initialized = false

  constructor() {
    this.worker = new LlmWorker()
  }

  /**
   * 设置模型配置
   */
  setConfig(config: ModelConfig): void {
    this.worker.postMessage({
      type: 'setConfig',
      requestId: nextRequestId(),
      payload: config,
    })
    this.initialized = true
  }

  /**
   * 流式对话
   */
  chat(
    messages: ChatMessage[],
    onChunk?: (chunk: string) => void
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      const requestId = nextRequestId()
      let fullContent = ''

      const handler = (e: MessageEvent) => {
        const { type, requestId: rid, data } = e.data
        if (rid !== requestId) return

        switch (type) {
          case 'chunk':
            fullContent += data
            onChunk?.(data)
            break
          case 'done':
            this.worker.removeEventListener('message', handler)
            resolve(fullContent)
            break
          case 'error':
            this.worker.removeEventListener('message', handler)
            reject(new Error(data?.message || 'Worker error'))
            break
        }
      }

      this.worker.addEventListener('message', handler)
      this.worker.postMessage({
        type: 'chat',
        requestId,
        payload: { messages },
      })
    })
  }

  /**
   * 文本向量化
   */
  embed(text: string): Promise<number[]> {
    return new Promise((resolve, reject) => {
      const requestId = nextRequestId()

      const handler = (e: MessageEvent) => {
        const { type, requestId: rid, data } = e.data
        if (rid !== requestId) return

        this.worker.removeEventListener('message', handler)

        if (type === 'done') {
          resolve(data as number[])
        } else if (type === 'error') {
          reject(new Error(data?.message || 'Worker error'))
        }
      }

      this.worker.addEventListener('message', handler)
      this.worker.postMessage({
        type: 'embed',
        requestId,
        payload: { text },
      })
    })
  }

  /**
   * 测试连接
   */
  testConnection(): Promise<{ status: string; latency: number }> {
    return new Promise((resolve, reject) => {
      const requestId = nextRequestId()

      const handler = (e: MessageEvent) => {
        const { type, requestId: rid, data } = e.data
        if (rid !== requestId) return

        this.worker.removeEventListener('message', handler)

        if (type === 'done') {
          resolve(data as { status: string; latency: number })
        } else if (type === 'error') {
          reject(new Error(data?.message || 'Worker error'))
        }
      }

      this.worker.addEventListener('message', handler)
      this.worker.postMessage({
        type: 'test',
        requestId,
        payload: {},
      })
    })
  }
}

// 导出单例
export const llmWorker = new LlmWorkerClient()
