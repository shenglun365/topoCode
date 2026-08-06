import type { ArchitectureModel, CodeMapping, ExtractConfig, ExtractResult } from '@/types'
import { buildModel } from './mock/order-system'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { mockResult } from './mock/delay'
import { useArchMcpStore } from '@/stores/mcp-store'

/**
 * 知识库抽取服务 —— 首轮执行完成后，从代码中提取架构模型与代码映射。
 *
 * 这是 greenfield → existing 的 handoff 关键步骤。
 * 当前 mock，真实接入时对接 codegraph / AST 索引。
 */

export const extractService = {
  async run(config: ExtractConfig): Promise<ExtractResult> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{
          snapshotId: string
          model?: ArchitectureModel
          mappings?: CodeMapping[]
          metrics?: { files?: number; symbols?: number; durationMs?: number }
        }>('/kb/extract', config)
        if (res.snapshotId) {
          const model = res.model ?? buildModel('v1')
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
        }
      } catch {
        // fall through to mock
      }
    }
    await mockResult(null, 700)
    const model = buildModel('v1')
    const mappings: CodeMapping[] = [
      { id: 'cm-order', targetType: 'component', targetId: 'c-order', targetName: '订单服务', file: 'app/order.go', line: 'L12', level: 'logical', note: '' },
      { id: 'cm-payment', targetType: 'component', targetId: 'c-payment', targetName: '支付服务', file: 'app/payment.go', line: 'L1', level: 'logical', note: '' },
      { id: 'cm-gateway', targetType: 'component', targetId: 'c-gateway', targetName: '网关', file: 'gateway/route.go', line: 'L5', level: 'logical', note: '' },
    ]
    this.record('topocode.kb.extract', `抽取完成：${config.commit} · ${model.components.length} 组件`)
    return {
      snapshotId: `snap-${Date.now().toString(36)}`,
      model,
      mappings,
      metrics: { components: model.components.length, entities: model.entityClasses.length, flows: model.executionFlows.length, mappings: mappings.length },
    }
  },

  async commitBaseline(extractToken: string): Promise<{ baselineId: string; commit: string; mode: 'existing' }> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{ baselineId: string; commit: string; mode: 'existing' }>('/kb/baseline', { extractToken })
        if (res.baselineId) {
          this.record('topocode.kb.baseline', `基线建立：${extractToken}`)
          return res
        }
      } catch {
        // fall through to mock
      }
    }
    await mockResult(null, 300)
    this.record('topocode.kb.baseline', `基线建立：${extractToken}`)
    return { baselineId: `snap-${Date.now().toString(36)}`, commit: `baseline-${Date.now().toString(16)}`, mode: 'existing' }
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