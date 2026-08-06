import { defineStore } from 'pinia'
import type { GranularityConfig, ProductForm, ProjectInfo, ProjectMode, ProjectScaffold, RepoStatus, Snapshot } from '@/types'
import { projectService } from '@/services/project-service'
import router from '@/router'

/** 项目选择持久化在 URL 内(?root=<path> / ?project=<arch行id>)，多页签各处理不同项目。 */
async function setProjectQuery(query: Record<string, string>): Promise<void> {
  const cur = router.currentRoute.value
  const merged: Record<string, string> = { ...(cur.query as Record<string, string>), ...query }
  await router.replace({ path: cur.path, query: merged })
}

async function clearProjectQuery(): Promise<void> {
  const cur = router.currentRoute.value
  await router.replace({ path: cur.path })
}

function currentRoot(): string | undefined {
  const r = router.currentRoute.value.query.root
  return typeof r === 'string' ? r : undefined
}

export const useArchProjectStore = defineStore('arch-project', {
  state: () => ({
    loaded: false,
    loading: false,
    project: null as ProjectInfo | null,
    status: null as RepoStatus | null,
    snapshots: [] as Snapshot[],
    baseline: null as Snapshot | null,
    current: null as Snapshot | null,
  }),
  getters: {
    mode(): ProjectMode { return this.project?.mode ?? 'existing' },
    isGreenfield(): boolean { return this.mode === 'greenfield' },
    scaffold(): ProjectScaffold | undefined { return this.project?.scaffold },
    productForm(): ProductForm | undefined { return this.project?.productForm },
    hasBaseline(): boolean { return !!this.project?.baselineId },
  },
  actions: {
    async load(force = false) {
      if (this.loaded && !force) return
      this.loading = true
      try {
        const [project, status, snapshots] = await Promise.all([
          projectService.getBound(),
          projectService.status(),
          projectService.snapshots(),
        ])
        this.project = project
        this.status = status
        this.snapshots = snapshots
      } catch {
        this.project = null
        this.status = null
        this.snapshots = []
      }
      this.baseline = this.snapshots.find((s) => s.id === 'snap-v0') ?? this.snapshots[0] ?? null
      this.current = this.snapshots.find((s) => s.id === 'snap-v1') ?? this.snapshots[1] ?? null
      this.loaded = true
      this.loading = false
    },
    /** 打开工作目录并关联 KB：校验通过后写 ?root=execRoot(选择持久化在 URL)。 */
    async bindKbProject(kbProjectId: string, execRoot: string, name?: string): Promise<ProjectInfo> {
      const project = await projectService.bindKbProject(kbProjectId, execRoot, name)
      await setProjectQuery({ root: execRoot })
      await this.load(true)
      return project
    },
    async bindWorkingDir(execRoot: string, name?: string): Promise<ProjectInfo> {
      const project = await projectService.bindWorkingDir(execRoot, name)
      await setProjectQuery({ root: execRoot })
      await this.load(true)
      return project
    },
    /** 项目页后补关联 KB(同源校验由后端执行)。 */
    async linkKb(kbProjectId: string): Promise<void> {
      await projectService.linkKb(kbProjectId, this.project?.rootPath ?? currentRoot())
      await this.load(true)
    },
    /** 解除 KB 关联(项目保留，回到降级)。 */
    async unlinkKb(): Promise<void> {
      await projectService.unlinkKb()
      await this.load(true)
    },
    async unbind(): Promise<boolean> {
      const ok = await projectService.unbind()
      await clearProjectQuery()
      this.project = null
      this.status = null
      this.snapshots = []
      this.baseline = null
      this.current = null
      return ok
    },
    async createGreenfield(opts: {
      name?: string; desc?: string; language?: string; framework?: string;
      moduleLayout?: string; productForm?: string; execRoot?: string; kbRoot?: string
    }): Promise<ProjectInfo> {
      const project = await projectService.createGreenfield(opts)
      this.project = project
      this.status = null
      this.snapshots = []
      this.baseline = null
      this.current = null
      if (project?.id && project.rootPath) {
        await setProjectQuery({ project: project.id, root: project.rootPath })
      }
      return project
    },
    updateConfig(patch: Partial<GranularityConfig>) {
      if (!this.project) return
      this.project.config = { ...this.project.config, ...patch }
    },
    updateScaffold(patch: Partial<ProjectScaffold>) {
      if (!this.project) return
      this.project.scaffold = { ...(this.project.scaffold ?? { language: '', moduleLayout: 'mono' }), ...patch }
    },
    setProductForm(form: ProductForm) {
      if (!this.project) return
      this.project.productForm = form
    },
    switchMode(mode: ProjectMode) {
      if (!this.project) return
      this.project.mode = mode
    },
    /** 知识库完成基线同步后，更新基线的 git 表示。 */
    updateBaselineGit(commit: string) {
      if (!this.status) return
      const now = Date.now()
      this.status = {
        ...this.status,
        baseline: {
          id: `baseline_id = N+1`,
          version: 'v1.0.0',
          commit,
          manifestHash: 'sha256:9f7…c21',
          createdAt: now,
        },
        head: { ...this.status.head, ahead: 0 },
        lastRebaseline: now,
      }
      if (this.project) this.project.baselineCommit = commit
    },
  },
})
