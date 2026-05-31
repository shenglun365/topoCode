import { useSettingsStore } from '@/stores/settings'

function getDefaultModelId(): string | null {
  try {
    const store = useSettingsStore()
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
}

export function chat(options: ChatOptions): Promise<string> {
  const modelId = getDefaultModelId()
  if (!modelId) throw new Error('LLM API 未配置')
  if (!window.api) throw new Error('IPC bridge not available')
  const bridge = window.api

  return new Promise<string>(async (resolve, reject) => {
    try {
      const result = await bridge.llm.chat({
        sessionId: `_inline_${Date.now()}`,
        modelId,
        messages: options.messages,
        templateId: options.templateId,
        variables: options.variables,
        mode: options.mode || 'chat',
      })

      const unsubscribe = bridge.llm.subscribe(result.requestId, {
        onChunk(data: { index: number; text: string }) {
          options.onChunk?.(data.text)
        },
        onDone(data: { content: string; structured?: Record<string, any> }) {
          unsubscribe()
          resolve(data.content)
        },
        onError(errData: { message: string; code: string }) {
          unsubscribe()
          reject(new Error(errData.message))
        },
      })
    } catch (e) {
      reject(e)
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
  const systemPrompt = '你是一个专业的代码架构分析助手。用户会提供一个代码社区（由 Louvain 算法生成的代码模块分组）。请解释这个社区的可能含义。用中文回答。'
  const userPrompt = `## 社区信息
- 社区 ID: ${params.commId}
- 节点数: ${params.nodeCount}
- 边数: ${params.edgeCount}
- 质量分数: ${params.qualityScore}
${params.description ? `- 描述: ${params.description}` : ''}

请解释这个社区在代码架构中可能代表的模块或功能。`

  return chat({
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ],
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
