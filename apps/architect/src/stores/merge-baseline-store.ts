import { defineStore } from 'pinia'
import type { GitCommit, GitFileChange } from '@/services/git-service'
import { gitService } from '@/services/git-service'
import { currentProjectRoot } from '@/services/project-service'
import { apiPost } from '@/services/api-client'
import { useArchMcpStore } from './mcp-store'
import { useArchProjectStore } from './project-store'

export type BaselineSyncStatus = 'idle' | 'syncing' | 'done'

export interface BaselineSyncRequest {
  branch: string
  tag: string
  commit: string
}

export const useArchMergeBaselineStore = defineStore('arch-merge-baseline', {
  state: () => ({
    loading: false,
    commits: [] as GitCommit[],
    uncommitted: [] as GitFileChange[],
    sync: {
      status: 'idle' as BaselineSyncStatus,
      request: null as BaselineSyncRequest | null,
      requestedAt: 0 as number,
      message: '',
    },
  }),
  getters: {
    hasUncommitted(state): boolean {
      return state.uncommitted.length > 0
    },
    loaded(state): boolean {
      return state.commits.length > 0
    },
    syncing(state): boolean {
      return state.sync.status === 'syncing'
    },
    done(state): boolean {
      return state.sync.status === 'done'
    },
  },
  actions: {
    async load() {
      if (this.loaded || this.loading) return
      this.loading = true
      const root = currentProjectRoot()
      const [commits, uncommitted] = await Promise.all([
        gitService.log(root, '', ''),
        gitService.workingTree(root),
      ])
      this.commits = commits
      this.uncommitted = uncommitted
      this.loading = false
    },
    async commitUncommitted() {
      const msg = 'chore: 提交未入库变更'
      const res = await apiPost<{ oid: string; subject: string }>('/git/commit', { message: msg })
      const oid = res.oid || `unknown${Date.now().toString(16)}`
      const head = this.commits[0]
      this.commits = [
        {
          hash: oid,
          short: oid.slice(0, 7),
          message: res.subject || msg,
          author: 'git',
          date: Date.now(),
          files: this.uncommitted,
        },
        ...(head ? this.commits : []),
      ]
      this.uncommitted = []
    },
    async sendBaselineSync() {
      if (this.syncing) return
      const project = useArchProjectStore()
      const st = project.status
      const req: BaselineSyncRequest = {
        branch: st?.head.branch ?? 'main',
        tag: st?.baseline.version ?? 'v0.0.1',
        commit: st?.head.commit ?? 'HEAD',
      }
      const mcp = useArchMcpStore()
      mcp.record({
        id: `kbsync-${Date.now()}`,
        source: 'topocode-architect',
        tool: 'architect.baseline.requestSync',
        method: 'invoke',
        time: Date.now(),
        status: 'pending',
        detail: `请求知识库基于 git (${req.branch} @ ${req.commit}) 同步代码并更新基线`,
      })
      this.sync.request = req
      this.sync.requestedAt = Date.now()
      this.sync.status = 'syncing'
      this.sync.message = ''
      await apiPost('/project/baseline/sync', req)
      this.sync.status = 'done'
      this.sync.message = '知识库已基于 git 同步代码并更新基线 git 表示'
      mcp.record({
        id: `kbsync-ok-${Date.now()}`,
        source: 'topocode-architect',
        tool: 'architect.baseline.requestSync',
        method: 'invoke',
        time: Date.now(),
        status: 'ok',
        detail: '基线同步完成: KB 完成代码同步 → 基线 git 表示已更新',
      })
      project.updateBaselineGit(req.commit)
    },
  },
})
