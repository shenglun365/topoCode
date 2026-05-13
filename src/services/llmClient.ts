/**
 * LLM 前端客户端 — 双通道调用
 *
 * 1. 前端直调: 通过 llmService 直接 fetch 调用 LLM API（流式）
 * 2. 后端代理: 通过 Electron IPC → ZeroMQ → Python 后端（非流式）
 *
 * 默认优先前端直调，失败时自动降级到后端代理。
 */

import { llmService } from '@/services/llm'
import { useSettingsStore } from '@/stores/settings'
import type { ModelConfigItem } from '@/types/ipc'

// ==================== 配置管理 ====================

/**
 * 获取当前默认模型配置
 */
function getDefaultModel(): ModelConfigItem | null {
  try {
    const store = useSettingsStore()
    const defaultModel = store.models.find(m => m.isDefault)
    return defaultModel || store.models[0] || null
  } catch {
    return null
  }
}

/**
 * 检查 LLM API 是否已配置
 */
export function isLLMConfigured(): boolean {
  const model = getDefaultModel()
  return !!model
}

/**
 * 确保 LLM 已配置并设置到 service
 */
function ensureConfig(): ModelConfigItem | null {
  const model = getDefaultModel()
  if (model) {
    llmService.setConfig(model)
  }
  return model
}

/**
 * 通过后端代理调用 LLM（非流式）
 */
async function callBackendLLM(method: string, params: Record<string, any>): Promise<any> {
  return window.api.ipc.invoke(`llm.${method}`, params)
}

// ==================== 代码解释 ====================

export interface ExplainResult {
  content: string
  streaming: boolean
}

/**
 * 解释代码符号（函数/类/方法/宏）
 * @param symbolName 符号名称
 * @param symbolType 符号类型
 * @param codeSnippet 代码片段
 * @param onChunk 流式回调（仅前端直调支持）
 */
export async function explainSymbol(
  params: {
    symbolName: string
    symbolType: string
    codeSnippet: string
    fileName?: string
  },
  onChunk?: (chunk: string) => void
): Promise<string> {
  const model = ensureConfig()
  if (!model) {
    throw new Error('LLM API 未配置')
  }

  const systemPrompt = `你是一个专业的代码分析助手。用户会提供一个代码符号（函数/类/方法/宏）及其代码片段。请用简洁的语言解释：
1. 这个符号的功能和作用
2. 关键参数和返回值
3. 在项目中可能的角色
请用中文回答，保持简洁专业。`

  const userPrompt = `## 符号信息
- 名称: ${params.symbolName}
- 类型: ${params.symbolType}
${params.fileName ? `- 文件: ${params.fileName}` : ''}

## 代码片段
\`\`\`
${params.codeSnippet}
\`\`\`

请解释这个代码符号。`

  // 优先前端直调
  try {
    return await llmService.chat(
      [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt },
      ],
      onChunk
    )
  } catch {
    // 降级到后端代理
    const result = await callBackendLLM('explainSymbol', {
      symbolName: params.symbolName,
      symbolType: params.symbolType,
      codeSnippet: params.codeSnippet,
      fileName: params.fileName,
    })
    return result.content
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
  },
  onChunk?: (chunk: string) => void
): Promise<string> {
  const model = ensureConfig()
  if (!model) throw new Error('LLM API 未配置')

  const systemPrompt = `你是一个专业的代码分析助手。用户会提供一个代码中的调用关系或依赖关系。请解释这个关系的含义和作用。用中文回答。`
  let userPrompt = `## 边信息\n- 类型: ${params.edgeType === 'CALL' ? '调用关系' : '依赖关系'}\n`
  userPrompt += `- 源: ${params.source}\n- 目标: ${params.target}\n`
  if (params.callSite) userPrompt += `- 调用位置: ${params.callSite}\n`
  if (params.includePath) userPrompt += `- 包含路径: ${params.includePath}\n`
  if (params.isSystem !== undefined) userPrompt += `- 系统头文件: ${params.isSystem ? '是' : '否'}\n`
  userPrompt += '\n请解释这个关系。'

  try {
    return await llmService.chat(
      [{ role: 'system', content: systemPrompt }, { role: 'user', content: userPrompt }],
      onChunk
    )
  } catch {
    // explainEdge 无后端代理，直接报错
    throw new Error('LLM 调用失败')
  }
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
  const model = ensureConfig()
  if (!model) throw new Error('LLM API 未配置')

  const systemPrompt = `你是一个专业的代码架构分析助手。用户会提供一个代码社区（由 Louvain 算法生成的代码模块分组）。请解释这个社区的可能含义。用中文回答。`
  const userPrompt = `## 社区信息
- 社区 ID: ${params.commId}
- 节点数: ${params.nodeCount}
- 边数: ${params.edgeCount}
- 质量分数: ${params.qualityScore}
${params.description ? `- 描述: ${params.description}` : ''}

请解释这个社区在代码架构中可能代表的模块或功能。`

  try {
    return await llmService.chat(
      [{ role: 'system', content: systemPrompt }, { role: 'user', content: userPrompt }],
      onChunk
    )
  } catch {
    throw new Error('LLM 调用失败')
  }
}

/**
 * 压缩长代码为伪码
 */
export async function summarizeCode(
  code: string,
  onChunk?: (chunk: string) => void
): Promise<string> {
  const model = ensureConfig()
  if (!model) throw new Error('LLM API 未配置')

  const systemPrompt = `你是一个代码压缩助手。用户会提供一段较长的代码，请将其压缩为简洁的伪码，保留核心逻辑和关键步骤。用中文回答。`
  const userPrompt = `请将以下代码压缩为伪码：\n\n\`\`\`\n${code}\n\`\`\`\n\n只保留核心逻辑，用简洁的中文伪码表示。`

  // 优先前端直调
  try {
    return await llmService.chat(
      [{ role: 'system', content: systemPrompt }, { role: 'user', content: userPrompt }],
      onChunk
    )
  } catch {
    // 降级到后端代理
    const result = await callBackendLLM('summarizeCode', { code })
    return result.content
  }
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
  const model = ensureConfig()
  if (!model) throw new Error('LLM API 未配置')

  const systemPrompt = `你是一个代码架构命名助手。用户会提供一个代码社区的统计信息，请为其生成一个简洁的名称（不超过 10 个中文字）。只返回名称，不要其他内容。`
  let userPrompt = `社区信息：${params.nodeCount} 个节点，${params.edgeCount} 条边`
  if (params.nodeNames && params.nodeNames.length > 0) {
    userPrompt += `\n节点列表：${params.nodeNames.slice(0, 20).join(', ')}`
  }
  userPrompt += '\n\n请为这个社区生成一个简洁的名称。'

  // 优先前端直调
  try {
    return await llmService.chat(
      [{ role: 'system', content: systemPrompt }, { role: 'user', content: userPrompt }],
      onChunk
    )
  } catch {
    // 降级到后端代理
    const result = await callBackendLLM('summarizeCommunityName', {
      nodeCount: params.nodeCount,
      edgeCount: params.edgeCount,
      nodeNames: params.nodeNames,
    })
    return result.content
  }
}
