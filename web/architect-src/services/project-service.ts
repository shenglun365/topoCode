import type { ProjectInfo, RepoStatus, Snapshot } from '@/types'
import { apiGet, apiPost } from './api-client'

function resolveRootPath(): string {
  const params = new URLSearchParams(window.location.search)
  const root = params.get('root')
  if (root) return root
  return import.meta.env.VITE_BOUND_ROOT || ''
}

function resolveKbRoot(): string | undefined {
  return new URLSearchParams(window.location.search).get('kb') || undefined
}

export const projectService = {
  async getBound(): Promise<ProjectInfo> {
    const params = new URLSearchParams()
    const rootPath = resolveRootPath()
    if (rootPath) params.set('root', rootPath)
    const kbRoot = resolveKbRoot()
    if (kbRoot) params.set('kb', kbRoot)
    const qs = params.toString()
    return apiGet<ProjectInfo>(`/project/bound${qs ? '?' + qs : ''}`)
  },
  async createGreenfield(opts: {
    name?: string; desc?: string; language?: string; framework?: string;
    moduleLayout?: string; productForm?: string; execRoot?: string; kbRoot?: string
  }): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/bound', opts)
  },
  async status(): Promise<RepoStatus> {
    return apiGet<RepoStatus>('/project/status')
  },
  async snapshots(): Promise<Snapshot[]> {
    return apiGet<Snapshot[]>('/project/snapshots')
  },
}
