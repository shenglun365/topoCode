import type { AgentMessage, AgentSession, AgentStatus, ExecutionTask, TaskNode } from '@/types'
import { INITIAL_SESSIONS } from './mock/order-system'
import { runMockAgentSession } from './mock/agent-engine'
import { mockResult } from './mock/delay'

/**
 * 三方 Coding Agent 适配接口。
 *
 * 后端需提供「会话保持」能力 —— opencode / codex 等主流 CLI agent 均支持
 * 多轮会话(multi-turn)且沿用同一会话上下文，本工具以 subagent 模式对接：
 *   1. 每个执行任务(ExecutionTask)创建一个独立会话，会话绑定到方案的任务方案树
 *   2. 会话携带「上下文包」(方案 + 需求 + 编码规约 + 相关文件)
 *   3. 多轮对话持续引用同一上下文，直至测试验收通过
 *
 * 原型阶段全部为 mock 实现，真实接入时替换为对后端 HTTP/WebSocket 的调用。
 */
export interface AgentAdapter {
  createSession(opts: { exec: ExecutionTask; planTitle: string; keepContext?: boolean }): Promise<AgentSession>
  sendMessage(sessionId: string, content: string, opts?: { keepContext?: boolean }): Promise<AgentMessage>
  runTask(session: AgentSession, task: TaskNode, opts?: RunHooks): Promise<void>
  getStatus(sessionId: string): Promise<AgentStatus>
  terminate(sessionId: string): Promise<void>
}

export interface RunHooks {
  onMessage?: (msg: AgentMessage) => void
  onStatus?: (status: AgentStatus) => void
  /** 任务树结构发生重大变化时回调(旧树由调用方保存后重建)。 */
  onTreeChange?: (reason: string) => void
  /** 是否已请求取消执行(停止)。 */
  isCancelled?: () => boolean
}

const sessions = new Map<string, AgentSession>(Object.entries(INITIAL_SESSIONS))
/** 已请求停止的会话 id(前端 mock 停止接口)。 */
const cancelled = new Set<string>()

let seq = 0

class MockAgentAdapter implements AgentAdapter {
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

  async sendMessage(sessionId: string, content: string): Promise<AgentMessage> {
    await mockResult(null, 400)
    const s = sessions.get(sessionId)
    const msg: AgentMessage = {
      id: `m-${++seq}`, role: 'user', time: Date.now(), content,
    }
    s?.messages.push(msg)
    return msg
  }

  async runTask(session: AgentSession, task: TaskNode, opts?: RunHooks): Promise<void> {
    // 会话保持: 直接复用传入的会话对象(与 store 同一引用), 保证 UI 实时可见
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

  /** 停止执行(前端 mock；后端需适配各 agent 的终止接口)。 */
  async terminate(sessionId: string): Promise<void> {
    cancelled.add(sessionId)
    const s = sessions.get(sessionId)
    if (s && s.status !== 'done' && s.status !== 'failed') s.status = 'stopped'
  }
}

export const agentService: AgentAdapter = new MockAgentAdapter()

export function getSession(sessionId: string): AgentSession | undefined {
  return sessions.get(sessionId)
}
