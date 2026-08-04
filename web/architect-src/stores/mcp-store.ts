import { defineStore } from 'pinia'
import type { ExternalCall } from '@/types'
import { EXTERNAL_CALLS } from '@/services/mock/order-system'
import { mockResult } from '@/services/mock/delay'

export const useArchMcpStore = defineStore('arch-mcp', {
  state: () => ({
    calls: [] as ExternalCall[],
    loaded: false,
    loading: false,
  }),
  getters: {
    pendingCount(): number {
      return this.calls.filter((c) => c.status === 'pending').length
    },
  },
  actions: {
    async load() {
      if (this.loaded || this.loading) return
      this.loading = true
      const existing = this.calls
      this.calls = await mockResult([...EXTERNAL_CALLS, ...existing], 200)
      this.loaded = true
      this.loading = false
    },
    record(call: ExternalCall) {
      this.calls.unshift(call)
    },
  },
})
