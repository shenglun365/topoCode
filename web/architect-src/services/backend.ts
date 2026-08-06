import { apiGet } from './api-client'

/**
 * 后端可达性探测(一次性)。
 *
 * 以 `/git/status`(阶段 4 新增路由)为探针: 旧栈没有该路由 → 不可达 → 前端回退 mock;
 * 新栈具备 → 走真实后端。与 agent/unit-test 域的 ensureBackend 独立。
 */
let probed = false
let up = false

export async function backendUp(): Promise<boolean> {
  if (probed) return up
  probed = true
  try {
    await apiGet<unknown>('/git/status')
    up = true
  } catch {
    up = false
  }
  return up
}

/** 探测结果是否已确定且可达(同步读取, 仅探测完成后有效)。 */
export function backendReady(): boolean {
  return up
}
