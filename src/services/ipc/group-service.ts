import type { GroupNode, SuccessResponse } from '@/types/ipc'

export interface GroupService {
  list(): Promise<GroupNode[]>
  create(name: string, parentId?: string | null): Promise<GroupNode>
  update(id: string, name?: string, parentId?: string | null): Promise<SuccessResponse>
  delete(id: string): Promise<SuccessResponse>
  addProject(projectId: string, groupId: string): Promise<SuccessResponse>
  removeProject(projectId: string, groupId: string): Promise<SuccessResponse>
  getProjectGroups(projectId: string): Promise<GroupNode[]>
}

export function createGroupService(api: any): GroupService {
  return {
    list: async () => {
      return await api.group.list() as GroupNode[]
    },
    create: async (name: string, parentId?: string | null) => {
      return await api.group.create(name, parentId || null) as GroupNode
    },
    update: async (id: string, name?: string, parentId?: string | null) => {
      return await api.group.update(id, name, parentId ?? null) as SuccessResponse
    },
    delete: async (id: string) => {
      return await api.group.delete(id) as SuccessResponse
    },
    addProject: async (projectId: string, groupId: string) => {
      return await api.group.addProject(projectId, groupId) as SuccessResponse
    },
    removeProject: async (projectId: string, groupId: string) => {
      return await api.group.removeProject(projectId, groupId) as SuccessResponse
    },
    getProjectGroups: async (projectId: string) => {
      return await api.group.getProjectGroups(projectId) as GroupNode[]
    },
  }
}
