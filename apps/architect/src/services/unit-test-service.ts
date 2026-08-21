import type { AgentMessage, TestChannel, UnitTest, UnitTestSession } from '@/types'
import { apiGet, apiPost } from './api-client'
import { ArchWs } from './ws-client'

/**
 * 单元测试适配接口。
 * 后端可用: REST(列表/添加/会话) + WS(执行/对话), 服务端模拟并落库。
 * 后端失败直接抛出——不复用本地 mock。
 */

export interface UnitTestRunOpts {
  onMessage?: (msg: AgentMessage) => void
  isCancelled?: () => boolean
}

export const unitTestService = {
  async listTests(): Promise<UnitTest[]> {
    return apiGet<UnitTest[]>('/unit-tests')
  },

  async listSessions(): Promise<UnitTestSession[]> {
    return apiGet<UnitTestSession[]>('/unit-test-sessions')
  },

  async addTest(data: Partial<UnitTest>): Promise<UnitTest> {
    return apiPost<UnitTest>('/unit-tests', data)
  },

  async createSession(opts: { title: string; channel: TestChannel; adapter: string; testIds?: string[] }): Promise<UnitTestSession> {
    return apiPost<UnitTestSession>('/unit-test-sessions', opts)
  },

  async runTests(session: UnitTestSession, target: UnitTest[], opts?: UnitTestRunOpts): Promise<void> {
    session.status = 'running'
    const ws = new ArchWs('ws/unit-test')
    await ws.ready()

    const terminal = new Promise<string>((resolve) => {
      ws.on('status', (ev) => {
        session.status = ev.status
        if (ev.status === 'done' || ev.status === 'stopped') resolve(ev.status)
      })
    })

    const offTool = ws.on('tool_call', (ev) => {
      const m: AgentMessage = { id: ev.id, role: 'tool', time: ev.time, tool: ev.tool, content: '' }
      session.messages.push(m)
      opts?.onMessage?.(m)
    })

    const offResult = ws.on('result', (ev) => {
      const t = target.find((x) => x.id === ev.testId)
      if (!t) return
      t.status = ev.status
      t.lastResult = ev.lastResult
    })

    ws.send('run', { sessionId: session.id, testIds: target.map((x) => x.id) })

    try {
      await Promise.race([terminal, new Promise((_, reject) => setTimeout(() => reject(new Error('run timeout')), 120000))])
    } finally {
      if (opts?.isCancelled?.()) ws.send('stop', { sessionId: session.id })
      offTool()
      offResult()
      ws.close()
    }
  },

  async sendMessage(session: UnitTestSession, content: string): Promise<AgentMessage> {
    const userMsg: AgentMessage = { id: `m-${Date.now()}`, role: 'user', time: Date.now(), content }
    session.messages.push(userMsg)
    const ws = new ArchWs('ws/unit-test')
    await ws.ready()
    const replyP = ws.once<any>('message', 15000)
    ws.send('message', { sessionId: session.id, content })
    try {
      const reply = await replyP
      const m: AgentMessage = { id: reply.id, role: reply.role, time: reply.time, content: reply.content }
      session.messages.push(m)
    } catch {
      // 后端无回复时仅保留本地用户消息
    }
    ws.close()
    return userMsg
  },
}