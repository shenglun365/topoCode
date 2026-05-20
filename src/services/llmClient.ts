/**
 * LLM 前端客户端 — v2 IPC 网关模式
 *
 * 通过 window.api.llm.chat (IPC → ZMQ → Python) 调用 LLM，
 * window.api.llm.subscribe 接收流式 chunk 事件。
 *
 * 保留业务方法 (explainSymbol / explainEdge / summarizeCode ...)，
 * 但核心 chat() 不再走 Worker。
 */

import { useSettingsStore } from '@/stores/settings'

// ==================== 配置管理 ====================

/**
 * 获取当前默认模型 ID
 */
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

/**
 * 检查 LLM API 是否已配置
 */
export function isLLMConfigured(): boolean {
  return getDefaultModelId() !== null
}

// ==================== 核心方法 ====================

export interface ChatOptions {
  messages: Array<{ role: string; content: string }>
  onChunk?: (chunk: string) => void
}

/**
 * 流式对话 — 通过 IPC 调用后端 LLM 网关
 *
 * 返回完整内容字符串。流式 chunk 通过 onChunk 回调实时推送。
 */
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
        mode: 'chat',
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

/**
 * 测试连接 — 通过后端 ping 指定模型
 */
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

// ==================== 业务方法 ====================

/**
 * 解释代码符号（函数/类/方法/宏）
 */
export async function explainSymbol(
  params: {
    symbolName: string
    symbolType: string
    codeSnippet: string
    fileName?: string
  }
): Promise<string> {
  const modelId = getDefaultModelId()
  if (!modelId) throw new Error('LLM API 未配置')
  if (!window.api) throw new Error('IPC bridge not available')

  try {
    const result = await window.api.llm.explainSymbol({
      symbolName: params.symbolName,
      symbolType: params.symbolType,
      codeSnippet: params.codeSnippet,
      fileName: params.fileName,
      modelId,
    })
    return result.content
  } catch (e) {
    throw e
  }
}

/**
 * 解释边的含义（调用关系/依赖关系）
 */
export async function explainEdge(
  params: {
    edgeType: 'CALL' | 'DEPENDENCE'
    source: string
    target: string
    callSite?: string
    includePath?: string
    isSystem?: boolean
  }
): Promise<string> {
  const systemPrompt = '你是一个专业的代码分析助手。用户会提供一个代码中的调用关系或依赖关系。请解释这个关系的含义和作用。用中文回答。'
  let userPrompt = `## 边信息\n- 类型: ${params.edgeType === 'CALL' ? '调用关系' : '依赖关系'}\n`
  userPrompt += `- 源: ${params.source}\n- 目标: ${params.target}\n`
  if (params.callSite) userPrompt += `- 调用位置: ${params.callSite}\n`
  if (params.includePath) userPrompt += `- 包含路径: ${params.includePath}\n`
  if (params.isSystem !== undefined) userPrompt += `- 系统头文件: ${params.isSystem ? '是' : '否'}\n`
  userPrompt += '\n请解释这个关系。'

  return chat({
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ],
  })
}

/**
 * 解释社区（未完全展开的社区节点）
 */
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

/**
 * 压缩长代码为伪码
 */
export async function summarizeCode(
  code: string,
  onChunk?: (chunk: string) => void
): Promise<string> {
  const systemPrompt = '你是一个代码压缩助手。用户会提供一段较长的代码，请将其压缩为简洁的伪码，保留核心逻辑和关键步骤。用中文回答。'
  const userPrompt = `请将以下代码压缩为伪码：\n\n\`\`\`\n${code}\n\`\`\`\n\n只保留核心逻辑，用简洁的中文伪码表示。`

  return chat({
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ],
    onChunk,
  })
}

/**
 * 总结社区名称（用于社区节点 label）
 */
export async function summarizeCommunityName(
  params: {
    nodeCount: number
    edgeCount: number
    nodeNames?: string[]
  },
  onChunk?: (chunk: string) => void
): Promise<string> {
  const systemPrompt = '你是一个代码架构命名助手。用户会提供一个代码社区的统计信息，请为其生成一个简洁的名称（不超过 10 个中文字）。只返回名称，不要其他内容。'
  let userPrompt = `社区信息：${params.nodeCount} 个节点，${params.edgeCount} 条边`
  if (params.nodeNames && params.nodeNames.length > 0) {
    userPrompt += `\n节点列表：${params.nodeNames.slice(0, 20).join(', ')}`
  }
  userPrompt += '\n\n请为这个社区生成一个简洁的名称。'

  return chat({
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt },
    ],
    onChunk,
  })
}
