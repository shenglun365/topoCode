import type { ArchitectureModel, CodeMapping, ExtractConfig, ExtractResult } from '@/types'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { useArchMcpStore } from '@/stores/mcp-store'

/**
 * 知识库抽取服务 —— 首轮执行完成后，从代码中提取架构模型与代码映射。
 *
 * 这是 greenfield → existing 的 handoff 关键步骤。
 * 全部由后端对接 codegraph / AST 索引；失败向上抛出——不复用本地 mock。
 */

export const extractService = {
  async run(config: ExtractConfig): Promise<ExtractResult> {
    if (!(await backendUp())) throw new Error('后端不可达，无法执行知识库抽取')
    try {
      const res = await apiPost<{
        snapshotId: string
        model?: ArchitectureModel
        mappings?: CodeMapping[]
        metrics?: { files?: number; symbols?: number; durationMs?: number }
      }>('/kb/extract', config)
      if (!res.snapshotId) throw new Error('后端未返回抽取 snapshot')
      const model = res.model ?? { components: [], erTables: [], ormMappings: [], entityClasses: [], executionFlows: [], dataFlows: [] }
      const mappings = res.mappings ?? []
      this.record('topocode.kb.extract', `抽取完成：${config.commit} · ${model.components.length} 组件`)
      return {
        snapshotId: res.snapshotId,
        model,
        mappings,
        metrics: {
          components: model.components.length,
          entities: model.entityClasses.length,
          flows: model.executionFlows.length,
          mappings: mappings.length,
        },
      }
    } catch (err) {
      throw err
    }
  },

  async commitBaseline(extractToken: string): Promise<{ baselineId: string; commit: string; mode: 'existing' }> {
    if (!(await backendUp())) throw new Error('后端不可达，无法建立基线')
    try {
      const res = await apiPost<{ baselineId: string; commit: string; mode: 'existing' }>('/kb/baseline', { extractToken })
      if (!res.baselineId) throw new Error('后端未返回基线结果')
      this.record('topocode.kb.baseline', `基线建立：${extractToken}`)
      return res
    } catch (err) {
      throw err
    }
  },

  record(tool: string, detail: string) {
    const mcp = useArchMcpStore()
    mcp.record({
      id: `ext-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
      source: 'topocode-extract',
      tool,
      method: 'invoke',
      time: Date.now(),
      status: 'ok',
      detail,
    })
  },
}