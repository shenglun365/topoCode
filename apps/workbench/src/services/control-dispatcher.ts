export interface ControlPollConfig {
  interval: number
  fetcher: () => Promise<any>
  onData?: (data: any) => void
  onError?: (err: any) => void
}

class ControlDispatcher {
  private entries = new Map<string, ControlPollConfig>()
  private timers = new Map<string, ReturnType<typeof setTimeout>>()
  private port1: MessagePort
  private port2: MessagePort

  constructor() {
    const { port1, port2 } = new MessageChannel()
    this.port1 = port1
    this.port2 = port2
    this.port1.onmessage = (ev: MessageEvent) => {
      const key = ev.data as string
      const config = this.entries.get(key)
      if (!config) return
      this.execute(key, config)
    }
  }

  register(key: string, config: ControlPollConfig) {
    if (this.entries.has(key)) {
      console.warn(`[ControlDispatcher] key "${key}" already registered, skipping`)
      return
    }
    this.entries.set(key, config)
    this.scheduleNext(key, config.interval)
  }

  unregister(key: string) {
    this.entries.delete(key)
    this.clearTimer(key)
  }

  has(key: string): boolean {
    return this.entries.has(key)
  }

  getActiveKeys(): string[] {
    return Array.from(this.entries.keys())
  }

  private execute(key: string, config: ControlPollConfig) {
    Promise.resolve().then(() => config.fetcher())
      .then((data) => {
        config.onData?.(data)
      })
      .catch((err) => {
        config.onError?.(err)
      })

    // 同步注册下一轮心跳——不受上方微任务影响
    if (this.entries.has(key)) {
      this.scheduleNext(key, config.interval)
    }
  }

  private scheduleNext(key: string, interval: number) {
    this.clearTimer(key)
    const timer = setTimeout(() => {
      this.port2.postMessage(key)
    }, interval)
    this.timers.set(key, timer)
  }

  private clearTimer(key: string) {
    const t = this.timers.get(key)
    if (t) {
      clearTimeout(t)
      this.timers.delete(key)
    }
  }
}

export const controlDispatcher = new ControlDispatcher()
