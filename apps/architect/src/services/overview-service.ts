import type { OverviewData } from '@/types'
import { apiGet } from './api-client'
import { currentProjectParams } from './project-service'

/**
 * 概览页聚合接口：GET /overview 一次返回四组栏目所需数据
 * (launch / recent / adapters / kb / missions)，避免多次并发小请求。
 * 旧端点仍各自可用(project-service / agent-service / launch-service)。
 */
export async function getOverview(mode?: string): Promise<OverviewData | null> {
  try {
    const { root, project } = currentProjectParams()
    const qs = new URLSearchParams()
    if (mode) qs.set('mode', mode)
    if (root) qs.set('root', root)
    if (project) qs.set('project', project)
    const query = qs.toString()
    const data = await apiGet<OverviewData | null>(`/overview${query ? '?' + query : ''}`)
    return data && typeof data === 'object' ? data : null
  } catch {
    return null
  }
}