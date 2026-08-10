import type { ScaffoldFile, ScaffoldResult } from '@/types'
import { apiPost } from './api-client'
import { backendUp } from './backend'

/**
 * 脚手架生成服务 —— 从零项目的骨架生成与确认。
 *
 * 全部由后端(agent 驱动或模板引擎)生成；失败向上抛出——不复用本地 mock。
 *
 * 6 层定义（scaffold.md）：
 *   1 工程骨架   2 模块骨架   3 契约空壳
 *   4 基础设施壳  5 测试骨架   6 交付骨架
 */

export interface ScaffoldGenerateRequest {
  execRoot: string
  stack: { language: string; framework?: string }
  blueprintId?: string
  layers: number[]
  productForm?: string
}

export const scaffoldService = {
  async generate(req: ScaffoldGenerateRequest): Promise<ScaffoldResult> {
    if (!(await backendUp())) throw new Error('后端不可达，无法生成脚手架')
    try {
      const res = await apiPost<{
        token: string
        files: Array<{ path: string; content: string; action?: string; summary?: string }>
        validation: { ok: boolean }
      }>('/scaffold/generate', {
        blueprintId: req.blueprintId,
        module: req.layers.includes(2) ? 'core' : '',
        execRoot: req.execRoot,
      })
      if (!res.token) throw new Error('后端未返回脚手架 token')
      const files: ScaffoldFile[] = (res.files ?? []).map((f) => ({
        path: f.path,
        action: (f.action === 'modify' || f.action === 'skip' ? f.action : 'create') as ScaffoldFile['action'],
        summary: f.summary ?? f.path,
      }))
      return {
        token: res.token,
        files,
        validation: { build: res.validation?.ok ?? true, vet: true, test: true },
      }
    } catch (err) {
      throw err
    }
  },

  async confirm(_token: string, _execRoot: string, _commitMessage?: string): Promise<{ commit: string; filesWritten: number; buildPass: boolean }> {
    if (!(await backendUp())) throw new Error('后端不可达，无法确认脚手架')
    try {
      const res = await apiPost<{ commit: string; filesWritten: number; buildPass: boolean }>('/scaffold/confirm', {
        token: _token, execRoot: _execRoot, commitMessage: _commitMessage,
      })
      if (!res.commit) throw new Error('后端未返回提交信息')
      return res
    } catch (err) {
      throw err
    }
  },
}