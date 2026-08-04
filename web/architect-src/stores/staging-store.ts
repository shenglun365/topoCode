import { defineStore } from 'pinia'
import type { ComplianceCheck, GateKey, IncrementalLogEntry, Rebaseline, StagingModel } from '@/types'
import { BASELINE_COMMIT, COMPLIANCE_CHECKS, INCREMENTAL_LOG, STAGING_MODEL } from '@/services/mock/order-system'
import { delay } from '@/services/mock/delay'
import { useArchWorkflowStore } from './workflow-store'

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
      commit: BASELINE_COMMIT,
      manifestHash: 'sha256:9f7…c21',
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
      await delay(150)
      this.model = STAGING_MODEL
      this.log = [...INCREMENTAL_LOG]
      this.compliance = [...COMPLIANCE_CHECKS]
      this.loading = false
    },
    get loaded(): boolean {
      return !!this.model
    },
    async runIncrementalScan() {
      this.loading = true
      await delay(700)
      this.model = { ...STAGING_MODEL }
      this.log = [
        {
          id: `inc-${Date.now()}`,
          time: Date.now(),
          scope: '递归执行 batch (增量扫描)',
          grade: 'M',
          files: STAGING_MODEL.scope.filesChanged,
          edgesChanged: STAGING_MODEL.layers.file.edgesChanged,
          reExplained: ['comm-order', 'comm-mq'],
          boundaryChanged: [],
        },
        ...INCREMENTAL_LOG,
      ]
      this.compliance = [...COMPLIANCE_CHECKS]
      this.scanned = true
      this.loading = false
    },
    setGate(key: GateKey, value: boolean) {
      this.gates[key] = value
    },
    async verifyBaseline() {
      await delay(500)
      this.rebaseline.status = 'verified'
      this.rebaseline.handshake.verifyOk = true
      this.rebaseline.handshake.verify = 'ok · manifest_hash 与 scope 一致'
      this.rebaseline.baselineId = 'baseline_id = N (基线 v0.0.1)'
    },
    async commitRebaseline() {
      await delay(600)
      this.rebaseline.status = 'committed'
      this.rebaseline.handshake.commitResult = '原子写入成功'
      this.rebaseline.handshake.committedId = 'N+1 (v1.0.0)'
      this.rebaseline.baselineId = 'baseline_id = N+1 (新基线 v1.0.0)'
      const workflow = useArchWorkflowStore()
      workflow.finishAcceptance()
    },
  },
})
