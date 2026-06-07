/** ZeroMQ Router - 消息路由中枢 (真实后端连接) */

import { EventEmitter } from 'events'

// ZMQ 端口 — 优先从环境变量读取
const ZMQ_DEALER_PORT = parseInt(process.env.ZMQ_DEALER_PORT || '5671', 10)
const ZMQ_PUB_PORT = parseInt(process.env.ZMQ_PUB_PORT || '5680', 10)
const ZMQ_HOST = process.env.ZMQ_BIND_HOST || '127.0.0.1'

let ZMQ: any = null
try {
  ZMQ = require('zeromq')
} catch (e: any) {
  console.error('[ZMQRouter] zeromq load failed:', e.message)
}

export interface ZMQEvent {
  topic: string
  eventType: string
  data: Record<string, any>
}

export class ZMQRouter extends EventEmitter {
  private dealer: any = null
  private sub: any = null
  private pendingRequests = new Map<string, { resolve: Function; reject: Function; timer: NodeJS.Timeout }>()
  private requestCounter = 0
  private connected = false
  private reconnectTimer: NodeJS.Timeout | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 10
  private shouldReconnect = true

  constructor() {
    super()
  }

  get isConnected(): boolean {
    return this.connected
  }

  get pendingCount(): number {
    return this.pendingRequests.size
  }

  /** 连接到后端 */
  async connect(): Promise<void> {
    if (!ZMQ) {
      throw new Error('zeromq module not available')
    }

    this.shouldReconnect = true
    this.reconnectAttempts = 0

    try {
      this.dealer = new ZMQ.Dealer()
      await this.dealer.connect(`tcp://${ZMQ_HOST}:${ZMQ_DEALER_PORT}`)
      console.log(`[ZMQRouter] DEALER connected to tcp://${ZMQ_HOST}:${ZMQ_DEALER_PORT}`)

      this.sub = new ZMQ.Subscriber()
      await this.sub.connect(`tcp://${ZMQ_HOST}:${ZMQ_PUB_PORT}`)
      this.sub.subscribe('task')
      this.sub.subscribe('project')
      this.sub.subscribe('backend')
      this.sub.subscribe('llm')
      console.log(`[ZMQRouter] SUB connected to tcp://${ZMQ_HOST}:${ZMQ_PUB_PORT}`)

      this.connected = true
      this.reconnectAttempts = 0
      this.startListening()
    } catch (error) {
      console.error('[ZMQRouter] Connection failed:', error)
      this.connected = false
      this.scheduleReconnect()
      throw error
    }
  }

  /** 自动重连 (指数退避) */
  private scheduleReconnect(): void {
    if (!this.shouldReconnect || this.reconnectAttempts >= this.maxReconnectAttempts) return

    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000)
    this.reconnectAttempts++
    console.log(`[ZMQRouter] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`)

    this.reconnectTimer = setTimeout(async () => {
      try {
        await this.connect()
        this.emit('reconnected')
      } catch {
        this.scheduleReconnect()
      }
    }, delay)
  }

  /** 开始监听 */
  private startListening(): void {
    if (!this.sub) return

    ;(async () => {
      try {
        for await (const [topic, eventType, data] of this.sub) {
          const event: ZMQEvent = {
            topic: topic.toString(),
            eventType: eventType.toString(),
            data: JSON.parse(data.toString()),
          }
          this.emit(`event:${event.topic}.${event.eventType}`, event.data)
          this.emit('event', event)
        }
      } catch (err) {
        console.error('[ZMQRouter] SUB listener error:', err)
        this.connected = false
        this.scheduleReconnect()
      }
    })()

    ;(async () => {
      try {
        for await (const frames of this.dealer) {
          this.handleResponse(frames)
        }
      } catch (err) {
        console.error('[ZMQRouter] DEALER listener error:', err)
        this.connected = false
        this.scheduleReconnect()
      }
    })()
  }

  /** 发送 RPC 请求 */
  async call<T = any>(method: string, params: Record<string, any> = {}): Promise<T> {
    if (!this.connected || !this.dealer) {
      throw new Error('ZMQ not connected')
    }

    const requestId = `req-${++this.requestCounter}`

    return new Promise<T>((resolve, reject) => {
      const timeoutMap: Record<string, number> = {
        'project.import': 300000,
        'analysis.runTask': 600000,
        'analysis.clearProjectCacheTable': 120000,
        'report.generateProjectSummary': 120000,
      }
      const timeout = timeoutMap[method] || 30000

      const timer = setTimeout(() => {
        this.pendingRequests.delete(requestId)
        reject(new Error(`Request timeout: ${method} (${timeout / 1000}s)`))
      }, timeout)

      this.pendingRequests.set(requestId, { resolve, reject, timer })

      this.dealer.send([requestId, method, JSON.stringify(params)])
    })
  }

  /** 处理响应 */
  handleResponse(frames: Buffer[]): void {
    if (frames.length < 3) return

    const requestId = frames[0].toString()
    const resultStr = frames[1].toString()
    const errorStr = frames[2].toString()

    const pending = this.pendingRequests.get(requestId)
    if (!pending) return

    this.pendingRequests.delete(requestId)
    clearTimeout(pending.timer)

    let result: any = null
    try { result = JSON.parse(resultStr) } catch { result = resultStr }

    let error: any = null
    try { error = JSON.parse(errorStr) } catch {
      if (errorStr && errorStr !== 'null') {
        error = { code: -32000, message: errorStr }
      }
    }

    if (error) pending.reject(new Error(error.message))
    else pending.resolve(result)
  }

  /** 健康检查 ping */
  async ping(timeout = 3000): Promise<boolean> {
    try {
      await Promise.race([
        this.call('backend.ping', {}),
        new Promise((_, reject) => setTimeout(() => reject(new Error('ping timeout')), timeout)),
      ])
      return true
    } catch {
      return false
    }
  }

  /** 关闭连接 */
  async close(): Promise<void> {
    this.shouldReconnect = false
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.dealer) this.dealer.close()
    if (this.sub) this.sub.close()
    this.connected = false

    for (const [_id, pending] of this.pendingRequests) {
      clearTimeout(pending.timer)
      pending.reject(new Error('Connection closed'))
    }
    this.pendingRequests.clear()
  }
}

export const zmqRouter = new ZMQRouter()
