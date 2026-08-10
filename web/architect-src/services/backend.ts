import { apiGet } from './api-client'

/**
 * 后端可达性探测(结果带时效, 失败会自动重探)。
 *
 * 以 `/git/status`(阶段 4 新增路由)为探针: 旧栈没有该路由 → 不可达 → 前端回退 mock;
 * 新栈具备 → 走真实后端。与 agent/unit-test 域的 ensureBackend 独立。
 */
let up = false
let lastProbeAt = 0
const PROBE_TTL = 30_000

async function probe(): Promise<void> {
  const now = Date.now()
  if (up && now - lastProbeAt < PROBE_TTL) return
  try {
    await apiGet<unknown>('/git/status')
    up = true
  } catch {
    up = false
  }
  lastProbeAt = now
}

export async function backendUp(): Promise<boolean> {
  await probe()
  return up
}

/** 强制重新探测(页面挂载等关键时机，确保恢复真实后端而非永久停留在 mock)。 */
export async function reProbeBackend(): Promise<boolean> {
  up = false
  lastProbeAt = 0
  await probe()
  return up
}

/** 探测结果是否已确认可达(同步读取, 仅探测完成后有效)。 */
export function backendReady(): boolean {
  return up
}
