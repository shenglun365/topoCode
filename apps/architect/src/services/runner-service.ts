import { apiPost } from './api-client'
import { ArchWs } from './ws-client'

/**
 * Runner 任务树执行接口 → 后端 /exec/{id}/run + WS /ws/trees/{id}/events(代理)。
 *
 * 执行链路(P2-A)：
 *   runExecution(execId)  → POST /exec/{id}/run → {treeId, progress}(SE 提交 runner，开始执行)
 *   connectTreeEvents(treeId) → WS 进度流：
 *     - `state`  初始 tree+progress(对齐，消除 run 先于订阅的竞态)
 *     - `status` {stage, message(节点 id / 树级原因), ...} 节点/树级进度
 *     - `error`  错误
 *   控制经同一 WS 发送 {cmd: pause/resume/cancel/skip/retry, taskId?}。
 */

export interface RunnerRunResult {
  treeId: string
  progress?: Record<string, unknown>
}

export interface RunnerStateData {
  tree?: { roots?: RunnerRunnerNode[] }
  progress?: Record<string, unknown>
}

/** runner 侧节点(snake_case) */
export interface RunnerRunnerNode {
  id: string
  title: string
  kind: string
  status: string
  depends_on?: string[]
  context?: string[]
  files?: string[]
  est_min?: number
  children?: RunnerRunnerNode[]
}

export interface RunnerStatusData {
  stage: string
  message?: string
  [key: string]: unknown
}

export interface TreeEventHandlers {
  onState?: (data: RunnerStateData) => void
  onStatus?: (data: RunnerStatusData) => void
  onError?: (data: { message?: string; [key: string]: unknown }) => void
  onClosed?: () => void
}

export interface TreeEventConnection {
  close(): void
  send(cmd: string, taskId?: string): void
}

/** 提交执行任务到 runner 并触发执行。返回 treeId(供进度流订阅)。 */
export async function runExecution(execId: string): Promise<RunnerRunResult> {
  return (await apiPost<RunnerRunResult>(`/exec/${execId}/run`)) as RunnerRunResult
}

export interface RejudgeResult {
  treeId: string
  staleIds: string[]
  /** 重判后的更新树(前端 TaskNode 形状，供 UI 再确认)。 */
  newTree: { id: string; [key: string]: any }
}

/** A3：触发 stale 重判(SE 基于当前源码重判)，返回更新树供用户再确认。 */
export async function rejudge(execId: string): Promise<RejudgeResult> {
  return (await apiPost<RejudgeResult>(`/exec/${execId}/rejudge`)) as RejudgeResult
}

/** A3：确认重判 → 后端 PUT 新树 + rejudge(刷新基线) + run，返回 treeId(续订阅进度)。 */
export async function confirmRejudge(execId: string): Promise<RunnerRunResult> {
  return (await apiPost<RunnerRunResult>(`/exec/${execId}/rejudge/confirm`)) as RunnerRunResult
}

export interface VerifyResult {
  treeId: string
  passed: boolean
  issues: string[]
  unmetRequirements: string[]
  report: string
}

/** A4：SE 验证(基于已变更文件 agentic 复查，不跑测试)，返回验证报告。 */
export async function verifyExecution(execId: string): Promise<VerifyResult> {
  return (await apiPost<VerifyResult>(`/exec/${execId}/verify`)) as VerifyResult
}

/** B3 闭环：真实执行任务关联单测(testIds)，返回汇总。 */
export interface RunTestsResult {
  ran: number
  passed: number
  failed: number
  allPassed: boolean
  results: { testId: string; status: string; lastResult: { passed: number; failed: number; error?: string; note: string; at: number } }[]
  note?: string
  at: number
}

export async function runLinkedTests(execId: string, root: string): Promise<RunTestsResult> {
  return (await apiPost<RunTestsResult>(`/exec/${execId}/run-tests`, { root })) as RunTestsResult
}

/** 树级 stage(非节点级)：message 是原因而非节点 id。 */
const TREE_LEVEL_STAGES = new Set([
  'completed', 'blocked', 'blocked_stale', 'paused', 'resumed',
  'cancelling', 'cancelled', 'stale',
])

export function isTreeLevelStage(stage: string): boolean {
  return TREE_LEVEL_STAGES.has(stage)
}

/**
 * 连接 runner 进度事件流(经 architect WS 代理，同源)。
 * 返回 { close, send }；close 注销处理器并断开。
 */
export function connectTreeEvents(treeId: string, h: TreeEventHandlers): TreeEventConnection {
  const ws = new ArchWs(`ws/trees/${treeId}/events`)
  let closed = false
  const offs = [
    ws.on('state', (m: any) => h.onState?.(m?.data ?? {})),
    ws.on('status', (m: any) => h.onStatus?.(m?.data ?? {})),
    ws.on('error', (m: any) => h.onError?.(m?.data ?? {})),
    ws.onClose(() => {
      if (closed) return
      closed = true
      h.onClosed?.()
    }),
  ]
  ws.ready().catch(() => h.onError?.({ message: '无法连接 runner 进度流' }))
  return {
    close() {
      if (closed) return
      closed = true
      offs.forEach((off) => off())
      ws.close()
    },
    send(cmd: string, taskId?: string) {
      ws.send('control', { cmd, taskId })
    },
  }
}
