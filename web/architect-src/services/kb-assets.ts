import type { AssetDetail, CodeMapping } from '@/types'
import { apiGet } from './api-client'
import { currentProjectParams } from './project-service'

function ctx(): string {
  const { root, project } = currentProjectParams()
  const qs = new URLSearchParams()
  if (root) qs.set('root', root)
  if (project) qs.set('project', project)
  return qs.toString()
}

let mappingsCache: CodeMapping[] | undefined
let rulesCache: string | undefined

export const kbAssetService = {
  async detail(assetId: string): Promise<AssetDetail | undefined> {
    // 语义数据资产(sa-*)走语义资产详情端点，映射为 AssetDetail 兼容形状。
    if (assetId.startsWith('sa-')) {
      const { semanticAssetService } = await import('./semantic-asset-service')
      const a = await semanticAssetService.detail(assetId)
      if (!a) return undefined
      return {
        assetId: a.id,
        name: a.name,
        type: a.kind as AssetDetail['type'],
        change: a.change ?? 'same',
        desc: a.desc,
        file: a.astRefs?.[0]?.file,
        ast: a.astRefs?.[0],
      }
    }
    const qs = ctx()
    return await apiGet<AssetDetail>(`/kb/assets/${assetId}${qs ? '?' + qs : ''}`)
  },
  async searchComponents(query: string, filters?: { type?: string; level?: string }): Promise<AssetDetail[]> {
    const parts: string[] = []
    if (query) parts.push(`q=${encodeURIComponent(query)}`)
    if (filters?.type) parts.push(`type=${encodeURIComponent(filters.type)}`)
    if (filters?.level) parts.push(`level=${encodeURIComponent(filters.level)}`)
    const qs = [parts.join('&'), ctx()].filter(Boolean).join('&')
    return apiGet<AssetDetail[]>(`/kb/assets/search${qs ? '?' + qs : ''}`)
  },
  async codeMappings(): Promise<CodeMapping[]> {
    if (!mappingsCache) mappingsCache = await apiGet<CodeMapping[]>('/kb/code-mappings')
    return mappingsCache
  },
  async codingRules(): Promise<string> {
    if (!rulesCache) rulesCache = await apiGet<string>('/kb/coding-rules')
    return rulesCache
  },
}
