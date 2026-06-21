import { pollingRegistry } from './polling-registry'

export interface DisplayPollConfig {
  interval: number
  fetcher: () => Promise<any>
  onData?: (data: any) => void
  onError?: (err: any) => void
}

class DisplayDispatcher {
  private entries = new Map<string, DisplayPollConfig>()
  private timers = new Map<string, ReturnType<typeof setInterval>>()

  register(key: string, config: DisplayPollConfig) {
    if (this.entries.has(key)) {
      console.warn(`[DisplayDispatcher] key "${key}" already registered, skipping`)
      return
    }
    this.entries.set(key, config)
    pollingRegistry.register({
      key,
      category: 'display',
      interval: config.interval,
      status: 'running',
    })
    this.execute(key)
    this.startTimer(key, config.interval)
  }

  unregister(key: string) {
    this.clearTimer(key)
    this.entries.delete(key)
    pollingRegistry.unregister(key)
  }

  has(key: string): boolean {
    return this.entries.has(key)
  }

  pause(key: string) {
    this.clearTimer(key)
    pollingRegistry.update(key, { status: 'paused' })
  }

  resume(key: string) {
    const config = this.entries.get(key)
    if (!config) return
    this.execute(key)
    this.startTimer(key, config.interval)
    pollingRegistry.update(key, { status: 'running' })
  }

  getActiveKeys(): string[] {
    return Array.from(this.entries.keys())
  }

  private execute(key: string) {
    const config = this.entries.get(key)
    if (!config) return
    pollingRegistry.update(key, { lastRunAt: Date.now() })
    config.fetcher()
      .then((data) => {
        config.onData?.(data)
        pollingRegistry.update(key, { lastData: data, error: undefined })
      })
      .catch((err) => {
        config.onError?.(err)
        pollingRegistry.update(key, { error: err?.message || String(err) })
      })
  }

  private startTimer(key: string, interval: number) {
    this.clearTimer(key)
    this.timers.set(key, setInterval(() => this.execute(key), interval))
  }

  private clearTimer(key: string) {
    const t = this.timers.get(key)
    if (t) {
      clearInterval(t)
      this.timers.delete(key)
    }
  }
}

export const displayDispatcher = new DisplayDispatcher()
