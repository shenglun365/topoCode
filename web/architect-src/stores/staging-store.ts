import { defineStore } from 'pinia'
import type { ComplianceCheck, GateKey, IncrementalLogEntry, Rebaseline, StagingModel } from '@/types'
import { apiGet, apiPost } from '@/services/api-client'
import { backendReady, backendUp } from '@/services/backend'
import { currentProjectParams } from '@/services/project-service'
import { useArchWorkflowStore } from './workflow-store'

/** 项目上下文(root/project)透传(GET 走 query，POST 走 body)。 */
function ctxQuery(): string {
  const { root, project } = currentProjectParams()
  const qs = new URLSearchParams()
  if (root) qs.set('root', root)
  if (project) qs.set('project', project)
  return qs.toString()
}

function ctxBody(): Record<string, string | undefined> {
  return currentProjectParams()
}

export const useArchStagingStore = defineStore('arch-staging', {
  state: () => ({
    loading: false,
    scanned: false,
    model: null as StagingModel | null,
    log: [] as IncrementalLogEntry[],
    compliance: [] as ComplianceCheck[],
    gates: { codeMerge: false, specChange: false, baselineCreate: false } as Record<GateKey, boolean>,
    rebaseline: {
      status: 'idle',
      baselineId: '',
      commit: '',
      manifestHash: '',
      handshake: { verify: '', verifyOk: false, commitResult: '', committedId: '' },
    } as Rebaseline,
  }),
  getters: {
    gatesAll(state): boolean {
      return state.gates.codeMerge && state.gates.specChange && state.gates.baselineCreate
    },
    gatesDone(state): number {
      return [state.gates.codeMerge, state.gates.specChange, state.gates.baselineCreate].filter(Boolean).length
    },
    compliancePassed(state): number {
      return state.compliance.filter((c) => c.pass).length
    },
  },
  actions: {
    async load() {
      if (this.loaded || this.loading) return
      this.loading = true
      if (!(await backendUp())) throw new Error('后端不可达，无法加载基线/合规数据')
      try {
        const ext = ctxQuery()
        const api = (p: string) => apiGet<unknown>(`${p}${ext ? '?' + ext : ''}`)
        const [model, log, compliance] = await Promise.all([
          api('/arch/staging') as Promise<StagingModel>,
          api('/arch/staging/log') as Promise<IncrementalLogEntry[]>,
          api('/arch/staging/compliance') as Promise<ComplianceCheck[]>,
        ])
        this.model = model
        this.log = log ?? []
        this.compliance = compliance ?? []
        this.loading = false
      } catch (err) {
        this.loading = false
        throw err
      }
    },
    get loaded(): boolean {
      return !!this.model
    },
    async runIncrementalScan() {
      this.loading = true
      if (!(await backendUp())) throw new Error('后端不可达，无法执行增量扫描')
      try {
        const res = await apiPost<{ log: IncrementalLogEntry; compliance?: ComplianceCheck[] }>('/arch/staging/scan', ctxBody())
        if (this.model) this.model = { ...this.model }
        this.log = [res.log, ...(this.log ?? [])]
        this.compliance = res.compliance ?? this.compliance
        this.scanned = true
        this.loading = false
      } catch (err) {
        this.loading = false
        throw err
      }
    },
    setGate(key: GateKey, value: boolean) {
      this.gates[key] = value
      if (backendReady()) apiPost<unknown>('/arch/staging/gates', { key, value }).catch(() => {})
    },
    async verifyBaseline() {
      if (!(await backendUp())) throw new Error('后端不可达，无法校验基线')
      try {
        const res = await apiPost<{ verify: string; verifyOk: boolean }>('/arch/baseline/verify', ctxBody())
        this.rebaseline.status = 'verified'
        this.rebaseline.handshake.verifyOk = res.verifyOk
        this.rebaseline.handshake.verify = res.verify
        this.rebaseline.baselineId = 'baseline_id = N (基线 v0.0.1)'
      } catch (err) {
        throw err
      }
    },
    async commitRebaseline() {
      if (!(await backendUp())) throw new Error('后端不可达，无法提交新基线')
      try {
        const res = await apiPost<{ commitResult: string; committedId: string }>('/arch/baseline/commit', ctxBody())
        this.rebaseline.status = 'committed'
        this.rebaseline.handshake.commitResult = res.commitResult
        this.rebaseline.handshake.committedId = res.committedId
        this.rebaseline.baselineId = 'baseline_id = N+1 (新基线 v1.0.0)'
        const workflow = useArchWorkflowStore()
        workflow.finishAcceptance()
      } catch (err) {
        throw err
      }
    },
  },
})
