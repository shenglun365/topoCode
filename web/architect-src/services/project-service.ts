import type { KbProject, ProjectInfo, RepoStatus, Snapshot } from '@/types'
import { apiGet, apiPost } from './api-client'
import router from '@/router'

/** 当前 URL 中的项目选择参数(持久化在 URL，多页签各处理不同项目)。 */
export function currentProjectParams(): { root?: string; project?: string } {
  const q = router.currentRoute.value.query
  const root = typeof q.root === 'string' ? q.root : undefined
  const project = typeof q.project === 'string' ? q.project : undefined
  return { root: root || undefined, project: project || undefined }
}

function resolveRootPath(): string {
  const { root } = currentProjectParams()
  if (root) return root
  return import.meta.env.VITE_BOUND_ROOT || ''
}

function projectQuery(): URLSearchParams {
  const params = new URLSearchParams()
  const { project } = currentProjectParams()
  if (project) params.set('project', project)
  const rootPath = resolveRootPath()
  if (rootPath) params.set('root', rootPath)
  return params
}

export const projectService = {
  async getBound(): Promise<ProjectInfo | null> {
    const qs = projectQuery().toString()
    return apiGet<ProjectInfo | null>(`/project/bound${qs ? '?' + qs : ''}`)
  },
  async createGreenfield(opts: {
    name?: string; desc?: string; language?: string; framework?: string;
    moduleLayout?: string; productForm?: string; execRoot?: string; kbRoot?: string
  }): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/bound', opts)
  },
  /** 列出 KB 项目(KB 关联源候选)。 */
  async listKbProjects(): Promise<KbProject[]> {
    return apiGet<KbProject[]>('/project/kb/list')
  },
  /** 近期项目列表：architect 自持项目(arch_projects)按最近更新倒序。 */
  async listProjects(): Promise<ProjectInfo[]> {
    try {
      const list = await apiGet<ProjectInfo[] | null>('/project/list')
      return list ?? []
    } catch {
      return []
    }
  },
  /** 置顶 / 收藏切换。 */
  async flagProject(opts: { execRoot?: string; root?: string; project?: string; pinned?: boolean; favorite?: boolean }): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/flag', opts)
  },
  /** 删除项目列表记录(可选同时删除 architect 相关数据，如架构快照)。 */
  async deleteProject(opts: { execRoot?: string; root?: string; project?: string; deleteData?: boolean }): Promise<{ deleted: boolean; deleteData: boolean; id: string }> {
    return apiPost('/project/delete', opts)
  },
  /** 打开工作目录并(可选)关联 KB：校验通过后登记 arch_projects(选择持久化在 URL ?root=)。 */
  async bindKbProject(kbProjectId: string, execRoot: string, name?: string): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/bind', { kbProjectId, execRoot, name })
  },
  /** 仅打开工作目录(不关联 KB)。 */
  async bindWorkingDir(execRoot: string, name?: string): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/bind', { execRoot, name })
  },
  /** 项目页后补关联 KB(同源校验由后端执行)。 */
  async linkKb(kbProjectId: string, execRoot?: string): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/link', { kbProjectId, execRoot })
  },
  /** 解除 KB 关联(architect 项目保留)。 */
  async unlinkKb(): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/unlink', {})
  },
  /** 解除选择(URL 参数清除由 store 处理)。 */
  async unbind(): Promise<boolean> {
    return apiPost<boolean>('/project/unbind')
  },
  async status(): Promise<RepoStatus | null> {
    const qs = projectQuery().toString()
    return apiGet<RepoStatus | null>(`/project/status${qs ? '?' + qs : ''}`)
  },
  async snapshots(): Promise<Snapshot[]> {
    const qs = projectQuery().toString()
    return apiGet<Snapshot[]>(`/project/snapshots${qs ? '?' + qs : ''}`)
  },
}
