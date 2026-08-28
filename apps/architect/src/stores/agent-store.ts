import { defineStore } from 'pinia'
import type { AgentSession, AgentStatus, ExecutionTask, TaskNode } from '@/types'
import { agentService } from '@/services/agent-service'
import {
  runExecution, connectTreeEvents, isTreeLevelStage,
  rejudge as rejudgeApi, confirmRejudge as confirmRejudgeApi,
  verifyExecution as verifyApi, type TreeEventConnection,
} from '@/services/runner-service'
import { apiGet } from '@/services/api-client'
import { currentProjectParams } from '@/services/project-service'
import { useArchTaskStore } from './task-store'
import { useArchRequirementStore } from './requirement-store'

/** 在途 coding-agent 对话的 AbortController(供 stop 中止)。 */
let chatAbort: AbortController | null = null

export const useArchAgentStore = defineStore('arch-agent', {
  state: () => ({
    sessions: [] as AgentSession[],
    activeSessionId: null as string | null,
    loaded: false,
    loading: false,
    running: false,
    log: [] as string[],
    /** 已请求停止的会话。 */
    stopping: new Set<string>(),
    /** 当前 runner 执行：treeId + 进度流连接(供停止/控制)。 */
    activeTreeId: null as string | null,
    activeConn: null as TreeEventConnection | null,
  }),
  getters: {
    active(): AgentSession | undefined {
      return this.sessions.find((s) => s.id === this.activeSessionId)
    },
    byExecution(state): Record<string, AgentSession | undefined> {
      const map: Record<string, AgentSession | undefined> = {}
      state.sessions.forEach((s) => { map[s.taskId] = s })
      return map
    },
  },
  actions: {
    async load() {
      if (this.loaded || this.loading) return
      this.loading = true
      try {
        const { project } = currentProjectParams()
        const qs = project ? `?project=${encodeURIComponent(project)}` : ''
        const sessions = await apiGet<AgentSession[]>(`/agent/sessions${qs}`).catch(() => [] as AgentSession[])
        // 仅并入对当前(已存在)执行任务的会话；其余保持不显示，避免残留。
        this.sessions = (sessions ?? []).filter((s) => !!s.taskId)
        this.activeSessionId = this.sessions[0]?.id ?? null
        this.loaded = true
        this.loading = false
      } catch (err) {
        this.loading = false
        console.error('[arch] agent 会话加载失败', err)
        this.loaded = true
      }
    },
    async openSession(executionId: string) {
      const taskStore = useArchTaskStore()
      const exec = taskStore.findExecution(executionId)
      if (!exec) return
      const plan = useArchRequirementStore().planById(exec.planId)
      const session = await agentService.createSession({
        exec,
        planTitle: plan?.title ?? exec.planId,
        keepContext: true,
      })
      this.sessions.push(session)
      exec.sessionIds.push(session.id)
      this.activeSessionId = session.id
      this.log.unshift(`[会话] ${plan?.title ?? exec.planId} → ${session.adapter}`)
      return session
    },
    select(sessionId: string) {
      this.activeSessionId = sessionId
    },
    async send(sessionId: string, content: string) {
      const s = this.sessions.find((x) => x.id === sessionId)
      if (!s) return
      chatAbort = new AbortController()
      try {
        await agentService.sendMessage(s, content, { signal: chatAbort.signal })
      } finally {
        chatAbort = null
      }
    },
    async runTask(sessionId: string) {
      const s = this.sessions.find((x) => x.id === sessionId)
      if (!s || this.running) return
      const taskStore = useArchTaskStore()
      const exec = taskStore.findExecution(s.taskId)
      if (!exec) return
      await this.runExec(exec.id)
    },
    /** P2-A 主入口：按执行任务直接提交 runner 执行(无需 opencode 会话)。 */
    async runExec(execId: string) {
      if (this.running) return
      const taskStore = useArchTaskStore()
      const exec = taskStore.findExecution(execId)
      if (!exec) return
      this.running = true
      taskStore.setExecStatus(exec.id, 'running')
      try {
        await this._runViaRunner(exec)
      } finally {
        this.running = false
      }
    },
    /** P2-A：把已确认任务树提交 runner 并订阅进度流(替换 opencode WS task.run)。 */
    async _runViaRunner(exec: ExecutionTask) {
      const taskStore = useArchTaskStore()
      this.log.unshift(`[执行] ${exec.planId} → 提交 runner`)
      let treeId: string
      try {
        const res = await runExecution(exec.id)
        treeId = res.treeId
      } catch (e: any) {
        this.log.unshift(`[执行] 提交 runner 失败: ${e?.message ?? e}`)
        taskStore.setExecStatus(exec.id, 'failed')
        return
      }
      taskStore.setRunnerTreeId(exec.id, treeId)
      this.log.unshift(`[执行] runner tree=${treeId}`)
      await this._watchTree(exec, treeId)
    },
    /** 订阅指定 runner 树的进度流并等待终态(设置执行任务终态)。runExec/confirmRejudge 复用。 */
    async _watchTree(exec: ExecutionTask, treeId: string) {
      const taskStore = useArchTaskStore()
      this.activeTreeId = treeId
      const finishState = { reason: 'closed' as 'completed' | 'cancelled' | 'blocked_stale' | 'closed' }
      await new Promise<void>((resolve) => {
        let settled = false
        const finish = (reason: 'completed' | 'cancelled' | 'blocked_stale' | 'closed') => {
          if (settled) return
          settled = true
          finishState.reason = reason
          this.activeConn = null
          this.activeTreeId = null
          resolve()
        }
        const conn = connectTreeEvents(treeId, {
          onState: (data) => taskStore.applyRunnerTree(data.tree?.roots ?? []),
          onStatus: (data) => {
            const stage = data.stage
            if (!stage) return
            if (isTreeLevelStage(stage)) {
              if (stage === 'blocked_stale') this.log.unshift(`[重判] 源码变更，任务失效需重判: ${data.message ?? ''}`)
              else if (stage === 'cancelled') this.log.unshift('[执行] 已取消')
              else if (stage === 'completed') this.log.unshift('[执行] runner 执行完成')
            } else if (data.message) {
              taskStore.applyRunnerNodeStatus(String(data.message), stage)
            }
            if (stage === 'completed') finish('completed')
            else if (stage === 'cancelled') finish('cancelled')
            else if (stage === 'blocked_stale') finish('blocked_stale')
          },
          onError: (data) => this.log.unshift(`[错误] ${data.message ?? 'runner 错误'}`),
          onClosed: () => finish('closed'),
        })
        this.activeConn = conn
        // 兜底：runner 已终态(无后续事件) → 靠 onClosed 收口；超时保护避免悬挂
        setTimeout(() => finish('closed'), 6 * 3600 * 1000)
      })

      let finalStatus: ExecutionTask['status']
      if (finishState.reason === 'cancelled') finalStatus = 'stopped'
      else if (finishState.reason === 'blocked_stale') finalStatus = 'blocked'
      else {
        const root = taskStore.taskPlan(exec.planId)
        let bad = false
        const walk = (n: TaskNode) => {
          if (n.status === 'blocked') bad = true
          ;(n.children ?? []).forEach(walk)
        }
        if (root) walk(root)
        finalStatus = bad ? 'failed' : 'accepting'
      }
      taskStore.setExecStatus(exec.id, finalStatus)
      this.log.unshift(`[执行] ${exec.planId} → ${finalStatus}`)
    },
    /** A3：触发 stale 重判(SE 基于当前源码重判)，更新树反映到任务树供用户再确认。 */
    async rejudge(execId: string) {
      const taskStore = useArchTaskStore()
      const exec = taskStore.findExecution(execId)
      if (!exec) return
      this.log.unshift(`[重判] ${exec.planId} → SE 重判失效节点`)
      try {
        const { newTree, staleIds } = await rejudgeApi(execId)
        const key = taskStore.taskPlan(exec.planId)?.id
        if (key) taskStore.planToTaskTree[key] = newTree as any
        this.log.unshift(`[重判] ${exec.planId} → 完成(${staleIds.length} 个失效节点)，请再确认后继续`)
      } catch (e: any) {
        this.log.unshift(`[重判] 失败: ${e?.message ?? e}`)
      }
    },
    /** A3：确认重判 → 后端 PUT+rejudge+run，续订阅进度流执行。 */
    async confirmRejudge(execId: string) {
      if (this.running) return
      const taskStore = useArchTaskStore()
      const exec = taskStore.findExecution(execId)
      if (!exec) return
      this.running = true
      taskStore.setExecStatus(exec.id, 'running')
      try {
        const { treeId } = await confirmRejudgeApi(execId)
        await this._watchTree(exec, treeId)
      } catch (e: any) {
        this.log.unshift(`[重判] 确认失败: ${e?.message ?? e}`)
        taskStore.setExecStatus(exec.id, 'blocked')
      } finally {
        this.running = false
      }
    },
    /** A4：SE 验证(不跑测试)，返回并记录验证报告。 */
    async verify(execId: string) {
      const taskStore = useArchTaskStore()
      const exec = taskStore.findExecution(execId)
      if (!exec) return null
      this.log.unshift(`[验证] ${exec.planId} → SE 复查变更`)
      try {
        const v = await verifyApi(execId)
        this.log.unshift(`[验证] ${exec.planId} → ${v.passed ? '通过' : '未通过'}${v.issues.length ? `(${v.issues.length} 问题)` : ''}`)
        return v
      } catch (e: any) {
        this.log.unshift(`[验证] 失败: ${e?.message ?? e}`)
        return null
      }
    },
    /** 停止执行：经 runner 进度流发送 cancel(无活动连接时回退旧 terminate)。 */
    async stop(sessionId: string) {
      const s = this.sessions.find((x) => x.id === sessionId)
      if (!s) return
      this.stopping.add(sessionId)
      const abortedChat = !!chatAbort
      if (chatAbort) {
        chatAbort.abort()
        chatAbort = null
        this.log.unshift(`[停止] 已中止会话对话 ${sessionId}`)
      }
      if (this.activeConn && this.activeTreeId) {
        this.activeConn.send('cancel')
        this.log.unshift(`[停止] 已请求取消 runner ${this.activeTreeId}`)
      } else if (!abortedChat) {
        await agentService.terminate(sessionId)
        this.log.unshift(`[停止] 已请求停止会话 ${sessionId}`)
      }
    },
    setStatus(sessionId: string, status: AgentStatus) {
      const s = this.sessions.find((x) => x.id === sessionId)
      if (s) s.status = status
    },
    /** 代码级回流配套：移除执行任务关联的会话。 */
    removeByTask(taskId: string) {
      this.sessions = this.sessions.filter((s) => s.taskId !== taskId)
      this.activeSessionId = this.sessions[0]?.id ?? null
    },
    /** 会话内追加需求已并入任务后的确认消息。 */
    noteAppended(sessionId: string, title: string) {
      const s = this.sessions.find((x) => x.id === sessionId)
      if (!s) return
      s.messages.push({
        id: `m-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
        role: 'assistant',
        time: Date.now(),
        content: `已将会话中的追加需求「${title}」就地并入当前任务树，继续执行。`,
      })
      this.log.unshift(`[追加需求] ${title} → 已并入 ${sessionId}`)
    },
    /** 依次执行所有已创建/执行中的任务。 */
    async runAll() {
      const taskStore = useArchTaskStore()
      const pending = taskStore.executionTasks.filter((t) => t.status === 'created' || t.status === 'running')
      for (const exec of pending) {
        await this.runExec(exec.id)
      }
      const finished = taskStore.executionTasks.filter((t) => t.status === 'accepting' || t.status === 'done').length
      this.log.unshift(`[批量执行] 完成执行 ${finished}/${taskStore.totalCount} 个任务(含待验收)`)
      return finished === taskStore.totalCount
    },
    /** 只执行下一个未完成的任务(单步)。 */
    async runNextPending(): Promise<ExecutionTask | null> {
      const taskStore = useArchTaskStore()
      const pending = taskStore.executionTasks.filter((t) => t.status === 'created' && t.connectivity === 'ok')
      if (!pending.length || this.running) return null
      const exec = pending[0]
      await this.runExec(exec.id)
      this.log.unshift(`[单步执行] ${exec.planId} → ${taskStore.findExecution(exec.id)?.status}`)
      return exec
    },
  },
})
