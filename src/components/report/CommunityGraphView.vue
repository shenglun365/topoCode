<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'
import { usePanelStore } from '@/stores/panel'
import { useGraphCommandStore } from '@/stores/graph-command-store'
import type { GraphCommand, CommandResult, GraphState } from '@/types/graph-commands'
import { useComponentId } from '@/composables/useComponentId'
import { useGraphFullscreen } from '@/composables/useGraphFullscreen'
import { useGraphPosition } from '@/composables/useGraphPosition'
import { communityLabel, communityIdLabel } from '@/utils/communityLabel'
import { ipc } from '@/services/ipc'
import { LinkSlashIcon, LockClosedIcon, Cog6ToothIcon, FunnelIcon, ArrowsPointingOutIcon, ArrowsPointingInIcon, ArrowDownTrayIcon } from '@heroicons/vue/24/outline'
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
const panelStore = usePanelStore()
const cmdStore = useGraphCommandStore()

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
const { getNodePosition, setNodePosition, positions: localPositions } = useGraphPosition(
  props.projectId, props.taskId, props.taskUpdatedAt
)

/* ---- view mode state ---- */

const fontSize = ref(10)
const zoomLevel = ref(1)
const graphCanvasRef = ref<InstanceType<typeof GraphCanvas> | null>(null)

const externalViewMode = ref<'force' | 'table' | 'heatmap'>('force')
const internalViewMode = ref<'force' | 'table' | 'heatmap'>('force')
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
const compareTimeline = ref<any[]>([])
const compareNodeStates = ref<Map<string, 'added' | 'removed' | 'changed' | 'unchanged'>>(new Map())

async function toggleCompare() {
  if (compareActive.value) {
    compareActive.value = false
    compareNodeStates.value = new Map()
    return
  }
  try {
    const list = await ipc.analysis.listTimeline({ projectId: props.projectId })
    const taskEntries = list.filter((e: any) => e.taskId === props.taskId)
    compareTimeline.value = taskEntries
    if (taskEntries.length < 2) {
      compareActive.value = false
      return
    }
    const prev = taskEntries[taskEntries.length - 2]
    const curr = taskEntries[taskEntries.length - 1]
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
    const [prevRes, currRes] = await Promise.all([
      ipc.analysis.getTimelineEntry({ timelineId: fromId }),
      ipc.analysis.getTimelineEntry({ timelineId: toId }),
    ])
    const prevComms = prevRes.communities || []
    const currComms = currRes.communities || []
    const prevIds = new Set(prevComms.map((c: any) => c.communityId))
    const currIds = new Set(currComms.map((c: any) => c.communityId))
    const states = new Map<string, 'added' | 'removed' | 'changed' | 'unchanged'>()
    for (const c of currComms) {
      const cid = c.communityId
      if (!prevIds.has(cid)) states.set(cid, 'added')
      else {
        const prevC = prevComms.find((p: any) => p.communityId === cid)
        const changed = prevC && (prevC.nodeCount !== c.nodeCount || Math.abs((prevC.qualityScore || 0) - (c.qualityScore || 0)) > 0.01)
        states.set(cid, changed ? 'changed' : 'unchanged')
      }
    }
    for (const c of prevComms) {
      if (!currIds.has(c.communityId)) states.set(c.communityId, 'removed')
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
const forceRepulsionSlider = ref(50)
const forceRepulsion = computed(() =>
  Math.round(Math.exp(forceRepulsionSlider.value / 28) * 1500)
)

/* ---- saved positions (DB) ---- */
const savedPositions = ref<Record<string, { x: number; y: number }>>({})
const dragGeneration = ref(0)
const savedGeneration = ref(0)
const hasUnsavedChanges = computed(() => dragGeneration.value > savedGeneration.value)

/* ---- 位置复原弹窗 ---- */
const showPositionReset = ref(false)
const showClearConfirm = ref(false)
const positionKeys = ref<Array<{ taskId: string; edgeType: string; drillKey: string; layoutType: string; count: number }>>([])
const selectedKeys = ref<Set<string>>(new Set())
const resetLoading = ref(false)

/* ---- gear panel ---- */
const gearOpen = ref(false)
const gearPanelRect = ref<{ top: string; right: string; bottom?: string }>({ top: '0px', right: '0px' })

function toggleGear(e: MouseEvent) {
  gearOpen.value = !gearOpen.value
  if (!gearOpen.value) return
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  if (isFullscreen.value) {
    gearPanelRect.value = {
      top: '',
      bottom: `${window.innerHeight - rect.top + 4}px`,
      right: `${window.innerWidth - rect.right}px`,
    }
  } else {
    gearPanelRect.value = {
      top: `${rect.bottom + 4}px`,
      bottom: '',
      right: `${window.innerWidth - rect.right}px`,
    }
  }
}

async function handleClearAllPositions() {
  try {
    await ipc.graph.clearPositions({
      taskId: props.taskId,
      edgeType: props.edgeType,
      drillKey: drillMeta.value.drillKey,
      layoutType: 'force',
    })
    console.log('[CGV] cleared all positions for', props.edgeType, drillMeta.value.drillKey)
  } catch (e) {
    console.warn('[CGV] clearAllPositions failed:', e)
  }
}

function keyId(k: { taskId: string; edgeType: string; drillKey: string; layoutType: string }) {
  return `${k.taskId}|${k.edgeType}|${k.drillKey}|${k.layoutType}`
}

async function loadPositionKeys() {
  try {
    const result = await ipc.graph.listSavedPositionKeys({ projectId: props.projectId })
    positionKeys.value = (result as any)?.keys || []
  } catch {
    positionKeys.value = []
  }
}

function toggleKey(k: { taskId: string; edgeType: string; drillKey: string; layoutType: string }) {
  const id = keyId(k)
  const next = new Set(selectedKeys.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedKeys.value = next
}

function toggleAllKeys() {
  if (selectedKeys.value.size === positionKeys.value.length) {
    selectedKeys.value = new Set()
  } else {
    selectedKeys.value = new Set(positionKeys.value.map(k => keyId(k)))
  }
}

async function handleClearSelectedPositions() {
  if (selectedKeys.value.size === 0) return
  showClearConfirm.value = true
}

async function executeClearPositions() {
  showClearConfirm.value = false
  resetLoading.value = true
  let deleted = 0
  for (const k of positionKeys.value) {
    if (selectedKeys.value.has(keyId(k))) {
      try {
        console.log('[CGV] clearing position key:', k.taskId, k.edgeType, k.drillKey, k.layoutType)
        await ipc.graph.clearPositions({
          taskId: k.taskId,
          edgeType: k.edgeType,
          drillKey: k.drillKey,
          layoutType: k.layoutType,
        })
        deleted++
      } catch (e) {
        console.error('[CGV] clearPositions failed for', k, e)
      }
    }
  }
  resetLoading.value = false
  positionKeys.value = positionKeys.value.filter(k => !selectedKeys.value.has(keyId(k)))
  selectedKeys.value = new Set()
  console.log('[CGV] cleared', deleted, 'position keys')
  if (deleted > 0) {
    setTimeout(() => { showPositionReset.value = false }, 1000)
  }
}

async function openPositionReset() {
  selectedKeys.value = new Set()
  resetLoading.value = false
  await loadPositionKeys()
  showPositionReset.value = true
}

const edgeTypeLabel: Record<string, string> = {
  INCLUDE: 'INCLUDE', CALL: 'CALL', EXTERNAL_INCLUDE: 'EXTERNAL_INCLUDE', EXTERNAL_CALL: 'EXTERNAL_CALL',
}

function drillKeyLabel(k: { taskId: string; drillKey: string }): string {
  if (k.drillKey === 'L0') return `L0 (全部社区) — ${k.taskId.slice(0, 8)}`
  if (k.drillKey.startsWith('comm-')) {
    const commId = k.drillKey.slice(5)
    const com = commMap.value?.get(commId)
    if (com?.name && com.name !== com.communityId) {
      return `${com.name} (${commId.slice(0, 28)})`
    }
    return commId.length > 36 ? commId.slice(0, 36) + '\u2026' : commId
  }
  return k.drillKey
}

async function loadDBPositions() {
  const layoutType = 'force'
  try {
    const result = await ipc.graph.loadPositions({
      taskId: props.taskId,
      edgeType: props.edgeType,
      drillKey: drillMeta.value.drillKey,
      layoutType,
    })
    savedPositions.value = result.positions || {}
    dragGeneration.value = 0
    savedGeneration.value = 0
    const keys = Object.keys(savedPositions.value)
    console.log('[CGV] loadDBPositions loaded layoutType=', layoutType, 'edgeType=', props.edgeType, 'drillKey=', drillMeta.value.drillKey, 'count=', keys.length, 'sample=', keys.slice(0, 3), 'dragGen/savedGen reset')
  } catch (_) {
    savedPositions.value = {}
    dragGeneration.value = 0
    savedGeneration.value = 0
    console.log('[CGV] loadDBPositions failed, reset')
  }
}

async function handleSavePositions() {
  const layoutType = 'force'
  console.log('[CGV] handleSavePositions start internalViewMode=', internalViewMode.value, 'isExternal=', isExternalTab.value, 'dragGen=', dragGeneration.value, 'savedGen=', savedGeneration.value)
  const allPos = graphCanvasRef.value?.getAllPositions?.()
  const positions: Array<{ nodeId: string; x: number; y: number }> = []
  if (allPos) {
    for (const [nodeId, pos] of Object.entries(allPos)) {
      if (pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
        positions.push({ nodeId, x: pos.x, y: pos.y })
      }
    }
  }
  const viewPositions = localPositions.value?.[props.edgeType]?.[drillMeta.value.drillKey] || {}
  for (const [nodeId, pos] of Object.entries(viewPositions)) {
    if (pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
      if (!positions.find(p => p.nodeId === nodeId)) {
        positions.push({ nodeId, x: pos.x, y: pos.y })
      }
    }
  }
  console.log('[CGV] handleSavePositions merged', positions.length, 'positions from cytoscape:', allPos ? Object.keys(allPos).length : 0, 'localStorage:', Object.keys(viewPositions).length)
  if (positions.length === 0) return
  try {
    const result = await ipc.graph.savePositions({
      taskId: props.taskId,
      edgeType: props.edgeType,
      drillKey: drillMeta.value.drillKey,
      layoutType,
      positions,
    })
    const saved: Record<string, { x: number; y: number }> = {}
    for (const p of positions) saved[p.nodeId] = { x: p.x, y: p.y }
    savedPositions.value = saved
    savedGeneration.value = dragGeneration.value
    console.log('[CGV] handleSavePositions done edgeType=', props.edgeType, 'drillKey=', drillMeta.value.drillKey, 'layoutType=', layoutType, 'count=', result.saved, 'savedGen=', savedGeneration.value, 'sample=', positions.slice(0, 3))
  } catch (err) {
    console.warn('[CGV] handleSavePositions failed:', err)
  }
}

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
        result.push({ id: n.id, label: n.label, nodeCount: n.nodeCount, type: n.isExternal ? 'external' as const : 'community' as const, qualityScore: n.qualityScore ?? null, avgCoreness: (n as any).avgCoreness ?? null, maxCoreness: (n as any).maxCoreness ?? null, inDegree: d?.in ?? 0, outDegree: d?.out ?? 0 })
      }
    }
    for (const n of externalCommunityNodes.value) {
      if (!seen.has(n.id)) {
        seen.add(n.id)
        const d = deg.get(n.id)
        result.push({ id: n.id, label: n.label, nodeCount: n.nodeCount, type: 'community' as const, qualityScore: null, avgCoreness: null, maxCoreness: null, inDegree: d?.in ?? 0, outDegree: d?.out ?? 0 })
      }
    }
    return result
  }
  return rawGraphNodes.value
    .filter(n => !n.isMerged)
    .map(n => ({ id: n.id, label: n.label, nodeCount: n.nodeCount, type: n.isExternal ? 'external' as const : 'community' as const, qualityScore: n.qualityScore ?? null, avgCoreness: (n as any).avgCoreness ?? null, maxCoreness: (n as any).maxCoreness ?? null, inDegree: deg.get(n.id)?.in ?? 0, outDegree: deg.get(n.id)?.out ?? 0 }))
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
    avgCoreness: c.avgCoreness,
    maxCoreness: c.maxCoreness,
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
      cmdStore.pushEvent('drill-event', { communityId: targetId, communityName: label })
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
  zoomLevel.value = 1
  resetTrigger.value++
}

function handleGuideClick() {
  if (panelStore.rightCollapsed) {
    panelStore.toggleRight()
  }
  panelStore.setRightTab('ai')
  cmdStore.pushEvent('guide-start', {})
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

function handleToggleFilter(event?: MouseEvent) {
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

/* ========================================================
   GraphCommandBus integration — AI 助手命令执行 + 图状态同步
   ======================================================== */

function syncGraphState() {
  const vsMode = isExternalTab.value ? externalViewMode.value : internalViewMode.value
  const allNodes = graphNodes.value
  const visible = allNodes.filter(n => !hiddenNodeIds.value.has(n.id))
  const visibleIds = visible.map(n => n.id)

  const l0s = allCommunities.value.filter(c => c.level === 'L0' && c.edgeType === effectiveEdgeType.value)
  const totalL0 = l0s.length
  const qualities = l0s.map(c => c.qualityScore ?? 0).filter(q => q > 0)
  const avgQ = qualities.length > 0 ? qualities.reduce((s, v) => s + v, 0) / qualities.length : 0
  const lowQC = l0s.filter(c => (c.qualityScore ?? 0) > 0 && (c.qualityScore ?? 0) < 0.3)
  const highCC = l0s.filter(c => (c.avgCoreness ?? 0) >= 3)

  const tops = [...l0s].sort((a, b) => (b.nodeCount || 0) - (a.nodeCount || 0)).slice(0, 5).map(c => ({
    id: c.communityId, name: c.name || c.communityId,
    nodeCount: c.nodeCount || 0, qualityScore: c.qualityScore ?? undefined, avgCoreness: c.avgCoreness ?? undefined,
  }))

  const lows = lowQC.slice(0, 10).map(c => ({
    id: c.communityId, name: c.name || c.communityId, qualityScore: c.qualityScore ?? 0,
  }))

  const patch: Partial<GraphState> = {
    edgeType: props.edgeType,
    viewMode: vsMode,
    drillLevel: drillMeta.value.drillLevel,
    drillCommId: drillMeta.value.drillCommId,
    selectedCommunityId: drillMeta.value.drillCommId,
    nodeCount: allNodes.length,
    visibleNodeIds: visibleIds,
    stats: { totalL0, avgQuality: Math.round(avgQ * 100) / 100, lowQualityCount: lowQC.length,
      highCorenessCount: highCC.length, maxDepth: 0, topCommunities: tops, lowQualityCommunities: lows },
  }
  cmdStore.updateGraphState(patch)
}

/** AI → 图的命令路由：将 GraphCommand 映射到现有 CGV 方法 */
async function executeGraphCommand(cmd: GraphCommand): Promise<CommandResult> {
  try {
    switch (cmd.type) {
      case 'highlight': {
        const ids = new Set(cmd.nodeIds)
        hiddenNodeIds.value = new Set(
          graphNodes.value.filter(n => !ids.has(n.id)).map(n => n.id)
        )
        return { success: true }
      }
      case 'clearHighlight':
        hiddenNodeIds.value = new Set()
        return { success: true }
      case 'focus': {
        graphCanvasRef.value?.zoomTo?.(cmd.nodeId, cmd.animate)
        return { success: true }
      }
      case 'drill':
        await drillPath.value.length > 1 ? handleRollUp() : null
        await handleDrill(cmd.communityId)
        return { success: true }
      case 'rollUp':
        handleRollUp()
        return { success: true }
      case 'filterByQuality':
      case 'filterByCoreness':
      case 'filterBySize': {
        const all = graphNodes.value
        const next = new Set<string>()
        for (const n of all) {
          const q = (n as any).qualityScore
          const c = (n as any).avgCoreness
          const s = n.nodeCount || 0
          let show = true
          if (cmd.type === 'filterByQuality') {
            if (cmd.min != null && (q ?? 0) < cmd.min) show = false
            if (cmd.max != null && (q ?? 0) > cmd.max) show = false
          } else if (cmd.type === 'filterByCoreness') {
            if (cmd.min != null && (c ?? 0) < cmd.min) show = false
          } else if (cmd.type === 'filterBySize') {
            if (cmd.min != null && s < cmd.min) show = false
            if (cmd.max != null && s > cmd.max) show = false
          }
          if (!show) next.add(n.id)
        }
        hiddenNodeIds.value = next
        return { success: true }
      }
      case 'hideNodes':
        hiddenNodeIds.value = new Set([...hiddenNodeIds.value, ...cmd.nodeIds])
        return { success: true }
      case 'clearFilter':
        hiddenNodeIds.value = new Set()
        return { success: true }
      case 'setViewMode':
        if (isExternalTab.value) externalViewMode.value = cmd.mode as any
        else internalViewMode.value = cmd.mode as any
        return { success: true }
      case 'setEdgeType':
        return { success: false, error: 'setEdgeType: need to propagate to parent (not implemented yet)' }
      case 'resetView':
        handleResetView()
        return { success: true }
      case 'compareVersions':
        await toggleCompare()
        return { success: true }
      case 'openCommunityDetail': {
        const com = commMap.value.get(cmd.communityId)
        if (com?.summary) {
          emit('open-md', { taskId: props.taskId, content: `## ${com.name || com.communityId}\n\n${com.summary || ''}`, title: com.name || com.communityId })
        }
        return { success: true }
      }
      case 'dispatchAgent':
        await communityStore.triggerArchAnalysis(props.taskId, effectiveEdgeType.value, 'L0')
        return { success: true }
      default:
        return { success: false, error: `unknown command: ${(cmd as any).type}` }
    }
  } catch (err: any) {
    return { success: false, error: err.message || String(err) }
  }
}

// 监听状态变化 → 自动同步 graphState 到 store
watch([() => drillMeta.value.drillKey, () => props.edgeType, isExternalTab, hiddenNodeIds, graphNodes, allCommunities], () => {
  syncGraphState()
}, { immediate: false, deep: false })

onMounted(async () => {
  cmdStore.registerExecutor(executeGraphCommand)
  syncGraphState()
  if (!isExternalTab.value) {
    await communityStore.loadCrossCommunityEdges(props.taskId, effectiveEdgeType.value, drillMeta.value.drillLevel)
  }
  document.addEventListener('keydown', onKeydown)
  loadDBPositions()
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  if (positionLoadTimer) clearTimeout(positionLoadTimer)
})

let positionLoadTimer: ReturnType<typeof setTimeout> | null = null
watch([() => drillMeta.value.drillKey, () => props.edgeType, internalViewMode], () => {
  if (positionLoadTimer) clearTimeout(positionLoadTimer)
  positionLoadTimer = setTimeout(loadDBPositions, 100)
})

watch(isFullscreen, () => {
  recenterTrigger.value++
})

watch(hasUnsavedChanges, (v) => {
  console.log('[CGV] hasUnsavedChanges =', v, 'dragGen:', dragGeneration.value, 'savedGen:', savedGeneration.value)
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
        v-if="hasUnsavedChanges"
        class="cgv-save-btn"
        title="保存节点位置"
        @click="handleSavePositions"
      >
        <ArrowDownTrayIcon class="w-3.5 h-3.5" />
        <span>保存节点位置</span>
      </button>
      <div class="cgv-search">
        <input
          v-model="graphSearch"
          type="text"
          :placeholder="t('report.searchCommunity', '搜索...')"
          class="cgv-search-input"
        >
      </div>
      <button
        class="cgv-filter-btn"
        :class="{ active: hiddenNodeIds.size > 0 }"
        :title="t('report.nodeFilter', '节点筛选')"
        @click="handleToggleFilter"
      >
        <FunnelIcon class="w-3.5 h-3.5" />
      </button>
      <GraphToolbar
        :mode="isExternalTab ? externalViewMode : internalViewMode"
        @update:mode="(m) => isExternalTab ? (externalViewMode = m) : (internalViewMode = m)"
        @reset-view="handleResetView"
        @export-arch="handleExportArch"
        @compare="toggleCompare"
      />
      <button
        class="cgv-gear-btn"
        title="图配置"
        @click="toggleGear"
      >
        <Cog6ToothIcon class="w-3.5 h-3.5" />
      </button>
      <button
        class="cgv-gear-btn"
        title="全屏"
        @click="enterFullscreen"
      >
        <ArrowsPointingOutIcon class="w-3.5 h-3.5" />
      </button>
    </div>
    <div v-if="compareActive" class="cgv-compare-bar">
      <button class="cgv-compare-exit" @click="toggleCompare">
        <span>&times; 退出对比</span>
      </button>
      <select
        class="cgv-compare-select"
        :value="compareFrom"
        @change="setCompareVersion(($event.target as HTMLSelectElement).value, compareTo)"
      >
        <option
          v-for="s in compareTimeline"
          :key="s.id"
          :value="s.id"
        >{{ s.versionTag || s.alias || s.id }}</option>
      </select>
      <span class="cgv-compare-vs">=== vs ===</span>
      <select
        class="cgv-compare-select"
        :value="compareTo"
        @change="setCompareVersion(compareFrom, ($event.target as HTMLSelectElement).value)"
      >
        <option
          v-for="s in compareTimeline"
          :key="s.id"
          :value="s.id"
        >{{ s.versionTag || s.alias || s.id }}</option>
      </select>
      <div class="cgv-compare-legend">
        <span class="legend-item"><span class="legend-dot added"></span>新增</span>
        <span class="legend-item"><span class="legend-dot removed"></span>删除</span>
        <span class="legend-item"><span class="legend-dot changed"></span>变更</span>
        <span class="legend-item"><span class="legend-dot unchanged"></span>无变化</span>
      </div>
    </div>

    <!-- 下钻/上卷 加载遮罩 -->
    <div v-if="drilling" class="cgv-drill-overlay">
      <div class="cgv-drill-spinner" />
      <span class="cgv-drill-text">加载中...</span>
    </div>

    <template v-if="isExternalTab">
      <GraphCanvas
        v-if="externalViewMode === 'force'"
        ref="graphCanvasRef"
        :key="'ext-force-' + props.edgeType + '-' + drillMeta.drillKey"
        :nodes="graphNodes"
        :edges="crossEdges"
        :style="'force'"
        :highlighted-ids="highlightedNodeIds"
        :hidden-ids="hiddenNodeIds"
        :reset-trigger="resetTrigger"
        :lock-mode="forceLockMode"
        :repulsion="forceRepulsion"
        :recenter-trigger="recenterTrigger"
        :zoom-level="zoomLevel"
        :font-size="fontSize"
        :fullscreen="isFullscreen"
        :positions="savedPositions"
        @node-dblclick="(id: string) => handleDrill(id)"
        @node-context-menu="(id: string) => handleNodeContextMenu(id)"
        @node-drag-end="(id: string, x: number, y: number) => { setNodePosition(props.edgeType, drillMeta.drillKey, id, { x, y }); dragGeneration++; console.log('[CGV] node-drag-end', id, 'dragGen:', dragGeneration) }"
        @zoom-changed="(level: number) => zoomLevel = level"
        @guide-click="handleGuideClick"
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
        v-if="internalViewMode === 'force'"
        ref="graphCanvasRef"
        :key="drillMeta.drillKey + '-' + props.edgeType + '-' + internalViewMode"
        :nodes="graphNodes"
        :edges="crossEdges"
        :style="'force'"
        :highlighted-ids="highlightedNodeIds"
        :hidden-ids="hiddenNodeIds"
        :reset-trigger="resetTrigger"
        :lock-mode="forceLockMode"
        :repulsion="forceRepulsion"
        :recenter-trigger="recenterTrigger"
        :zoom-level="zoomLevel"
        :font-size="fontSize"
        :fullscreen="isFullscreen"
        :positions="savedPositions"
        @node-dblclick="(id: string) => handleDrill(id)"
        @node-context-menu="(id: string) => handleNodeContextMenu(id)"
        @node-drag-end="(id: string, x: number, y: number) => { setNodePosition(props.edgeType, drillMeta.drillKey, id, { x, y }); dragGeneration++; console.log('[CGV] node-drag-end', id, 'dragGen:', dragGeneration) }"
        @zoom-changed="(level: number) => zoomLevel = level"
        @guide-click="handleGuideClick"
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
          v-if="hasUnsavedChanges"
          class="cgv-save-btn"
          title="保存节点位置"
          @click="handleSavePositions"
        >
          <ArrowDownTrayIcon class="w-3.5 h-3.5" />
          <span>保存节点位置</span>
        </button>
        <div class="cgv-search">
          <input
            v-model="graphSearch"
            type="text"
            :placeholder="t('report.searchCommunity', '搜索...')"
            class="cgv-search-input"
          >
        </div>
        <button
          class="cgv-filter-btn"
          :class="{ active: hiddenNodeIds.size > 0 }"
          :title="t('report.nodeFilter', '节点筛选')"
          @click="handleToggleFilter"
        >
          <FunnelIcon class="w-3.5 h-3.5" />
        </button>
        <GraphToolbar
          :mode="isExternalTab ? externalViewMode : internalViewMode"
          :fullscreen="true"
          @update:mode="(m) => isExternalTab ? (externalViewMode = m) : (internalViewMode = m)"
          @reset-view="handleResetView"
          @export-arch="handleExportArch"
          @compare="toggleCompare"
        />
        <button
          class="cgv-gear-btn"
          title="图配置"
          @click="toggleGear"
        >
          <Cog6ToothIcon class="w-3.5 h-3.5" />
        </button>
        <button
          class="cgv-gear-btn"
          title="退出全屏"
          @click="exitFullscreen"
        >
          <ArrowsPointingInIcon class="w-3.5 h-3.5" />
        </button>
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
      :search="graphSearch"
      :visible="showFilter"
      :click-x="filterClickX"
      :click-y="filterClickY"
      @update:hidden-ids="updateHiddenIds"
      @connect-complete="handleConnectComplete"
      @close="showFilter = false"
    />

    <!-- 位置复原弹窗 -->
    <Teleport to="body">
      <div v-if="showPositionReset" class="cgv-overlay" @click.self="showPositionReset = false">
        <div class="cgv-position-reset-dialog">
          <div class="cgv-prd-header">
            <span class="cgv-prd-title">位置复原</span>
            <button class="cgv-prd-close" @click="showPositionReset = false">&times;</button>
          </div>
          <div class="cgv-prd-body">
            <div v-if="positionKeys.length === 0" class="cgv-prd-empty">
              当前项目无已保存的位置信息
            </div>
            <template v-else>
              <div class="cgv-prd-toolbar">
                <label class="cgv-prd-select-all">
                  <input type="checkbox" :checked="selectedKeys.size === positionKeys.length" @change="toggleAllKeys">
                  全选 ({{ positionKeys.length }})
                </label>
              </div>
              <div class="cgv-prd-header-row">
                <span></span>
                <span class="cgv-prd-col-edge">边类型</span>
                <span class="cgv-prd-col-drill" title="当前图的钻取范围：L0 表示整层全部社区，comm-xxx 表示下钻到该社区的子树视图">图范围</span>
                <span class="cgv-prd-col-count">节点数</span>
              </div>
              <div class="cgv-prd-list">
                <label
                  v-for="k in positionKeys"
                  :key="keyId(k)"
                  class="cgv-prd-item"
                >
                  <input
                    type="checkbox"
                    :checked="selectedKeys.has(keyId(k))"
                    @change="toggleKey(k)"
                  >
                  <span class="cgv-prd-edge">{{ edgeTypeLabel[k.edgeType] || k.edgeType }}</span>
                  <span class="cgv-prd-drill" :title="k.drillKey === 'L0' ? '顶层全图 — 所有L0社区的位置快照' : `钻取到 ${k.drillKey} 的子图位置快照`">{{ drillKeyLabel(k) }}</span>
                  <span class="cgv-prd-count">{{ k.count }} 个节点</span>
                </label>
              </div>
            </template>
          </div>
          <div class="cgv-prd-footer">
            <template v-if="!showClearConfirm">
              <button
                class="cgv-prd-btn-danger"
                :disabled="selectedKeys.size === 0 || resetLoading"
                @click="handleClearSelectedPositions"
              >
                {{ resetLoading ? '清除中...' : `清除选中 (${selectedKeys.size})` }}
              </button>
              <button class="cgv-prd-btn-cancel" @click="showPositionReset = false">取消</button>
            </template>
            <template v-else>
              <span class="cgv-prd-confirm-text">确认清除 {{ selectedKeys.size }} 个已保存的位置信息？此操作不可撤销。</span>
              <div class="cgv-prd-confirm-actions">
                <button class="cgv-prd-btn-danger" @click="executeClearPositions">确认清除</button>
                <button class="cgv-prd-btn-cancel" @click="showClearConfirm = false">取消</button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 齿轮设置面板 -->
    <Teleport to="body">
      <div v-if="gearOpen" class="cgv-gear-overlay" @click.self="gearOpen = false">
        <div class="cgv-gear-panel" :style="{ position: 'fixed', top: gearPanelRect.top || undefined, bottom: gearPanelRect.bottom || undefined, right: gearPanelRect.right }">
          <div class="cgv-gear-row">
            <span class="cgv-gear-label">字号</span>
            <span class="cgv-gear-val">{{ fontSize }}px</span>
            <input type="range" min="6" max="18" step="0.5" :value="fontSize" @input="fontSize = parseFloat(($event.target as HTMLInputElement).value)" class="cgv-gear-slider">
          </div>
          <div v-if="(isExternalTab && externalViewMode === 'force') || (!isExternalTab && internalViewMode === 'force')" class="cgv-gear-row">
            <span class="cgv-gear-label">斥力</span>
            <span class="cgv-gear-val">{{ forceRepulsion }}</span>
            <input type="range" min="1" max="100" :value="forceRepulsionSlider" @input="forceRepulsionSlider = Number(($event.target as HTMLInputElement).value)" class="cgv-gear-slider">
          </div>
          <div class="cgv-gear-row cgv-gear-mode">
            <label class="cgv-gear-radio">
              <input type="radio" :value="'linked'" v-model="forceLockMode">
              <LockClosedIcon class="w-3.5 h-3.5" />
              <span>跟随模式</span>
            </label>
            <label class="cgv-gear-radio">
              <input type="radio" :value="'locked'" v-model="forceLockMode">
              <LinkSlashIcon class="w-3.5 h-3.5" />
              <span>独立模式</span>
            </label>
          </div>
          <hr class="cgv-gear-divider">
          <button class="cgv-gear-action" :class="{ active: hasUnsavedChanges }" :disabled="!hasUnsavedChanges" @click="handleSavePositions()">
            <span v-if="hasUnsavedChanges">&#x1F4BE; 保存位置</span>
            <span v-else>&#x1F4BE; 位置已保存</span>
          </button>
          <button class="cgv-gear-action" @click="openPositionReset(); gearOpen = false">
            位置复原…
          </button>
          <button class="cgv-gear-action cgv-gear-action-danger" @click="handleClearAllPositions(); gearOpen = false">
            清除所有保存位置…
          </button>
        </div>
      </div>
    </Teleport>
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

.cgv-filter-btn {
  display: flex; align-items: center; justify-content: center;
  width: 26px; height: 24px; padding: 0;
  background: transparent; border: 1px solid var(--border);
  border-radius: 0.25rem; color: var(--text-muted); cursor: pointer;
  transition: all 0.15s; flex-shrink: 0;
}
.cgv-filter-btn:hover { color: var(--text-primary); border-color: var(--accent); }
.cgv-filter-btn.active { background: var(--bg-accent-subtle, #2d1f5e); border-color: var(--accent); color: var(--accent); }

.cgv-gear-btn {
  display: flex; align-items: center; justify-content: center;
  width: 26px; height: 24px; padding: 0;
  background: transparent; border: 1px solid var(--border);
  border-radius: 0.25rem; color: var(--text-muted); cursor: pointer;
  transition: all 0.15s; flex-shrink: 0;
}
.cgv-gear-btn:hover { color: var(--text-primary); border-color: var(--accent); }

.cgv-save-btn {
  display: inline-flex; align-items: center; gap: 0.25rem;
  height: 24px; padding: 0 0.5rem;
  background: var(--bg-accent-subtle, #2d1f5e); border: 1px solid var(--accent);
  border-radius: 0.25rem; color: var(--accent); cursor: pointer;
  transition: all 0.15s; flex-shrink: 0; font-size: 0.7rem; white-space: nowrap;
}
.cgv-save-btn:hover { opacity: 0.85; }

/* -- compare bar -- */
.cgv-compare-bar {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.25rem 0.75rem; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.cgv-compare-exit {
  display: flex; align-items: center; gap: 0.2rem;
  font-size: 0.65rem; color: var(--text-muted);
  background: none; border: 1px solid var(--border);
  border-radius: 0.2rem; padding: 0.1rem 0.4rem; cursor: pointer;
  white-space: nowrap;
}
.cgv-compare-exit:hover { color: var(--text-primary); border-color: var(--accent); }
.cgv-compare-select {
  padding: 0.1rem 0.3rem; font-size: 0.65rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  border-radius: 0.2rem; color: var(--text-muted); outline: none;
}
.cgv-compare-select:focus { border-color: var(--accent); }
.cgv-compare-vs { font-size: 0.65rem; color: var(--text-muted); white-space: nowrap; }
.cgv-compare-legend { display: flex; align-items: center; gap: 0.75rem; margin-left: auto; }
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
.fs-left { display: flex; align-items: center; gap: 0.75rem; flex: 1; overflow: visible; }
.fs-title { font-size: 0.8rem; font-weight: 600; color: var(--text-primary); flex-shrink: 0; }
.fs-actions { display: flex; gap: 0.5rem; flex-shrink: 0; }
.fs-btn {
  padding: 0.2rem 0.6rem; font-size: 0.75rem; color: var(--text-muted);
  background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: 0.25rem; cursor: pointer; transition: all 0.15s;
}
.fs-btn:hover { color: var(--text-primary); border-color: var(--accent, #7c3aed); }
.fs-btn-active { background: var(--accent, #7c3aed); color: #fff; border-color: var(--accent); }
.cgv-empty { font-size: 0.8rem; color: var(--text-muted); text-align: center; padding: 2rem; flex: 1; }

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
/* ── 齿轮设置面板 ── */
.cgv-gear-overlay {
  position: fixed; inset: 0; z-index: 1999;
}
.cgv-gear-panel {
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: 0.35rem; box-shadow: 0 4px 16px rgba(0,0,0,0.35);
  padding: 0.5rem; min-width: 220px; z-index: 2000;
  display: flex; flex-direction: column; gap: 0.4rem;
}
.cgv-gear-row {
  display: flex; align-items: center; gap: 0.4rem;
}
.cgv-gear-label {
  font-size: 0.65rem; color: var(--text-muted); min-width: 30px;
}
.cgv-gear-val {
  font-size: 0.6rem; color: var(--text-muted); min-width: 50px; text-align: right;
}
.cgv-gear-slider {
  flex: 1; height: 4px; cursor: pointer; accent-color: var(--accent, #7c3aed);
}
.cgv-gear-mode {
  display: flex; flex-direction: column; gap: 0.2rem;
}
.cgv-gear-radio {
  display: flex; align-items: center; gap: 0.35rem; font-size: 0.65rem;
  color: var(--text-muted); cursor: pointer; padding: 0.15rem 0;
}
.cgv-gear-radio:hover { color: var(--text-primary); }
.cgv-gear-radio input[type="radio"] { accent-color: var(--accent); margin: 0; }
.cgv-gear-divider {
  border: none; border-top: 1px solid var(--border); margin: 0.2rem 0;
}
.cgv-gear-action {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.2rem 0.4rem; font-size: 0.7rem; width: 100%;
  background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: 0.2rem; color: var(--text-primary); cursor: pointer;
  text-align: left; transition: all 0.1s;
}
.cgv-gear-action:hover:not(:disabled) { border-color: var(--accent); background: var(--bg-secondary); }
.cgv-gear-action.active { color: var(--accent); }
.cgv-gear-action:disabled { opacity: 0.4; cursor: not-allowed; }
.cgv-gear-action-danger { color: #ef4444; }
.cgv-gear-action-danger:hover { color: #ef4444; border-color: #ef4444; }

/* ---- 位置复原弹窗 ---- */
.cgv-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 2000;
}
.cgv-position-reset-dialog {
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: 0.5rem; width: 420px; max-height: 70vh;
  display: flex; flex-direction: column; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}
.cgv-prd-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid var(--border);
}
.cgv-prd-title { font-size: 0.9rem; font-weight: 600; }
.cgv-prd-close { font-size: 1.2rem; color: var(--text-muted); cursor: pointer; background: none; border: none; }
.cgv-prd-body { padding: 12px 16px; overflow-y: auto; flex: 1; }
.cgv-prd-empty { color: var(--text-muted); font-size: 0.8rem; text-align: center; padding: 20px 0; }
.cgv-prd-toolbar { margin-bottom: 8px; }
.cgv-prd-select-all { font-size: 0.75rem; cursor: pointer; display: flex; align-items: center; gap: 4px; color: var(--text-muted); }
.cgv-prd-header-row {
  display: flex; align-items: center; gap: 8px; padding: 4px 8px;
  border-bottom: 1px solid var(--border); margin-bottom: 4px;
}
.cgv-prd-col-edge { font-size: 0.65rem; color: var(--text-muted); font-weight: 600; width: 110px; flex-shrink: 0; }
.cgv-prd-col-drill { font-size: 0.65rem; color: var(--text-muted); font-weight: 600; flex: 1; cursor: help; }
.cgv-prd-col-count { font-size: 0.65rem; color: var(--text-muted); font-weight: 600; text-align: right; flex-shrink: 0; }
.cgv-prd-list { display: flex; flex-direction: column; gap: 2px; max-height: 280px; overflow-y: auto; }
.cgv-prd-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 8px;
  border-radius: 0.2rem; cursor: pointer; font-size: 0.75rem;
}
.cgv-prd-item:hover { background: var(--bg-tertiary); }
.cgv-prd-edge { color: var(--accent); font-weight: 600; min-width: 110px; }
.cgv-prd-drill { color: var(--text-primary); min-width: 150px; font-size: 0.7rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cgv-prd-count { color: var(--text-muted); margin-left: auto; }
.cgv-prd-footer {
  display: flex; gap: 8px; justify-content: flex-end;
  padding: 12px 16px; border-top: 1px solid var(--border);
}
.cgv-prd-footer-confirm {
  flex-direction: column; align-items: stretch; gap: 8px;
}
.cgv-prd-confirm-text { font-size: 0.75rem; color: var(--text-muted); }
.cgv-prd-confirm-actions { display: flex; gap: 8px; justify-content: flex-end; }
.cgv-prd-btn-danger {
  background: #ef4444; color: #fff; border: none; border-radius: 0.25rem;
  padding: 6px 14px; font-size: 0.75rem; cursor: pointer;
}
.cgv-prd-btn-danger:disabled { opacity: 0.4; cursor: not-allowed; }
.cgv-prd-btn-cancel {
  background: var(--bg-tertiary); color: var(--text-muted);
  border: 1px solid var(--border); border-radius: 0.25rem;
  padding: 6px 14px; font-size: 0.75rem; cursor: pointer;
}
</style>
