import { describe, it, expect } from 'vitest'
import { WORKFLOW_STAGES } from '@/config/workflow'

const baseCtx = {
  proposalCount: 0, poolCount: 0, activeTaskCount: 0,
  acceptingCount: 0, doneTaskCount: 0, passedTestCount: 0,
} as any

describe('WORKFLOW_STAGES（4 阶段流水线定义）', () => {
  it('阶段顺序 = pool → design → execute → accept', () => {
    expect(WORKFLOW_STAGES.map((s) => s.key)).toEqual(['pool', 'design', 'execute', 'accept'])
  })

  it('每阶段都有 matches 与 isDone 判定', () => {
    for (const s of WORKFLOW_STAGES) {
      expect(typeof s.matches).toBe('function')
      expect(typeof s.isDone).toBe('function')
    }
  })

  it('pool：提案数 > 0 即完成；需求页非 pool tab 时命中', () => {
    const pool = WORKFLOW_STAGES[0]
    expect(pool.matches(baseCtx, '/workbench/requirements', {})).toBe(true)
    expect(pool.matches(baseCtx, '/workbench/requirements', { tab: 'pool' })).toBe(false)
    expect(pool.isDone({ ...baseCtx, proposalCount: 1 })).toBe(true)
    expect(pool.isDone(baseCtx)).toBe(false)
  })

  it('design：需求池 tab 命中；poolCount > 0 即完成', () => {
    const design = WORKFLOW_STAGES[1]
    expect(design.matches(baseCtx, '/workbench/requirements', { tab: 'pool' })).toBe(true)
    expect(design.isDone({ ...baseCtx, poolCount: 2 })).toBe(true)
  })

  it('execute：有活动/完成/验收中任务即完成', () => {
    const execute = WORKFLOW_STAGES[2]
    expect(execute.isDone({ ...baseCtx, activeTaskCount: 1 })).toBe(true)
    expect(execute.isDone({ ...baseCtx, doneTaskCount: 1 })).toBe(true)
    expect(execute.isDone(baseCtx)).toBe(false)
  })

  it('accept：单测页或 execute 页有验收/完成任务时命中', () => {
    const accept = WORKFLOW_STAGES[3]
    expect(accept.matches(baseCtx, '/workbench/unit-test', undefined)).toBe(true)
    expect(accept.matches({ ...baseCtx, acceptingCount: 2 }, '/workbench/execute', undefined)).toBe(true)
    expect(accept.matches(baseCtx, '/workbench/execute', undefined)).toBe(false)
    expect(accept.isDone({ ...baseCtx, passedTestCount: 1 })).toBe(true)
  })
})
