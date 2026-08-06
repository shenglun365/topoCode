/** Shared WebSocket client for architect streaming endpoints.
 *
 * 走 Vite `/api` 代理(ws:true)到后端；独立服务时经 VITE_ARCH_API_BASE 指向 3470。
 * 消息形如 { type, ...payload }。
 * 提供按 type 订阅 + 一次性等待 + 发送；无请求/响应耦合，适合流式协议。
 */

function buildWsBase(): string {
  const configured = import.meta.env.VITE_ARCH_API_BASE as string | undefined
  if (configured) {
    // http(s)://host[:port]/api/architect → ws(s)://host[:port]/api/architect
    return configured.replace(/^http/, 'ws').replace(/\/+$/, '')
  }
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/api/architect`
}

const WS_BASE = buildWsBase()

type Handler = (msg: any) => void

export class ArchWs {
  private ws: WebSocket
  private readyPromise: Promise<void>
  private anyHandlers = new Set<Handler>()
  private onType = new Map<string, Set<Handler>>()

  constructor(path: string) {
    this.ws = new WebSocket(`${WS_BASE}/${path}`)
    this.readyPromise = new Promise((resolve, reject) => {
      this.ws.onopen = () => resolve()
      this.ws.onerror = () => reject(new Error(`WebSocket connect failed: ${path}`))
    })
    this.ws.onmessage = (e) => {
      let msg: any
      try {
        msg = JSON.parse(e.data)
      } catch {
        return
      }
      this.anyHandlers.forEach((h) => h(msg))
      this.onType.get(msg?.type)?.forEach((h) => h(msg))
    }
  }

  async ready(): Promise<void> {
    await this.readyPromise
  }

  send(type: string, payload: Record<string, unknown> = {}): void {
    this.ws.send(JSON.stringify({ type, ...payload }))
  }

  on(type: string, handler: Handler): () => void {
    const set = this.onType.get(type) ?? new Set<Handler>()
    set.add(handler)
    this.onType.set(type, set)
    return () => set.delete(handler)
  }

  onAny(handler: Handler): () => void {
    this.anyHandlers.add(handler)
    return () => this.anyHandlers.delete(handler)
  }

  /** 等到第一个 type 事件解析。不自动关闭。 */
  once<T = any>(type: string, timeoutMs = 15000): Promise<T> {
    return new Promise((resolve, reject) => {
      const off = this.on(type, (msg) => {
        off()
        resolve(msg as T)
      })
      setTimeout(() => {
        off()
        reject(new Error(`WS timeout waiting for '${type}'`))
      }, timeoutMs)
    })
  }

  close(): void {
    this.ws.close()
  }
}