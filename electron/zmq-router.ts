/** ZeroMQ Router - 消息路由中枢 (真实后端连接) */

import { EventEmitter } from 'events'

// 动态导入 zeromq (仅在 Electron 环境中)
let ZMQ: any = null
try {
  // @ts-ignore - zeromq 仅在 Electron 环境中可用
  ZMQ = require('zeromq')
} catch (e: any) {
  console.error('[ZMQRouter] zeromq load failed:', e.message)
  process.exit(1)
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

  constructor() {
    super()
    console.log('[ZMQRouter] initialized with zeromq')
  }

  /** 连接到后端 */
  async connect(): Promise<void> {
    try {
      // DEALER socket - 连接 Python DEALER (RPC 请求/响应)
      this.dealer = new ZMQ.Dealer()
      await this.dealer.connect('tcp://127.0.0.1:5671')
      console.log('[ZMQRouter] DEALER connected to tcp://127.0.0.1:5671')

      // SUB socket - 订阅 Python PUB (事件推送)
      this.sub = new ZMQ.Subscriber()
      await this.sub.connect('tcp://127.0.0.1:5680')
      this.sub.subscribe('task')
      this.sub.subscribe('project')
      this.sub.subscribe('backend')
      this.sub.subscribe('llm')
      console.log('[ZMQRouter] SUB connected to tcp://127.0.0.1:5680')

      this.connected = true
      this.startListening()
      console.log('[ZMQRouter] connected successfully')
    } catch (error) {
      console.error('[ZMQRouter] Connection failed:', error)
      throw error
    }
  }

  /** 开始监听 */
  private startListening(): void {
    if (!this.sub) return

    // 监听事件推送
    ;(async () => {
      for await (const [topic, eventType, data] of this.sub) {
        const event: ZMQEvent = {
          topic: topic.toString(),
          eventType: eventType.toString(),
          data: JSON.parse(data.toString()),
        }
        this.emit(`event:${event.topic}.${event.eventType}`, event.data)
        this.emit('event', event)
      }
    })().catch(console.error)

    // 监听 DEALER 响应
    ;(async () => {
      for await (const frames of this.dealer) {
        this.handleResponse(frames)
      }
    })().catch(console.error)
  }

  /** 发送 RPC 请求 */
  async call<T = any>(method: string, params: Record<string, any> = {}): Promise<T> {
    console.log(`[ZMQ] call -> ${method}`, params)
    const requestId = `req-${++this.requestCounter}`

    return new Promise<T>((resolve, reject) => {
      // 按方法类型设置不同超时
      const timeoutMap: Record<string, number> = {
        'project.import': 300000,    // 300s — 大项目导入（数千文件扫描 + 批量写入）
        'analysis.runTask': 600000,  // 600s — 分析任务（AST 解析 + 符号 + 调用图 + 依赖图 + 社区）
      }
      const timeout = timeoutMap[method] || 30000  // 默认 30s

      const timer = setTimeout(() => {
        this.pendingRequests.delete(requestId)
        reject(new Error(`Request timeout: ${method} (${timeout / 1000}s)`))
      }, timeout)

      this.pendingRequests.set(requestId, { resolve, reject, timer })

      // 发送请求: [REQUEST_ID, METHOD, PARAMS_JSON]
      this.dealer.send([
        requestId,
        method,
        JSON.stringify(params),
      ])
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

    let result = null
    try {
      result = JSON.parse(resultStr)
    } catch {
      result = resultStr
    }

    let error = null
    try {
      error = JSON.parse(errorStr)
    } catch {
      if (errorStr && errorStr !== 'null') {
        error = { code: -32000, message: errorStr }
      }
    }

    if (error) {
      pending.reject(new Error(error.message))
    } else {
      pending.resolve(result)
    }
  }

  /** 关闭连接 */
  async close(): Promise<void> {
    if (this.dealer) {
      this.dealer.close()
    }
    if (this.sub) {
      this.sub.close()
    }
    this.connected = false

    for (const [id, pending] of this.pendingRequests) {
      clearTimeout(pending.timer)
      pending.reject(new Error('Connection closed'))
    }
    this.pendingRequests.clear()
  }
}

// 单例
export const zmqRouter = new ZMQRouter()
