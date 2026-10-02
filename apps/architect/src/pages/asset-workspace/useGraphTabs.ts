/**
 * 资产工作区 · 图谱 tab + 静态图弹窗域（MS6-W1 搬移，纯移动零逻辑改动）。
 * 多资源图谱 tab 管理(>500 资产文件索引圈定) + entity/state 静态图弹窗。
 */
import { computed, ref } from 'vue'
import { semanticAssetService } from '@/services/semantic-asset-service'
import type { GraphFileEntry, SemanticAsset, AssetDiagramItem } from '@/types'
import type { GraphTabDef } from '@/components/assets/graph-view/graphTypes'
import type { WsDeps } from './useAssetCore'

export function useGraphTabs(D: WsDeps) {
  const core = D.core
  const items = core.items

  /** 语义图谱多资源 tab(从语义列表/组件列表打开，可并存)。 */
  const graphTabs = ref<GraphTabDef[]>([])
  const activeGraphTab = ref('')

  /** 打开(或激活已存在的同名资源)图谱 tab；kind 相同时复用，避免重复。 */
  function openGraphTab(kind: GraphTabDef['kind'], id: string, title: string, members?: string[]) {
    const key = `${kind}:${id}`
    const existing = graphTabs.value.find((x) => x.id === key)
    if (existing) {
      if (kind === 'logic' && members) existing.members = members   // 重新分析后刷新成员快照
      activeGraphTab.value = existing.id
    } else {
      const def: GraphTabDef = { id: key, kind, title, compId: kind === 'comp' ? id : undefined, assetId: kind === 'asset' ? id : undefined, fileId: kind === 'file' ? id : undefined, viewId: kind === 'logic' ? id : undefined, members }
      graphTabs.value.push(def)
      activeGraphTab.value = def.id
    }
    core.tab.value = 'graph'
    core.onSearch()
  }

  function closeGraphTab(id: string) {
    const i = graphTabs.value.findIndex((x) => x.id === id)
    if (i < 0) return
    graphTabs.value.splice(i, 1)
    if (activeGraphTab.value === id) {
      activeGraphTab.value = graphTabs.value[i]?.id ?? graphTabs.value[i - 1]?.id ?? ''
    }
  }

  // ---- 图谱文件索引(>500 资产强制手动圈定)：按 tab 范围预算 文件→资产数/组件归属 ----
  /** all/comp tab：范围内每个首锚点文件的资产数与归属组件；asset/file tab 无需圈定。 */
  function buildGraphFileIndex(gt: GraphTabDef): GraphFileEntry[] {
    if (gt.kind !== 'all' && gt.kind !== 'comp') return []
    const inScope = (a: SemanticAsset) =>
      gt.kind === 'all' ? true : core.componentsOf(a).includes(gt.compId!)
    const byFile = new Map<string, { n: number; comps: Set<string> }>()
    for (const a of items.value) {
      if (a.status === 'deleted' || !inScope(a)) continue
      const f = a.astRefs?.[0]?.file || ''
      if (!f) continue
      const e = byFile.get(f) ?? { n: 0, comps: new Set<string>() }
      e.n += 1
      for (const c of core.componentsOf(a)) e.comps.add(c)
      byFile.set(f, e)
    }
    return [...byFile.entries()].map(([file, e]) => ({
      file,
      dir: file.includes('/') ? file.slice(0, file.lastIndexOf('/')) : '/',
      n: e.n,
      comps: [...e.comps],
    }))
  }
  const graphFileIndexes = computed<Record<string, GraphFileEntry[]>>(() => {
    const out: Record<string, GraphFileEntry[]> = {}
    for (const gt of graphTabs.value) out[gt.id] = buildGraphFileIndex(gt)
    return out
  })
  const graphCompNames = computed<Record<string, string>>(() =>
    Object.fromEntries(core.compCatalog.value.map((c) => [c.assetId, c.name])))

  // ---- 静态资产图弹窗(entity → 类图，state → 状态图) ----
  const diagramModalOpen = ref(false)
  const diagramModalLoading = ref(false)
  const diagramModalItems = ref<AssetDiagramItem[]>([])
  const diagramModalTitle = ref('')

  async function openAssetDiagram(a: SemanticAsset) {
    diagramModalOpen.value = true
    diagramModalLoading.value = true
    diagramModalTitle.value = a.name
    diagramModalItems.value = []
    try {
      const res = await semanticAssetService.assetDiagram([a.id])
      diagramModalItems.value = res.diagrams ?? []
    } catch {
      diagramModalItems.value = []
    } finally {
      diagramModalLoading.value = false
    }
  }

  return {
    graphTabs, activeGraphTab, openGraphTab, closeGraphTab,
    buildGraphFileIndex, graphFileIndexes, graphCompNames,
    diagramModalOpen, diagramModalLoading, diagramModalItems, diagramModalTitle, openAssetDiagram,
  }
}
