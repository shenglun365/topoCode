import type { DirAnalysis, DirList } from '@/types'
import { apiGet, apiPost } from './api-client'

/** 宿主目录浏览/新建/分析(打开新项目弹窗用)。 */
export const dirService = {
  /** 列出目录内容；path 缺省为主目录。 */
  async list(path?: string): Promise<DirList> {
    const qs = path ? `?path=${encodeURIComponent(path)}` : ''
    return apiGet<DirList>(`/dir/list${qs}`)
  },
  /** 在指定父目录下新建目录(需父目录写权限)。 */
  async createDir(parent: string, name: string): Promise<{ path: string; name: string; readable: boolean; writable: boolean }> {
    return apiPost('/dir/create', { parent, name })
  },
  /** 分析选定目录(建 architect 项目根目录前的前置识别)。 */
  async analyze(root: string): Promise<DirAnalysis> {
    return apiPost('/dir/analyze', { root })
  },
}
