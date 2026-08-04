import { defineStore } from 'pinia'
import type { AppendedReq, ExecutionTask, Requirement, TaskNode, TaskStatus } from '@/types'
import { EXECUTION_TASKS, PLAN_TASK_TREES } from '@/services/mock/order-system'
import { useArchRequirementStore } from './requirement-store'

export const useArchTaskStore = defineStore('arch-task', {
  state: () => ({
    planToTaskTree: {} as Record<string, TaskNode>,
    /** 任务树历史(重建前的缩略快照，供复盘分析)。 */
    treeHistory: {} as Record<string, { old: TaskNode; ts: number }[]>,
    executionTasks: [] as ExecutionTask[],
    loading: false,
    loaded: false,
  }),
  getters: {
    allTaskNodes(): TaskNode[] {
      const out: TaskNode[] = []
      const walk = (n: TaskNode) => {
        out.push(n)
        ;(n.children ?? []).forEach(walk)
      }
      Object.values(this.planToTaskTree).forEach(walk)
      return out
    },
    activeTasks(): ExecutionTask[] {
      return this.executionTasks.filter((t) => t.status === 'running' || t.status === 'created' || t.status === 'accepting')
    },
    /** 同一工作目录(源码目录)当前是否有活动任务(互斥校验：提示性)。 */
    hasActiveTask(): boolean {
      return this.activeTasks.length > 0
    },
    activeTaskOf(): ExecutionTask | undefined {
      return this.activeTasks[0]
    },
    runningCount(): number {
      return this.executionTasks.filter((t) => t.status === 'running').length
    },
    doneCount(): number {
      return this.executionTasks.filter((t) => t.status === 'done').length
    },
    totalCount(): number {
      return this.executionTasks.length
    },
  },
  actions: {
    async load() {
      if (this.loaded) return
      this.loading = true
      this.planToTaskTree = { ...PLAN_TASK_TREES }
      this.executionTasks = structuredClone(EXECUTION_TASKS)
      this.loaded = true
      this.loading = false
    },
    findExecution(id: string): ExecutionTask | undefined {
      return this.executionTasks.find((t) => t.id === id)
    },
    taskPlan(planId: string): TaskNode | undefined {
      const req = useArchRequirementStore()
      const plan = req.planById(planId)
      return plan?.taskPlanId ? this.planToTaskTree[plan.taskPlanId] : undefined
    },
    updateStatus(id: string, status: TaskStatus) {
      const node = this.allTaskNodes.find((n) => n.id === id)
      if (node) node.status = status
    },
    async createTask(planId: string, adapter: string, opts?: { model?: string; reqIds?: string[] }): Promise<ExecutionTask> {
      const task: ExecutionTask = {
        id: `ex-${Date.now().toString().slice(-4)}`,
        planId,
        adapter,
        model: opts?.model,
        reqIds: opts?.reqIds ?? [],
        connectivity: 'unknown',
        status: 'created',
        sessionIds: [],
        baseCommit: '1a2b3c4d5e6f',
        runCount: 1,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        stats: { requests: 0, tokensIn: 0, tokensOut: 0, bytesIn: 0, bytesOut: 0 },
        amendments: [],
      }
      this.executionTasks.unshift(task)
      useArchRequirementStore().markPlanReqsExecuting(planId)
      return task
    },
    setConnectivity(id: string, value: ExecutionTask['connectivity']) {
      const t = this.findExecution(id)
      if (t) t.connectivity = value
    },
    setExecStatus(id: string, status: ExecutionTask['status']) {
      const t = this.findExecution(id)
      if (t) {
        t.status = status
        t.updatedAt = Date.now()
        if (status === 'done' || status === 'failed' || status === 'stopped' || status === 'blocked') t.endedAt = Date.now()
      }
    },
    setStats(id: string, stats: NonNullable<ExecutionTask['stats']>) {
      const t = this.findExecution(id)
      if (t) t.stats = { ...stats }
    },
    /** 停止执行(配合会话停止)。 */
    stopTask(id: string) {
      const t = this.findExecution(id)
      if (t && t.status !== 'done' && t.status !== 'accepting') {
        t.status = 'stopped'
        t.endedAt = Date.now()
        t.updatedAt = Date.now()
      }
    },
    /** 保存当前任务树为历史快照，替换为新树(任务树随执行过程整体废弃重建)。 */
    replaceTaskTree(planId: string, tree: TaskNode) {
      const key = useArchRequirementStore().planById(planId)?.taskPlanId ?? planId
      const current = this.planToTaskTree[key]
      if (current) {
        const hist = this.treeHistory[key] ?? []
        hist.push({ old: structuredClone(current), ts: Date.now() })
        this.treeHistory[key] = hist.slice(-20)
      }
      this.planToTaskTree[key] = tree
      const exec = this.executionTasks.find((e) => e.planId === planId)
      if (exec) exec.treeRevision = (exec.treeRevision ?? 0) + 1
    },
    /** 任务树重构(mock)：把当前树克隆后做结构性调整，旧树缩略保存。 */
    rebuildPlanTree(planId: string, reason?: string) {
      const key = useArchRequirementStore().planById(planId)?.taskPlanId ?? planId
      const current = this.planToTaskTree[key]
      if (!current) return
      const next = structuredClone(current)
      const pending = (next.children ?? []).find((c) => c.status === 'pending')
      if (pending) {
        next.children = next.children ?? []
        next.children.push({
          id: `${pending.id}-rev`, title: `${pending.title}(重构补充)`, kind: 'task',
          status: 'pending', estMin: 30,
          context: [...pending.context, reason ?? '任务树整体废弃重建'],
          files: [...pending.files],
        })
      }
      next.title = `${current.title} · R${(this.executionTasks.find((e) => e.planId === planId)?.treeRevision ?? 0) + 1}`
      this.replaceTaskTree(planId, next)
    },
    /** 验收通过：任务完成，方案覆盖的需求标记完成。 */
    passAcceptance(id: string) {
      const t = this.findExecution(id)
      if (!t) return
      t.status = 'done'
      useArchRequirementStore().markPlanReqsDone(t.planId)
    },
    addAmendment(execId: string, req: AppendedReq) {
      const t = this.findExecution(execId)
      if (t) t.amendments.unshift(req)
    },
    updateAmendment(execId: string, reqId: string, patch: Partial<AppendedReq>) {
      const t = this.findExecution(execId)
      const a = t?.amendments.find((x) => x.id === reqId)
      if (a) Object.assign(a, patch, { updatedAt: Date.now() })
    },
    /** 追加需求确认设计后，把新增改动任务并入方案任务树。 */
    mergeAmendmentIntoPlan(execId: string, reqId: string) {
      const t = this.findExecution(execId)
      if (!t) return
      const a = t.amendments.find((x) => x.id === reqId)
      if (!a) return
      const tree = this.planToTaskTree[t.planId]
      if (tree) {
        tree.children = tree.children ?? []
        tree.children.push({
          id: `${reqId}-task`,
          title: `追加: ${a.title}`,
          kind: 'task',
          status: 'pending',
          estMin: a.analysis?.feasibility.estMin ?? 60,
          context: [`追加需求: ${a.title}`, ...a.scope],
          files: a.scope,
        })
        tree.estMin += a.analysis?.feasibility.estMin ?? 60
      }
      a.status = 'executing'
      t.status = 'running'
    },
    /** 追加(对话通道)：会话内触发词(追加：/append:)回复 → 就地分析并并入任务树，继续执行。 */
    addConversationalAmendment(execId: string, text: string): AppendedReq | null {
      const t = this.findExecution(execId)
      if (!t) return null
      const m = text.match(/^(?:追加|append)\s*[：:]\s*(.+)$/i)
      const title = m?.[1]?.trim() || text.trim().slice(0, 24)
      const req: AppendedReq = {
        id: `ap-${Date.now().toString().slice(-4)}`,
        title,
        desc: text,
        scope: [],
        status: 'designed',
        updatedAt: Date.now(),
        analysis: {
          functionalScope: [`${title} 主链路`, '边界与异常'],
          entityBoundary: [],
          feasibility: { ok: true, reason: '会话内追加：模型就地评估，改动集中在既有服务内', estMin: 60 },
          assetScope: [],
        },
        design: { approach: `在既有执行内扩展以覆盖「${title}」，复用当前会话上下文与规约。`, changes: [] },
      }
      this.addAmendment(execId, req)
      this.mergeAmendmentIntoPlan(execId, req.id)
      return req
    },
    /** 追加(池选择通道)：从需求池选已分析项并入当前执行，继续执行。 */
    appendFromPool(execId: string, r: Requirement) {
      const t = this.findExecution(execId)
      if (!t) return
      const req: AppendedReq = {
        id: `ap-${Date.now().toString().slice(-4)}`,
        title: r.title,
        desc: r.desc,
        scope: r.traceTo,
        status: 'designed',
        updatedAt: Date.now(),
        analysis: r.analysis ?? {
          functionalScope: [`${r.title} 主链路`],
          entityBoundary: [],
          feasibility: { ok: true, reason: '来自需求池的已分析项', estMin: 60 },
          assetScope: [],
        },
        design: {
          approach: r.analysis?.implementationPath ?? `在既有执行内扩展以覆盖「${r.title}」`,
          changes: r.analysis?.changes ?? [],
        },
      }
      this.addAmendment(execId, req)
      this.mergeAmendmentIntoPlan(execId, req.id)
    },
    /** 代码级回流配套：移除执行任务(需求已由 requirement.reflowPlan 回池)。 */
    removeExecution(id: string) {
      const i = this.executionTasks.findIndex((t) => t.id === id)
      if (i >= 0) this.executionTasks.splice(i, 1)
    },
  },
})
