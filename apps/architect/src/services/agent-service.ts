import type { AgentMessage, AgentSession, ExecutionTask } from '@/types'
import { ArchWs } from './ws-client'
import { currentProjectParams } from './project-service'

/**
 * Coding agent 会话接口 → 后端(WS /ws/coding-agent)。
 *
 * A7 起对话经 tAgent(代码问答, agentic_loop + KB/代码工具)；执行走 runner(见 runner-service)。
 * 三方 agent 连接池/配置/实例(原 agent_config/agent_server/agent_adapters)已移除。
 * 后端契约见 docs/architect/api-execution.md §5。
 */

export interface AgentAdapter {
  createSession(opts: { exec: ExecutionTask; planTitle: string; keepContext?: boolean }): Promise<AgentSession>
  sendMessage(session: AgentSession, content: string, opts?: { keepContext?: boolean }): Promise<AgentMessage>
  terminate(sessionId: string): Promise<void>
}

class HttpAgentAdapter implements AgentAdapter {
  async createSession(opts: { exec: ExecutionTask; planTitle: string; keepContext?: boolean }): Promise<AgentSession> {
    const ws = new ArchWs('ws/coding-agent')
    await ws.ready()
    ws.send('session.create', {
      exec: opts.exec,
      planTitle: opts.planTitle,
      keepContext: opts.keepContext ?? true,
      root: currentProjectParams().root,
      project: currentProjectParams().project,
    })
    const res = await ws.once<any>('session_created')
    ws.close()
    return res.session as AgentSession
  }

  async sendMessage(session: AgentSession, content: string): Promise<AgentMessage> {
    const userMsg: AgentMessage = { id: `m-${Date.now()}`, role: 'user', time: Date.now(), content }
    session.messages.push(userMsg)
    const ws = new ArchWs('ws/coding-agent')
    await ws.ready()
    const replyP = ws.once<any>('message', 15000)
    ws.send('session.message', { sessionId: session.id, content })
    try {
      const reply = await replyP
      const m: AgentMessage = { id: reply.id, role: reply.role, time: reply.time, content: reply.content }
      session.messages.push(m)
    } catch {
      // 后端无回复时仅保留本地用户消息
    }
    ws.close()
    return userMsg
  }

  async terminate(sessionId: string): Promise<void> {
    const ws = new ArchWs('ws/coding-agent')
    await ws.ready()
    ws.send('session.stop', { sessionId })
    ws.close()
  }
}

const httpAdapter = new HttpAgentAdapter()

export const agentService: AgentAdapter = httpAdapter
