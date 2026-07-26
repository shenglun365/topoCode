export interface Project {
  id: string
  name: string
  rootPath: string
  isResource: boolean
}

export interface Task {
  id: string
  name: string
  type: string
  status: string
  projectId: string
  hasDoc: boolean
}

export interface ChatSession {
  id: string
  title: string
  projectId: string
  modelId: string
  status: string
  activeSkills: string[]
  messageCount: number
  createdAt: string
  updatedAt: string
}

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, any>
  result?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool' | 'error'
  content: string
  refs?: any[]
  reasoning?: string
  toolCalls?: ToolCall[]
  createdAt?: string
  isStreaming?: boolean
  showReasoning?: boolean
  showToolCalls?: boolean
  qualityLow?: boolean
}

export interface ModelConfig {
  id: string
  name: string
  provider: string
  model: string
  isDefault: boolean
  badge: string
}

export interface Note {
  id: string
  title: string
  content: string
  refs: any[]
  status: 'draft' | 'sent'
  sessionId: string
  projectId: string
  createdAt: string
  updatedAt: string
}

export interface GraphNode {
  id: string
  label: string
}

export interface GraphEdge {
  id: string
  source: string
  target: string
}

export interface CommunityDoc {
  id: string
  taskId: string
  projectId: string
  projectName: string
  title: string
  content: string
  createdAt: string
  updatedAt: string
}

export interface CommunityChild {
  commId: string
  name: string
  commLv: string
  parentId?: string
  edgeType?: string
  nodeCount?: number
}
