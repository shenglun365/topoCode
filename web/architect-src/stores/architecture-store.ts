import { defineStore } from 'pinia'
import type { ArchComponent, ArchitectureModel, DataFlow, EntityClass, ErTable, ExecutionFlow, OrmMapping } from '@/types'
import { architectureService } from '@/services/architecture-service'

export const useArchArchitectureStore = defineStore('arch-architecture', {
  state: () => ({
    model: null as ArchitectureModel | null,
    loading: false,
    loadedAt: 0 as number,
    modelVersion: 'v1' as string,
  }),
  getters: {
    components(): ArchComponent[] {
      return this.model?.components ?? []
    },
    erTables(): ErTable[] {
      return this.model?.erTables ?? []
    },
    ormMappings(): OrmMapping[] {
      return this.model?.ormMappings ?? []
    },
    entityClasses(): EntityClass[] {
      return this.model?.entityClasses ?? []
    },
    executionFlows(): ExecutionFlow[] {
      return this.model?.executionFlows ?? []
    },
    dataFlows(): DataFlow[] {
      return this.model?.dataFlows ?? []
    },
    rootComponents(): ArchComponent[] {
      return this.components.filter((c) => !c.parentId)
    },
  },
  actions: {
    async loadFromSnapshot() {
      this.loading = true
      this.model = await architectureService.loadModel('v1')
      this.loadedAt = Date.now()
      this.loading = false
    },
    setModel(model: ArchitectureModel) {
      this.model = model
      this.loadedAt = Date.now()
    },
  },
})
