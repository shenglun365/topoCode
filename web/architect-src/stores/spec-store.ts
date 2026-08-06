import { defineStore } from 'pinia'
import type { ArchitectureSpec } from '@/types'
import { ARCHITECTURE_SPEC } from '@/services/mock/order-system'
import { apiGet, apiPost } from '@/services/api-client'
import { backendUp } from '@/services/backend'
import { mockResult } from '@/services/mock/delay'
import { useArchWorkflowStore } from './workflow-store'

export const useArchSpecStore = defineStore('arch-spec', {
  state: () => ({
    spec: null as ArchitectureSpec | null,
    loading: false,
    loaded: false,
  }),
  getters: {
    ruleCount: (s): number => {
      if (!s.spec) return 0
      return s.spec.explicitRules.length + s.spec.derivedRules.length
    },
  },
  actions: {
    async load() {
      if (this.loaded) return
      this.loading = true
      if (await backendUp()) {
        try {
          this.spec = await apiGet<ArchitectureSpec>('/spec')
          this.loaded = true
          this.loading = false
          return
        } catch {
          // fall through to mock
        }
      }
      this.spec = await mockResult(ARCHITECTURE_SPEC, 200)
      this.loaded = true
      this.loading = false
    },
    async confirm() {
      const workflow = useArchWorkflowStore()
      workflow.confirmSpec()
      if (await backendUp()) apiPost<unknown>('/spec/confirm').catch(() => {})
    },
  },
})
