import type { ArchitectureModel, Blueprint } from '@/types'
import type { KbAnalysisTurn } from './kb-analysis-agent'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { mockResult } from './mock/delay'
import { useArchMcpStore } from '@/stores/mcp-store'

/**
 * Blueprint Agent —— 从零产品架构蓝图的双向细化协议。
 *
 * 与 kb-analysis-agent 同构（复用 KbAnalysisTurn 对话结构），
 * 但右栏产出不是 FormDraft，而是 ArchitectureModel（Blueprint）。
 *
 * 原型阶段为 mock；真实接入时对接知识库 agent 服务。
 */

export interface BlueprintInitRequest {
  reqIds: string[]
  productForm: 'ui-ue' | 'io' | 'hybrid'
  stack?: { language: string; framework?: string }
}

export interface BlueprintInitResult {
  turns: KbAnalysisTurn[]
  blueprint: Blueprint
}

export interface BlueprintRefineRequest {
  blueprintId: string
  action: 'lock' | 'drill-down' | 'backtrack' | 'update-what' | 'update-how'
  nodeId: string
  what?: string
  how?: string
  parentId?: string
  childWhat?: string
}

export interface BlueprintRefineResult {
  blueprint: Blueprint
  questions?: KbAnalysisTurn[]
}

export interface BlueprintFreezeResult {
  blueprint: Blueprint
  taskTreeHint: { nodeCount: number; estMin: number; scaffoldTasks: string[] }
}

function emptyModel(): ArchitectureModel {
  return { components: [], erTables: [], ormMappings: [], entityClasses: [], executionFlows: [], dataFlows: [] }
}

function buildDraftModel(): ArchitectureModel {
  const arch = useArchArchitectureStore()
  if (arch.model) return { ...arch.model }
  return emptyModel()
}

let bpSeq = 0

export const blueprintAgent = {
  async init(req: BlueprintInitRequest): Promise<BlueprintInitResult> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{ turns: KbAnalysisTurn[]; blueprint: { id: string } }>('/blueprint/init', req)
        if (res.turns?.length && res.blueprint?.id) {
          const blueprint: Blueprint = {
            id: res.blueprint.id,
            title: `${req.productForm === 'ui-ue' ? '界面' : '服务'}架构蓝图`,
            description: `依据 ${req.reqIds.length} 条需求初始草拟`,
            model: buildDraftModel(),
            source: 'agent-draft',
            status: 'draft',
            createdAt: Date.now(),
          }
          this.record('topocode.blueprint.init', `蓝图初始化：${req.productForm} · ${req.reqIds.length} 条需求`)
          return { turns: res.turns, blueprint }
        }
      } catch {
        // fall through to mock
      }
    }
    await mockResult(null, 500)
    bpSeq += 1
    const turns: KbAnalysisTurn[] = [
      { role: 'user', content: `依据 ${req.reqIds.length} 条需求生成架构蓝图。` },
      { role: 'assistant', content: `正在生成架构蓝图草案……建议按「${req.productForm}」形态逐层细化。`, questions: [
        { key: 'boundaries', label: '整体功能边界？建议的模块/服务划分？', type: 'text', hint: '如订单管理、支付、库存…' },
        { key: 'entities', label: '核心业务实体？', type: 'text', hint: '如 Order、Payment、Product…' },
      ] },
    ]
    const blueprint: Blueprint = {
      id: `bp-${Date.now().toString(36)}-${bpSeq}`,
      title: `${req.productForm === 'ui-ue' ? '界面' : '服务'}架构蓝图`,
      description: `依据 ${req.reqIds.length} 条需求初始草拟`,
      model: buildDraftModel(),
      source: 'agent-draft',
      status: 'draft',
      createdAt: Date.now(),
    }
    this.record('topocode.blueprint.init', `蓝图初始化：${req.productForm} · ${req.reqIds.length} 条需求`)
    return { turns, blueprint }
  },

  async refine(req: BlueprintRefineRequest): Promise<BlueprintRefineResult> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{ blueprint: { id: string }; questions?: KbAnalysisTurn[] }>('/blueprint/refine', req)
        if (res.blueprint?.id) {
          const blueprint: Blueprint = {
            id: req.blueprintId,
            title: '架构蓝图',
            description: `已${req.action}节点 ${req.nodeId}`,
            model: buildDraftModel(),
            source: 'agent+user',
            status: 'draft',
            createdAt: Date.now(),
          }
          this.record('topocode.blueprint.refine', `细化：${req.action} · 节点 ${req.nodeId}`)
          return { blueprint, questions: res.questions as KbAnalysisTurn[] | undefined }
        }
      } catch {
        // fall through to mock
      }
    }
    await mockResult(null, 400)
    const model = buildDraftModel()
    const blueprint: Blueprint = {
      id: req.blueprintId,
      title: '架构蓝图',
      description: `已${req.action}节点 ${req.nodeId}`,
      model,
      source: 'agent+user',
      status: 'draft',
      createdAt: Date.now(),
    }
    this.record('topocode.blueprint.refine', `细化：${req.action} · 节点 ${req.nodeId}`)
    return { blueprint }
  },

  async freeze(blueprintId: string): Promise<BlueprintFreezeResult> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{ blueprint: { id: string }; taskTreeHint: BlueprintFreezeResult['taskTreeHint'] }>('/blueprint/demo-freeze', { blueprintId })
        if (res.blueprint?.id && res.taskTreeHint) {
          this.record('topocode.blueprint.freeze', `出 demo：蓝图 ${blueprintId}`)
          return {
            blueprint: { id: blueprintId, title: '', description: '', model: emptyModel(), source: 'agent+user', status: 'draft', createdAt: Date.now() },
            taskTreeHint: res.taskTreeHint,
          }
        }
      } catch {
        // fall through to mock
      }
    }
    await mockResult(null, 350)
    this.record('topocode.blueprint.freeze', `出 demo：蓝图 ${blueprintId}`)
    return {
      blueprint: { id: blueprintId, title: '', description: '', model: emptyModel(), source: 'agent+user', status: 'draft', createdAt: Date.now() },
      taskTreeHint: { nodeCount: 6, estMin: 240, scaffoldTasks: ['scaffold-core', 'scaffold-infra'] },
    }
  },

  async confirm(blueprintId: string): Promise<{ status: string }> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{ status: string }>('/blueprint/confirm', { blueprintId })
        if (res.status) {
          this.record('topocode.blueprint.confirm', `蓝图确认：${blueprintId}`)
          return { status: res.status }
        }
      } catch {
        // fall through to mock
      }
    }
    await mockResult(null, 300)
    this.record('topocode.blueprint.confirm', `蓝图确认：${blueprintId}`)
    return { status: 'confirmed' }
  },

  record(tool: string, detail: string) {
    const mcp = useArchMcpStore()
    mcp.record({
      id: `bp-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
      source: 'topocode-blueprint',
      tool,
      method: 'invoke',
      time: Date.now(),
      status: 'ok',
      detail,
    })
  },
}