import type { AssetDetail, ArchitectureModel, CodeMapping } from '@/types'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { assetFile } from './asset-validator'
import { CODE_MAPPINGS, CODING_RULES } from './mock/order-system'
import { apiGet } from './api-client'

function toDetail(model: ArchitectureModel, assetId: string): AssetDetail | undefined {
  const comp = model.components.find((c) => c.id === assetId)
  if (comp) {
    return {
      assetId: comp.id, name: comp.name, type: 'component', change: comp.change, desc: comp.desc,
      file: assetFile(assetId), lang: comp.lang, kind: comp.kind,
      responsibilities: comp.responsibilities, owns: comp.owns, dependsOn: comp.dependsOn,
    }
  }
  return undefined
}

export const kbAssetService = {
  async detail(assetId: string): Promise<AssetDetail | undefined> {
    try {
      return await apiGet<AssetDetail>(`/kb/assets/${assetId}`)
    } catch {
      const model = useArchArchitectureStore().model
      return model ? toDetail(model, assetId) : undefined
    }
  },
  async searchComponents(query: string): Promise<AssetDetail[]> {
    const qs = query ? `?q=${encodeURIComponent(query)}` : ''
    return apiGet<AssetDetail[]>(`/kb/assets/search${qs}`)
  },
  codeMappings(): CodeMapping[] {
    return [...CODE_MAPPINGS]
  },
  codingRules(): string {
    return CODING_RULES
  },
}
