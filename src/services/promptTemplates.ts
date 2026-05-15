/**
 * LLM 提示词模板管理系统
 *
 * 统一管理社区解析、源码解析的提示词模板。
 * 支持: 非结构化输出(Markdown)、结构化输出(JSON)、tools call(未来拓展)、skills(未来拓展)
 */

// ==================== 类型定义 ====================

export type OutputFormat = 'markdown' | 'structured' | 'tool_call'
export type ParseMode = 'community' | 'source_code'

export interface PromptTemplate {
  id: string
  name: string
  mode: ParseMode
  outputFormat: OutputFormat
  /** 系统提示词 */
  systemPrompt: string
  /** 用户提示词模板, 支持 {variable} 占位符 */
  userPrompt: string
  /** 需要的变量列表 */
  variables: string[]
  /** 是否默认模板 */
  isDefault: boolean
}

export interface PromptVariable {
  key: string
  label: string
  description: string
  required: boolean
}

export interface ToolCallRequest {
  tool: 'getNodeDetail' | 'getSourceCode'
  params: {
    nodeId?: string
    filePath?: string
    symbolId?: string
  }[]
}

// ==================== 模板注册表 ====================

const templates: PromptTemplate[] = [
  // ---- 社区解析模板 ----
  {
    id: 'community_explain',
    name: '社区功能说明',
    mode: 'community',
    outputFormat: 'markdown',
    systemPrompt: `你是一个专业的软件架构分析专家。用户会提供一个代码社区(由 Louvain 社区发现算法生成的代码模块分组)的结构信息。
请根据提供的节点和边关系,分析并解释:
1. 这个社区在整体架构中承担什么角色
2. 核心功能模块有哪些
3. 模块间的协作关系
4. 可能的设计模式或架构风格
请用中文回答,保持专业且易于理解。使用 Markdown 格式组织内容。`,
    userPrompt: `## 社区信息
- 社区ID: {commId}
- 节点数: {nodeCount}
- 边数: {edgeCount}
- 质量分数: {qualityScore}

## 节点列表(语法结构/文件)
{nodeList}

## 边关系(调用/依赖)
{edgeList}

{detailNodes}

请分析这个社区的功能和架构含义。`,
    variables: ['commId', 'nodeCount', 'edgeCount', 'qualityScore', 'nodeList', 'edgeList', 'detailNodes'],
    isDefault: true,
  },
  {
    id: 'community_architecture',
    name: '社区架构说明',
    mode: 'community',
    outputFormat: 'structured',
    systemPrompt: `你是一个软件架构师。请根据提供的代码社区结构信息,生成结构化的架构说明文档。
输出格式要求:
- 使用 Markdown 标题层级组织
- 包含: 概述、模块划分、核心流程、依赖关系、设计评价
- 每个模块用表格列出关键节点
- 使用 Mermaid 图表展示模块关系`,
    userPrompt: `## 社区结构数据
- 社区ID: {commId}
- 节点数: {nodeCount}
- 边数: {edgeCount}

## 节点列表
{nodeList}

## 边关系
{edgeList}

{detailNodes}

请生成结构化的架构说明文档。`,
    variables: ['commId', 'nodeCount', 'edgeCount', 'nodeList', 'edgeList', 'detailNodes'],
    isDefault: false,
  },
  {
    id: 'community_business',
    name: '业务场景适配分析',
    mode: 'community',
    outputFormat: 'markdown',
    systemPrompt: `你是一个业务架构分析师。请根据提供的代码社区结构,分析:
1. 这段代码可能适配的业务场景
2. 核心业务流程
3. 可扩展性评估
4. 可能的优化方向
用中文回答,结合软件工程最佳实践。`,
    userPrompt: `## 社区结构
- 社区ID: {commId}
- 节点数: {nodeCount}
- 边数: {edgeCount}

## 节点列表
{nodeList}

## 边关系
{edgeList}

{detailNodes}

请分析这个社区适配的业务场景。`,
    variables: ['commId', 'nodeCount', 'edgeCount', 'nodeList', 'edgeList', 'detailNodes'],
    isDefault: false,
  },
  {
    id: 'community_pseudocode',
    name: '社区伪代码生成',
    mode: 'community',
    outputFormat: 'markdown',
    systemPrompt: `你是一个代码抽象专家。请根据提供的代码社区结构信息,生成该社区核心逻辑的伪代码。
要求:
- 保留核心算法流程和关键判断逻辑
- 用中文注释说明每个步骤
- 忽略具体语法细节,关注逻辑结构`,
    userPrompt: `## 社区结构
- 社区ID: {commId}
- 节点数: {nodeCount}

## 节点列表
{nodeList}

## 边关系
{edgeList}

{detailNodes}

请生成这个社区核心逻辑的伪代码。`,
    variables: ['commId', 'nodeCount', 'nodeList', 'edgeList', 'detailNodes'],
    isDefault: false,
  },

  // ---- 源码解析模板 ----
  {
    id: 'source_explain',
    name: '源码功能说明',
    mode: 'source_code',
    outputFormat: 'markdown',
    systemPrompt: `你是一个代码解释专家。用户会提供一段源码及其上下文信息。请解释:
1. 这段代码实现什么功能
2. 核心逻辑流程
3. 关键数据结构和算法
4. 可能的边界条件处理
用中文回答,保持简洁专业。`,
    userPrompt: `## 文件信息
- 文件路径: {filePath}
- 文件名: {fileName}
- 语言: {language}

## 代码内容
\`\`\`{language}
{codeContent}
\`\`\`

请解释这段代码的功能。`,
    variables: ['filePath', 'fileName', 'language', 'codeContent'],
    isDefault: true,
  },
  {
    id: 'source_summary',
    name: '源码摘要',
    mode: 'source_code',
    outputFormat: 'markdown',
    systemPrompt: `你是一个代码摘要专家。请为提供的源码生成简洁的功能摘要。
要求:
- 不超过 200 字
- 说明核心功能和关键接口
- 适合用作文档索引`,
    userPrompt: `## 文件: {filePath}

\`\`\`{language}
{codeContent}
\`\`\`

请生成这段代码的功能摘要。`,
    variables: ['filePath', 'language', 'codeContent'],
    isDefault: false,
  },
  {
    id: 'source_pseudocode',
    name: '源码伪代码',
    mode: 'source_code',
    outputFormat: 'markdown',
    systemPrompt: `你是一个代码抽象专家。请将提供的源码转换为简洁的伪代码,保留核心逻辑和关键步骤。
要求:
- 使用中文关键字和注释
- 保留循环、条件、函数调用等核心结构
- 省略具体语法细节`,
    userPrompt: `## 文件: {filePath}

\`\`\`{language}
{codeContent}
\`\`\`

请将这段代码转换为伪代码。`,
    variables: ['filePath', 'language', 'codeContent'],
    isDefault: false,
  },
]

// ==================== 工具函数 ====================

/**
 * 获取所有模板
 */
export function getAllTemplates(): PromptTemplate[] {
  return templates
}

/**
 * 按解析模式获取模板
 */
export function getTemplatesByMode(mode: ParseMode): PromptTemplate[] {
  return templates.filter(t => t.mode === mode)
}

/**
 * 按 ID 获取模板
 */
export function getTemplateById(id: string): PromptTemplate | undefined {
  return templates.find(t => t.id === id)
}

/**
 * 获取默认模板
 */
export function getDefaultTemplate(mode: ParseMode): PromptTemplate | undefined {
  return templates.find(t => t.mode === mode && t.isDefault)
}

/**
 * 渲染提示词模板, 替换占位符
 * @param template 模板对象
 * @param variables 变量键值对
 */
export function renderPrompt(
  template: PromptTemplate,
  variables: Record<string, string>
): { systemPrompt: string; userPrompt: string } {
  const systemPrompt = template.systemPrompt
  const userPrompt = template.userPrompt.replace(/\{(\w+)\}/g, (_, key) => {
    return variables[key] ?? `{${key}}`
  })
  return { systemPrompt, userPrompt }
}

/**
 * 获取模板需要的变量列表
 */
export function getTemplateVariables(template: PromptTemplate): PromptVariable[] {
  return template.variables.map(key => ({
    key,
    label: key,
    description: `变量: ${key}`,
    required: true,
  }))
}
