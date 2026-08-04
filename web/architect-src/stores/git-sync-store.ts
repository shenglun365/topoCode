import { defineStore } from 'pinia'
import type { GitChangesSummary, GitRepoState } from '@/services/git-service'
import { PROJECT_GIT_PATH, gitService } from '@/services/git-service'

/**
 * git 变更同步 store：把 git 读取/操作统一收敛到 store 层。
 *
 * 组件经此访问 git，不在 UI 中直接依赖 git-service（后续接入真实后端时只需改此处实现）。
 */
export const useArchGitSyncStore = defineStore('arch-git-sync', {
  state: () => ({
    changes: null as GitChangesSummary | null,
    changesLoading: false,
  }),
  getters: {
    fileCount(state): number {
      return state.changes?.files.length ?? 0
    },
  },
  actions: {
    /** 加载代码变更汇总(git diff)。 */
    async loadChanges(): Promise<GitChangesSummary> {
      if (this.changesLoading) return this.changes ?? { base: '', head: '', files: [] }
      this.changesLoading = true
      this.changes = await gitService.changes(PROJECT_GIT_PATH)
      this.changesLoading = false
      return this.changes
    },
    /** 读取当前 HEAD。 */
    async head(): Promise<GitRepoState> {
      return gitService.head(PROJECT_GIT_PATH)
    },
    /** 重置到基线 commit。 */
    async resetToBase(commit: string): Promise<void> {
      await gitService.resetToBase(PROJECT_GIT_PATH, commit)
    },
  },
})