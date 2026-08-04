import type { Requirement } from '@/types'
import { apiGet, apiPost, apiPatch } from './api-client'

export const requirementService = {
  async list(): Promise<Requirement[]> {
    return apiGet<Requirement[]>('/requirements')
  },
  async create(data: Partial<Requirement>): Promise<Requirement> {
    return apiPost<Requirement>('/requirements', data)
  },
  async update(id: string, data: Partial<Requirement>): Promise<Requirement> {
    return apiPatch<Requirement>(`/requirements/${id}`, data)
  },
}
