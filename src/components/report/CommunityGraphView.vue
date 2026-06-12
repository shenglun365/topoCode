<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'
import { useComponentId } from '@/composables/useComponentId'
import { useGraphFullscreen } from '@/composables/useGraphFullscreen'
import { useGraphPosition } from '@/composables/useGraphPosition'
import { communityLabel, communityIdLabel } from '@/utils/communityLabel'
import GraphBreadcrumb from './GraphBreadcrumb.vue'
import GraphToolbar from './GraphToolbar.vue'
import GraphCanvas from './GraphCanvas.vue'
import ExternalTableView from './ExternalTableView.vue'
import ExternalHeatmapView from './ExternalHeatmapView.vue'
import NodeFilterPanel from './NodeFilterPanel.vue'
import CommunityTableView from './CommunityTableView.vue'

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

const graphStyle = ref<'d3force' | 'dagre'>('dagre')
const externalViewMode = ref<'force' | 'table' | 'heatmap'>('force')
const internalViewMode = ref<'force' | 'dagre' | 'table' | 'heatmap'>('dagre')
const resetTrigger = ref(0)
const showFilter = ref(false)
const filterClickX = ref(0)
const filterClickY = ref(0)
const currentViewKey = ref('L0')
const currentDrillLevel = ref('L0')
const externalDrillItem = ref<string | null>(null)
const breadcrumbPath = ref<Array<{ key: string; label: string; level: string }>>([
  { key: 'L0', label: t('report.allL0', '全部L0社区'), level: 'L0' }
])

const MERGE_THRESHOLD = 100
const BATCH_EXPAND_SIZE = 50

const mergedHiddenNodes = ref<any[]>([])
const expandBatchCount = ref(0)
const graphSearch = ref('')

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

const isExternalTab = computed(() =>
  props.edgeType === 'EXTERNAL_INCLUDE' || props.edgeType === 'EXTERNAL_CALL'
)

const allCommunities = computed(() => {
  if (isExternalTab.value) return []
  return communityStore.tasks[props.taskId]?.communities || []
})

const parentCommId = computed(() => {
  if (currentViewKey.value === 'L0') return null
  return currentViewKey.value.replace(/^comm-/, '')
})

const rawGraphNodes = computed(() => {
  if (isExternalTab.value) {
    const extNodes = buildExternalNodes()
    const commNodes = externalCommunityNodes.value
    const all = [...extNodes, ...commNodes]
    if (externalDrillItem.value) {
      const drillId = externalDrillItem.value
      const extNode = extNodes.find(n => n.id === drillId)
      if (extNode) {
        const connectedCommIds = new Set<string>()
        for (const e of externalCrossEdges.value) {
          if (e.source === drillId) connectedCommIds.add(e.target)
          if (e.target === drillId) connectedCommIds.add(e.source)
        }
        return all.filter(n => n.id === drillId || connectedCommIds.has(n.id))
      }
    }
    return all
  }
  const coms = allCommunities.value
  if (currentViewKey.value === 'L0') {
    return coms.filter(c => c.level === 'L0' && c.edgeType === props.edgeType)
      .map(c => mapCommunityToNode(c))
  }
  const parentId = parentCommId.value
  if (!parentId) return []
  const parent = coms.find(c => c.communityId === parentId)
  if (!parent) return []
  const nextLevel = `L${parseInt(parent.level?.[1] || '0') + 1}`
  return coms.filter(c =>
    c.edgeType === props.edgeType &&
    c.level === nextLevel &&
    c.parentId === parentId
  ).map(c => mapCommunityToNode(c))
})

function mapCommunityToNode(c: CommunityItem) {
  return {
    id: c.communityId,
    label: communityLabel(c),
    nodeCount: c.nodeCount,
    fileCount: c.fileCount,
    qualityScore: c.qualityScore,
    status: c.status,
    hasChildren: allCommunities.value.some(ch => ch.parentId === c.communityId),
  }
}

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
    for (let i = 0; i < showing; i++) {
      result.push(currentHidden[i])
    }
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
    expandBatchCount.value++ // 全展开
  }
}

const crossEdges = computed(() => {
  if (isExternalTab.value) return externalCrossEdges.value
  const lv = currentDrillLevel.value
  const raw = communityStore.tasks[props.taskId]?.crossCommunityEdges?.[props.edgeType]?.[lv] || []
  return raw.map(e => ({ source: e.sourceCommId, target: e.targetCommId, count: e.edgeCount }))
})

const externalItems = computed(() => {
  if (!isExternalTab.value || !props.externalStats) return []
  return props.edgeType === 'EXTERNAL_INCLUDE'
    ? (props.externalStats.externalDeps || [])
    : (props.externalStats.externalCalls || [])
})

function buildExternalNodes(): any[] {
  if (!props.externalStats) return []
  const items = props.edgeType === 'EXTERNAL_INCLUDE'
    ? (props.externalStats.externalDeps || [])
    : (props.externalStats.externalCalls || [])
  const nodes: any[] = []
  const edgeType = props.edgeType

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
      edges.push({
        source: extId,
        target: c.communityId,
      })
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
          hasChildren: true,
        })
      }
    })
  })

  return nodes
})

async function handleDrillDown(communityId: string) {
  if (communityId === '__merged__') {
    handleExpandMerged()
    return
  }
  if (isExternalTab.value) {
    externalDrillItem.value = communityId
    return
  }
  const com = allCommunities.value.find(c => c.communityId === communityId)
  if (!com) return
  expandBatchCount.value = 0
  graphSearch.value = ''
  const label = com.name && com.name !== com.communityId ? com.name : communityId
  const nextLevel = `L${parseInt(com.level?.[1] || '0') + 1}`
  currentViewKey.value = `comm-${communityId}`
  currentDrillLevel.value = nextLevel
  breadcrumbPath.value.push({ key: currentViewKey.value, label: label.length > 24 ? label.slice(0, 24) + '…' : label, level: nextLevel })
}

function handleBreadcrumbClick(index: number) {
  if (index === breadcrumbPath.value.length - 1) return
  breadcrumbPath.value = breadcrumbPath.value.slice(0, index + 1)
  currentViewKey.value = breadcrumbPath.value[index].key
  currentDrillLevel.value = breadcrumbPath.value[index].level
  expandBatchCount.value = 0
  graphSearch.value = ''
}

function handleRollUp() {
  if (isExternalTab.value && externalDrillItem.value) {
    externalDrillItem.value = null
    return
  }
  if (breadcrumbPath.value.length <= 1) return
  breadcrumbPath.value.pop()
  currentViewKey.value = breadcrumbPath.value[breadcrumbPath.value.length - 1].key
  currentDrillLevel.value = breadcrumbPath.value[breadcrumbPath.value.length - 1].level
  expandBatchCount.value = 0
  graphSearch.value = ''
}

const canRollUp = computed(() =>
  isExternalTab.value ? !!externalDrillItem.value : breadcrumbPath.value.length > 1
)

function handleNodeContextMenu(nodeId: string) {
  if (nodeId === '__merged__') return
  const com = allCommunities.value.find(c => c.communityId === nodeId)
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

function handleResetView() {
  hiddenNodeIds.value = new Set()
  saveHiddenIds()
  resetTrigger.value++
}

function handleToggleFilter(event?: { clientX: number; clientY: number }) {
  if (event) {
    filterClickX.value = event.clientX
    filterClickY.value = event.clientY
  }
  showFilter.value = !showFilter.value
}

const filterNodes = computed(() => {
  if (isExternalTab.value) {
    const items = graphNodes.value.filter(n => !n.isMerged).map(n => ({ id: n.id, label: n.label, nodeCount: n.nodeCount }))
    const commNodes = externalCommunityNodes.value.map(n => ({ id: n.id, label: n.label, nodeCount: n.nodeCount }))
    return [...items, ...commNodes]
  }
  return graphNodes.value
    .filter(n => !n.isMerged)
    .map(n => ({ id: n.id, label: n.label, nodeCount: n.nodeCount }))
})

const internalHeatmapItems = computed(() => {
  const raw = crossEdges.value
  if (raw.length === 0) return []
  const pkgMap = new Map<string, { package: string; fileCount: number; files: string[]; communities: Array<{ communityId: string; name?: string }> }>()
  for (const e of raw) {
    const key = e.source
    if (!pkgMap.has(key)) {
      pkgMap.set(key, { package: key, fileCount: 0, files: [], communities: [] })
    }
    const item = pkgMap.get(key)!
    item.fileCount += e.count || 1
    const tgtComm = allCommunities.value.find(c => c.communityId === e.target)
    item.communities.push({ communityId: e.target, name: tgtComm?.name || communityIdLabel(e.target) })
  }
  return Array.from(pkgMap.values())
})

watch(() => [props.edgeType, currentViewKey.value], async () => {
  if (!isExternalTab.value) {
    const lv = currentDrillLevel.value
    await communityStore.loadCrossCommunityEdges(props.taskId, props.edgeType, lv)
  }
})

onMounted(async () => {
  if (!isExternalTab.value) {
    await communityStore.loadCrossCommunityEdges(props.taskId, props.edgeType, currentDrillLevel.value)
  }
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
  <div class="cgv-container" :class="{ 'cgv-fullscreen': isFullscreen }">
    <div class="cgv-topbar" v-show="!isFullscreen">
      <GraphBreadcrumb
        :path="breadcrumbPath"
        @click="handleBreadcrumbClick"
        @roll-up="handleRollUp"
      />
      <div class="cgv-search">
        <input
          v-model="graphSearch"
          type="text"
          :placeholder="t('report.searchCommunity', '搜索...')"
          class="cgv-search-input"
        />
      </div>
      <GraphToolbar
        v-model:style="graphStyle"
        :can-roll-up="canRollUp"
        :external-mode="isExternalTab"
        :filter-active="hiddenNodeIds.size > 0"
        v-model:external-view-mode="externalViewMode"
        v-model:internal-view-mode="internalViewMode"
        @roll-up="handleRollUp"
        @fullscreen="enterFullscreen"
        @reset-view="handleResetView"
        @toggle-filter="handleToggleFilter"
      />
    </div>
    <template v-if="isExternalTab">
      <GraphCanvas
        v-if="externalViewMode === 'force'"
        :nodes="graphNodes"
        :edges="crossEdges"
        :style="'d3force'"
        :key="'ext-force-' + props.edgeType"
        :highlighted-ids="highlightedNodeIds"
        :hidden-ids="hiddenNodeIds"
        :reset-trigger="resetTrigger"
        @node-dblclick="(id: string) => handleDrillDown(id)"
        @node-context-menu="(id: string) => handleNodeContextMenu(id)"
        @node-drag-end="(id: string, x: number, y: number) => setNodePosition(props.edgeType, currentViewKey, id, { x, y })"
      />
      <ExternalTableView
        v-else-if="externalViewMode === 'table'"
        :items="externalItems"
        :edge-type="props.edgeType"
      />
      <ExternalHeatmapView
        v-else
        :items="externalItems"
      />
    </template>
    <template v-else>
      <GraphCanvas
        v-if="internalViewMode === 'force' || internalViewMode === 'dagre'"
        :nodes="graphNodes"
        :edges="crossEdges"
        :style="internalViewMode === 'dagre' ? 'dagre' : 'd3force'"
        :key="currentViewKey + '-' + props.edgeType + '-' + internalViewMode"
        :highlighted-ids="highlightedNodeIds"
        :hidden-ids="hiddenNodeIds"
        :reset-trigger="resetTrigger"
        @node-dblclick="(id: string) => handleDrillDown(id)"
        @node-context-menu="(id: string) => handleNodeContextMenu(id)"
        @node-drag-end="(id: string, x: number, y: number) => setNodePosition(props.edgeType, currentViewKey, id, { x, y })"
      />
      <CommunityTableView
        v-else-if="internalViewMode === 'table'"
        :communities="allCommunities"
        :edge-type="props.edgeType"
        @open-community="(item) => handleNodeContextMenu(item.communityId)"
      />
      <ExternalHeatmapView
        v-else
        :items="internalHeatmapItems"
        :all-communities="allCommunities"
      />
    </template>
    <div v-if="isFullscreen" class="cgv-fullscreen-bar">
      <div class="fs-left">
        <span class="fs-title">{{ breadcrumbPath[breadcrumbPath.length - 1]?.label || '组件结构图' }}</span>
        <div class="cgv-search">
          <input
            v-model="graphSearch"
            type="text"
            :placeholder="t('report.searchCommunity', '搜索...')"
            class="cgv-search-input"
          />
        </div>
        <GraphToolbar
          v-model:style="graphStyle"
          :can-roll-up="canRollUp"
          :external-mode="isExternalTab"
          :filter-active="hiddenNodeIds.size > 0"
          v-model:external-view-mode="externalViewMode"
          v-model:internal-view-mode="internalViewMode"
          @roll-up="handleRollUp"
          @fullscreen="exitFullscreen"
          @reset-view="handleResetView"
          @toggle-filter="handleToggleFilter"
        />
      </div>
      <div class="fs-actions">
        <button class="fs-btn" @click="exitFullscreen">{{ t('report.exitFullscreen', '退出全屏') }}</button>
      </div>
    </div>
    <NodeFilterPanel
      :nodes="filterNodes"
      :hidden-ids="hiddenNodeIds"
      :visible="showFilter"
      :click-x="filterClickX"
      :click-y="filterClickY"
      @update:hidden-ids="updateHiddenIds"
      @close="showFilter = false"
    />
  </div>
</template>

<style scoped>
.cgv-container { display: flex; flex-direction: column; height: 420px; min-height: 280px; border: 1px solid var(--border); border-radius: 0.5rem; overflow: hidden; background: var(--bg-primary); position: relative; }
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
</style>
