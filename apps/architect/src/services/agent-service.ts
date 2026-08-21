import type { AgentAdapterInfo, AgentConfig, AgentEnvCheck, AgentInstance, AgentMessage, AgentProbeResult, AgentSession, AgentStatus, Connectivity, ExecutionTask, TaskNode } from '@/types'
import { apiGet, apiPost, apiPatch, apiDelete } from './api-client'
import { ArchWs } from './ws-client'
import { currentProjectParams } from './project-service'

/**
 * 三方 Coding Agent 适配接口 → 后端优先。
 *
 * 后端契约见 docs/architect/api-execution.md §5：
 *   - 会话创建/对话/执行均走 WS `/ws/coding-agent`(会话保持, 多轮沿用上下文)
 *   - 连通性经 `GET /agent/adapters/{id}/connectivity`
 * 后端不可达时直接抛错——不复用本地 mock。
 */

export interface AgentAdapter {
  createSession(opts: { exec: ExecutionTask; planTitle: string; keepContext?: boolean }): Promise<AgentSession>
  sendMessage(session: AgentSession, content: string, opts?: { keepContext?: boolean }): Promise<AgentMessage>
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

function pushLocal(session: AgentSession, msg: AgentMessage): void {
  session.messages.push(msg)
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
    pushLocal(session, userMsg)
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

  async runTask(session: AgentSession, task: TaskNode, opts?: RunHooks): Promise<void> {
    const ws = new ArchWs('ws/coding-agent')
    await ws.ready()

    const offStatus = ws.on('status', (ev) => {
      session.status = ev.status
      opts?.onStatus?.(ev.status)
    })
    const offMsg = ws.on('message', (ev) => {
      const m: AgentMessage = { id: ev.id, role: ev.role, time: ev.time, content: ev.content }
      session.messages.push(m)
      opts?.onMessage?.(m)
    })
    const offTool = ws.on('tool_call', (ev) => {
      const m: AgentMessage = { id: ev.id, role: 'tool', time: ev.time, tool: ev.tool, content: '' }
      session.messages.push(m)
      opts?.onMessage?.(m)
    })
    const offTree = ws.on('tree.change', (ev) => opts?.onTreeChange?.(ev.reason))

    const terminal = new Promise<AgentStatus>((resolve) => {
      ;['done', 'failed', 'stopped'].forEach((t) => {
        ws.on(t, (ev) => {
          session.status = ev.status
          if (ev.stats) session.stats = ev.stats
          if (ev.artifacts) session.artifacts = ev.artifacts
          if (ev.testResult) session.testResult = ev.testResult
          resolve(ev.status)
        })
      })
    })

    ws.send('task.run', { sessionId: session.id, task })
    try {
      await terminal
    } finally {
      offStatus()
      offMsg()
      offTool()
      offTree()
      ws.close()
    }
  }

  async getStatus(sessionId: string): Promise<AgentStatus> {
    const session = await apiGet<AgentSession>(`/agent/sessions/${sessionId}`)
    return session?.status ?? 'idle'
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

/** 列出 coding agent 适配器(真实来源: 后端 installer targets 注册表)。 */
export async function listAgentAdapters(): Promise<AgentAdapterInfo[]> {
  return apiGet<AgentAdapterInfo[]>('/agent/adapters')
}

/** 探测某个适配器的联通性(真实 detect())。 */
export async function checkAdapterConnectivity(id: string): Promise<Connectivity> {
  const res = await apiGet<{ status?: string }>(`/agent/adapters/${id}/connectivity`)
  return res?.status === 'ok' ? 'ok' : 'fail'
}

/** 验证本机 opencode 安装/适配完整性(可执行 + 版本 + 配置)。 */
export async function getOpencodeEnv(): Promise<AgentEnvCheck> {
  return apiGet<AgentEnvCheck>('/agent/opencode/env')
}

/** 列出已保存的三方 agent 连接配置。 */
export async function listAgentConfigs(): Promise<AgentConfig[]> {
  return apiGet<AgentConfig[]>('/agent/configs')
}

/** 新建连接配置。 */
export async function createAgentConfig(opts: Partial<AgentConfig>): Promise<AgentConfig> {
  return apiPost<AgentConfig>('/agent/configs', opts)
}

/** 更新连接配置。 */
export async function updateAgentConfig(id: string, opts: Partial<AgentConfig>): Promise<AgentConfig> {
  return apiPatch<AgentConfig>(`/agent/configs/${id}`, opts)
}

/** 删除连接配置。 */
export async function deleteAgentConfig(id: string): Promise<{ deleted: string }> {
  return apiDelete<{ deleted: string }>(`/agent/configs/${id}`)
}

/** 已保存配置的真实连通性测试。 */
export async function testAgentConfig(id: string): Promise<AgentConfig> {
  return apiPost<AgentConfig>(`/agent/configs/${id}/test`)
}

/** 未保存前的连通性预测试(弹窗内「测试连通性」用)。 */
export async function previewAgentConfig(opts: Partial<AgentConfig>): Promise<AgentProbeResult> {
  return apiPost<AgentProbeResult>('/agent/configs/preview', opts)
}

// ── 实例层(AgentInstancePool) ────────────────────────────────

/** 列出全部 agent 实例((project, adapter, host) 维度)。 */
export async function listAgentInstances(): Promise<AgentInstance[]> {
  return apiGet<AgentInstance[]>('/agent/instances')
}

/** 停止某实例(managed terminate / external 置 stopped)。 */
export async function stopAgentInstance(id: string): Promise<AgentInstance> {
  return apiPost<AgentInstance>(`/agent/instances/${id}/stop`, {})
}

/** 重启实例(重新 spawn / 重新探测)。 */
export async function restartAgentInstance(id: string): Promise<AgentInstance> {
  return apiPost<AgentInstance>(`/agent/instances/${id}/restart`, {})
}
