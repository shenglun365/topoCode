import { reactive, readonly } from 'vue'

export interface PollEntryInfo {
  key: string
  category: 'control' | 'display'
  interval: number
  status: 'running' | 'paused' | 'stopped'
  lastRunAt?: number
  lastData?: any
  error?: string
}

class PollingRegistry {
  private _entries = reactive<Record<string, PollEntryInfo>>({})

  get entries() {
    return readonly(this._entries)
  }

  register(info: PollEntryInfo) {
    this._entries[info.key] = info
  }

  unregister(key: string) {
    delete this._entries[key]
  }

  update(key: string, partial: Partial<PollEntryInfo>) {
    const entry = this._entries[key]
    if (entry) Object.assign(entry, partial)
  }

  getEntry(key: string): PollEntryInfo | undefined {
    return this._entries[key]
  }

  getAll(): PollEntryInfo[] {
    return Object.values(this._entries)
  }
}

export const pollingRegistry = new PollingRegistry()
