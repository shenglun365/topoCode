import { defineStore } from 'pinia'
import type { ArchitectureSpec } from '@/types'
import { apiGet, apiPost } from '@/services/api-client'
import { backendUp } from '@/services/backend'
import { currentProjectParams } from '@/services/project-service'
import { useArchProjectStore } from '@/stores/project-store'

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
    /** KB 未关联等场景的降级态(cv-205): 后端 400 显式语义保留(禁静默兜底),
     * 前端记录降级而非向全局抛未处理拒绝——侧栏每页挂载都会触发 load。 */
    degraded: false,
    degradedReason: '',
  }),
  getters: {
    ruleCount: (s): number => {
      if (!s.spec) return 0
      return s.spec.explicitRules.length + s.spec.derivedRules.length
    },
  },
  actions: {
    async load() {
      if (this.loaded || this.loading || this.degraded) return
      // cv-205: KB 项目缺失(工作目录直开)直接降级——不发起注定 400 的
      // 请求(与后端 kb_degraded 同口径: baselineId 缺失即未关联)
      const ps = useArchProjectStore()
      if (ps.loaded && !ps.hasBaseline) {
        this.degraded = true
        this.degradedReason = '项目未关联知识库——规约/基线功能不可用（项目概览「查找关联」后刷新重试）'
        return
      }
      this.loading = true
      if (!(await backendUp())) {
        this.loading = false
        this.degraded = true
        this.degradedReason = '后端不可达，无法加载架构规约'
        return
      }
      try {
        const ext = ctx()
        this.spec = await apiGet<ArchitectureSpec>(`/spec${ext ? '?' + ext : ''}`)
        this.loaded = true
        this.degraded = false
      } catch (err) {
        this.degraded = true
        this.degradedReason = err instanceof Error ? err.message : String(err)
      } finally {
        this.loading = false
      }
    },
    async confirm() {
      if (await backendUp()) {
        const { root, project } = currentProjectParams()
        apiPost<unknown>('/spec/confirm', { root, project }).catch(() => {})
      }
    },
  },
})
