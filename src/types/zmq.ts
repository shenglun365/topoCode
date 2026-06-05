/** ZMQ 协议类型 — 消息队列通讯帧格式 */

export interface ZMQRequest {
  identity: string
  requestId: string
  method: string
  params: Record<string, any>
}

export interface ZMQResponse<T = any> {
  requestId: string
  result: T | null
  error: ZMQError | null
}

export interface ZMQError {
  code: number
  message: string
  data?: any
}

export interface ZMQEvent {
  topic: string
  eventType: string
  data: Record<string, any>
  timestamp: number
}
