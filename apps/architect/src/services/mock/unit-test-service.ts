import type { AgentMessage, TestChannel, UnitTest, UnitTestSession } from '@/types'
import { UNIT_TESTS, UNIT_TEST_SESSIONS } from './unit-test-system'
import { mockResult } from './delay'
import type { UnitTestRunOpts } from '../unit-test-service'

/**
 * 后端不可达时的本地 mock 兜底(服务端模拟的镜像, 不落库)。
 * 形状对齐 services/unit-test-service.ts。
 */

const tests: UnitTest[] = structuredClone(UNIT_TESTS)
const sessions: UnitTestSession[] = structuredClone(UNIT_TEST_SESSIONS)

let seq = 0

export const mockUnitTestService = {
  async listTests(): Promise<UnitTest[]> {
    await mockResult(null, 150)
    return structuredClone(tests)
  },

  async listSessions(): Promise<UnitTestSession[]> {
    await mockResult(null, 150)
    return structuredClone(sessions)
  },

  async addTest(data: Partial<UnitTest>): Promise<UnitTest> {
    await mockResult(null, 200)
    const now = Date.now()
    const t: UnitTest = {
      id: `ut-${++seq}`,
      name: data.name ?? '未命名单测',
      levels: data.levels ?? [],
      scriptPath: data.scriptPath ?? '',
      source: data.source ?? 'manual',
      status: 'idle',
      createdAt: now,
      updatedAt: now,
    }
    tests.unshift(t)
    return structuredClone(t)
  },

  async createSession(opts: { title: string; channel: TestChannel; adapter: string; testIds?: string[] }): Promise<UnitTestSession> {
    await mockResult(null, 300)
    const now = Date.now()
    const s: UnitTestSession = {
      id: `uts-${++seq}`,
      title: opts.title,
      channel: opts.channel,
      adapter: opts.adapter,
      testIds: opts.testIds ?? [],
      status: 'created',
      messages: [
        { id: `m-init-${seq}`, role: 'user', time: now, content: `创建单测会话「${opts.title}」 · 执行通道: ${opts.channel === 'cli' ? 'topocode 命令行' : '三方 agent'}` },
      ],
      stats: { requests: 0, tokensIn: 0, tokensOut: 0, bytesIn: 0, bytesOut: 0 },
      createdAt: now,
      updatedAt: now,
    }
    sessions.unshift(s)
    return structuredClone(s)
  },

  async runTests(session: UnitTestSession, target: UnitTest[], opts?: UnitTestRunOpts): Promise<void> {
    for (const t of target) {
      if (opts?.isCancelled?.()) {
        session.status = 'stopped'
        return
      }
      session.status = 'running'
      t.status = 'running'
      opts?.onMessage?.({
        id: `m-${++seq}`, role: 'tool', time: Date.now(),
        tool: { type: 'run-test', label: t.scriptPath || t.name, detail: `开始执行「${t.name}」`, ok: true },
        content: '',
      })
      await mockResult(null, 600)
      if (opts?.isCancelled?.()) {
        t.status = 'skipped'
        session.status = 'stopped'
        return
      }
      const fail = t.id === 'ut-3'
      t.status = fail ? 'failed' : 'passed'
      const result = fail
        ? { passed: 5, failed: 2, error: 'TestRelayRetry: 重试退避断言失败', note: 'go test ./outbox-service', at: Date.now() }
        : { passed: t.id === 'ut-2' ? 8 : 12, failed: 0, note: '全部通过', at: Date.now() }
      t.lastResult = result
      opts?.onMessage?.({
        id: `m-${++seq}`, role: 'tool', time: Date.now(),
        tool: {
          type: 'run-test', label: t.scriptPath || t.name,
          detail: fail ? `失败: ${result.error}` : `通过: ${result.passed} 用例`,
          ok: !fail,
        },
        content: '',
      })
    }
    session.status = 'done'
  },

  async sendMessage(session: UnitTestSession, content: string): Promise<AgentMessage> {
    await mockResult(null, 400)
    const msg: AgentMessage = { id: `m-${++seq}`, role: 'user', time: Date.now(), content }
    session.messages.push(msg)
    const reply: AgentMessage = {
      id: `m-${++seq}`, role: 'assistant', time: Date.now(),
      content: session.channel === 'cli'
        ? '已接收指令。请回到左栏选择失败用例重新执行，或补充修复提示。'
        : `收到，将基于报错「${content.slice(0, 24)}」分析并修复，修复后可重新触发关联单测。`,
    }
    session.messages.push(reply)
    return msg
  },
}
