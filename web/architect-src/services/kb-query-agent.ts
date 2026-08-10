import type { KbQueryResult, KbQuerySpec } from '@/types'
import { useArchMcpStore } from '@/stores/mcp-store'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { currentProjectParams } from './project-service'

/**
 * 知识库复合查询 agent —— 系统基线工作区专用。
 *
 * 报表式查询：以「组件 → 依赖/被调用组件」为轴，按需展开基本信息 / 核心数据结构 / 核心流程，
 * 每次查询调用一组知识库 skill 提供专项能力；命中条件缓存由基线变更驱动失效。
 *
 * 全部由后端处理；后端不可达/调用失败时向上抛错——不复用本地 mock。
 */
export interface KbAgentOptions {
  /** 命中缓存时由调用方标记，走缓存旁路。 */
  cached?: boolean
}

export const kbQueryAgent = {
  /** 执行一次知识库复合查询。 */
  async query(spec: KbQuerySpec, opts: KbAgentOptions = {}): Promise<KbQueryResult> {
    if (!(await backendUp())) throw new Error('后端不可达，无法执行知识库复合查询')
    try {
      const { root, project } = currentProjectParams()
      const body = { ...spec, ...(root ? { root } : {}), ...(project ? { project } : {}) }
      const res = await apiPost<KbQueryResult>('/kb/query', body)
      if (!res.id || !res.compResults) throw new Error('后端未返回复合查询结果')
      this.record('topocode.kb.query', `复合查询: ${spec.kind === 'depends' ? '依赖' : '被调用'} · ${res.compResults.length} 组件 · skill ${res.skills.length}`)
      return { ...res, cached: opts.cached ?? res.cached ?? false }
    } catch (err) {
      throw err
    }
  },

  /** 判定缓存命中：基于输入条件生成稳定 key。 */
  cacheKey(spec: KbQuerySpec): string {
    return [
      spec.kind,
      [...spec.compIds].sort().join(','),
      [...spec.sections].sort().join(','),
      (spec.note ?? '').trim(),
    ].join('|')
  },

  record(tool: string, detail: string) {
    const mcp = useArchMcpStore()
    mcp.record({
      id: `kbq-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      source: 'topocode-kb',
      tool,
      method: 'invoke',
      time: Date.now(),
      status: 'ok',
      detail,
    })
  },
}
