import type { LaunchInfo } from '@/types'
import { apiGet } from './api-client'

/**
 * 概览页「启动命令」数据源：后端 /launch。
 * 返回 execRoot/kbRoot/mode/productForm/scaffold，用于展示启动方式与宿主机工作目录。
 */
export async function getLaunch(): Promise<LaunchInfo | null> {
  try {
    const info = await apiGet<LaunchInfo | null>('/launch')
    return info && typeof info === 'object' ? info : null
  } catch {
    return null
  }
}