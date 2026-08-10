import { defineStore } from 'pinia'
import type { ExternalCall } from '@/types'
import { apiGet, apiPost } from '@/services/api-client'
import { backendReady, backendUp } from '@/services/backend'

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
      if (!(await backendUp())) throw new Error('后端不可达，无法加载 MCP 调用')
      try {
        this.calls = (await apiGet<ExternalCall[]>('/mcp/calls')) ?? []
        this.loaded = true
        this.loading = false
      } catch (err) {
        this.loading = false
        throw err
      }
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
