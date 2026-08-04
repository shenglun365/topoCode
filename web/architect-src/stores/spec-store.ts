import { defineStore } from 'pinia'
import type { ArchitectureSpec } from '@/types'
import { ARCHITECTURE_SPEC } from '@/services/mock/order-system'
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
      this.spec = await mockResult(ARCHITECTURE_SPEC, 200)
      this.loaded = true
      this.loading = false
    },
    confirm() {
      const workflow = useArchWorkflowStore()
      workflow.confirmSpec()
    },
  },
})
