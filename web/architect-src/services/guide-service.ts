import type { MissionKey, ProductForm, ProjectMode, WorkflowCtx, WorkflowMission, GuidedWorkflow } from '@/types'

/**
 * 引导工作流服务 —— 纯只读，推导 mission 完备度。
 *
 * 所有 mission 的 completeness 由 store 数据推导，
 * 引导自身不持有任何业务状态。
 */

export function buildWorkflowCtx(opts: {
  mode: ProjectMode
  productForm?: ProductForm
  scaffoldConfigured: boolean
  poolCount: number
  blueprintConfirmed: boolean
  execRootInitialized: boolean
  baselineCreated: boolean
}): WorkflowCtx {
  return { ...opts }
}

const MISSIONS: WorkflowMission[] = [
  {
    key: 'product-form',
    labelKey: 'guide.mission.productForm',
    route: '/overview',
    completeness: (ctx) => (ctx.productForm ? 1 : 0),
    example: { title: '产品形态参考', content: '选择产品形态：ui-ue（交互型：Web/移动端），io（契约型：服务/API/中间件）' },
  },
  {
    key: 'stack',
    labelKey: 'guide.mission.stack',
    route: '/workbench/config',
    completeness: (ctx) => {
      if (!ctx.scaffoldConfigured) return 0
      return 1
    },
    example: { title: '技术栈示例', content: 'Go + Gin + PostgreSQL，前端 Vue 3 + Vite' },
  },
  {
    key: 'initial-requirements',
    labelKey: 'guide.mission.initialRequirements',
    route: '/workbench/requirements',
    completeness: (ctx) => {
      if (ctx.poolCount === 0) return 0
      if (ctx.poolCount >= 1) return 1
      return 0.5
    },
    example: { title: '初始需求示例', content: '用户 Story：用户可提交订单并完成支付——从需求提案开始，经知识库分析入池。' },
  },
  {
    key: 'blueprint',
    labelKey: 'guide.mission.blueprint',
    route: '/workbench/requirements',
    completeness: (ctx) => {
      if (!ctx.blueprintConfirmed) return 0
      return 1
    },
    example: { title: '架构蓝图示例', content: 'mermaid 展示服务拆分 + ER 图——由 agent 依据需求草拟，用户逐层细化确认。' },
  },
  {
    key: 'scaffold',
    labelKey: 'guide.mission.scaffold',
    route: '/workbench/execute',
    completeness: (ctx) => {
      if (!ctx.execRootInitialized) return 0
      return 0.5
    },
    example: { title: '脚手架文件树', content: 'Go 项目骨架：cmd/ internal/ go.mod Dockerfile Makefile' },
  },
  {
    key: 'first-demo',
    labelKey: 'guide.mission.firstDemo',
    route: '/workbench/execute',
    completeness: (ctx) => {
      if (ctx.baselineCreated) return 1
      if (ctx.execRootInitialized) return 0.5
      return 0
    },
    example: { title: '首版 Demo', content: '优先价值路径：核心交互或核心 I/O 完整跑通——体验后回到 DesignTree 继续细化。' },
  },
]

export function buildGuidedWorkflow(ctx: WorkflowCtx): GuidedWorkflow {
  const missions = MISSIONS.map((m) => ({
    ...m,
    completeness: (c: WorkflowCtx) => m.completeness(c),
  }))
  return { missions, ctx: () => ctx }
}

export function overallCompleteness(missions: WorkflowMission[], ctx: WorkflowCtx): number {
  if (!missions.length) return 0
  const sum = missions.reduce((s, m) => s + m.completeness(ctx), 0)
  return Math.round((sum / missions.length) * 100)
}

export function missionByKey(key: MissionKey): WorkflowMission | undefined {
  return MISSIONS.find((m) => m.key === key)
}