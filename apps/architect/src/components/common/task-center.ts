/**
 * 全局任务中心（批 1-5）：语义作业浮窗。
 * 数据源 /kb/semantic/jobs（持久化作业行，跨页面/刷新存活）；轮询 2.5s
 * （仅展开或 badge 有活跃作业时激活）。入口：WorkbenchLayout 全局挂载，
 * 各页面可按需引用 `taskCenterVisible` 呼出。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiGet, apiPost } from '@/services/api-client'
import { currentProjectParams } from '@/services/project-service'

export interface SemanticJob {
  id: string
  kind: string
  scope: { type?: string; keys?: string[]; files?: string[]; [k: string]: unknown }
  state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'lost'
  progress: { total?: number; done?: number; current?: string; saved?: number; batch?: number }
  result: { saved?: number; errors?: { files: string[]; error: string }[]; summary?: string }
  llm: number
  createdAt: number
  startedAt: number
  finishedAt: number
}

export const KIND_LABEL: Record<string, string> = {
  extract_delta: '变化量提取',
  extract_unowned: '未归属提取',
  extract_impl: '实现级提取',
  enhance_desc: '描述增强',
  enhance_semantic: '语义增强',
  extract_logic: '逻辑级提取',
  gen_component_view: '组件聚合',
}

const STATE_LABEL: Record<string, string> = {
  queued: '排队中', running: '运行中', done: '已完成',
  failed: '失败', cancelled: '已取消', lost: '已中断',
}

const visible = ref(false)
const jobs = ref<SemanticJob[]>([])
let timer: ReturnType<typeof setInterval> | null = null

const active = computed(() => jobs.value.filter((j) => j.state === 'queued' || j.state === 'running'))
const recent = computed(() => jobs.value.slice(0, 30))

async function refresh(): Promise<void> {
  try {
    const { project, root } = currentProjectParams()
    const qs = new URLSearchParams()
    if (project) qs.set('project', project)
    if (root) qs.set('root', root)
    const r = await apiGet<{ jobs: SemanticJob[] }>(`/kb/semantic/jobs?${qs.toString()}`)
    jobs.value = r?.jobs ?? []
  } catch {
    /* 轮询失败静默，下轮重试 */
  }
}

function ensurePolling(): void {
  if (timer) return
  timer = setInterval(refresh, 2500)
  void refresh()
}

function stopPolling(): void {
  if (timer) { clearInterval(timer); timer = null }
}

export function useTaskCenter() {
  const open = (): void => { visible.value = true; ensurePolling() }
  const toggle = (): void => {
    visible.value = !visible.value
    if (visible.value) ensurePolling()
    else if (!active.value.length) stopPolling()
  }
  const close = (): void => { visible.value = false }

  async function cancel(id: string): Promise<void> {
    const { project, root } = currentProjectParams()
    const qs = new URLSearchParams()
    if (project) qs.set('project', project)
    if (root) qs.set('root', root)
    try {
      await apiPost(`/kb/semantic/jobs/${id}/cancel?${qs.toString()}`, {})
      void refresh()
    } catch { /* 忽略 */ }
  }

  const labelOf = (j: SemanticJob): string => KIND_LABEL[j.kind] || j.kind
  const stateOf = (j: SemanticJob): string => STATE_LABEL[j.state] || j.state
  const pctOf = (j: SemanticJob): number => {
    const t = j.progress?.total ?? 0
    if (!t) return j.state === 'done' ? 100 : 0
    return Math.min(100, Math.round(((j.progress?.done ?? 0) / t) * 100))
  }

  // 活跃作业存在 → 持续轮询（badge）；空闲且浮窗收起 → 停轮询
  watch(active, (a) => {
    if (a.length) ensurePolling()
    else if (!visible.value) stopPolling()
  })

  onBeforeUnmount(stopPolling)

  return { visible, jobs: recent, active, open, toggle, close, refresh, cancel, labelOf, stateOf, pctOf }
}
