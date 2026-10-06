import type { EvolutionFrames, GitCommitInfo, GitInfoLite, KbMatchResult, KbProject, ProjectInfo, ProjectOverview, RepoStatus, Snapshot } from '@/types'
import { apiGet, apiPost } from './api-client'
import router from '@/router'

/** 当前 URL 中的项目选择参数(持久化在 URL，多页签各处理不同项目)。 */
export function currentProjectParams(): { root?: string; project?: string } {
  const q = router.currentRoute.value.query
  const root = typeof q.root === 'string' ? q.root : undefined
  const project = typeof q.project === 'string' ? q.project : undefined
  return { root: root || undefined, project: project || undefined }
}

function resolveRootPath(): string {
  const { root } = currentProjectParams()
  if (root) return root
  return import.meta.env.VITE_BOUND_ROOT || ''
}

/** 当前项目工作目录(真实 root，来自 URL ?root= 或绑定兜底；空串表示未选定)。 */
export function currentProjectRoot(): string {
  return resolveRootPath()
}

function projectQuery(): URLSearchParams {
  const params = new URLSearchParams()
  const { project } = currentProjectParams()
  if (project) params.set('project', project)
  const rootPath = resolveRootPath()
  if (rootPath) params.set('root', rootPath)
  return params
}

export const projectService = {
  async getBound(): Promise<ProjectInfo | null> {
    const qs = projectQuery().toString()
    return apiGet<ProjectInfo | null>(`/project/bound${qs ? '?' + qs : ''}`)
  },
  async createGreenfield(opts: {
    name?: string; desc?: string; language?: string; framework?: string;
    moduleLayout?: string; productForm?: string; execRoot?: string; kbRoot?: string
  }): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/bound', opts)
  },
  /** 列出 KB 项目(KB 关联源候选)。 */
  async listKbProjects(): Promise<KbProject[]> {
    return apiGet<KbProject[]>('/project/kb/list')
  },
  /** 「增加关联」自动匹配：按工作主目录(本地 repo 为主)、远端地址为辅 返回 KB 候选。 */
  async matchKbProjects(): Promise<KbMatchResult> {
    const qs = projectQuery().toString()
    return apiGet<KbMatchResult>(`/project/kb/match${qs ? '?' + qs : ''}`)
  },
  /** 近期项目列表：architect 自持项目(arch_projects)按最近更新倒序。 */
  async listProjects(): Promise<ProjectInfo[]> {
    try {
      const list = await apiGet<ProjectInfo[] | null>('/project/list')
      return list ?? []
    } catch {
      return []
    }
  },
  /** 置顶 / 收藏切换。 */
  async flagProject(opts: { execRoot?: string; root?: string; project?: string; pinned?: boolean; favorite?: boolean }): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/flag', opts)
  },
  /** 项目改名(仅 architect 本地 arch_projects，不联动 KB)。 */
  async renameProject(opts: { name: string; execRoot?: string; root?: string; project?: string }): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/rename', opts)
  },
  /** 删除项目列表记录(可选同时删除 architect 相关数据——项目子库/主库关联行/项目级 KV)。 */
  async deleteProject(opts: { execRoot?: string; root?: string; project?: string; deleteData?: boolean }): Promise<{ deleted: boolean; deleteData: boolean; id: string; purged?: Record<string, number> }> {
    return apiPost('/project/delete', opts)
  },
  /** 打开工作目录并(可选)关联 KB：校验通过后登记 arch_projects(选择持久化在 URL ?root=)。 */
  async bindKbProject(kbProjectId: string, execRoot: string, name?: string): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/bind', { kbProjectId, execRoot, name })
  },
  /** 仅打开工作目录(不关联 KB)。 */
  async bindWorkingDir(execRoot: string, name?: string): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/bind', { execRoot, name })
  },
  /** 项目页后补关联 KB(同源校验由后端执行)。 */
  async linkKb(opts: { kbProjectId: string; execRoot?: string; project?: string }): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/link', {
      kbProjectId: opts.kbProjectId,
      execRoot: opts.execRoot,
      project: opts.project,
    })
  },
  /** 解除 KB 关联(architect 项目保留)。 */
  async unlinkKb(opts: { root?: string; project?: string }): Promise<ProjectInfo> {
    return apiPost<ProjectInfo>('/project/unlink', opts)
  },
  /** 解除选择(URL 参数清除由 store 处理)。 */
  async unbind(): Promise<boolean> {
    return apiPost<boolean>('/project/unbind')
  },
  /** 工作目录本地分支列表(基线锚定选单分支下拉)。 */
  async gitBranches(): Promise<{ branches: string[]; current: string }> {
    const qs = projectQuery().toString()
    return apiGet(`/project/git-branches${qs ? '?' + qs : ''}`)
  },
  /** 提交列表分页(基线锚定选单): branch/search/offset, 默认 10 条/页。 */
  async gitCommits(opts: { branch?: string; search?: string; offset?: number; limit?: number }): Promise<{ commits: GitCommitInfo[]; hasMore: boolean }> {
    const qs = projectQuery()
    if (opts.branch?.trim()) qs.set('branch', opts.branch.trim())
    if (opts.search?.trim()) qs.set('search', opts.search.trim())
    qs.set('offset', String(Math.max(opts.offset ?? 0, 0)))
    if (opts.limit) qs.set('limit', String(opts.limit))
    return apiGet(`/project/git-commits?${qs.toString()}`)
  },
  /** 工作目录 git 状态轻量探测(不依赖 KB 关联)。 */
  async gitInfo(): Promise<GitInfoLite | null> {
    const qs = projectQuery().toString()
    return apiGet<GitInfoLite | null>(`/project/git-info${qs ? '?' + qs : ''}`)
  },
  /** 自动初始化工作目录 git 仓库(按钮点击即授权; 已是 repo 幂等返回)。 */
  async initGit(): Promise<{ alreadyRepo?: boolean; initialized?: boolean; branch?: string; head?: string }> {
    return apiPost('/project/init-git', currentProjectParams())
  },
  async status(): Promise<RepoStatus | null> {
    const qs = projectQuery().toString()
    return apiGet<RepoStatus | null>(`/project/status${qs ? '?' + qs : ''}`)
  },
  async overview(): Promise<ProjectOverview | null> {
    const qs = projectQuery().toString()
    return apiGet<ProjectOverview | null>(`/project/overview${qs ? '?' + qs : ''}`)
  },
  async snapshots(): Promise<Snapshot[]> {
    const qs = projectQuery().toString()
    return apiGet<Snapshot[]>(`/project/snapshots${qs ? '?' + qs : ''}`)
  },

  /** KB 版本列表只读(KB 表壳冻结期兼容; 基线管理宏观概览「版本历史」)：新→旧。 */
  async versions(): Promise<Array<{ id: string; label: string; head: string; createdAt: string }>> {
    const qs = projectQuery().toString()
    return apiGet<Array<{ id: string; label: string; head: string; createdAt: string }>>(`/project/versions${qs ? '?' + qs : ''}`)
  },

  /** 演化帧序列(B2+ 真数据): 任意 base..head ref 对 → 组件图谱帧推演。
   *  ref 接受 baseline / KB version id / branch / commit sha(前缀) / HEAD；缺省 baseline→HEAD。 */
  async evolutionFrames(base?: string, head?: string, layer?: 'component' | 'file',
                        refs?: string[]): Promise<EvolutionFrames | null> {
    const qs = projectQuery()
    if (base?.trim()) qs.set('base', base.trim())
    if (head?.trim()) qs.set('head', head.trim())
    if (layer) qs.set('layer', layer)
    // 显式帧序列(需求 7)：指定分支/head 列表作为 step 帧
    if (refs?.length) qs.set('refs', refs.filter((r) => r.trim()).join(','))
    return apiGet<EvolutionFrames | null>(`/project/evolution-frames?${qs.toString()}`)
  },
}
