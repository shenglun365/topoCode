import { defineStore } from 'pinia'
import type { ExternalCall } from '@/types'
import { EXTERNAL_CALLS } from '@/services/mock/order-system'
import { apiGet, apiPost } from '@/services/api-client'
import { backendReady, backendUp } from '@/services/backend'
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
      if (await backendUp()) {
        try {
          this.calls = (await apiGet<ExternalCall[]>('/mcp/calls')) ?? []
          this.loaded = true
          this.loading = false
          return
        } catch {
          // fall through to mock
        }
      }
      const existing = this.calls
      this.calls = await mockResult([...EXTERNAL_CALLS, ...existing], 200)
      this.loaded = true
      this.loading = false
    },
    record(call: ExternalCall) {
      this.calls.unshift(call)
      if (backendReady()) {
        apiPost<unknown>('/mcp/calls', {
          tool: call.tool,
          method: call.method,
          status: call.status,
          input: { source: call.source, detail: call.detail },
        }).catch(() => {})
      }
    },
  },
})
