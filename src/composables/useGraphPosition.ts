import { ref, watch, onUnmounted } from 'vue'

export interface NodePosition {
  x: number
  y: number
  fx?: number
  fy?: number
}

interface PositionStore {
  v: number
  taskAt: string
  positions: Record<string, Record<string, Record<string, NodePosition>>>
}

const STORE_VERSION = 1

function buildKey(projectId: string, taskId: string): string {
  return `graph-pos-${projectId}-${taskId}`
}

export function useGraphPosition(projectId: string, taskId: string, taskUpdatedAt?: string) {
  const positions = ref<Record<string, Record<string, Record<string, NodePosition>>>>({})
  const loaded = ref(false)
  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  function load() {
    try {
      const raw = localStorage.getItem(buildKey(projectId, taskId))
      if (!raw) return
      const store: PositionStore = JSON.parse(raw)
      if (store.v !== STORE_VERSION) {
        localStorage.removeItem(buildKey(projectId, taskId))
        return
      }
      if (taskUpdatedAt && store.taskAt !== taskUpdatedAt) {
        localStorage.removeItem(buildKey(projectId, taskId))
        return
      }
      positions.value = store.positions
    } catch {
      localStorage.removeItem(buildKey(projectId, taskId))
    } finally {
      loaded.value = true
    }
  }

  function save() {
    const store: PositionStore = {
      v: STORE_VERSION,
      taskAt: taskUpdatedAt || '',
      positions: positions.value,
    }
    try {
      localStorage.setItem(buildKey(projectId, taskId), JSON.stringify(store))
    } catch {
      console.warn('[useGraphPosition] failed to save positions')
    }
  }

  function saveDebounced() {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(save, 300)
  }

  function getNodePosition(edgeType: string, viewKey: string, nodeId: string): NodePosition | undefined {
    return positions.value[edgeType]?.[viewKey]?.[nodeId]
  }

  function setNodePosition(edgeType: string, viewKey: string, nodeId: string, pos: NodePosition) {
    if (!positions.value[edgeType]) positions.value[edgeType] = {}
    if (!positions.value[edgeType][viewKey]) positions.value[edgeType][viewKey] = {}
    positions.value[edgeType][viewKey][nodeId] = pos
    saveDebounced()
  }

  function clearView(edgeType: string, viewKey: string) {
    if (positions.value[edgeType]) {
      delete positions.value[edgeType][viewKey]
      saveDebounced()
    }
  }

  function clearAll() {
    positions.value = {}
    localStorage.removeItem(buildKey(projectId, taskId))
  }

  load()

  onUnmounted(() => {
    if (debounceTimer) clearTimeout(debounceTimer)
  })

  return {
    positions,
    loaded,
    getNodePosition,
    setNodePosition,
    clearView,
    clearAll,
    save,
  }
}
