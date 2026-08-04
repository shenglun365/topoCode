import { defineStore } from 'pinia'
import type { GranularityConfig, ProductForm, ProjectInfo, ProjectMode, ProjectScaffold, RepoStatus, Snapshot } from '@/types'
import { projectService } from '@/services/project-service'

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
    async load() {
      if (this.loaded) return
      this.loading = true
      const [project, status, snapshots] = await Promise.all([
        projectService.getBound(),
        projectService.status(),
        projectService.snapshots(),
      ])
      this.project = project
      this.status = status
      this.snapshots = snapshots
      this.baseline = snapshots.find((s) => s.id === 'snap-v0') ?? snapshots[0] ?? null
      this.current = snapshots.find((s) => s.id === 'snap-v1') ?? snapshots[1] ?? null
      this.loaded = true
      this.loading = false
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
