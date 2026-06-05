import type {
  KnowledgeDoc, KnowledgeGraph, DimensionsResult,
} from '@/types/ipc'
type KnowledgeDocDTO = KnowledgeDoc
type KnowledgeGraphDTO = KnowledgeGraph

function adaptDoc(d: any): KnowledgeDocDTO {
  if (!d) return null as any
  return {
    ...d,
    projectId: d.project_id ?? d.projectId,
    tags: typeof d.tags === 'string' ? JSON.parse(d.tags) : (d.tags || {}),
  }
}

export interface KnowledgeService {
  listDocs(params?: {
    search?: string
    dimensions?: { lifecycle?: string[]; techStack?: string[]; abstraction?: string[]; purpose?: string[] }
    sortBy?: string
  }): Promise<KnowledgeDocDTO[]>
  createDoc(params: {
    title: string; content: string; projectId: string; tags?: Partial<DimensionsResult>
  }): Promise<KnowledgeDocDTO>
  getDoc(id: string): Promise<KnowledgeDocDTO | null>
  updateDoc(params: {
    id: string; content?: string; tags?: Partial<DimensionsResult>;
    status?: string; favorite?: boolean; pinned?: boolean
  }): Promise<KnowledgeDocDTO>
  deleteDoc(id: string): Promise<void>
  getGraph(params?: { projectId?: string }): Promise<KnowledgeGraphDTO>
  getDimensions(): Promise<DimensionsResult>
}

export function createKnowledgeService(api: any): KnowledgeService {
  return {
    listDocs: async (params?) => {
      const list = await api.knowledge.listDocs(params || {})
      return (list || []).map(adaptDoc)
    },
    createDoc: async (params) => {
      const result = await api.knowledge.createDoc(params)
      return adaptDoc(result)
    },
    getDoc: async (id: string) => {
      const result = await api.knowledge.getDoc(id)
      return result ? adaptDoc(result) : null
    },
    updateDoc: async (params) => {
      const result = await api.knowledge.updateDoc(params)
      return adaptDoc(result)
    },
    deleteDoc: async (id: string) => {
      await api.knowledge.deleteDoc(id)
    },
    getGraph: async (params?) => {
      return await api.knowledge.getGraph(params || {}) as KnowledgeGraphDTO
    },
    getDimensions: async () => {
      return await api.knowledge.getDimensions() as DimensionsResult
    },
  }
}
