/** LLM Service - HTTP 调用外部 LLM API */
import type { ModelConfigItem } from '@/types/ipc'

export class LLMService {
  private config: ModelConfigItem | null = null

  setConfig(config: ModelConfigItem) {
    this.config = config
  }

  getConfig(): ModelConfigItem | null {
    return this.config
  }

  private getBaseUrl(): string {
    if (!this.config) throw new Error('No LLM config set')
    return this.config.url.replace(/\/+$/, '')
  }

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (this.config?.apiKey) {
      headers['Authorization'] = `Bearer ${this.config.apiKey}`
    }
    return headers
  }

  /**
   * 流式对话
   * @param messages 消息历史
   * @param onChunk 流式回调
   * @returns 完整回复内容
   */
  async chat(
    messages: Array<{ role: string; content: string }>,
    onChunk?: (chunk: string) => void
  ): Promise<string> {
    if (!this.config) throw new Error('No LLM config set')

    switch (this.config.provider) {
      case 'ollama':
        return this.ollamaChat(messages, onChunk)
      case 'openai':
      case 'custom':
        return this.openAIChat(messages, onChunk)
      case 'lm-studio':
        return this.lmStudioChat(messages, onChunk)
      default:
        throw new Error(`Unsupported provider: ${this.config.provider}`)
    }
  }

  /**
   * Ollama 流式对话
   */
  private async ollamaChat(
    messages: Array<{ role: string; content: string }>,
    onChunk?: (chunk: string) => void
  ): Promise<string> {
    const response = await fetch(`${this.getBaseUrl()}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: this.config!.model,
        messages,
        stream: true,
        options: {
          temperature: this.config?.temperature,
          num_predict: this.config?.maxTokens,
        },
      }),
    })

    if (!response.ok) {
      throw new Error(`Ollama API error: ${response.status}`)
    }

    if (!response.body) throw new Error('No response body')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let fullContent = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        for (const line of chunk.split('\n').filter(Boolean)) {
          try {
            const data = JSON.parse(line)
            const content = data.message?.content || ''
            if (content) {
              fullContent += content
              onChunk?.(content)
            }
          } catch {
            // Ignore malformed JSON
          }
        }
      }
    } finally {
      reader.releaseLock()
    }

    return fullContent
  }

  /**
   * OpenAI 流式对话
   */
  private async openAIChat(
    messages: Array<{ role: string; content: string }>,
    onChunk?: (chunk: string) => void
  ): Promise<string> {
    const response = await fetch(`${this.getBaseUrl()}/v1/chat/completions`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({
        model: this.config!.model,
        messages,
        stream: true,
        temperature: this.config?.temperature,
        max_tokens: this.config?.maxTokens,
      }),
    })

    if (!response.ok) {
      throw new Error(`OpenAI API error: ${response.status}`)
    }

    if (!response.body) throw new Error('No response body')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let fullContent = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        for (const line of chunk.split('\n').filter(Boolean)) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') break

            try {
              const parsed = JSON.parse(data)
              const content = parsed.choices?.[0]?.delta?.content || ''
              if (content) {
                fullContent += content
                onChunk?.(content)
              }
            } catch {
              // Ignore malformed JSON
            }
          }
        }
      }
    } finally {
      reader.releaseLock()
    }

    return fullContent
  }

  /**
   * LM-Studio 流式对话 (兼容 OpenAI API)
   */
  private async lmStudioChat(
    messages: Array<{ role: string; content: string }>,
    onChunk?: (chunk: string) => void
  ): Promise<string> {
    return this.openAIChat(messages, onChunk)
  }

  /**
   * 文本向量化
   */
  async embed(text: string): Promise<number[]> {
    if (!this.config) throw new Error('No LLM config set')

    switch (this.config.provider) {
      case 'ollama':
        return this.ollamaEmbed(text)
      case 'openai':
        return this.openAIEmbed(text)
      default:
        throw new Error(`Embedding not supported for: ${this.config.provider}`)
    }
  }

  /**
   * Ollama Embedding
   */
  private async ollamaEmbed(text: string): Promise<number[]> {
    const response = await fetch(`${this.getBaseUrl()}/api/embeddings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'nomic-embed-text',
        prompt: text,
      }),
    })

    if (!response.ok) {
      throw new Error(`Ollama embeddings error: ${response.status}`)
    }

    const data = await response.json()
    return data.embedding
  }

  /**
   * OpenAI Embedding
   */
  private async openAIEmbed(text: string): Promise<number[]> {
    const response = await fetch(`${this.getBaseUrl()}/v1/embeddings`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({
        model: 'text-embedding-3-small',
        input: text,
      }),
    })

    if (!response.ok) {
      throw new Error(`OpenAI embeddings error: ${response.status}`)
    }

    const data = await response.json()
    return data.data?.[0]?.embedding || []
  }

  /**
   * 测试连接
   */
  async testConnection(): Promise<{ status: string; latency: number }> {
    const start = Date.now()
    try {
      if (this.config?.provider === 'ollama') {
        const response = await fetch(`${this.getBaseUrl()}/api/tags`)
        if (!response.ok) throw new Error('Connection failed')
        await response.json()
      } else {
        const response = await fetch(`${this.getBaseUrl()}/v1/models`, {
          headers: this.getHeaders(),
        })
        if (!response.ok) throw new Error('Connection failed')
        await response.json()
      }
      const latency = Date.now() - start
      return { status: 'connected', latency }
    } catch {
      return { status: 'error', latency: 0 }
    }
  }
}

// 导出单例
export const llmService = new LLMService()
