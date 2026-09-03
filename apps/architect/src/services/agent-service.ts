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
  sendMessage(session: AgentSession, content: string, opts?: { keepContext?: boolean; signal?: AbortSignal; onStatus?: (phase: string) => void }): Promise<AgentMessage>
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

  async sendMessage(session: AgentSession, content: string, opts?: { keepContext?: boolean; signal?: AbortSignal; onStatus?: (phase: string) => void }): Promise<AgentMessage> {
    const userMsg: AgentMessage = { id: `m-${Date.now()}`, role: 'user', time: Date.now(), content }
    session.messages.push(userMsg)
    const ws = new ArchWs('ws/coding-agent')
    const signal = opts?.signal
    await ws.ready()
    // 后端 status 相位(chat=问答处理中/idle=结束)：降级通道长等待的进度感知
    if (opts?.onStatus) ws.on('status', (ev: any) => opts.onStatus?.(ev?.phase || ''))
    const replyP = ws.once<any>('message', 15000)
    replyP.catch(() => {}) // 防 abort 后 replyP 的 reject 成 unhandled rejection
    ws.send('session.message', { sessionId: session.id, content })
    let onAbort: (() => void) | null = null
    const abortP = signal
      ? new Promise<never>((_, rej) => {
          onAbort = () => { ws.close(); rej(new Error('aborted')) }
          if (signal.aborted) onAbort()
          else signal.addEventListener('abort', onAbort, { once: true })
        })
      : null
    try {
      const reply = abortP ? await Promise.race([replyP, abortP]) : await replyP
      const m: AgentMessage = { id: reply.id, role: reply.role, time: reply.time, content: reply.content }
      session.messages.push(m)
    } catch {
      // 后端无回复或被终止时仅保留本地用户消息
    } finally {
      if (signal && onAbort) signal.removeEventListener('abort', onAbort)
      ws.close()
    }
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
