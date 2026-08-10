import type { AssetScopeItem, AssetType, FormDraft } from '@/types'
import { useArchArchitectureStore } from '@/stores/architecture-store'
import { CODE_MAPPINGS } from './mock/order-system'

export interface ValidationIssue {
  field: string
  message: string
  level: 'error' | 'warn'
}

/** 是否为规划中资产(p-前缀) —— greenfield 模式下放行。 */
export function isPlannedAsset(assetId: string): boolean {
  return assetId.startsWith('p-')
}

/** 是否为语义数据资产(sa-前缀) —— architect 自持，随最新代码结构提取。 */
export function isSemanticAsset(assetId: string): boolean {
  return assetId.startsWith('sa-')
}

export interface AssetRefInfo {
  assetId: string
  name: string
  type: AssetType
  file?: string
}

/** 知识库中已知资产(模块/ER 表/ORM 映射/实体类/流程/数据流)。 */
export function knownAssets(): AssetRefInfo[] {
  const arch = useArchArchitectureStore()
  const list: AssetRefInfo[] = []
  arch.components.forEach((c) => list.push({ assetId: c.id, name: c.name, type: 'component', file: assetFile(c.id) }))
  arch.erTables.forEach((d) => list.push({ assetId: d.id, name: d.name, type: 'er', file: assetFile(d.id) }))
  arch.ormMappings.forEach((d) => list.push({ assetId: d.id, name: d.name, type: 'orm', file: assetFile(d.id) }))
  arch.entityClasses.forEach((d) => list.push({ assetId: d.id, name: d.name, type: 'entity', file: assetFile(d.id) }))
  arch.executionFlows.forEach((f) => list.push({ assetId: f.id, name: f.name, type: 'flow', file: assetFile(f.id) }))
  arch.dataFlows.forEach((f) => list.push({ assetId: f.id, name: f.name, type: 'dataflow', file: assetFile(f.id) }))
  return list
}

/** 代码映射中的已知文件集合。 */
export function knownFiles(): string[] {
  return [...new Set(CODE_MAPPINGS.map((m) => m.file))]
}

/** 资产 ID → 代码映射文件。 */
export function assetFile(assetId: string): string | undefined {
  return CODE_MAPPINGS.find((m) => m.targetId === assetId)?.file
}

export function resolveAsset(assetId: string): AssetRefInfo | undefined {
  return knownAssets().find((a) => a.assetId === assetId)
}

/** 资产归属组件：组件自属；结构(er/orm/entity)看组件 owns；流程看执行步骤 owner；否则未归属。 */
export function ownerOf(assetId: string): string | undefined {
  const arch = useArchArchitectureStore()
  const comp = arch.components.find((c) => c.id === assetId)
  if (comp) return undefined
  const dsOwner = arch.components.find((c) => c.owns.includes(assetId))
  if (dsOwner) return dsOwner.id
  const flow = arch.executionFlows.find((f) => f.id === assetId)
  if (flow) {
    const owners = [...new Set(flow.steps.map((s) => s.owner))].filter(Boolean)
    return owners[0]
  }
  return undefined
}

export function matchAssetIds(query: string): AssetRefInfo[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  return knownAssets()
    .filter((a) => a.assetId.toLowerCase().includes(q) || a.name.toLowerCase().includes(q))
    .slice(0, 12)
}

export function matchFiles(query: string): string[] {
  const q = query.trim().toLowerCase()
  if (!q) return []
  return knownFiles().filter((f) => f.toLowerCase().includes(q)).slice(0, 8)
}

/** 单条资产引用校验：ID 必须命中知识库；file 需在已知文件内(允许手动引用降级为 warn)。 */
export function validateAssetRef(item: AssetScopeItem): ValidationIssue[] {
  const issues: ValidationIssue[] = []
  const known = resolveAsset(item.assetId)
  if (!known) {
    // greenfield p-前缀规划资产 / sa-语义数据资产 均放行
    if (!isPlannedAsset(item.assetId) && !isSemanticAsset(item.assetId)) {
      issues.push({ field: `asset.${item.assetId}`, message: `资产 ${item.assetId} 未在知识库命中，将按手动引用保存`, level: 'warn' })
    }
  }
  if (item.file && !knownFiles().includes(item.file)) {
    issues.push({ field: `file.${item.file}`, message: `文件 ${item.file} 未在代码映射中`, level: 'warn' })
  }
  return issues
}

/** 整份表单校验：基本信息(MD)非空；资产范围必须非空且有核心资产；ID 映射全部通过。 */
export function validateForm(form: FormDraft): { ok: boolean; issues: ValidationIssue[] } {
  const issues: ValidationIssue[] = []
  if (!form.title.trim()) issues.push({ field: 'title', message: '需求标题不能为空', level: 'error' })
  if (!form.basicMd.trim()) issues.push({ field: 'basicMd', message: '缺少基本信息(描述/可验收标准需并入基本信息)', level: 'error' })
  if (!form.assetScope.length) issues.push({ field: 'assetScope', message: '涉及的数据资产必须明确(至少一项)', level: 'error' })
  else if (!form.assetScope.some((a) => a.role === 'core')) issues.push({ field: 'assetScope', message: '至少需要一项核心修改资产', level: 'error' })
  form.assetScope.forEach((a) => issues.push(...validateAssetRef(a)))
  return { ok: issues.filter((i) => i.level === 'error').length === 0, issues }
}
