import { apiGet } from './api-client'
import { currentProjectParams } from './project-service'

export interface GitLogEntry {
  oid: string
  subject: string
  author: string
  date: string
}

export interface GitLogResult {
  entries: GitLogEntry[]
  baseline: string
}

/** 后端不可达时保持旧行为(空结果), 不中断 UI。 */
function fallback<T>(value: T): T {
  return value
}

const gitService = {
  /** 近期提交 + 基线 commit(资产 diff 对比选择器数据源)。显式携带当前项目上下文。 */
  async commitLog(limit = 50): Promise<GitLogResult> {
    try {
      const { root, project } = currentProjectParams()
      const qs = new URLSearchParams({ limit: String(limit) })
      if (root) qs.set('root', root)
      if (project) qs.set('project', project)
      return await apiGet<GitLogResult>(`/git/log?${qs.toString()}`)
    } catch {
      return fallback({ entries: [], baseline: '' })
    }
  },
}

export { gitService }
