import type { BaselineInfo } from '@/types'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { apiGet } from './api-client'

function buildInfo(): BaselineInfo {
  const project = useArchProjectStore()
  const arch = useArchArchitectureStore()
  const p = project.project
  const st = project.status
  return {
    gitTag: p ? `v1.0.0-${p.name}` : 'v1.0.0',
    branch: p?.branch ?? st?.head.branch ?? 'main',
    gitDate: st?.baseline.createdAt ?? Date.now(),
    analyzedAt: arch.loadedAt ?? Date.now(),
    archVersion: arch.modelVersion ?? 'v1',
    commit: p?.baselineCommit ?? st?.baseline.commit ?? '',
    desc: p?.desc ?? '',
  }
}

function buildDirty(): boolean {
  const project = useArchProjectStore()
  return !!project.status && project.status.head.ahead > 0
}

export const baselineService = {
  async meta(): Promise<BaselineInfo> {
    return apiGet<BaselineInfo>('/project/baseline/meta')
  },
  async dirty(): Promise<boolean> {
    const result = await apiGet<{ dirty: boolean }>('/project/baseline/dirty')
    return result.dirty
  },
}

export function currentBaselineInfo(): BaselineInfo {
  return buildInfo()
}

export function baselineDirty(): boolean {
  return buildDirty()
}
