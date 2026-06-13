import { useModelConfigStore } from '@/stores/model-config-store'

function getDefaultModelId(): string | null {
  try {
    const store = useModelConfigStore()
    const defaultModel = store.models.find(m => m.isDefault)
    if (defaultModel) return defaultModel.id
    if (store.models.length > 0) return store.models[0].id
    return null
  } catch {
    return null
  }
}

export function isLLMConfigured(): boolean {
  return getDefaultModelId() !== null
}

export interface ChatOptions {
  messages?: Array<{ role: string; content: string }>
  templateId?: string
  variables?: Record<string, any>
  mode?: 'chat' | 'tools' | 'structured'
  onChunk?: (chunk: string) => void
  signal?: AbortSignal
}

export function chat(options: ChatOptions): Promise<string> {
  const modelId = getDefaultModelId()
  if (!modelId) throw new Error('LLM API 未配置')
  if (!window.api) throw new Error('IPC bridge not available')
  const bridge = window.api

  return new Promise<string>(async (resolve, reject) => {
    let aborted = false
    let requestId: string | null = null
    let unsub: (() => void) | null = null

    function abortHandler() {
      aborted = true
      if (requestId) bridge.llm.abortChat({ requestId })
      unsub?.()
      reject(new DOMException('Aborted', 'AbortError'))
    }

    if (options.signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    options.signal?.addEventListener('abort', abortHandler)

    try {
      const result = await bridge.llm.chat({
        sessionId: `_inline_${Date.now()}`,
        modelId,
        messages: options.messages,
        templateId: options.templateId,
        variables: options.variables,
        mode: options.mode || 'chat',
      })

      if (aborted) {
        bridge.llm.abortChat({ requestId: result.requestId })
        return
      }

      requestId = result.requestId
      unsub = bridge.llm.subscribe(result.requestId, {
        onChunk(data: { index: number; text: string }) {
          if (aborted) return
          options.onChunk?.(data.text)
        },
        onDone(data: { content: string; structured?: Record<string, any> }) {
          if (aborted) return
          options.signal?.removeEventListener('abort', abortHandler)
          unsub?.()
          resolve(data.content)
        },
        onError(errData: { message: string; code: string }) {
          if (aborted) return
          options.signal?.removeEventListener('abort', abortHandler)
          unsub?.()
          reject(new Error(errData.message))
        },
      })
    } catch (e) {
      if (!aborted) {
        options.signal?.removeEventListener('abort', abortHandler)
        reject(e)
      }
    }
  })
}

export async function testConnection(modelId: string): Promise<{ status: string; latency: number }> {
  if (!window.api) throw new Error('IPC bridge not available')
  const start = Date.now()
  try {
    await window.api.settings.testModel(modelId)
    return { status: 'ok', latency: Date.now() - start }
  } catch (e: any) {
    return { status: 'error', latency: Date.now() - start }
  }
}

export async function explainSymbol(
  params: {
    symbolName: string
    symbolType: string
    codeSnippet: string
    fileName?: string
  },
  onChunk?: (chunk: string) => void
): Promise<string> {
  return chat({
    templateId: 'source_explain',
    variables: {
      filePath: params.fileName || params.symbolName,
      fileName: params.fileName || params.symbolName,
      language: params.symbolType,
      codeContent: params.codeSnippet,
      symbolInfo: `- 符号名: ${params.symbolName}\n- 符号类型: ${params.symbolType}\n`,
    },
    onChunk,
  })
}

export async function explainEdge(
  params: {
    edgeType: 'CALL' | 'DEPENDENCE'
    source: string
    target: string
    callSite?: string
    includePath?: string
    isSystem?: boolean
  },
  onChunk?: (chunk: string) => void
): Promise<string> {
  return chat({
    templateId: 'edge_explain',
    variables: {
      edgeTypeLabel: params.edgeType === 'CALL' ? '调用关系' : '依赖关系',
      source: params.source,
      target: params.target,
      callSite: params.callSite ? `- 调用位置: ${params.callSite}\n` : '',
      includePath: params.includePath ? `- 包含路径: ${params.includePath}\n` : '',
      isSystem: params.isSystem !== undefined ? `- 系统头文件: ${params.isSystem ? '是' : '否'}\n` : '',
    },
    onChunk,
  })
}

export async function explainCommunity(
  params: {
    commId: string
    nodeCount: number
    edgeCount: number
    qualityScore: number
    description?: string
  },
  onChunk?: (chunk: string) => void
): Promise<string> {
  return chat({
    templateId: 'agent_explain_community',
    variables: {
      comm_id: params.commId,
      node_count: String(params.nodeCount),
      edge_count: String(params.edgeCount),
      quality_score: String(params.qualityScore),
      description: params.description ? `- 描述: ${params.description}` : '',
    },
    onChunk,
  })
}

export async function summarizeCode(
  code: string,
  onChunk?: (chunk: string) => void
): Promise<string> {
  return chat({
    templateId: 'src_to_pseudocode',
    variables: {
      language: 'code',
      code,
    },
    onChunk,
  })
}

export async function summarizeCommunityName(
  params: {
    nodeCount: number
    edgeCount: number
    nodeNames?: string[]
  },
  onChunk?: (chunk: string) => void
): Promise<string> {
  return chat({
    templateId: 'community_name',
    variables: {
      nodeCount: String(params.nodeCount),
      edgeCount: String(params.edgeCount),
      nodeNames: (params.nodeNames || []).slice(0, 20).join(', '),
    },
    mode: 'structured',
    onChunk,
  })
}
