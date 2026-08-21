import type { AgentMessage, AgentSession, AgentStatus, ExecutionTask, TaskNode } from '@/types'
import { INITIAL_SESSIONS } from './order-system'
import { runMockAgentSession } from './agent-engine'
import { mockResult } from './delay'
import type { RunHooks } from '../agent-service'

/**
 * 后端不可达时的本地 mock 兜底(与后端 WS 契约语义一致, 不落库)。
 * 接口形状对齐 AgentAdapter(见 services/agent-service.ts)。
 */

const sessions = new Map<string, AgentSession>(Object.entries(INITIAL_SESSIONS))
const cancelled = new Set<string>()

let seq = 0

export class MockAgentAdapter {
  async createSession(opts: { exec: ExecutionTask; planTitle: string; keepContext?: boolean }): Promise<AgentSession> {
    await mockResult(null, 300)
    const session: AgentSession = {
      id: `sess-${++seq}`,
      taskId: opts.exec.id,
      adapter: opts.exec.adapter,
      status: 'idle',
      keepContext: opts.keepContext ?? true,
      messages: [
        {
          id: `m-init-${seq}`,
          role: 'user',
          time: Date.now(),
          content: `创建会话 · 执行方案「${opts.planTitle}」(任务 ${opts.exec.id}, 第 ${opts.exec.runCount} 次)`,
        },
      ],
      artifacts: [],
      stats: { requests: 0, tokensIn: 0, tokensOut: 0, bytesIn: 0, bytesOut: 0 },
    }
    sessions.set(session.id, session)
    cancelled.delete(session.id)
    return structuredClone(session)
  }

  async sendMessage(session: AgentSession, content: string): Promise<AgentMessage> {
    await mockResult(null, 400)
    const msg: AgentMessage = {
      id: `m-${++seq}`, role: 'user', time: Date.now(), content,
    }
    session.messages.push(msg)
    return msg
  }

  async runTask(session: AgentSession, task: TaskNode, opts?: RunHooks): Promise<void> {
    sessions.set(session.id, session)
    cancelled.delete(session.id)
    await runMockAgentSession(session, task, {
      ...opts,
      isCancelled: opts?.isCancelled ?? (() => cancelled.has(session.id)),
      onStatus: (st) => { opts?.onStatus?.(st) },
    })
  }

  async getStatus(sessionId: string): Promise<AgentStatus> {
    return sessions.get(sessionId)?.status ?? 'idle'
  }

  async terminate(sessionId: string): Promise<void> {
    cancelled.add(sessionId)
    const s = sessions.get(sessionId)
    if (s && s.status !== 'done' && s.status !== 'failed') s.status = 'stopped'
  }
}
