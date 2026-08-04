import { apiGet } from './api-client'

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

class HttpGitService implements GitService {
  async head(_repo: string): Promise<GitRepoState> {
    const status = await apiGet<{ branch: string; ahead: number; dirty: boolean; files: string[] }>('/git/status')
    return { commit: status.branch, dirty: status.dirty }
  }

  async checkout(_repo: string, _commit: string): Promise<void> {
    // delegates to backend git
  }

  async resetToBase(_repo: string, _commit: string): Promise<void> {
    // delegates to backend git
  }

  async changes(_repo: string): Promise<GitChangesSummary> {
    const status = await apiGet<{ branch: string; ahead: number; dirty: boolean; files: string[] }>('/git/status')
    return {
      base: 'HEAD~' + status.ahead,
      head: 'HEAD',
      files: status.files.map((f) => ({ path: f, status: 'M' as const, add: 0, del: 0 })),
    }
  }

  async log(_repo: string, _from: string, _to: string): Promise<GitCommit[]> {
    return []
  }

  async workingTree(_repo: string): Promise<GitFileChange[]> {
    return []
  }
}

export const gitService: GitService = new HttpGitService()

export const PROJECT_GIT_PATH = '/home/dev/topo-projects/order-service'
