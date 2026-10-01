/**
 * 全局任务中心（批 1-5）：语义作业浮窗。
 * 数据源 /kb/semantic/jobs（持久化作业行，跨页面/刷新存活）；轮询 2.5s
 * （仅展开或 tag 有活跃作业时激活）。入口：底部状态栏 tag（StatusBar 挂载），
 * 各页面可按需引用 `taskCenterVisible` 呼出。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { apiDelete, apiGet, apiPost } from '@/services/api-client'
import { currentProjectParams } from '@/services/project-service'
import { notifyJobFinished } from '@/pages/asset-workspace/invalidate-bus'

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
  extract_logic: '逻辑视图归纳',
  analyze_logic: '逻辑视图分析',
  gen_component_view: '组件聚合',
}

const STATE_LABEL: Record<string, string> = {
  queued: '排队中', running: '运行中', done: '已完成',
  failed: '失败', cancelled: '已取消', lost: '已中断',
}

const visible = ref(false)
const jobs = ref<SemanticJob[]>([])
/** 本地「停止中」标记（协作式取消有批次延迟，须即时反馈；终态后清除）。 */
const cancelling = ref<Set<string>>(new Set())
let timer: ReturnType<typeof setInterval> | null = null
let intervalMs = 0
/** 已见过的活跃作业 id（识别「新任务进入」→ 自动展开）。 */
const seenActiveIds = new Set<string>()

const active = computed(() => jobs.value.filter((j) => j.state === 'queued' || j.state === 'running'))
const recent = computed(() => jobs.value.slice(0, 30))

async function refresh(): Promise<void> {
  try {
    const { project, root } = currentProjectParams()
    const qs = new URLSearchParams()
    if (project) qs.set('project', project)
    if (root) qs.set('root', root)
    const prev = jobs.value
    const r = await apiGet<{ jobs: SemanticJob[] }>(`/kb/semantic/jobs?${qs.toString()}`)
    jobs.value = r?.jobs ?? []
    // 作业完成 → 失效总线（资产工作区等订阅方刷新）
    for (const j of jobs.value) {
      const before = prev.find((x) => x.id === j.id)
      if (before && (before.state === 'running' || before.state === 'queued')
        && j.state !== 'running' && j.state !== 'queued') {
        notifyJobFinished(j)
        if (cancelling.value.has(j.id)) {
          const c = new Set(cancelling.value); c.delete(j.id); cancelling.value = c
        }
      }
    }
    // 新任务进入 → 自动展开浮窗（已展开则保持；手动收起后新任务仍会再次展开）
    for (const a of jobs.value) {
      if ((a.state === 'queued' || a.state === 'running') && !seenActiveIds.has(a.id)) {
        seenActiveIds.add(a.id)
        if (!visible.value) visible.value = true
      } else if (a.state !== 'queued' && a.state !== 'running') {
        seenActiveIds.delete(a.id)
      }
    }
    // 轮询频率：有活跃(或展开) → 2.5s；空闲且收起 → 6s 低频探测(新任务进入仍可被发现)
    ensurePolling(jobs.value.some((j) => j.state === 'queued' || j.state === 'running') || visible.value
      ? 2500 : 6000)
  } catch {
    /* 轮询失败静默，下轮重试 */
  }
}

function ensurePolling(ms = 2500): void {
  if (timer && intervalMs === ms) return
  if (timer) clearInterval(timer)
  intervalMs = ms
  timer = setInterval(() => void refresh(), ms)
  void refresh()
}

function stopPolling(): void {
  if (timer) { clearInterval(timer); timer = null }
  intervalMs = 0
}

export function useTaskCenter() {
  const open = (): void => { visible.value = true; ensurePolling() }
  const toggle = (): void => {
    visible.value = !visible.value
    ensurePolling(visible.value || active.value.length ? 2500 : 6000)
  }
  const close = (): void => {
    visible.value = false
    ensurePolling(active.value.length ? 2500 : 6000)
  }
  // 常驻低频探测：任务进入(含后端自动提交)时自动展开并升级到 2.5s
  ensurePolling(6000)

  async function cancel(id: string): Promise<void> {
    const { project, root } = currentProjectParams()
    const qs = new URLSearchParams()
    if (project) qs.set('project', project)
    if (root) qs.set('root', root)
    const next = new Set(cancelling.value)
    next.add(id)
    cancelling.value = next
    try {
      await apiPost(`/kb/semantic/jobs/${id}/cancel?${qs.toString()}`, {})
      void refresh()
    } catch {
      const c = new Set(cancelling.value); c.delete(id); cancelling.value = c
    }
  }

  /** 删除单条已结束作业记录（终态：done/failed/cancelled/lost；进行中后端 409 拒绝）。
   *  失败须可见提示——静默吞掉会表现为「清了又被轮询拉回来」。 */
  async function remove(id: string): Promise<void> {
    try {
      await apiDelete(`/kb/semantic/jobs/${id}`)
      jobs.value = jobs.value.filter((j) => j.id !== id)
    } catch {
      alert('删除失败：后端不可用或版本较旧（需重启服务后重试）')
    }
  }

  /** 一键清除全部已结束记录（进行中不受影响）。 */
  async function clearFinished(): Promise<void> {
    const { project, root } = currentProjectParams()
    const qs = new URLSearchParams()
    if (project) qs.set('project', project)
    if (root) qs.set('root', root)
    try {
      await apiPost(`/kb/semantic/jobs/clear?${qs.toString()}`, {})
      jobs.value = jobs.value.filter((j) => j.state === 'queued' || j.state === 'running')
    } catch {
      alert('清除失败：后端不可用或版本较旧（需重启服务后重试）')
    }
  }

  const labelOf = (j: SemanticJob): string => KIND_LABEL[j.kind] || j.kind
  const stateOf = (j: SemanticJob): string => STATE_LABEL[j.state] || j.state
  const pctOf = (j: SemanticJob): number => {
    const t = j.progress?.total ?? 0
    if (!t) return j.state === 'done' ? 100 : 0
    return Math.min(100, Math.round(((j.progress?.done ?? 0) / t) * 100))
  }

  // 活跃作业存在 → 高频轮询；空闲收起 → 低频探测（不再全停，任务进入需被发现）
  watch(active, (a) => {
    ensurePolling(a.length || visible.value ? 2500 : 6000)
  })

  onBeforeUnmount(stopPolling)

  return { visible, jobs: recent, active, cancelling, open, toggle, close, refresh, cancel, remove, clearFinished, labelOf, stateOf, pctOf }
}
