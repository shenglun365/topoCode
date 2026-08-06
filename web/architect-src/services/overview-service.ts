import type { OverviewData } from '@/types'
import { apiGet } from './api-client'

/**
 * 概览页聚合接口：GET /overview 一次返回四组栏目所需数据
 * (launch / recent / adapters / kb / missions)，避免多次并发小请求。
 * 旧端点仍各自可用(project-service / agent-service / launch-service)。
 */
export async function getOverview(mode?: string): Promise<OverviewData | null> {
  try {
    const qs = mode ? `?mode=${encodeURIComponent(mode)}` : ''
    const data = await apiGet<OverviewData | null>(`/overview${qs}`)
    return data && typeof data === 'object' ? data : null
  } catch {
    return null
  }
}