import { defineStore } from 'pinia'
import type { GitCommit, GitFileChange } from '@/services/git-service'
import { gitService } from '@/services/git-service'
import { currentProjectRoot } from '@/services/project-service'
import { apiPost } from '@/services/api-client'
import { semanticAssetService, type BaselineRefreshJob } from '@/services/semantic-asset-service'
import { useArchMcpStore } from './mcp-store'
import { useArchProjectStore } from './project-store'

export type BaselineSyncStatus = 'idle' | 'syncing' | 'done' | 'error'

export interface BaselineSyncRequest {
  branch: string
  tag: string
  commit: string
}

/** 基线管理本地版（数据主权批E）：「更新基线」= architect 本地编排
 * （采集→分组→命名），KB 仅提供算力（parseFileAst/communityFromGraph/llm）。
 * 状态机：idle → syncing(作业进行中) → done / error——任何失败回 error
 * 且 message 带原因，不再有发起-确认流与假完成。 */
export const useArchMergeBaselineStore = defineStore('arch-merge-baseline', {
  state: () => ({
    loading: false,
    commits: [] as GitCommit[],
    uncommitted: [] as GitFileChange[],
    sync: {
      status: 'idle' as BaselineSyncStatus,
      request: null as BaselineSyncRequest | null,
      jobId: '' as string,
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
    failed(state): boolean {
      return state.sync.status === 'error'
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
        tool: 'architect.baseline.refresh',
        method: 'invoke',
        time: Date.now(),
        status: 'pending',
        detail: `更新自有基线（本地编排：采集→分组→命名 @ ${req.commit.slice(0, 7)}）`,
      })
      this.sync.request = req
      this.sync.requestedAt = Date.now()
      this.sync.status = 'syncing'
      this.sync.message = ''
      try {
        const r = await semanticAssetService.baselineRefresh()
        if (!r?.started) {
          this.sync.status = 'error'
          this.sync.message = `未启动: ${r?.reason || '未知原因'}`
          mcp.record({
            id: `kbsync-err-${Date.now()}`,
            source: 'topocode-architect',
            tool: 'architect.baseline.refresh',
            method: 'invoke',
            time: Date.now(),
            status: 'blocked',
            detail: this.sync.message,
          })
          return
        }
        this.sync.jobId = r.job?.id || ''
        await this.pollUntilDone()
      } catch (e: any) {
        this.sync.status = 'error'
        this.sync.message = e?.message || String(e)
      }
    },
    async pollUntilDone() {
      const MAX_ROUNDS = 240 // ≈10min(2.5s 轮询)
      for (let i = 0; i < MAX_ROUNDS; i++) {
        await new Promise((r) => setTimeout(r, 2500))
        const st = await semanticAssetService.baselineRefreshStatus().catch(() => null)
        const job: BaselineRefreshJob | undefined =
          st?.jobs.find((j) => j.id === this.sync.jobId) || st?.latest
        if (!job) continue
        if (job.state === 'running' || job.state === 'queued') {
          const cur = job.progress?.current || ''
          if (cur) this.sync.message = cur
          continue
        }
        if (job.state === 'done') {
          this.sync.status = 'done'
          const steps = job.result?.steps || {}
          const parts = [
            steps.collect ? `采集 ${steps.collect.nodes ?? 0} 符号` : '',
            steps.group ? `分组 ${steps.group.components ?? 0} 组件` : '',
            steps.naming && !steps.naming.error ? `命名 ${steps.naming.named ?? 0}` : '',
          ].filter(Boolean)
          this.sync.message = parts.length
            ? `完成：${parts.join('，')}`
            : '基线刷新完成'
          const mcp = useArchMcpStore()
          mcp.record({
            id: `kbsync-ok-${Date.now()}`,
            source: 'topocode-architect',
            tool: 'architect.baseline.refresh',
            method: 'invoke',
            time: Date.now(),
            status: 'ok',
            detail: this.sync.message,
          })
          return
        }
        this.sync.status = 'error'
        this.sync.message = `作业终态: ${job.state}`
        return
      }
      this.sync.status = 'error'
      this.sync.message = '轮询超时(10min)——请到任务中心查看作业'
    },
  },
})
