import type { LaunchInfo } from '@/types'
import { apiGet } from './api-client'
import { currentProjectParams } from './project-service'

/**
 * 概览页「启动命令」数据源：后端 /launch(透传当前项目上下文)。
 * 返回 execRoot/kbRoot/mode/productForm/scaffold，用于展示启动方式与宿主机工作目录。
 */
export async function getLaunch(): Promise<LaunchInfo | null> {
  try {
    const { root, project } = currentProjectParams()
    const qs = new URLSearchParams()
    if (root) qs.set('root', root)
    if (project) qs.set('project', project)
    const query = qs.toString()
    const info = await apiGet<LaunchInfo | null>(`/launch${query ? '?' + query : ''}`)
    return info && typeof info === 'object' ? info : null
  } catch {
    return null
  }
}