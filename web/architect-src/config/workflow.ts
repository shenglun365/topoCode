import type { WorkflowStageCtx, WorkflowStageDef } from '@/types'

/**
 * 流水线阶段的数据对象定义(声明式)。
 * 这里的顺序即 stepper 展示顺序；后续微调阶段、路由或完成判定，只改本文件。
 * 需求提案 → 需求池(概要设计产出) → 任务执行 → 质量验收
 */
export const WORKFLOW_STAGES: WorkflowStageDef[] = [
  {
    key: 'pool',
    labelKey: 'pool',
    route: { path: '/workbench/requirements' },
    matches: (_ctx, path, query) => path === '/workbench/requirements' && query?.tab !== 'pool',
    isDone: (ctx: WorkflowStageCtx) => ctx.proposalCount > 0,
  },
  {
    key: 'design',
    labelKey: 'design',
    route: { path: '/workbench/requirements', query: { tab: 'pool' } },
    matches: (_ctx, path, query) => path === '/workbench/requirements' && query?.tab === 'pool',
    isDone: (ctx: WorkflowStageCtx) => ctx.poolCount > 0,
  },
  {
    key: 'execute',
    labelKey: 'execute',
    route: { path: '/workbench/execute' },
    matches: (ctx, path) => path === '/workbench/execute' && ctx.acceptingCount === 0,
    isDone: (ctx: WorkflowStageCtx) => ctx.activeTaskCount > 0 || ctx.acceptingCount > 0 || ctx.doneTaskCount > 0,
  },
  {
    key: 'accept',
    labelKey: 'accept',
    route: { path: '/workbench/execute' },
    matches: (ctx, path) => path === '/workbench/execute' && ctx.acceptingCount > 0,
    isDone: (ctx: WorkflowStageCtx) => ctx.doneTaskCount > 0,
  },
]
