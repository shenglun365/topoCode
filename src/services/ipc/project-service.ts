import type {
  Project, FileTreeNode, ProjectStorageStats,
  FileChangesResult, PathValidityResult, UpdatePathResult, SuccessResponse,
} from '@/types/ipc'

function adaptProject(p: any): Project {
  if (!p) return null as any
  return {
    ...p,
    rootPath: p.root_path || p.rootPath || '',
    path: p.root_path || p.path || '',
    fileCount: p.file_count ?? p.fileCount ?? 0,
    needsResync: p.needs_resync ?? p.needsResync ?? 0,
    hasFileChanges: p.has_file_changes ?? p.hasFileChanges ?? 0,
    isSample: p.is_sample ?? p.isSample ?? 0,
    lastSync: p.last_sync ?? p.lastSync ?? null,
    createdAt: p.created_at ?? p.createdAt ?? '',
    groups: p.groups || [],
    doneTaskCount: p.done_task_count ?? p.doneTaskCount ?? 0,
  }
}

function adaptProjectList(list: any[]): Project[] {
  return (list || []).filter(Boolean).map(adaptProject)
}

export interface ProjectService {
  list(): Promise<Project[]>
  import(path: string): Promise<Project>
  get(id: string): Promise<Project | null>
  remove(id: string): Promise<void>
  sync(id: string): Promise<Project>
  getFileTree(id: string, fromPath?: string | null): Promise<FileTreeNode[]>
  updatePath(id: string, newRootPath: string): Promise<UpdatePathResult>
  checkFileChanges(id: string): Promise<FileChangesResult>
  initSampleData(): Promise<any>
  clearSampleData(id: string): Promise<SuccessResponse>
  checkPathValidity(id: string): Promise<PathValidityResult>
  updateMeta(id: string, meta: Record<string, any>): Promise<Project>
  getStorageStats(projectId: string): Promise<ProjectStorageStats>
}

export function createProjectService(api: any): ProjectService {
  return {
    list: async () => {
      const list = await api.project.list()
      return adaptProjectList(list)
    },
    import: async (path: string) => {
      const result = await api.project.import(path)
      return adaptProject(result)
    },
    get: async (id: string) => {
      const result = await api.project.get(id)
      return result ? adaptProject(result) : null
    },
    remove: async (id: string) => {
      await api.project.remove(id)
    },
    sync: async (id: string) => {
      const result = await api.project.sync(id)
      return adaptProject(result)
    },
    getFileTree: async (id: string, fromPath?: string | null) => {
      return await api.project.getFileTree(id, fromPath) as FileTreeNode[]
    },
    updatePath: async (id: string, newRootPath: string) => {
      return await api.project.updatePath(id, newRootPath) as UpdatePathResult
    },
    checkFileChanges: async (id: string) => {
      return await api.project.checkFileChanges(id) as FileChangesResult
    },
    initSampleData: async () => {
      return await api.project.initSampleData()
    },
    clearSampleData: async (id: string) => {
      return await api.project.clearSampleData(id) as SuccessResponse
    },
    checkPathValidity: async (id: string) => {
      return await api.project.checkPathValidity(id) as PathValidityResult
    },
    updateMeta: async (id: string, meta: Record<string, any>) => {
      const result = await api.project.updateMeta(id, meta)
      return adaptProject(result)
    },
    getStorageStats: async (projectId: string) => {
      return await api.project.getStorageStats(projectId) as ProjectStorageStats
    },
  }
}
