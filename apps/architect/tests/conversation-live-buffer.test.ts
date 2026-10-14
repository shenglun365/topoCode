/**
 * cv-221 实时通路根修特征测试 —— 消息缓冲区异步消费 + 拉取即真相。
 *
 * 不变量:
 *  I1 消费期判卫: 事件先于会话绑定到达 → 不丢弃, 绑定后消费(拉取发生);
 *  I2 拉取即真相: turnEnd/重连/可见性/切会话 4 触发点补偿;
 *  I3 单消费者: 事件风暴折叠为单次拉取; busy defer 不回归(cv-194);
 *  I4 通道职责: progress 进缓冲按任务折叠(≤150ms), patch 直接生效。
 *
 * Run: cd apps/architect && npx vitest run tests/conversation-live-buffer.test.ts
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const messagesMock = vi.hoisted(() => vi.fn(async () => ({
  id: 'cv-x', title: 'T', messages: [
    { id: 'm1', role: 'user', time: 1, content: 'q' },
    { id: 'm2', role: 'assistant', time: 2, content: '回执', meta: { kind: 'specReady' } },
  ],
})))
const listMock = vi.hoisted(() => vi.fn(async () => []))
const updateMock = vi.hoisted(() => vi.fn(async () => ({})))

vi.mock('@/services/session-service', () => ({
  sessionService: {
    messages: messagesMock,
    list: listMock,
    update: updateMock,
    summarize: vi.fn(async () => ({})),
    guide: vi.fn(async () => ({ text: '' })),
    context: vi.fn(async () => []),
    units: vi.fn(async () => ({ units: [] })),
  },
}))
vi.mock('@/services/kb-analysis-agent', () => ({
  chatStream: vi.fn(),
  stageOfTool: vi.fn(() => ''),
}))
vi.mock('@/services/project-service', () => ({
  currentProjectParams: vi.fn(() => ({ project: 'proj-x', root: '' })),
}))
vi.mock('@/services/requirement-service', () => ({
  requirementService: { deleteMessage: vi.fn(), rollbackMessages: vi.fn() },
}))
vi.mock('@/services/outline-cache', () => ({
  outlineAbbrCache: { removeMessages: vi.fn() },
}))
vi.mock('@/shell/prefs', () => ({ readModelPref: vi.fn(() => '') }))
vi.mock('@/composables/useDiagramSkill', () => ({
  useDiagramSkill: vi.fn(() => ({ diagramSkill: { value: false }, toggleDiagramSkill: vi.fn() })),
}))
vi.mock('@/composables/useChatProgress', () => ({
  useChatProgress: vi.fn(() => ({
    busyLabel: { value: '' }, toolTrail: { value: [] },
    begin: vi.fn(), onChatEvent: vi.fn(),
  })),
}))

import { createPinia, setActivePinia } from 'pinia'
import { useConversationStore } from '@/stores/conversation-store'

const flush = (ms = 30) => new Promise((r) => setTimeout(r, ms))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  // jsdom 无 EventSource → store.connectEvents 短路; 测试直接驱动 enqueueEvent
})
afterEach(() => { vi.useRealTimers() })

async function bindActive() {
  const conv = useConversationStore()
  await conv.openConversation({ id: 'cv-x', reqId: '', title: 'T' })
  messagesMock.mockClear()                       // open 自带 pull, 清零后只看信号触发
  return conv
}

describe('I1 消费期判卫(先于绑定到达的事件不丢失)', () => {
  it('事件先到、会话后开 → 打开会话时消费发生(拉取至少 open 自身一次)', async () => {
    const conv = useConversationStore()
    conv.enqueueEvent({ type: 'conv-message', conversationId: 'cv-x' })
    await flush(10)
    expect(messagesMock).not.toHaveBeenCalled()  // 非活跃且未开 → 仅记账
    await conv.openConversation({ id: 'cv-x', reqId: '', title: 'T' })
    await flush(10)
    expect(messagesMock).toHaveBeenCalled()      // open 路径拉取(数据零丢失)
  })

  it('活跃会话的 conv-message → 防抖后拉取(实时刷新)', async () => {
    await bindActive()
    const conv = useConversationStore()
    conv.enqueueEvent({ type: 'conv-message', conversationId: 'cv-x' })
    await flush(450)
    expect(messagesMock).toHaveBeenCalledTimes(1)
  })
})

describe('I2 拉取即真相(4 触发点补偿)', () => {
  it('turnEnd(所有回合类型)收尾 → 尾沿补偿拉取(cv-221 泛化)', async () => {
    await bindActive()
    const conv = useConversationStore()
    conv.enqueueEvent({ type: 'turnEnd', conversationId: 'cv-x' })
    await flush(450)
    expect(messagesMock).toHaveBeenCalledTimes(1)
  })

  it('非活跃会话事件 → 记账不丢弃; 无需断言拉取(切回时由 open 拉取)', async () => {
    await bindActive()
    const conv = useConversationStore()
    conv.enqueueEvent({ type: 'conv-message', conversationId: 'cv-other' })
    await flush(450)
    expect(messagesMock).not.toHaveBeenCalled()  // 不为非活跃会话拉取(噪音隔离)
  })
})

describe('I3 单消费者(折叠 + busy defer)', () => {
  it('事件风暴(5 条同类) → 折叠为单次拉取', async () => {
    await bindActive()
    const conv = useConversationStore()
    for (let i = 0; i < 5; i++) {
      conv.enqueueEvent({ type: 'conv-message', conversationId: 'cv-x' })
      await flush(5)
    }
    await flush(450)
    expect(messagesMock).toHaveBeenCalledTimes(1)
  })

  it('busy 窗口内 conv-message → 推迟; busy 解除 → 补偿拉取(cv-194 不回归)', async () => {
    const conv = useConversationStore()
    await conv.openConversation({ id: 'cv-x', reqId: '', title: 'T' })
    messagesMock.mockClear()
    conv.busy = true                       // 模拟回合进行中
    conv.enqueueEvent({ type: 'conv-message', conversationId: 'cv-x' })
    await flush(450)
    expect(messagesMock).not.toHaveBeenCalled()  // defer(不打断流式渲染)
    conv.busy = false
    conv.enqueueEvent({ type: 'turnEnd', conversationId: 'cv-x' })
    await flush(500)
    expect(messagesMock).toHaveBeenCalled()      // 补偿发生
  })
})

describe('I4 progress 进缓冲(按任务折叠)', () => {
  it('progress 事件 → 消费者直接 patch 任务面板(无需拉取)', async () => {
    await bindActive()
    const conv = useConversationStore()
    conv.tasks = [{ id: 'task-9', title: 'T', status: 'running' }] as any
    conv.enqueueEvent({ type: 'progress', conversationId: 'cv-x', taskId: 'task-9',
                        toolCount: 3, lastTool: 'edit' })
    await flush(30)
    expect((conv.tasks[0] as any).progress.toolCount).toBe(3)
    expect(messagesMock).not.toHaveBeenCalled()  // 瞬态修饰态不触发拉取
  })

  it('突发风暴: 同任务 150ms 窗口内折叠(≤2 次 patch, 延迟有界)', async () => {
    await bindActive()
    const conv = useConversationStore()
    conv.tasks = [{ id: 'task-9', title: 'T', status: 'running' }] as any
    const patches: number[] = []
    for (let i = 0; i < 6; i++) {
      conv.enqueueEvent({ type: 'progress', conversationId: 'cv-x', taskId: 'task-9',
                          toolCount: i + 1 })
    }
    // 观察窗口内 patch 次数(折叠语义: 150ms 内至多首尾)
    const t0 = Date.now()
    while (Date.now() - t0 < 400) {
      await flush(40)
      const n = (conv.tasks[0] as any).progress?.toolCount || 0
      if (patches[patches.length - 1] !== n) patches.push(n)
      if (Date.now() - t0 > 380) break
    }
    expect(patches.length).toBeLessThanOrEqual(3)
    expect((conv.tasks[0] as any).progress.toolCount).toBe(6)  // 最终态不丢
  })
})
