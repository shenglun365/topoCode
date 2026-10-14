/**
 * MS6-W0 安全网：community-store(1,252 行) 形状守卫。
 * MS6-W5 将抽 useComponentAnalysis——先锁 store 公共面(状态键/动作函数)。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const RICH = { items: [], total: 0, list: [], data: [], entries: [], tasks: [], ok: true }
vi.mock('@/services/ipc', () => ({
  ipc: new Proxy({}, { get: () => vi.fn(async () => ({ ...RICH })) }),
}))
vi.mock('@/services/llmClient', () => ({
  isLLMConfigured: vi.fn(() => false),
}))
vi.mock('@/services/control-dispatcher', () => ({
  controlDispatcher: new Proxy({}, { get: () => vi.fn() }),
}))
vi.mock('@/services/sound', () => ({
  playSuccessSound: vi.fn(),
  playFailureSound: vi.fn(),
}))
vi.mock('@/services/display-dispatcher', () => ({
  displayDispatcher: new Proxy({}, { get: () => vi.fn() }),
}))

import { useCommunityStore, agentCompletedSignal, pipelineSummary } from '@/stores/community-store'

describe('community-store 形状守卫(MS6-W0, 抽 useComponentAnalysis 前锁面)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('ensureTask 创建完整任务运行时形状(15 键)', () => {
    const s = useCommunityStore()
    const rt: any = s.ensureTask('t1')
    for (const k of [
      'communityRunning', 'communityPaused', 'communities', 'projectContext',
      'llmResults', 'errorLogs', 'analysisStates', 'uniqueFileCounts',
      'externalStats', 'crossCommunityEdges', 'nodeLists', 'fileDetails',
      'fileGraphs', 'agentTasks',
    ]) {
      expect(rt, `运行时缺键: ${k}`).toHaveProperty(k)
    }
  })

  it('模块级信号量初始态(agentCompletedSignal=0, pipelineSummary=null)', () => {
    expect(agentCompletedSignal.value).toBe(0)
    expect(pipelineSummary.value).toBeNull()
  })

  it('store 公共动作面 > 10 个函数(重构后仍须保全)', () => {
    const s = useCommunityStore()
    const fns = Object.keys(s).filter((k) => typeof (s as any)[k] === 'function')
    expect(fns.length).toBeGreaterThan(10)
    expect(fns).toContain('ensureTask')
  })

  it('getSelections 默认空数组', () => {
    const s = useCommunityStore()
    expect(s.getSelections('no-such-task')).toEqual([])
  })
})
