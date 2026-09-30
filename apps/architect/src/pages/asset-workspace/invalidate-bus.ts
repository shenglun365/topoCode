/**
 * 资产工作区失效总线（批4-3，R5）：替代手动刷新级联的单一失效入口。
 *
 * 发布：任务中心轮询发现作业完成(kind 匹配语义域)、提取/清除等写操作完成后。
 * 订阅：资产工作区挂载时注册刷新回调（loadSemantic/refreshStatus/loadOverview…），
 * 卸载时注销。防抖合并（同一 tick 多次失效只刷一轮）。
 */
export type Listener = (reason: string) => void

const listeners = new Set<Listener>()
let pending: string | null = null
let timer: ReturnType<typeof setTimeout> | null = null

/** 语义域作业 kind → 需要失效资产数据 */
const SEMANTIC_KINDS = new Set([
  'extract_delta', 'extract_unowned', 'extract_impl', 'extract_logic',
  'extract_scope', 'enhance_desc', 'enhance_semantic', 'gen_component_view',
])

export function invalidateAssets(reason: string): void {
  pending = pending ? `${pending},${reason}` : reason
  if (timer) return
  timer = setTimeout(() => {
    const r = pending || ''
    pending = null
    timer = null
    for (const fn of listeners) {
      try { fn(r) } catch { /* 订阅方异常不拖垮总线 */ }
    }
  }, 300)
}

export function onAssetsInvalidated(fn: Listener): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** 任务中心轮询回调：语义域作业从 running → 终态时发失效。 */
export function notifyJobFinished(job: { kind: string; state: string }): void {
  if (SEMANTIC_KINDS.has(job.kind) && job.state !== 'running' && job.state !== 'queued') {
    invalidateAssets(`job:${job.kind}:${job.state}`)
  }
}
