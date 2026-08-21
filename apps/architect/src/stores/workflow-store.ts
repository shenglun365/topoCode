import { defineStore } from 'pinia'
import type { StepStatus, WorkflowStageCtx, WorkflowStageKey, WorkflowStep } from '@/types'
import { WORKFLOW_STAGES } from '@/config/workflow'
import { useArchRequirementStore } from './requirement-store'
import { useArchTaskStore } from './task-store'
import { useArchUnitTestStore } from './unit-test-store'

export const useArchWorkflowStore = defineStore('arch-workflow', {
  state: () => ({
    /** 当前阶段(写接口写入的游标)，由 syncFromRoute 依据路由 + 数据快照推导。 */
    current: 'pool' as WorkflowStageKey,
    // 遗留布尔态，供 AssetsPage / spec / staging 存量调用保持可用。
    designConfirmed: false,
    specConfirmed: false,
    executionDone: false,
    stagingDone: false,
    acceptanceDone: false,
  }),
  getters: {
    /** 数据快照：供阶段数据对象的 matches/isDone 谓词判定的上下文。 */
    ctx(): WorkflowStageCtx {
      const req = useArchRequirementStore()
      const task = useArchTaskStore()
      const ut = useArchUnitTestStore()
      return {
        proposalCount: req.proposals.length,
        poolCount: req.poolItems.length,
        analyzedCount: req.analyzedItems.length,
        confirmedPlanCount: req.confirmedPlans.length,
        activeTaskCount: task.activeTasks.length,
        acceptingCount: task.executionTasks.filter((t) => t.status === 'accepting').length,
        doneTaskCount: task.executionTasks.filter((t) => t.status === 'done').length,
        unitTestSessionCount: ut.sessions.length,
        passedTestCount: ut.tests.filter((t) => t.status === 'passed').length,
      }
    },
    /** 读接口：渲染用阶段列表(含 status 推导)。 */
    stages(state): WorkflowStep[] {
      const ctx = this.ctx
      const curIdx = WORKFLOW_STAGES.findIndex((s) => s.key === state.current)
      return WORKFLOW_STAGES.map((def, i) => {
        let status: StepStatus
        if (i < curIdx) status = 'done'
        else if (i === curIdx) status = 'active'
        else status = def.isDone(ctx) ? 'done' : 'locked'
        return { key: def.key, labelKey: def.labelKey, status, route: def.route }
      })
    },
    /** 读接口：当前命中的阶段(基于路由匹配)。 */
    currentStage(state): WorkflowStep | undefined {
      return this.stages.find((s) => s.key === state.current)
    },
    /** 读接口：当前阶段 i18n labelKey。 */
    currentLabelKey(state): string {
      return state.current
    },
  },
  actions: {
    /** 写接口：依据路由 path + query 推导当前阶段并落盘。 */
    syncFromRoute(path: string, query?: Record<string, unknown>) {
      const ctx = this.ctx
      const hit = WORKFLOW_STAGES.find((s) => s.matches(ctx, path, query))
      if (hit) this.current = hit.key
    },
    /** 写接口：显式设定当前阶段(如 stepper 点击跳转后同步)。 */
    setStage(key: WorkflowStageKey) {
      if (WORKFLOW_STAGES.some((s) => s.key === key)) this.current = key
    },
    // ---- 遗留动作(存量页面/存量 store 调用) ----
    confirmDesign() {
      this.designConfirmed = true
    },
    confirmSpec() {
      this.specConfirmed = true
    },
    finishExecution() {
      this.executionDone = true
    },
    confirmStaging() {
      this.stagingDone = true
    },
    finishAcceptance() {
      this.acceptanceDone = true
    },
    beginIteration() {
      this.designConfirmed = false
      this.specConfirmed = false
      this.executionDone = false
      this.stagingDone = false
      this.acceptanceDone = false
    },
  },
})
