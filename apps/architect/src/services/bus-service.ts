import { apiGet, apiPost } from './api-client'
import { ArchWs } from './ws-client'

/**
 * agent-bus 总线接口(P3.3)：经 architect 桥接(broker :3486 共享主库)。
 * - publish：向 broker 发布消息(前端/外部回报)；
 * - needsInput：「需要你输入(N)」汇总(blocked/accepting 任务 + 未回复 clarify)；
 * - connectBusEvents：WS 总线事件流(architect 同源代理 → broker，监控页用)。
 */

export interface BusMessage {
  id: string
  src: string
  dst: string
  topic: string
  payload: Record<string, unknown>
  status: string
  error?: string
  createdAt: number
  updatedAt?: number
}

export interface NeedsInputItem {
  type: 'task' | 'clarify'
  id: string
  reqId: string
  src: string
  label: string
  status: string
}

export const busService = {
  async publish(src: string, dst: string, topic: string,
                payload: Record<string, unknown> = {}): Promise<{ id: string; status: string }> {
    return apiPost<{ id: string; status: string }>('/bus/publish', { src, dst, topic, payload })
  },
  async needsInput(): Promise<{ count: number; items: NeedsInputItem[] }> {
    return apiGet<{ count: number; items: NeedsInputItem[] }>('/bus/needs-input')
  },
}

export interface BusEventHandlers {
  onState?: (messages: BusMessage[]) => void
  onMessage?: (message: BusMessage) => void
  onError?: (message: string) => void
  onClose?: () => void
}

export interface BusEventConnection {
  close(): void
}

/** 连接总线事件流(architect WS 代理 → broker)。state=初始最近20条，message=新消息。 */
export function connectBusEvents(h: BusEventHandlers): BusEventConnection {
  const ws = new ArchWs('ws/agent-bus')
  let closed = false
  const offs = [
    ws.on('state', (m: any) => h.onState?.(m?.messages ?? [])),
    ws.on('message', (m: any) => h.onMessage?.(m?.message ?? {})),
    ws.on('error', (m: any) => h.onError?.(m?.message ?? '')),
    ws.onClose(() => {
      if (closed) return
      closed = true
      h.onClose?.()
    }),
  ]
  ws.ready().catch(() => h.onError?.('无法连接 agent-bus 事件流'))
  return {
    close() {
      if (closed) return
      closed = true
      offs.forEach((off) => off())
      ws.close()
    },
  }
}
