<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'
import { useComponentId } from '@/composables/useComponentId'
import { useGraphFullscreen } from '@/composables/useGraphFullscreen'
import { useGraphPosition } from '@/composables/useGraphPosition'
import { communityLabel, communityIdLabel } from '@/utils/communityLabel'
import { ipc } from '@/services/ipc'
import GraphBreadcrumb from './GraphBreadcrumb.vue'
import GraphToolbar from './GraphToolbar.vue'
import GraphCanvas from './GraphCanvas.vue'
import ExternalTableView from './ExternalTableView.vue'
import ExternalHeatmapView from './ExternalHeatmapView.vue'
import NodeFilterPanel from './NodeFilterPanel.vue'
import CommunityTableView from './CommunityTableView.vue'

/* ========================================================
   Unified drill path — single source of truth for all views
   ======================================================== */

interface DrillPathNode {
  key: string
  label: string
  kind: 'root' | 'community' | 'external'
  commId?: string
  extItemId?: string
  commLevel?: string
}

const rootDrillNode = (): DrillPathNode => ({
  key: 'L0',
  label: t('report.allL0', '全部L0社区'),
  kind: 'root',
  commLevel: 'L0',
})

const { t } = useI18n()
const communityStore = useCommunityStore()

const props = defineProps<{
  taskId: string
  projectId: string
  taskUpdatedAt: string
  edgeType: 'INCLUDE' | 'CALL' | 'EXTERNAL_INCLUDE' | 'EXTERNAL_CALL'
  externalStats: any
}>()

const emit = defineEmits<{
  'open-md': [params: { taskId: string; content: string; title: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string; regenerationType?: 'community' | 'overall' }]
}>()

const { showId, componentId } = useComponentId('CG-001')
const { isFullscreen, enterFullscreen, exitFullscreen, onKeydown } = useGraphFullscreen()
const { getNodePosition, setNodePosition } = useGraphPosition(
  props.projectId, props.taskId, props.taskUpdatedAt
)

/* ---- view mode state ---- */
const graphStyle = ref<'d3force' | 'dagre'>('dagre')
const externalViewMode = ref<'force' | 'table' | 'heatmap'>('force')
const internalViewMode = ref<'force' | 'dagre' | 'table' | 'heatmap'>('dagre')
const resetTrigger = ref(0)
const recenterTrigger = ref(0)
const showFilter = ref(false)
const filterClickX = ref(0)
const filterClickY = ref(0)

/* ---- unified drill state ---- */
const drillPath = ref<DrillPathNode[]>([rootDrillNode()])

/* ---- compare mode ---- */
const compareActive = ref(false)
const compareFrom = ref('')
const compareTo = ref('')
const compareSnapshotIds = ref<Array<{ id: string; ts: string; commCount: number; summary: string }>>([])
const compareNodeStates = ref<Map<string, 'added' | 'removed' | 'changed' | 'unchanged'>>(new Map())

async function toggleCompare() {
  if (compareActive.value) {
    compareActive.value = false
    compareNodeStates.value = new Map()
    return
  }
  try {
    const list = await ipc.analysis.listArchSnapshots({ taskId: props.taskId })
    compareSnapshotIds.value = list
    if (list.length < 2) {
      compareActive.value = false
      return
    }
    const prev = list[list.length - 2]
    const curr = list[list.length - 1]
    compareFrom.value = prev.id
    compareTo.value = curr.id
    await loadCompareData(prev.id, curr.id)
    compareActive.value = true
  } catch {
    compareActive.value = false
  }
}

async function loadCompareData(fromId: string, toId: string) {
  try {
    const [prevData, currData] = await Promise.all([
      ipc.analysis.getArchSnapshot({ taskId: props.taskId, versionId: fromId }),
      ipc.analysis.getArchSnapshot({ taskId: props.taskId, versionId: toId }),
    ])
    const prevIds = new Set(prevData.map((c: any) => c.cid))
    const currIds = new Set(currData.map((c: any) => c.cid))
    const states = new Map<string, 'added' | 'removed' | 'changed' | 'unchanged'>()
    for (const c of currData) {
      const cid = c.cid
      if (!prevIds.has(cid)) states.set(cid, 'added')
      else {
        const prevC = prevData.find((p: any) => p.cid === cid)
        const changed = prevC && (prevC.nodes !== c.nodes || Math.abs((prevC.score || 0) - (c.score || 0)) > 0.01)
        states.set(cid, changed ? 'changed' : 'unchanged')
      }
    }
    for (const c of prevData) {
      if (!currIds.has(c.cid)) states.set(c.cid, 'removed')
    }
    compareNodeStates.value = states
  } catch { /* skip */ }
}

function setCompareVersion(fromId: string, toId: string) {
  compareFrom.value = fromId
  compareTo.value = toId
  loadCompareData(fromId, toId)
}

/* ---- graph / merge / search ---- */
const MERGE_THRESHOLD = 100
const BATCH_EXPAND_SIZE = 50
const expandBatchCount = ref(0)
const graphSearch = ref('')
const drilling = ref(false)

/* ---- force layout controls ---- */
const forceLockMode = ref<'linked' | 'locked'>('linked')
const forceRepulsion = ref(15000)

/* ---- filter persistence ---- */
const FILTER_STORAGE_KEY = computed(() => `graph-filter-${props.projectId}-${props.taskId}`)
const hiddenNodeIds = ref<Set<string>>(loadHiddenIds())

function loadHiddenIds(): Set<string> {
  try {
    const raw = localStorage.getItem(FILTER_STORAGE_KEY.value)
    if (raw) return new Set(JSON.parse(raw))
  } catch {}
  return new Set()
}
function saveHiddenIds() {
  try {
    localStorage.setItem(FILTER_STORAGE_KEY.value, JSON.stringify([...hiddenNodeIds.value]))
  } catch {}
}
function updateHiddenIds(ids: Set<string>) {
  hiddenNodeIds.value = ids
  saveHiddenIds()
}

/* ---- tab detection ---- */
const isExternalTab = computed(() =>
  props.edgeType === 'EXTERNAL_INCLUDE' || props.edgeType === 'EXTERNAL_CALL'
)
const effectiveEdgeType = computed(() => {
  if (props.edgeType === 'EXTERNAL_INCLUDE') return 'INCLUDE'
  if (props.edgeType === 'EXTERNAL_CALL') return 'CALL'
  return props.edgeType
})

/* ---- derived drill metadata ---- */
const drillMeta = computed(() => {
  const tail = drillPath.value[drillPath.value.length - 1]
  return {
    isAtRoot: drillPath.value.length <= 1,
    drillLevel: tail.commLevel || 'L0',
    drillCommId: tail.commId || null,
    drillExtItemId: tail.extItemId || null,
    drillKey: tail.key,
    breadcrumbSegments: drillPath.value.map(n => ({ key: n.key, label: n.label, level: n.commLevel })),
    fsTitle: tail.kind === 'root' ? t('report.communityArchitecture', '组件架构') : tail.label,
  }
})

/* ---- community data ---- */
const allCommunities = computed(() => {
  return communityStore.tasks[props.taskId]?.communities || []
})
const commMap = computed(() => {
  const m = new Map<string, CommunityItem>()
  for (const c of allCommunities.value) {
    m.set(c.communityId, c)
  }
  return m
})
const parentCommIds = computed(() => {
  const s = new Set<string>()
  for (const c of allCommunities.value) {
    if (c.parentId) s.add(c.parentId)
  }
  return s
})

/* ---- filter nodes for filter panel ---- */
const filterNodes = computed(() => {
  const deg = nodeDegrees.value
  if (isExternalTab.value) {
    const seen = new Set<string>()
    const result = []
    for (const n of rawGraphNodes.value) {
      if (!n.isMerged && !seen.has(n.id)) {
        seen.add(n.id)
        const d = deg.get(n.id)
        result.push({ id: n.id, label: n.label, nodeCount: n.nodeCount, type: n.isExternal ? 'external' as const : 'community' as const, qualityScore: n.qualityScore ?? null, inDegree: d?.in ?? 0, outDegree: d?.out ?? 0 })
      }
    }
    for (const n of externalCommunityNodes.value) {
      if (!seen.has(n.id)) {
        seen.add(n.id)
        const d = deg.get(n.id)
        result.push({ id: n.id, label: n.label, nodeCount: n.nodeCount, type: 'community' as const, qualityScore: null, inDegree: d?.in ?? 0, outDegree: d?.out ?? 0 })
      }
    }
    return result
  }
  return rawGraphNodes.value
    .filter(n => !n.isMerged)
    .map(n => ({ id: n.id, label: n.label, nodeCount: n.nodeCount, type: n.isExternal ? 'external' as const : 'community' as const, qualityScore: n.qualityScore ?? null, inDegree: deg.get(n.id)?.in ?? 0, outDegree: deg.get(n.id)?.out ?? 0 }))
})

/* ---- external data ---- */
const externalItems = computed(() => {
  if (!isExternalTab.value || !props.externalStats) return []
  return props.edgeType === 'EXTERNAL_INCLUDE'
    ? (props.externalStats.externalDeps || [])
    : (props.externalStats.externalCalls || [])
})

const externalCrossEdges = computed(() => {
  if (!isExternalTab.value || !props.externalStats) return []
  const edges: any[] = []
  const items = props.edgeType === 'EXTERNAL_INCLUDE'
    ? (props.externalStats.externalDeps || [])
    : (props.externalStats.externalCalls || [])
  items.forEach((item: any) => {
    const extId = item.package || item.name
    const communities = item.communities || []
    communities.forEach((c: any) => {
      edges.push({ source: extId, target: c.communityId })
    })
  })
  return edges
})

const externalCommunityNodes = computed(() => {
  if (!isExternalTab.value || !props.externalStats) return []
  const seen = new Set<string>()
  const nodes: any[] = []
  const items = props.edgeType === 'EXTERNAL_INCLUDE'
    ? (props.externalStats.externalDeps || [])
    : (props.externalStats.externalCalls || [])
  items.forEach((item: any) => {
    const communities = item.communities || []
    communities.forEach((c: any) => {
      if (!seen.has(c.communityId)) {
        seen.add(c.communityId)
        nodes.push({
          id: c.communityId,
          label: communityIdLabel(c.communityId),
          nodeCount: 0,
          isExternal: false,
          hasChildren: parentCommIds.value.has(c.communityId),
        })
      }
    })
  })
  return nodes
})

/* ---- external drill-filtered items ---- */
const drillExternalItems = computed(() => {
  if (!isExternalTab.value) return props.externalStats
  const extId = drillMeta.value.drillExtItemId
  if (!extId) return externalItems.value
  return externalItems.value.filter((i: any) => (i.package || i.name) === extId)
})

/* ---- graph nodes ---- */
function mapCommunityToNode(c: CommunityItem) {
  const state = compareActive.value ? compareNodeStates.value.get(c.communityId) : undefined
  return {
    id: c.communityId,
    label: communityLabel(c),
    nodeCount: c.nodeCount,
    fileCount: c.fileCount,
    qualityScore: c.qualityScore,
    status: c.status,
    hasChildren: parentCommIds.value.has(c.communityId),
    compareState: state,
  }
}

function buildExternalNodes(): any[] {
  if (!props.externalStats) return []
  const items = props.edgeType === 'EXTERNAL_INCLUDE'
    ? (props.externalStats.externalDeps || [])
    : (props.externalStats.externalCalls || [])
  const nodes: any[] = []
  items.forEach((item: any) => {
    const extId = item.package || item.name
    nodes.push({
      id: extId,
      label: extId.length > 16 ? extId.slice(0, 16) + '\u2026' : extId,
      nodeCount: item.fileCount || item.count,
      isExternal: true,
      hasChildren: !!(item.communities && item.communities.length > 0),
    })
  })
  return nodes
}

const rawGraphNodes = computed(() => {
  if (isExternalTab.value) {
    const commId = drillMeta.value.drillCommId
    if (commId) {
      const coms = allCommunities.value
      const parent = commMap.value.get(commId) || null
      if (!parent) return []
      const parentLevel = parent.level || 'L0'
      const nextLevel = `L${parseInt(parentLevel.slice(1) || '0') + 1}`
      const childNodes = coms.filter(c =>
        c.edgeType === parent.edgeType &&
        c.level === nextLevel &&
        c.parentId === commId
      ).map(c => mapCommunityToNode(c))
      const firstCommEntry = drillPath.value.find(n => n.kind === 'community')
      const rootL0Id = firstCommEntry?.commId
      const connectedExtIds = new Set<string>()
      if (rootL0Id) {
        for (const e of externalCrossEdges.value) {
          if (e.target === rootL0Id) connectedExtIds.add(e.source)
        }
      }
      const extNodes = buildExternalNodes().filter(n => {
        if (!connectedExtIds.has(n.id)) return false
        if (!commId) return true
        const edgeSet = new Set(crossEdges.value.map(e => e.source))
        return edgeSet.has(n.id)
      })
      return [...childNodes, ...extNodes]
    }
    const extNodes = buildExternalNodes()
    const commNodes = externalCommunityNodes.value
    const connectedIds = new Set<string>()
    for (const e of externalCrossEdges.value) {
      connectedIds.add(e.source)
      connectedIds.add(e.target)
    }
    const all = [...extNodes.filter(n => connectedIds.has(n.id)), ...commNodes]
    const extId = drillMeta.value.drillExtItemId
    if (extId) {
      const extNode = all.find(n => n.id === extId && n.isExternal)
      if (extNode) {
        const connectedCommIds = new Set<string>()
        for (const e of externalCrossEdges.value) {
          if (e.source === extId) connectedCommIds.add(e.target)
          if (e.target === extId) connectedCommIds.add(e.source)
        }
        return all.filter(n => n.id === extId || connectedCommIds.has(n.id))
      }
    }
    return all
  }
  const coms = allCommunities.value
  const commId = drillMeta.value.drillCommId
  if (!commId) {
    return coms.filter(c => c.level === 'L0' && c.edgeType === props.edgeType)
      .map(c => mapCommunityToNode(c))
  }
  const parent = coms.find(c => c.communityId === commId)
  if (!parent) return []
  const nextLevel = `L${parseInt(parent.level?.slice(1) || '0') + 1}`
  return coms.filter(c =>
    c.edgeType === props.edgeType &&
    c.level === nextLevel &&
    c.parentId === commId
  ).map(c => mapCommunityToNode(c))
})

const graphNodes = computed(() => {
  const raw = rawGraphNodes.value
  if (raw.length <= MERGE_THRESHOLD || isExternalTab.value) return applySearchFilter(raw)
  const sorted = [...raw].sort((a, b) => (b.nodeCount || 0) - (a.nodeCount || 0))
  const visible = sorted.slice(0, MERGE_THRESHOLD)
  const currentHidden = sorted.slice(MERGE_THRESHOLD)
  const expandedFromPrev = expandBatchCount.value * BATCH_EXPAND_SIZE
  const showing = Math.min(expandedFromPrev, currentHidden.length)
  const result = [...visible]
  if (currentHidden.length > 0) {
    for (let i = 0; i < showing; i++) result.push(currentHidden[i])
    const remaining = currentHidden.length - showing
    if (remaining > 0) {
      result.push({
        id: '__merged__',
        label: `${t('report.otherCommunities', '其他')} ${remaining} ${t('report.communitiesUnit', '个')}`,
        nodeCount: currentHidden.slice(showing).reduce((s: number, n: any) => s + (n.nodeCount || 0), 0),
        isMerged: true,
        remainingCount: remaining,
      })
    }
  }
  return applySearchFilter(result)
})

function applySearchFilter(nodes: any[]): any[] {
  const q = graphSearch.value.trim().toLowerCase()
  if (!q) return nodes
  return nodes.filter(n => {
    if (n.isMerged) return n.label.toLowerCase().includes(q)
    return n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q)
  })
}

const highlightedNodeIds = computed(() => {
  const q = graphSearch.value.trim().toLowerCase()
  if (!q) return new Set<string>()
  return new Set(graphNodes.value.filter(n => {
    if (n.isMerged) return false
    return n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q)
  }).map(n => n.id))
})

function handleExpandMerged() {
  const remaining = (rawGraphNodes.value.length - MERGE_THRESHOLD) - (expandBatchCount.value * BATCH_EXPAND_SIZE)
  if (remaining > BATCH_EXPAND_SIZE) {
    expandBatchCount.value++
  } else if (remaining > 0) {
    expandBatchCount.value++
  } else {
    expandBatchCount.value++
  }
}

/* ---- cross edges (uses drillLevel) ---- */
const crossEdges = computed(() => {
  if (isExternalTab.value && !drillMeta.value.drillCommId) return externalCrossEdges.value

  const parentComm = drillMeta.value.drillCommId
    ? commMap.value.get(drillMeta.value.drillCommId)
    : null
  const et = parentComm?.edgeType || effectiveEdgeType.value
  const lv = drillMeta.value.drillLevel
  const raw = communityStore.tasks[props.taskId]?.crossCommunityEdges?.[et]?.[lv] || []
  const internalEdges = raw.map(e => ({ source: e.sourceCommId, target: e.targetCommId, count: e.edgeCount }))

  if (!isExternalTab.value) return internalEdges
  if (!drillMeta.value.drillCommId) return internalEdges

  const nodeListMap = communityStore.tasks[props.taskId]?.nodeLists?.[et]?.[lv]
  const firstCommEntry = drillPath.value.find(n => n.kind === 'community')

  if (nodeListMap) {
    const rootL0Id = firstCommEntry?.commId
    const childCommIds = new Set(
      allCommunities.value.filter(c => c.parentId === drillMeta.value.drillCommId).map(c => c.communityId)
    )
    const fileToComm = new Map<string, string>()
    for (const [commId, files] of Object.entries(nodeListMap)) {
      if (!childCommIds.has(commId)) continue
      for (const f of files) {
        if (!fileToComm.has(f)) fileToComm.set(f, commId)
      }
    }
    const remappedEdges: { source: string; target: string }[] = []
    for (const item of externalItems.value) {
      const extId = item.package || item.name || ''
      if (!extId) continue
      if (!rootL0Id || !(item.communities || []).some(c => c.communityId === rootL0Id)) continue
      const matchedIds = new Set<string>()
      for (const f of (item.files || [])) {
        const cId = fileToComm.get(f)
        if (cId) matchedIds.add(cId)
      }
      for (const cId of matchedIds) {
        remappedEdges.push({ source: extId, target: cId })
      }
    }
    return [...internalEdges, ...remappedEdges]
  }

  const childIds = new Set<string>()
  for (const e of internalEdges) {
    childIds.add(e.source)
    childIds.add(e.target)
  }
  const rootL0IdFallback = firstCommEntry?.commId
  if (rootL0IdFallback) childIds.add(rootL0IdFallback)
  const relevantExternal = externalCrossEdges.value.filter(e =>
    childIds.has(e.source) || childIds.has(e.target)
  )
  return [...internalEdges, ...relevantExternal]
})

/* ---- node degree maps ---- */
const nodeDegrees = computed(() => {
  const map = new Map<string, { in: number; out: number }>()
  const get = (id: string) => {
    if (!map.has(id)) map.set(id, { in: 0, out: 0 })
    return map.get(id)!
  }
  for (const edge of crossEdges.value) {
    const weight = (edge as any).count || 1
    get(edge.source).out += weight
    get(edge.target).in += weight
  }
  return map
})

/* ---- heatmap items ---- */
const internalHeatmapItems = computed(() => {
  const raw = crossEdges.value
  if (raw.length === 0) {
    // eslint-disable-next-line no-console
    console.log('[heatmap] crossEdges empty for level:', drillMeta.value.drillLevel, 'edgeType:', props.edgeType)
    return []
  }
  const pkgMap = new Map<string, { package: string; name: string; fileCount: number; files: string[]; communities: Array<{ communityId: string; name?: string }> }>()
  for (const e of raw) {
    const key = e.source
    if (!pkgMap.has(key)) {
      pkgMap.set(key, { package: key, name: communityIdLabel(key), fileCount: 0, files: [], communities: [] })
    }
    const item = pkgMap.get(key)!
    item.fileCount += e.count || 1
    const tgtComm = commMap.value.get(e.target)
    item.communities.push({ communityId: e.target, name: tgtComm?.name || communityIdLabel(e.target) })
  }
  const result = Array.from(pkgMap.values())
  // eslint-disable-next-line no-console
  console.log('[heatmap] items built:', result.length, 'sources, level:', drillMeta.value.drillLevel, 'rawEdges:', raw.length)
  return result
})

/* ---- external drill heatmap items (external-package × child-community) ---- */
const drillHeatmapItems = computed(() => {
  if (!isExternalTab.value || !drillMeta.value.drillCommId) return []
  const raw = crossEdges.value
  if (raw.length === 0) return []
  const commIds = new Set(allCommunities.value.map(c => c.communityId))
  const extEdges = raw.filter(e => !commIds.has(e.source))
  if (extEdges.length === 0) return []
  const pkgMap = new Map<string, { package: string; name: string; fileCount: number; files: string[]; communities: Array<{ communityId: string; name?: string }> }>()
  for (const e of extEdges) {
    const key = e.source
    if (!pkgMap.has(key)) {
      pkgMap.set(key, { package: key, name: key, fileCount: 0, files: [], communities: [] })
    }
    const item = pkgMap.get(key)!
    item.fileCount += e.count || 1
    const tgtComm = commMap.value.get(e.target)
    item.communities.push({ communityId: e.target, name: tgtComm?.name || communityIdLabel(e.target) })
  }
  return Array.from(pkgMap.values())
})

/* ---- table communities (drill-filtered) ---- */
const drillTableCommunities = computed(() => {
  const commId = drillMeta.value.drillCommId
  if (!commId) {
    return allCommunities.value.filter(c => c.level === 'L0' && c.edgeType === props.edgeType)
  }
  return allCommunities.value.filter(c => c.parentId === commId && c.edgeType === props.edgeType)
})

/* ---- unified drill actions ---- */
async function handleDrill(targetId: string) {
  if (drilling.value) return
  if (targetId === '__merged__') {
    handleExpandMerged()
    return
  }
  expandBatchCount.value = 0
  graphSearch.value = ''

  const com = commMap.value.get(targetId)
  if (com) {
    if (drillMeta.value.drillCommId === targetId) return
    drilling.value = true
    try {
      const nextLevel = `L${parseInt(com.level?.[1] || '0') + 1}`
      await communityStore.loadCrossCommunityEdges(props.taskId, com.edgeType, nextLevel)
      await communityStore.loadCommunityNodeLists(props.taskId, com.edgeType, nextLevel)
      const label = com.name && com.name !== com.communityId ? com.name : communityIdLabel(com.communityId)
      drillPath.value.push({
        key: `comm-${targetId}`,
        label: label.length > 24 ? label.slice(0, 24) + '\u2026' : label,
        kind: 'community',
        commId: targetId,
        commLevel: nextLevel,
      })
    } finally {
      drilling.value = false
    }
    return
  }

  if (isExternalTab.value) {
    if (drillMeta.value.drillExtItemId === targetId) return
    const item = externalItems.value.find((i: any) => (i.package || i.name) === targetId)
    if (!item) return
    drillPath.value.push({
      key: `ext-${targetId}`,
      label: targetId.length > 24 ? targetId.slice(0, 24) + '\u2026' : targetId,
      kind: 'external',
      extItemId: targetId,
    })
    return
  }
}

function handleRollUp() {
  if (drillPath.value.length <= 1) return
  drillPath.value.pop()
  expandBatchCount.value = 0
  graphSearch.value = ''
}

function handleBreadcrumbClick(index: number) {
  if (index >= drillPath.value.length - 1) return
  drillPath.value = drillPath.value.slice(0, index + 1)
  expandBatchCount.value = 0
  graphSearch.value = ''
}

function handleResetView() {
  hiddenNodeIds.value = new Set()
  saveHiddenIds()
  resetTrigger.value++
}

function handleNodeContextMenu(nodeId: string) {
  if (nodeId === '__merged__') return
  const com = commMap.value.get(nodeId)
  if (com && com.summary) {
    emit('open-md', {
      taskId: props.taskId,
      content: `## ${com.name || com.communityId}\n\n${com.summary || ''}`,
      title: com.name || com.communityId,
      parentCommId: com.communityId,
      parentLevel: com.level || 'L0',
      parentEdgeType: com.edgeType,
      regenerationType: 'community',
    })
  }
}

function handleToggleFilter(event?: { clientX: number; clientY: number }) {
  if (event) {
    filterClickX.value = event.clientX
    filterClickY.value = event.clientY
  }
  showFilter.value = !showFilter.value
}

function handleExportArch() {
  const win = window.open('', '_blank')
  if (!win) return
  const commCount = allCommunities.value.filter(c => c.level === 'L0' && c.edgeType === props.edgeType).length
  win.document.write(`<html><body style="font-family:sans-serif;padding:2rem"><h2>架构导出 — ${props.taskId}</h2><p>社区数: ${commCount}</p><p>导出功能完整版将通过 reports 插件 HTTP 服务实现。</p></body></html>`)
}

function handleConnectComplete() {
  if (hiddenNodeIds.value.size === 0) return
  const visibleSet = new Set(graphNodes.value.filter(n => !hiddenNodeIds.value.has(n.id)).map(n => n.id))
  const connectedIds = new Set<string>()
  for (const e of crossEdges.value) {
    if (visibleSet.has(e.source) && hiddenNodeIds.value.has(e.target)) connectedIds.add(e.target)
    if (visibleSet.has(e.target) && hiddenNodeIds.value.has(e.source)) connectedIds.add(e.source)
  }
  if (connectedIds.size === 0) return
  const next = new Set(hiddenNodeIds.value)
  connectedIds.forEach(id => next.delete(id))
  updateHiddenIds(next)
}

/* ---- reset drill state on edgeType / tab switch ---- */
watch(() => props.edgeType, () => {
  drillPath.value = [rootDrillNode()]
  expandBatchCount.value = 0
  graphSearch.value = ''
})

/* ---- cross-edges loading ---- */
watch(() => [props.edgeType, drillMeta.value.drillLevel], async ([_et, lv]) => {
  if (!isExternalTab.value || drillMeta.value.drillCommId) {
    const parentComm = drillMeta.value.drillCommId
      ? commMap.value.get(drillMeta.value.drillCommId)
      : null
    const et = parentComm?.edgeType || effectiveEdgeType.value
    await communityStore.loadCrossCommunityEdges(props.taskId, et, lv as string)
  }
})

onMounted(async () => {
  if (!isExternalTab.value) {
    await communityStore.loadCrossCommunityEdges(props.taskId, effectiveEdgeType.value, drillMeta.value.drillLevel)
  }
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})

watch(isFullscreen, () => {
  recenterTrigger.value++
})
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div
    class="cgv-container"
    :class="{ 'cgv-fullscreen': isFullscreen }"
  >
    <div
      v-show="!isFullscreen"
      class="cgv-topbar"
    >
      <GraphBreadcrumb
        :path="drillMeta.breadcrumbSegments"
        @click="handleBreadcrumbClick"
        @roll-up="handleRollUp"
      />
      <button
        class="cgv-compare-btn"
        :class="{ active: compareActive }"
        :title="compareActive ? t('report.exitCompare', '退出对比') : t('report.compareArch', '对比架构')"
        @click="toggleCompare"
      >📊</button>
      <select
        v-if="compareActive && compareSnapshotIds.length > 1"
        class="cgv-compare-select"
        :value="compareFrom"
        @change="setCompareVersion(($event.target as HTMLSelectElement).value, compareTo)"
      >
        <option
          v-for="s in compareSnapshotIds"
          :key="s.id"
          :value="s.id"
        >{{ s.id }}</option>
      </select>
      <span v-if="compareActive && compareSnapshotIds.length > 1" class="cgv-compare-vs">vs</span>
      <select
        v-if="compareActive && compareSnapshotIds.length > 1"
        class="cgv-compare-select"
        :value="compareTo"
        @change="setCompareVersion(compareFrom, ($event.target as HTMLSelectElement).value)"
      >
        <option
          v-for="s in compareSnapshotIds"
          :key="s.id"
          :value="s.id"
        >{{ s.id }}</option>
      </select>
      <div class="cgv-search">
        <input
          v-model="graphSearch"
          type="text"
          :placeholder="t('report.searchCommunity', '搜索...')"
          class="cgv-search-input"
        >
      </div>
      <GraphToolbar
        v-model:style="graphStyle"
        v-model:external-view-mode="externalViewMode"
        v-model:internal-view-mode="internalViewMode"
        :can-roll-up="drillPath.length > 1"
        :external-mode="isExternalTab"
        :filter-active="hiddenNodeIds.size > 0"
        @roll-up="handleRollUp"
        @fullscreen="enterFullscreen"
        @reset-view="handleResetView"
        @toggle-filter="handleToggleFilter"
        @export-arch="handleExportArch"
      />
    </div>
    <div v-if="compareActive" class="cgv-compare-legend">
      <span class="legend-item"><span class="legend-dot added"></span>新增</span>
      <span class="legend-item"><span class="legend-dot removed"></span>删除</span>
      <span class="legend-item"><span class="legend-dot changed"></span>变更</span>
      <span class="legend-item"><span class="legend-dot unchanged"></span>无变化</span>
    </div>

    <!-- 下钻/上卷 加载遮罩 -->
    <div v-if="drilling" class="cgv-drill-overlay">
      <div class="cgv-drill-spinner" />
      <span class="cgv-drill-text">加载中...</span>
    </div>

    <!-- 力导向图控制条 -->
    <div
      v-if="(isExternalTab && externalViewMode === 'force') || externalViewMode === 'force' || internalViewMode === 'force'"
      class="cgv-force-bar"
    >
      <label class="cgv-force-label">
        <input type="range" :min="5000" :max="30000" :step="500" :value="forceRepulsion" @input="forceRepulsion = Number(($event.target as HTMLInputElement).value)" class="cgv-force-slider"/>
        <span class="cgv-force-val">斥力: {{ forceRepulsion }}</span>
      </label>
      <button class="cgv-force-btn" :class="{ active: forceLockMode === 'locked' }" @click="forceLockMode = forceLockMode === 'locked' ? 'linked' : 'locked'">
        {{ forceLockMode === 'locked' ? '🔒 锁定' : '🔗 联动' }}
      </button>
    </div>

    <template v-if="isExternalTab">
      <GraphCanvas
        v-if="externalViewMode === 'force'"
        :key="'ext-force-' + props.edgeType + '-' + drillMeta.drillKey"
        :nodes="graphNodes"
        :edges="crossEdges"
        :style="'d3force'"
        :highlighted-ids="highlightedNodeIds"
        :hidden-ids="hiddenNodeIds"
        :reset-trigger="resetTrigger"
        :lock-mode="forceLockMode"
        :repulsion="forceRepulsion"
        :recenter-trigger="recenterTrigger"
        @node-dblclick="(id: string) => handleDrill(id)"
        @node-context-menu="(id: string) => handleNodeContextMenu(id)"
        @node-drag-end="(id: string, x: number, y: number) => setNodePosition(props.edgeType, drillMeta.drillKey, id, { x, y })"
      />
      <ExternalTableView
        v-else-if="externalViewMode === 'table'"
        :items="externalItems"
        :edge-type="props.edgeType"
        @drill="handleDrill"
      />
      <ExternalHeatmapView
        v-else
        :key="'ext-heat-' + drillMeta.drillKey"
        :items="drillMeta.drillCommId ? drillHeatmapItems : externalItems"
        :all-communities="allCommunities"
        @drill="handleDrill"
      />
    </template>
    <template v-else>
      <GraphCanvas
        v-if="internalViewMode === 'force' || internalViewMode === 'dagre'"
        :key="drillMeta.drillKey + '-' + props.edgeType + '-' + internalViewMode"
        :nodes="graphNodes"
        :edges="crossEdges"
        :style="internalViewMode === 'dagre' ? 'dagre' : 'd3force'"
        :highlighted-ids="highlightedNodeIds"
        :hidden-ids="hiddenNodeIds"
        :reset-trigger="resetTrigger"
        :lock-mode="forceLockMode"
        :repulsion="forceRepulsion"
        :recenter-trigger="recenterTrigger"
        @node-dblclick="(id: string) => handleDrill(id)"
        @node-context-menu="(id: string) => handleNodeContextMenu(id)"
        @node-drag-end="(id: string, x: number, y: number) => setNodePosition(props.edgeType, drillMeta.drillKey, id, { x, y })"
      />
      <CommunityTableView
        v-else-if="internalViewMode === 'table'"
        :communities="drillTableCommunities"
        :edge-type="props.edgeType"
        @drill="handleDrill"
        @open-community="(item) => handleNodeContextMenu(item.communityId)"
      />
      <ExternalHeatmapView
        v-else
        :key="'internal-heat-' + drillMeta.drillKey"
        :items="internalHeatmapItems"
        :all-communities="allCommunities"
        @drill="handleDrill"
      />
    </template>

    <div
      v-if="isFullscreen"
      class="cgv-fullscreen-bar"
    >
      <div class="fs-left">
        <GraphBreadcrumb
          :path="drillMeta.breadcrumbSegments"
          @click="handleBreadcrumbClick"
          @roll-up="handleRollUp"
        />
        <button
          class="cgv-compare-btn"
          :class="{ active: compareActive }"
          :title="compareActive ? t('report.exitCompare', '退出对比') : t('report.compareArch', '对比架构')"
          @click="toggleCompare"
        >📊</button>
        <div class="cgv-search">
          <input
            v-model="graphSearch"
            type="text"
            :placeholder="t('report.searchCommunity', '搜索...')"
            class="cgv-search-input"
          >
        </div>
        <GraphToolbar
          v-model:style="graphStyle"
          v-model:external-view-mode="externalViewMode"
          v-model:internal-view-mode="internalViewMode"
          :can-roll-up="drillPath.length > 1"
          :external-mode="isExternalTab"
          :filter-active="hiddenNodeIds.size > 0"
          @roll-up="handleRollUp"
          @fullscreen="exitFullscreen"
          @reset-view="handleResetView"
          @toggle-filter="handleToggleFilter"
          @export-arch="handleExportArch"
        />
      </div>
      <div class="fs-actions">
        <button
          class="fs-btn"
          @click="exitFullscreen"
        >
          {{ t('report.exitFullscreen', '退出全屏') }}
        </button>
      </div>
    </div>

    <NodeFilterPanel
      :nodes="filterNodes"
      :hidden-ids="hiddenNodeIds"
      :visible="showFilter"
      :click-x="filterClickX"
      :click-y="filterClickY"
      @update:hidden-ids="updateHiddenIds"
      @connect-complete="handleConnectComplete"
      @close="showFilter = false"
    />
  </div>
</template>

<style scoped>
.cgv-container { display: flex; flex-direction: column; flex: 1; min-height: 320px; border: 1px solid var(--border); border-radius: 0.5rem; overflow: hidden; background: var(--bg-primary); position: relative; }
.cgv-topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.35rem 0.75rem; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border); flex-shrink: 0; gap: 0.5rem;
}
.cgv-search { display: flex; flex: 1; max-width: 200px; }
.cgv-search-input {
  width: 100%; padding: 0.15rem 0.4rem; font-size: 0.7rem;
  background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: 0.25rem; color: var(--text-primary);
}
.cgv-search-input:focus { outline: none; border-color: var(--accent); }
.cgv-compare-btn {
  display: flex; align-items: center; justify-content: center;
  width: 26px; height: 24px; padding: 0;
  background: transparent; border: 1px solid var(--border);
  border-radius: 0.25rem; cursor: pointer; font-size: 0.75rem;
  color: var(--text-muted); transition: all 0.15s;
}
.cgv-compare-btn:hover { border-color: var(--accent); color: var(--text-primary); }
.cgv-compare-btn.active { background: var(--bg-accent-subtle, #2d1f5e); border-color: var(--accent); color: var(--accent); }
.cgv-compare-select {
  padding: 0.1rem 0.3rem; font-size: 0.65rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.2rem; color: var(--text-muted); outline: none;
}
.cgv-compare-select:focus { border-color: var(--accent); }
.cgv-compare-vs { font-size: 0.65rem; color: var(--text-muted); }
.cgv-compare-legend {
  display: flex; align-items: center; gap: 1rem; padding: 0.2rem 0.75rem;
  background: var(--bg-secondary); border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.legend-item { display: flex; align-items: center; gap: 0.25rem; font-size: 0.65rem; color: var(--text-muted); }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; }
.legend-dot.added { background: #22c55e; }
.legend-dot.removed { background: #ef4444; }
.legend-dot.changed { background: #f97316; }
.legend-dot.unchanged { background: #6b7280; }
.cgv-fullscreen {
  position: fixed; inset: 0; z-index: 200;
  height: 100vh; border-radius: 0; border: none;
}
.cgv-fullscreen-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.35rem 0.75rem; background: var(--bg-secondary);
  border-top: 1px solid var(--border); flex-shrink: 0;
  position: absolute; bottom: 0; left: 0; right: 0; z-index: 201;
}
.fs-left { display: flex; align-items: center; gap: 0.75rem; flex: 1; overflow: hidden; }
.fs-title { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); flex-shrink: 0; }
.fs-actions { display: flex; gap: 0.5rem; flex-shrink: 0; }
.fs-btn {
  padding: 0.2rem 0.6rem; font-size: 0.75rem; color: var(--text-muted);
  background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: 0.25rem; cursor: pointer; transition: all 0.15s;
}
.fs-btn:hover { color: var(--text-primary); border-color: var(--accent, #7c3aed); }

/* ── 下钻/上卷 加载遮罩 ── */
.cgv-drill-overlay {
  position: absolute; inset: 0; z-index: 10;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.75rem;
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(2px);
}
.cgv-drill-spinner {
  width: 32px; height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: var(--accent, #7c3aed);
  border-radius: 50%;
  animation: cgv-spin 0.7s linear infinite;
}
@keyframes cgv-spin { to { transform: rotate(360deg); } }
.cgv-drill-text {
  font-size: 0.75rem; color: rgba(255, 255, 255, 0.85);
  letter-spacing: 0.04em;
}

/* ── 文件层底部工具栏 ── */
.cgv-bottom-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.35rem 0.75rem; background: var(--bg-secondary);
  border-top: 1px solid var(--border); flex-shrink: 0;
}
.fs-btn-active { background: var(--accent, #7c3aed); color: #fff; border-color: var(--accent); }
.cgv-empty { font-size: 0.8rem; color: var(--text-muted); text-align: center; padding: 2rem; flex: 1; }

/* ── 力导向图控制条 ── */
.cgv-force-bar {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.25rem 0.75rem; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.cgv-force-label {
  display: flex; align-items: center; gap: 0.4rem; flex: 1;
}
.cgv-force-slider {
  width: 140px; height: 4px; cursor: pointer; accent-color: var(--accent, #7c3aed);
}
.cgv-force-val {
  font-size: 0.65rem; color: var(--text-muted); white-space: nowrap; min-width: 80px;
}
.cgv-force-btn {
  padding: 0.15rem 0.5rem; font-size: 0.65rem;
  background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: 0.2rem; color: var(--text-muted); cursor: pointer;
  white-space: nowrap; transition: all 0.1s;
}
.cgv-force-btn:hover { border-color: var(--accent); color: var(--text-primary); }
.cgv-force-btn.active { background: var(--bg-accent-subtle, #2d1f5e); border-color: var(--accent); color: var(--accent); }
</style>
