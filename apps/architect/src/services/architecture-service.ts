import type { ArchitectureModel } from '@/types'
import { apiGet } from './api-client'
import { currentProjectParams } from './project-service'

function ctx(): string {
  const { root, project } = currentProjectParams()
  const qs = new URLSearchParams()
  if (root) qs.set('root', root)
  if (project) qs.set('project', project)
  return qs.toString()
}

export const architectureService = {
  async loadModel(version: 'v0' | 'v1'): Promise<ArchitectureModel> {
    const ext = ctx()
    return apiGet<ArchitectureModel>(`/kb/model?version=${version}${ext ? '&' + ext : ''}`)
  },
}
