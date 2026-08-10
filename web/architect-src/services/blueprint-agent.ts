import type { ArchitectureModel, Blueprint } from '@/types'
import type { KbAnalysisTurn } from './kb-analysis-agent'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { useArchMcpStore } from '@/stores/mcp-store'

/**
 * Blueprint Agent —— 从零产品架构蓝图的双向细化协议。
 *
 * 与 kb-analysis-agent 同构（复用 KbAnalysisTurn 对话结构），
 * 但右栏产出不是 FormDraft，而是 ArchitectureModel（Blueprint）。
 *
 * 全部由后端处理；失败向上抛出——不复用本地 mock。
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

export const blueprintAgent = {
  async init(req: BlueprintInitRequest): Promise<BlueprintInitResult> {
    if (!(await backendUp())) throw new Error('后端不可达，无法初始化蓝图')
    try {
      const res = await apiPost<{ turns: KbAnalysisTurn[]; blueprint: { id: string } }>('/blueprint/init', req)
      if (!res.turns?.length || !res.blueprint?.id) throw new Error('后端未返回蓝图初始化结果')
      const blueprint: Blueprint = {
        id: res.blueprint.id,
        title: `${req.productForm === 'ui-ue' ? '界面' : '服务'}架构蓝图`,
        description: `依据 ${req.reqIds.length} 条需求初始草拟`,
        model: emptyModel(),
        source: 'agent-draft',
        status: 'draft',
        createdAt: Date.now(),
      }
      this.record('topocode.blueprint.init', `蓝图初始化：${req.productForm} · ${req.reqIds.length} 条需求`)
      return { turns: res.turns, blueprint }
    } catch (err) {
      throw err
    }
  },

  async refine(req: BlueprintRefineRequest): Promise<BlueprintRefineResult> {
    if (!(await backendUp())) throw new Error('后端不可达，无法细化蓝图')
    try {
      const res = await apiPost<{ blueprint: { id: string }; questions?: KbAnalysisTurn[] }>('/blueprint/refine', req)
      if (!res.blueprint?.id) throw new Error('后端未返回蓝图细化结果')
      const blueprint: Blueprint = {
        id: req.blueprintId,
        title: '架构蓝图',
        description: `已${req.action}节点 ${req.nodeId}`,
        model: emptyModel(),
        source: 'agent+user',
        status: 'draft',
        createdAt: Date.now(),
      }
      this.record('topocode.blueprint.refine', `细化：${req.action} · 节点 ${req.nodeId}`)
      return { blueprint, questions: res.questions as KbAnalysisTurn[] | undefined }
    } catch (err) {
      throw err
    }
  },

  async freeze(blueprintId: string): Promise<BlueprintFreezeResult> {
    if (!(await backendUp())) throw new Error('后端不可达，无法出 demo')
    try {
      const res = await apiPost<{ blueprint: { id: string }; taskTreeHint: BlueprintFreezeResult['taskTreeHint'] }>('/blueprint/demo-freeze', { blueprintId })
      if (!res.blueprint?.id || !res.taskTreeHint) throw new Error('后端未返回 demo 结果')
      this.record('topocode.blueprint.freeze', `出 demo：蓝图 ${blueprintId}`)
      return {
        blueprint: { id: blueprintId, title: '', description: '', model: emptyModel(), source: 'agent+user', status: 'draft', createdAt: Date.now() },
        taskTreeHint: res.taskTreeHint,
      }
    } catch (err) {
      throw err
    }
  },

  async confirm(blueprintId: string): Promise<{ status: string }> {
    if (!(await backendUp())) throw new Error('后端不可达，无法确认蓝图')
    try {
      const res = await apiPost<{ status: string }>('/blueprint/confirm', { blueprintId })
      if (!res.status) throw new Error('后端未返回确认结果')
      this.record('topocode.blueprint.confirm', `蓝图确认：${blueprintId}`)
      return { status: res.status }
    } catch (err) {
      throw err
    }
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

function emptyModel(): ArchitectureModel {
  return { components: [], erTables: [], ormMappings: [], entityClasses: [], executionFlows: [], dataFlows: [] }
}