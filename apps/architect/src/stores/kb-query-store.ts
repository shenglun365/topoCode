import { defineStore } from 'pinia'
import type { KbQueryHistory, KbQueryResult, KbQuerySpec } from '@/types'
import { kbQueryAgent } from '@/services/kb-query-agent'
import { currentBaselineInfo } from '@/services/baseline-service'
import { useArchArchitectureStore } from './architecture-store'

interface CacheEntry {
  key: string
  result: KbQueryResult
  baselineTag: string
  createdAt: number
}

/** 组件相关文件集合(由代码映射推导)，用于基线变更判失效。 */
function filesOfComp(compId: string): string[] {
  const arch = useArchArchitectureStore()
  const comp = arch.components.find((c) => c.id === compId)
  const files = new Set<string>()
  comp?.owns.forEach((id) => {
    const asset = arch.erTables.find((t) => t.id === id)
      ?? arch.ormMappings.find((m) => m.id === id)
      ?? arch.entityClasses.find((e) => e.id === id)
    if (asset?.ast) files.add(asset.ast.file)
  })
  arch.executionFlows.forEach((f) => {
    if (f.steps.some((s) => s.owner === comp?.name)) f.steps.forEach((s) => s.ast && files.add(s.ast.file))
  })
  return [...files]
}

export const useArchKbQueryStore = defineStore('arch-kb-query', {
  state: () => ({
    loaded: false,
    loading: false,
    cache: {} as Record<string, CacheEntry>,
    history: [] as KbQueryHistory[],
    lastResult: null as KbQueryResult | null,
  }),
  getters: {
    cacheCount(s): number {
      return Object.keys(s.cache).length
    },
    /** 当前基线标签(用于展示与失效判定)。 */
    baselineTag(): string {
      return currentBaselineInfo().gitTag
    },
  },
  actions: {
    /** 初始化：加载历史记录(原型阶段内置样例)。 */
    async load() {
      if (this.loaded) return
      this.loading = true
      await this._seed()
      this.loaded = true
      this.loading = false
    },
    /**
     * 复合查询：命中条件缓存(同基线、未受基线变更影响)则直接返回，
     * 否则调用知识库 agent 生成并写入缓存 + 历史。
     */
    async query(spec: KbQuerySpec): Promise<KbQueryResult> {
      const key = kbQueryAgent.cacheKey(spec)
      const baselineTag = this.baselineTag
      const entry = this.cache[key]

      if (entry && entry.baselineTag === baselineTag && !this._affectedByBaseline(entry)) {
        this.lastResult = { ...entry.result, cached: true }
        return this.lastResult
      }

      this.loading = true
      const result = await kbQueryAgent.query(spec)
      this.loading = false

      this.cache[key] = { key, result, baselineTag, createdAt: Date.now() }
      this.history.unshift({
        id: result.id,
        spec,
        baselineTag,
        cached: false,
        createdAt: Date.now(),
        summary: result.summary,
      })
      this.lastResult = result
      return result
    },

    /** 基线变更：使受影响组件对应的缓存失效。 */
    invalidateForBaseline(affectedCompIds: string[]) {
      const affected = new Set(affectedCompIds)
      let cleared = 0
      for (const key of Object.keys(this.cache)) {
        const entry = this.cache[key]
        const specComps = entry.result.spec.compIds
        const hit = specComps.some((id) => {
          const files = filesOfComp(id)
          return affected.has(id) || files.some((f) => affected.has(f))
        })
        if (hit) {
          delete this.cache[key]
          cleared++
        }
      }
      return cleared
    },

    async _seed() {
      // 内置两条历史样例，便于信息流展示。
      const arch = useArchArchitectureStore()
      if (!arch.model) return
      const order = arch.components.find((c) => c.id === 'c-order')
      if (!order) return
      const seedSpecs: KbQuerySpec[] = [
        { kind: 'depends', compIds: ['c-order'], sections: ['basic', 'structure', 'flow'], note: '下单链路依赖梳理' },
        { kind: 'calls', compIds: ['c-gateway'], sections: ['basic', 'flow'] },
      ]
      for (const spec of seedSpecs) {
        const result = await kbQueryAgent.query(spec)
        const key = kbQueryAgent.cacheKey(spec)
        this.cache[key] = { key, result, baselineTag: this.baselineTag, createdAt: Date.now() }
        this.history.unshift({
          id: result.id,
          spec,
          baselineTag: this.baselineTag,
          cached: false,
          createdAt: Date.now(),
          summary: result.summary,
        })
      }
    },

    _affectedByBaseline(entry: CacheEntry): boolean {
      const arch = useArchArchitectureStore()
      return entry.result.spec.compIds.some((id) => {
        const comp = arch.components.find((c) => c.id === id)
        if (!comp) return false
        if (comp.change !== 'same') return true
        return filesOfComp(id).some((f) => compFileChanged(comp.name, f))
      })
    },
  },
})

/** 由代码变更集合推断某文件是否变更(原型: 以暂存变更文件集合为准)。 */
function compFileChanged(compName: string, _file: string): boolean {
  const arch = useArchArchitectureStore()
  const comp = arch.components.find((c) => c.name === compName)
  return comp?.change === 'modified' || comp?.change === 'added'
}
