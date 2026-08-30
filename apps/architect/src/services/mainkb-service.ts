import { apiGet } from './api-client'
import { currentProjectParams } from './project-service'

/**
 * 主 KB 对接适配接口 —— A2' 预留（plan-C §5.4/§5.6）。
 * 仅对接状态查询；"单机→主 KB 晋升"本体预留未实现（后端 501）。
 * 后端失败直接抛出——不复用本地 mock。
 */

function ctx(): string {
  const { root, project } = currentProjectParams()
  const qs = new URLSearchParams()
  if (root) qs.set('root', root)
  if (project) qs.set('project', project)
  return qs.toString()
}

export interface MainKbPromotion {
  implemented: boolean
  reserved: boolean
  note: string
}

export interface MainKbStatus {
  projectId: string
  mode: 'standalone' | 'main-kb'
  associated: boolean
  kbProjectId: string
  deepLink: string
  promotion: MainKbPromotion
}

export const mainkbService = {
  /** 主 KB 对接状态：授权策略开关（standalone / main-kb）+ 深链 + 晋升预留位。 */
  async status(): Promise<MainKbStatus> {
    const qs = ctx()
    return apiGet<MainKbStatus>(`/mainkb/status${qs ? `?${qs}` : ''}`)
  },
}
