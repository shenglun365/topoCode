import type { ScaffoldFile, ScaffoldResult } from '@/types'
import { apiPost } from './api-client'
import { backendUp } from './backend'
import { mockResult } from './mock/delay'

/**
 * 脚手架生成服务 —— 从零项目的骨架生成与确认。
 *
 * 当前全部 mock；真实接入时 agent 驱动或模板引擎生成。
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

const FILE_TEMPLATES: Record<string, (stack: { language: string; framework?: string }) => ScaffoldFile[]> = {
  Go: (_) => [
    { path: 'go.mod', action: 'create', summary: 'Go module init' },
    { path: 'cmd/main.go', action: 'create', summary: '入口与 server bootstrap' },
    { path: 'internal/config/config.go', action: 'create', summary: '配置加载骨架' },
    { path: 'internal/middleware/idempotency.go', action: 'create', summary: '幂等中间件空壳' },
    { path: 'Makefile', action: 'create', summary: '构建/测试/运行命令' },
    { path: '.gitignore', action: 'create', summary: 'Go 标准忽略规则' },
    { path: 'Dockerfile', action: 'create', summary: '多阶段构建' },
    { path: 'README.md', action: 'create', summary: '项目说明' },
  ],
  TypeScript: (sk) => [
    { path: 'package.json', action: 'create', summary: `Package init (${sk.framework ?? 'node'})` },
    { path: 'tsconfig.json', action: 'create', summary: 'TypeScript 配置' },
    { path: 'src/index.ts', action: 'create', summary: '入口文件' },
    { path: 'vite.config.ts', action: 'create', summary: sk.framework === 'Vue' || sk.framework === 'React' ? 'Vite 构建配置' : '构建配置' },
    { path: '.gitignore', action: 'create', summary: 'TS 标准忽略规则' },
    { path: 'Dockerfile', action: 'create', summary: '多阶段构建' },
    { path: 'README.md', action: 'create', summary: '项目说明' },
  ],
}

const DEFAULT_FILES: ScaffoldFile[] = [
  { path: '.gitignore', action: 'create', summary: '标准忽略规则' },
  { path: 'README.md', action: 'create', summary: '项目说明' },
  { path: 'Makefile', action: 'create', summary: '构建/测试/运行命令' },
]

let scaffoldTokenSeq = 0

export const scaffoldService = {
  async generate(req: ScaffoldGenerateRequest): Promise<ScaffoldResult> {
    if (await backendUp()) {
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
        if (res.token) {
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
        }
      } catch {
        // fall through to mock
      }
    }
    await mockResult(null, 600)
    scaffoldTokenSeq += 1
    const template = FILE_TEMPLATES[req.stack.language]
    const files = template
      ? template(req.stack).filter((f) => {
          if (f.path === 'Dockerfile' && !req.layers.includes(6)) return false
          if (f.path === 'Makefile' && !req.layers.includes(6)) return false
          if ((f.path.startsWith('internal/') || f.path.startsWith('src/')) && !req.layers.includes(2)) return false
          return true
        })
      : DEFAULT_FILES
    return {
      token: `scaffold-${Date.now().toString(36)}-${scaffoldTokenSeq}`,
      files,
      validation: { build: true, vet: true, test: true },
    }
  },

  async confirm(_token: string, _execRoot: string, _commitMessage?: string): Promise<{ commit: string; filesWritten: number; buildPass: boolean }> {
    if (await backendUp()) {
      try {
        const res = await apiPost<{ commit: string; filesWritten: number; buildPass: boolean }>('/scaffold/confirm', {
          token: _token, execRoot: _execRoot, commitMessage: _commitMessage,
        })
        if (res.commit) return res
      } catch {
        // fall through to mock
      }
    }
    await mockResult(null, 400)
    return { commit: `scaffold-${Date.now().toString(16).slice(0, 12)}`, filesWritten: 12, buildPass: true }
  },
}