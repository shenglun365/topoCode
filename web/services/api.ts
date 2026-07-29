import type { Project, Task, ChatSession, ChatMessage, ModelConfig, Note, GraphNode, GraphEdge, CommunityDoc, CommunityChild } from '@web/types'

const API_BASE = ''

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v))
  }
  const resp = await fetch(url.toString())
  if (!resp.ok) {
    const err = await resp.text().catch(() => resp.statusText)
    throw new Error(`API ${resp.status}: ${err}`)
  }
  return resp.json()
}

async function post<T>(path: string, body?: any): Promise<T> {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) throw new Error(`API ${resp.status}`)
  return resp.json()
}

async function put<T>(path: string, body: any): Promise<T> {
  const resp = await fetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`API ${resp.status}`)
  return resp.json()
}

async function del<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v))
  }
  const resp = await fetch(url.toString(), { method: 'DELETE' })
  if (!resp.ok) throw new Error(`API ${resp.status}`)
  return resp.json()
}

// ── Projects & Tasks ──

export function listProjects(): Promise<Project[]> {
  return get<Project[]>('/api/projects')
}

export function listTasks(projectId: string): Promise<Task[]> {
  return get<Task[]>('/api/tasks', { project_id: projectId })
}

// ── Chat Sessions ──

export function listSessions(projectId?: string): Promise<{ sessions: ChatSession[]; total: number }> {
  const params: Record<string, string> = {}
  if (projectId) params.project_id = projectId
  return get('/api/chat/sessions', params)
}

export function createSession(title: string, modelId?: string): Promise<ChatSession> {
  return post('/api/chat/sessions', { title, modelId })
}

export function getSession(id: string): Promise<ChatSession & { messages: ChatMessage[] }> {
  return get(`/api/chat/sessions/${id}`)
}

export function deleteSession(id: string): Promise<{ ok: boolean }> {
  return del(`/api/chat/sessions/${id}`)
}

export function updateSession(id: string, data: Partial<ChatSession>): Promise<{ ok: boolean }> {
  return put(`/api/chat/sessions/${id}`, data)
}

// ── Messages ──

export function getMessages(sessionId: string, limit = 50, offset = 0, debug = false): Promise<{ messages: ChatMessage[]; total: number }> {
  return get(`/api/chat/sessions/${sessionId}/messages`, { limit: String(limit), offset: String(offset), debug: String(debug) })
}

export function deleteMessages(sessionId: string, messageId: string): Promise<{ ok: boolean }> {
  return del(`/api/chat/sessions/${sessionId}/messages?message_id=${messageId}`)
}

// ── Models ──

export function listModels(): Promise<{ models: ModelConfig[]; webChatDefaultModelId: string | null }> {
  return get('/api/models')
}

// ── Notes ──

export function listNotes(status?: string, projectId?: string): Promise<{ notes: Note[]; total: number }> {
  const params: Record<string, string> = {}
  if (status) params.status = status
  if (projectId) params.project_id = projectId
  return get('/api/notes', params)
}

export function createNote(data: Partial<Note>): Promise<{ id: string; title: string; ok: boolean }> {
  return post('/api/notes', data)
}

export function deleteNote(id: string): Promise<{ ok: boolean }> {
  return del(`/api/notes/${id}`)
}

// ── Community / Graph ──

export function getCommunityDoc(taskId: string, communityId: string, edgeType?: string): Promise<CommunityDoc> {
  return get('/api/community-doc', { task_id: taskId, community_id: communityId, edge_type: edgeType || 'CALL' })
}

export function getCommunityChildren(taskId: string, parentCommId?: string, edgeType?: string): Promise<CommunityChild[]> {
  const params: Record<string, string> = { task_id: taskId }
  if (parentCommId) params.parent_comm_id = parentCommId
  if (edgeType) params.edge_type = edgeType
  return get('/api/community-children', params)
}

export function getCommunityGraph(taskId: string, edgeType?: string, commId?: string, gran?: string, depth?: number): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
  const params: Record<string, string> = { task_id: taskId, edge_type: edgeType || 'CALL' }
  if (commId) params.comm_id = commId
  if (gran) params.gran = gran
  if (depth) params.depth = String(depth)
  return get('/api/community-graph', params)
}

export function getSkills(): Promise<{ skills: any[]; defaults: string[] }> {
  return get('/api/skills')
}

export function getHeatmap(taskId: string, edgeType?: string, size?: number, commId?: string): Promise<any> {
  const params: Record<string, string> = { task_id: taskId, edge_type: edgeType || 'CALL', size: String(size || 10) }
  if (commId) params.comm_id = commId
  return get('/api/heatmap', params)
}

export function getExternalStats(taskId: string): Promise<any> {
  return get('/api/external-stats', { task_id: taskId })
}

export function listArchives(projectId?: string): Promise<{ archives: any[]; total: number }> {
  const params: Record<string, string> = {}
  if (projectId) params.project_id = projectId
  return get('/api/chat/archives', params)
}

export function deleteArchive(id: string): Promise<{ ok: boolean }> {
  return del(`/api/chat/archives/${id}`)
}

export function updateDoc(docId: string, data: any): Promise<any> {
  return put(`/api/documents/${docId}`, data)
}

export { get, post, put, del }
