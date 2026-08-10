import { defineStore } from 'pinia'
import type { AgentAdapterInfo, AgentMessage, AgentSession, AgentStatus, ExecutionTask } from '@/types'
import { agentService, listAgentAdapters } from '@/services/agent-service'
import { apiGet } from '@/services/api-client'
import { useArchTaskStore } from './task-store'
import { useArchRequirementStore } from './requirement-store'

export const useArchAgentStore = defineStore('arch-agent', {
  state: () => ({
    sessions: [] as AgentSession[],
    adapters: [] as AgentAdapterInfo[],
    activeSessionId: null as string | null,
    loaded: false,
    loading: false,
    running: false,
    log: [] as string[],
    /** 已请求停止的会话。 */
    stopping: new Set<string>(),
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
        const [adapters, sessions] = await Promise.all([
          listAgentAdapters().catch(() => [] as AgentAdapterInfo[]),
          apiGet<AgentSession[]>('/agent/sessions').catch(() => [] as AgentSession[]),
        ])
        this.adapters = adapters ?? []
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
      await agentService.sendMessage(s, content)
    },
    async runTask(sessionId: string) {
      const s = this.sessions.find((x) => x.id === sessionId)
      if (!s || this.running) return
      const taskStore = useArchTaskStore()
      const exec = taskStore.findExecution(s.taskId)
      const tree = exec ? taskStore.taskPlan(exec.planId) : undefined
      if (!exec || !tree) return
      this.running = true
      taskStore.setExecStatus(exec.id, 'running')
      const onMessage = (msg: AgentMessage) => {
        if (msg.role === 'tool' && msg.tool) this.log.unshift(`[工具] ${msg.tool.label}: ${msg.tool.detail}`)
      }
      await agentService.runTask(s, tree, {
        onMessage,
        onTreeChange: (reason) => taskStore.rebuildPlanTree(exec.planId, reason),
        isCancelled: () => this.stopping.has(sessionId),
      })
      if (s.status === 'done') taskStore.setExecStatus(exec.id, 'accepting')
      else if (s.status === 'failed') taskStore.setExecStatus(exec.id, 'failed')
      else if (s.status === 'stopped') taskStore.stopTask(exec.id)
      if (s.stats) taskStore.setStats(exec.id, s.stats)
      this.running = false
      this.stopping.delete(sessionId)
    },
    /** 停止执行(前端 mock；真实后端需适配各 agent 终止接口)。 */
    async stop(sessionId: string) {
      const s = this.sessions.find((x) => x.id === sessionId)
      if (!s) return
      this.stopping.add(sessionId)
      await agentService.terminate(sessionId)
      this.log.unshift(`[停止] 已请求停止会话 ${sessionId}`)
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
        let s = this.byExecution[exec.id]
        if (!s) {
          s = await this.openSession(exec.id)
          if (!s) continue
        }
        this.activeSessionId = s.id
        await this.runTask(s.id)
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
      let s = this.byExecution[exec.id]
      if (!s) {
        s = await this.openSession(exec.id)
        if (!s) return null
      }
      this.activeSessionId = s.id
      await this.runTask(s.id)
      this.log.unshift(`[单步执行] ${exec.planId} → ${s.status}`)
      return exec
    },
  },
})
