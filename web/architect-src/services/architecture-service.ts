import type { ArchitectureModel } from '@/types'
import { apiGet } from './api-client'

export const architectureService = {
  async loadModel(version: 'v0' | 'v1'): Promise<ArchitectureModel> {
    return apiGet<ArchitectureModel>(`/kb/model?version=${version}`)
  },
}
