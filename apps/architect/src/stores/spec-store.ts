import { defineStore } from 'pinia'
import type { ArchitectureSpec } from '@/types'
import { apiGet, apiPost } from '@/services/api-client'
import { backendUp } from '@/services/backend'
import { currentProjectParams } from '@/services/project-service'
import { useArchWorkflowStore } from './workflow-store'

/** 项目上下文(root/project)透传，随请求携带(与其余 KB 路由同一口径)。 */
function ctx(): string {
  const { root, project } = currentProjectParams()
  const qs = new URLSearchParams()
  if (root) qs.set('root', root)
  if (project) qs.set('project', project)
  return qs.toString()
}

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
      if (!(await backendUp())) throw new Error('后端不可达，无法加载架构规约')
      try {
        const ext = ctx()
        this.spec = await apiGet<ArchitectureSpec>(`/spec${ext ? '?' + ext : ''}`)
        this.loaded = true
        this.loading = false
      } catch (err) {
        this.loading = false
        throw err
      }
    },
    async confirm() {
      const workflow = useArchWorkflowStore()
      workflow.confirmSpec()
      if (await backendUp()) {
        const { root, project } = currentProjectParams()
        apiPost<unknown>('/spec/confirm', { root, project }).catch(() => {})
      }
    },
  },
})
