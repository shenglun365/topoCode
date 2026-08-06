import { apiGet, apiPost } from './api-client'

export interface GitRepoState {
  commit: string
  dirty: boolean
}

export interface GitFileChange {
  path: string
  status: 'A' | 'M' | 'D' | 'R'
  add: number
  del: number
}

export interface GitChangesSummary {
  base: string
  head: string
  files: GitFileChange[]
}

export interface GitCommit {
  hash: string
  short: string
  message: string
  author: string
  date: number
  files: GitFileChange[]
}

export interface GitService {
  head(repo: string): Promise<GitRepoState>
  checkout(repo: string, commit: string): Promise<void>
  resetToBase(repo: string, commit: string): Promise<void>
  changes(repo: string): Promise<GitChangesSummary>
  log(repo: string, from: string, to: string): Promise<GitCommit[]>
  workingTree(repo: string): Promise<GitFileChange[]>
}

/** 后端不可达时保持旧行为(空结果), 不中断 UI。 */
function fallback<T>(value: T): T {
  return value
}

class HttpGitService implements GitService {
  async head(_repo: string): Promise<GitRepoState> {
    try {
      const status = await apiGet<{ branch: string; dirty: boolean }>('/git/status')
      return { commit: status.branch, dirty: status.dirty }
    } catch {
      return fallback({ commit: 'main', dirty: false })
    }
  }

  async checkout(_repo: string, commit: string): Promise<void> {
    try {
      await apiPost('/git/checkout', { ref: commit || 'main' })
    } catch {
      fallback(undefined)
    }
  }

  async resetToBase(_repo: string, commit: string): Promise<void> {
    try {
      await apiPost('/git/reset', { mode: 'hard', target: commit })
    } catch {
      fallback(undefined)
    }
  }

  async changes(_repo: string): Promise<GitChangesSummary> {
    try {
      const status = await apiGet<{ branch: string; ahead: number; baseline: string; uncommitted: string[] }>('/git/status')
      return {
        base: status.baseline ?? 'HEAD~' + status.ahead,
        head: 'HEAD',
        files: (status.uncommitted ?? []).map((f) => ({ path: f, status: 'M' as const, add: 0, del: 0 })),
      }
    } catch {
      return fallback({ base: 'HEAD~0', head: 'HEAD', files: [] })
    }
  }

  async log(_repo: string, _from: string, _to: string): Promise<GitCommit[]> {
    try {
      const res = await apiGet<{ entries: Array<{ oid: string; subject: string; author: string; date: string }> }>('/git/log')
      return (res.entries ?? []).map((e) => ({
        hash: e.oid,
        short: e.oid.slice(0, 7),
        message: e.subject,
        author: e.author,
        date: Date.parse(e.date) || Date.now(),
        files: [],
      }))
    } catch {
      return fallback([])
    }
  }

  async workingTree(_repo: string): Promise<GitFileChange[]> {
    try {
      const res = await apiGet<{ files: Array<{ path: string; staged: boolean; content: string }> }>('/git/working-tree')
      return (res.files ?? []).map((f) => ({
        path: f.path,
        status: (f.staged ? 'A' : 'M') as 'A' | 'M',
        add: f.content ? f.content.split('\n').length : 0,
        del: 0,
      }))
    } catch {
      return fallback([])
    }
  }
}

export const gitService: GitService = new HttpGitService()

export const PROJECT_GIT_PATH = '/home/dev/topo-projects/order-service'
