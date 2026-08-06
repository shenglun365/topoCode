import type { DesignPlan, ExecutionTask, Requirement, TaskNode } from '@/types'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchTaskStore } from '@/stores/task-store'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { BASELINE_COMMIT } from './mock/order-system'

/**
 * 执行批次(DesignPlan 作为内部「执行批次」)的合成与落盘。
 *
 * 需求池多选 → 依据各需求的概要设计(analysis)自动合成批次方案 → 用户评估确认后
 * 落盘为已确认方案 + 任务树 + 执行任务(ExecutionTask)。供两处调用：
 *   1. 需求分析工作区的「立即执行」(跳过池选取)
 *   2. 任务执行页的创建表单(池多选 + 方案回合预览)
 *
 * greenfield 模式：buildTaskTree 可选注入脚手架前置任务。
 */

/** 依据池项概要设计合成批次方案(纯函数，未落盘)。 */
export function buildBatchPlan(reqs: Requirement[]): DesignPlan {
  const changes = reqs.flatMap((r) => r.analysis?.changes ?? [])
  const affected = [...new Set(reqs.flatMap((r) => r.traceTo))]
  const est = reqs.reduce((s, r) => s + (r.analysis?.feasibility.estMin ?? 0), 0)
  return {
    id: `plan-${Date.now().toString().slice(-4)}`,
    reqIds: reqs.map((r) => r.id),
    title: reqs.map((r) => r.title).join(' + ').slice(0, 40),
    approach: reqs
      .map((r) => r.analysis?.implementationPath ?? `按「${r.title}」在既有服务内扩展`)
      .join('；'),
    changes,
    impact: {
      affected,
      grade: reqs.length > 2 || changes.length > 6 ? 'L' : reqs.length > 1 ? 'M' : 'S',
      basis: `覆盖 ${reqs.length} 条需求池项 · 涉及 ${affected.length} 个资产 · 预估 ${est}m`,
      risks: ['需回归验证核心链路', '改动资产需与既有规约对齐'],
    },
    status: 'draft',
    taskPlanId: `tp-${Date.now().toString().slice(-4)}`,
    baseCommit: BASELINE_COMMIT,
    updatedAt: Date.now(),
  }
}

/** 由需求概要设计的执行步骤组装任务树(供 planToTaskTree 注册)。 */
export function buildTaskTree(plan: DesignPlan, reqs: Requirement[], opts?: { injectScaffold?: boolean }): TaskNode {
  const children = reqs.flatMap((r) =>
    (r.analysis?.steps ?? []).map((s) => ({
      id: `${r.id}-${s.id}`,
      title: s.title,
      kind: 'task' as const,
      status: 'pending' as const,
      estMin: s.estMin,
      context: [r.id, ...(s.context ?? [])],
      files: s.files ?? [],
    })),
  )
  if (opts?.injectScaffold) {
    children.unshift(
      { id: `scaffold-core`, title: '脚手架：工程骨架+基础设施', kind: 'task' as const, status: 'pending' as const, estMin: 60, context: ['greenfield scaffold'], files: [] },
      { id: `scaffold-modules`, title: '脚手架：模块骨架', kind: 'task' as const, status: 'pending' as const, estMin: 30, context: ['按蓝图目录划分'], files: [] },
    )
  }
  const est = children.reduce((s, c) => s + c.estMin, 0)
  return {
    id: plan.taskPlanId ?? `tp-${Date.now().toString().slice(-4)}`,
    title: `${plan.title}(任务方案)`,
    kind: 'epic',
    status: 'pending',
    estMin: est,
    context: [`需求: ${plan.reqIds.join('/')}`, opts?.injectScaffold ? '从零脚手架 + 需求步骤' : '由需求概要设计的执行步骤拆分'],
    files: [],
    children,
  }
}

/** 落盘批次：方案确认 + 任务树注册 + 创建执行任务，需求标记执行中并绑定 execId。 */
export async function commitBatch(reqs: Requirement[], adapter: string, plan?: DesignPlan, opts?: { model?: string; testIds?: string[] }): Promise<{ plan: DesignPlan; exec: ExecutionTask }> {
  const requirement = useArchRequirementStore()
  const task = useArchTaskStore()
  const p = plan ?? buildBatchPlan(reqs)
  if (!p.taskPlanId) p.taskPlanId = `tp-${Date.now().toString().slice(-4)}`

  // 后端优先：POST /exec 原子 commitBatch(方案+任务树+执行任务+需求绑定 单事务)。
  if (await backendUp()) {
    try {
      const res = await apiPost<{ plan: DesignPlan; exec: ExecutionTask }>('/exec', {
        reqIds: reqs.map((r) => r.id),
        adapter,
        model: opts?.model,
        plan: p,
        testIds: opts?.testIds,
      })
      const planOut = res.plan
      const execOut = res.exec
      task.planToTaskTree[planOut.taskPlanId ?? planOut.id] = buildTaskTree(planOut, reqs)
      requirement.addPlan(planOut)
      if (planOut.status === 'confirmed') {
        requirement.confirmPlan(planOut.id)
      }
      if (!task.findExecution(execOut.id)) task.executionTasks.unshift(execOut)
      reqs.forEach((r) => { r.execId = execOut.id })
      return { plan: planOut, exec: execOut }
    } catch {
      // 后端调用失败 → 本地 mock 落盘(与既有行为一致)
    }
  }

  task.planToTaskTree[p.taskPlanId] = buildTaskTree(p, reqs)
  requirement.addPlan(p)
  requirement.confirmPlan(p.id)
  const exec = await task.createTask(p.id, adapter, { model: opts?.model, reqIds: reqs.map((r) => r.id) })
  reqs.forEach((r) => { r.execId = exec.id })
  return { plan: p, exec }
}
